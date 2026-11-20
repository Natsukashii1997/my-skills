#!/usr/bin/env node
// 月度体检：统计 my-skills 里每个自建 skill 的调用、最近使用、版本、有没有 evals 和 CHANGELOG，
// 退役与合并只出提案。只读：不改、不删任何 skill，也不改日志。
//
// 用法：node scripts/monthly-health.mjs [--days 30] [--usage <skill-usage.jsonl>] [--codex <sessions 目录>]
//
// 数据来源：
// - Claude：agent-kit 的 hook 写的 ~/Library/Application Support/agent-kit/skill-usage.jsonl，
//   每行 {time, session, cwd, skill}，按次计。
// - Codex：~/.codex/sessions/YYYY/MM/DD/*.jsonl(.zst)。Codex 没有「调用 skill」事件，
//   以工具调用读取 skills/<名字>/SKILL.md 为准，同一会话只算一次。系统提示里列出的 skill 清单不算。

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath, pathToFileURL } from 'node:url';

const HOME = os.homedir();
export const DEFAULTS = {
  days: 30,
  usage: path.join(HOME, 'Library/Application Support/agent-kit/skill-usage.jsonl'),
  codex: path.join(HOME, '.codex/sessions'),
  repo: path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..'),
};
const CODEX_TOOL_CALLS = new Set(['function_call', 'custom_tool_call', 'local_shell_call']);
const DAY = 86400000;

// ---------- skill 清单 ----------

function frontmatter(text) {
  const m = text.match(/^---\n([\s\S]*?)\n---/);
  if (!m) return {};
  const fm = m[1];
  const field = (re) => (fm.match(re) || [])[1];
  let version = null;
  let inMetadata = false;
  let childIndent = null;
  // 逐行界定 metadata 及其直接子字段，缺 version 时也只扫描一次。
  for (const line of fm.split('\n')) {
    if (/^metadata:[ \t]*$/.test(line)) {
      inMetadata = true;
      childIndent = null;
      continue;
    }
    if (!inMetadata || !line.trim() || /^[ \t]*#/.test(line)) continue;
    const indent = line.match(/^[ \t]+/);
    if (!indent) { inMetadata = false; continue; }
    childIndent ??= indent[0].length;
    if (indent[0].length !== childIndent) continue;
    const value = line.slice(childIndent);
    const match = value.match(/^version:[ \t]*["']?([^"'\s]+)["']?/);
    if (match) version = match[1];
  }
  return {
    name: field(/^name:\s*(.+)$/m)?.trim(),
    description: field(/^description:\s*(.+)$/m)?.trim(),
    version,
  };
}

export function loadSkills(repo) {
  const skillsDir = path.join(repo, 'skills');
  const links = {};
  const linksFile = path.join(repo, 'links.tsv');
  if (fs.existsSync(linksFile)) {
    for (const line of fs.readFileSync(linksFile, 'utf8').split('\n')) {
      if (!line.trim() || line.startsWith('#')) continue;
      const [name, target] = line.split('\t');
      if (!name || !target) continue;
      const tool = target.includes('.claude') ? 'Claude' : 'Codex';
      (links[name] ||= new Set()).add(tool);
    }
  }
  return fs.readdirSync(skillsDir, { withFileTypes: true })
    .filter((d) => d.isDirectory() && fs.existsSync(path.join(skillsDir, d.name, 'SKILL.md')))
    .map((d) => {
      const dir = path.join(skillsDir, d.name);
      const fm = frontmatter(fs.readFileSync(path.join(dir, 'SKILL.md'), 'utf8'));
      return {
        name: d.name,
        description: fm.description || '',
        version: fm.version || null,
        evals: fs.existsSync(path.join(dir, 'evals.md')),
        changelog: fs.existsSync(path.join(dir, 'CHANGELOG.md')),
        tools: [...(links[d.name] || [])].sort(),
      };
    })
    .sort((a, b) => a.name.localeCompare(b.name));
}

// ---------- Claude：skill-usage.jsonl ----------

export function readClaudeUsage(file, names, since) {
  const result = { available: false, records: 0, bad: 0, hits: [] };
  if (!fs.existsSync(file)) return result;
  result.available = true;
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    if (!line.trim()) continue;
    let rec;
    try { rec = JSON.parse(line); } catch { result.bad += 1; continue; }
    const time = Date.parse(rec.time);
    if (!rec.skill || Number.isNaN(time)) { result.bad += 1; continue; }
    result.records += 1;
    // 插件 skill 形如「插件:名字」；只认和自建 skill 完全同名的。
    if (!names.has(rec.skill) || time < since) continue;
    result.hits.push({ skill: rec.skill, time, session: rec.session || '' });
  }
  return result;
}

// ---------- Codex：~/.codex/sessions ----------

function dayDirs(root, since) {
  // 目录按会话开始日期分；跨天的长会话往前多看一天。
  const out = [];
  const floor = since - DAY;
  for (const y of safeList(root)) {
    for (const m of safeList(path.join(root, y))) {
      for (const d of safeList(path.join(root, y, m))) {
        const t = Date.parse(`${y}-${m}-${d}T23:59:59Z`);
        if (!Number.isNaN(t) && t >= floor) out.push(path.join(root, y, m, d));
      }
    }
  }
  return out;
}

function safeList(dir) {
  try { return fs.readdirSync(dir).filter((n) => /^\d+$/.test(n)); } catch { return []; }
}

function readSession(file) {
  // 返回 Buffer：有的会话解压后超过 512MB，转成一个字符串会超出 V8 上限。
  const buf = fs.readFileSync(file);
  return file.endsWith('.zst') ? zlib.zstdDecompressSync(buf) : buf;
}

export function codexHitsInText(input, names) {
  // 返回本会话里读取过的自建 skill 及最早一次的时间。input 是 Buffer 或字符串，只解码含 SKILL.md 的行。
  const buf = Buffer.isBuffer(input) ? input : Buffer.from(input);
  const found = new Map();
  let idx = buf.indexOf('SKILL.md');
  while (idx !== -1) {
    const start = buf.lastIndexOf(10, idx) + 1;
    let end = buf.indexOf(10, idx);
    if (end === -1) end = buf.length;
    const line = buf.toString('utf8', start, end);
    idx = buf.indexOf('SKILL.md', end);
    let obj;
    try { obj = JSON.parse(line); } catch { continue; }
    const p = obj.payload;
    if (obj.type !== 'response_item' || !p || !CODEX_TOOL_CALLS.has(p.type)) continue;
    const body = JSON.stringify([p.arguments, p.input, p.action]);
    // 两种写法：路径里直接带 skills/<名字>/SKILL.md；或 `cat SKILL.md` 配 workdir=.../skills/<名字>。
    for (const m of body.matchAll(/skills\/([A-Za-z0-9_-]+)(?:\/SKILL\.md|\/?(?=\\*["']))/g)) {
      if (!names.has(m[1])) continue;
      const t = Date.parse(obj.timestamp);
      if (!found.has(m[1]) || t < found.get(m[1])) found.set(m[1], t);
    }
  }
  return found;
}

export function readCodexUsage(root, names, since) {
  const result = { available: fs.existsSync(root), sessions: 0, unreadable: 0, hits: [] };
  if (!result.available) return result;
  for (const dir of dayDirs(root, since)) {
    for (const f of fs.readdirSync(dir)) {
      if (!/\.jsonl(\.zst)?$/.test(f)) continue;
      const file = path.join(dir, f);
      let data;
      try { data = readSession(file); } catch { result.unreadable += 1; continue; }
      result.sessions += 1;
      for (const [skill, time] of codexHitsInText(data, names)) {
        if (time >= since) result.hits.push({ skill, time, session: f });
      }
    }
  }
  return result;
}

// ---------- 汇总与提案 ----------

export function buildReport({ skills, claude, codex, days, now }) {
  const rows = skills.map((s) => {
    const c = claude.hits.filter((h) => h.skill === s.name);
    const x = codex.hits.filter((h) => h.skill === s.name);
    const last = Math.max(-Infinity, ...c.map((h) => h.time), ...x.map((h) => h.time));
    return { ...s, claude: c.length, codex: x.length, last: Number.isFinite(last) ? last : null };
  });

  const proposals = [];
  // 1. 重复：description 一字不差的，提议合并。
  const byDesc = new Map();
  for (const r of rows) if (r.description) (byDesc.get(r.description) || byDesc.set(r.description, []).get(r.description)).push(r);
  for (const group of byDesc.values()) {
    if (group.length < 2) continue;
    const list = group.map((r) => `\`${r.name}\`（${r.version ? 'v' + r.version : '无版本号'}，近 ${days} 天 ${r.claude + r.codex} 次）`).join('、');
    proposals.push(`**合并**：${list} 的 description 一字不差，是同一个 skill 的几份拷贝。建议保留一份、其余退役，或者改出明确的分工；保留哪份由常浩定。`);
  }
  // 2. 0 调用：只在它链接到的工具都有数据时才提，否则只记「数据不足」。
  const covered = { Claude: claude.available, Codex: codex.available };
  for (const r of rows) {
    if (r.claude + r.codex > 0 || r.tools.length === 0) continue;
    if (r.tools.every((t) => covered[t])) {
      proposals.push(`**观察去留**：\`${r.name}\` 近 ${days} 天 0 调用（链接到 ${r.tools.join('、')}）。用 \`--days 90\` 再跑一次仍为 0 的，可以考虑退役。`);
    }
  }

  const nodata = rows.filter((r) => r.claude + r.codex === 0 && r.tools.some((t) => !covered[t])).map((r) => r.name);
  const gaps = rows.filter((r) => !r.version || !r.evals || !r.changelog);
  return { rows, proposals, nodata, gaps, claude, codex, days, now };
}

// 日志里的时间是 UTC，显示一律按北京时间（agent-kit G-02）。
export const fmtDate = (t) => (t ? new Date(t).toLocaleDateString('sv-SE', { timeZone: 'Asia/Shanghai' }) : '—');
const yes = (b) => (b ? '有' : '无');

export function renderMarkdown(r) {
  const out = [];
  out.push(`# skill 月度体检（${fmtDate(r.now)}，近 ${r.days} 天）`, '');
  out.push('## 数据来源', '');
  out.push(r.claude.available
    ? `- Claude：skill-usage.jsonl 共 ${r.claude.records} 条记录${r.claude.bad ? `，${r.claude.bad} 行读不了已跳过` : ''}，窗口内命中自建 skill ${r.claude.hits.length} 次。`
    : '- Claude：**没有数据**。skill-usage.jsonl 还不存在，agent-kit 的 skill 调用 hook 可能还没装；下面 Claude 一列都是 0，不代表没用过。');
  out.push(r.codex.available
    ? `- Codex：扫了 ${r.codex.sessions} 个会话${r.codex.unreadable ? `（${r.codex.unreadable} 个读不了）` : ''}，以工具调用读取 SKILL.md 为准，同一会话只算一次；窗口内命中 ${r.codex.hits.length} 次。`
    : '- Codex：**没有数据**，会话目录不存在。');
  out.push('');
  out.push('## 每个 skill', '');
  out.push('| skill | 链接到 | Claude 次数 | Codex 会话数 | 最近使用 | 版本 | evals | CHANGELOG |');
  out.push('|---|---|---:|---:|---|---|---|---|');
  for (const x of r.rows) {
    out.push(`| ${x.name} | ${x.tools.join('、') || '未链接'} | ${x.claude} | ${x.codex} | ${fmtDate(x.last)} | ${x.version || '—'} | ${yes(x.evals)} | ${yes(x.changelog)} |`);
  }
  out.push('', '「最近使用」只看这次扫描的窗口；窗口内没用过显示「—」。', '');
  out.push('## 提案（只是提案，常浩同意后才动）', '');
  if (r.proposals.length) r.proposals.forEach((p, i) => out.push(`${i + 1}. ${p}`));
  else out.push('无。');
  if (r.nodata.length) {
    out.push('', `数据不足、这次不提去留的：${r.nodata.map((n) => `\`${n}\``).join('、')}（链接到的工具里有一边没有调用数据）。`);
  }
  out.push('', '## 资产化缺口', '');
  if (r.gaps.length) {
    out.push('按 README「一个 skill 的一生」，下面这些下次改动时先补齐：', '');
    for (const g of r.gaps) {
      const miss = [!g.version && '版本号', !g.evals && 'evals', !g.changelog && 'CHANGELOG'].filter(Boolean).join('、');
      out.push(`- \`${g.name}\`：缺 ${miss}`);
    }
  } else out.push('无。');
  out.push('');
  return out.join('\n');
}

export function parseArgs(argv) {
  const opts = { ...DEFAULTS };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = () => { if (i + 1 >= argv.length) throw new Error(`${a} 后面要跟一个值`); return argv[++i]; };
    if (a === '--days') opts.days = Number(next());
    else if (a === '--usage') opts.usage = next();
    else if (a === '--codex') opts.codex = next();
    else if (a === '--repo') opts.repo = next();
    else if (a === '-h' || a === '--help') opts.help = true;
    else throw new Error(`不认识的参数：${a}`);
  }
  if (!Number.isInteger(opts.days) || opts.days <= 0) throw new Error('--days 要是正整数');
  return opts;
}

export function run(opts, now = Date.now()) {
  const since = now - opts.days * DAY;
  const skills = loadSkills(opts.repo);
  const names = new Set(skills.map((s) => s.name));
  const claude = readClaudeUsage(opts.usage, names, since);
  const codex = readCodexUsage(opts.codex, names, since);
  return renderMarkdown(buildReport({ skills, claude, codex, days: opts.days, now }));
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try {
    const opts = parseArgs(process.argv.slice(2));
    if (opts.help) {
      console.log('用法：node scripts/monthly-health.mjs [--days 30] [--usage <skill-usage.jsonl>] [--codex <sessions 目录>]');
    } else {
      process.stdout.write(run(opts));
    }
  } catch (e) {
    console.error(`monthly-health：${e.message}`);
    process.exit(2);
  }
}
