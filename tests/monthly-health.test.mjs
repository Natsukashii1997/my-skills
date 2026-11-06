// node --test tests/
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import { codexHitsInText, fmtDate, parseArgs, run } from '../scripts/monthly-health.mjs';

const SCRIPT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../scripts/monthly-health.mjs');
const NOW = Date.parse('2026-11-07T00:00:00Z');

function skill(repo, name, { description = `${name} 的说明`, version, evals, changelog } = {}) {
  const dir = path.join(repo, 'skills', name);
  fs.mkdirSync(dir, { recursive: true });
  const meta = version ? `metadata:\n  version: "${version}"\n` : '';
  fs.writeFileSync(path.join(dir, 'SKILL.md'), `---\nname: ${name}\ndescription: ${description}\n${meta}---\n\n# ${name}\n`);
  if (evals) fs.writeFileSync(path.join(dir, 'evals.md'), '# evals\n');
  if (changelog) fs.writeFileSync(path.join(dir, 'CHANGELOG.md'), '# changelog\n');
}

const line = (o) => JSON.stringify(o);
const toolCall = (ts, cmd) => line({ timestamp: ts, type: 'response_item', payload: { type: 'function_call', name: 'exec_command', arguments: JSON.stringify({ cmd }) } });

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'monthly-health-'));
  const repo = path.join(root, 'repo');
  skill(repo, 'alpha', { version: '1.0.0', evals: true, changelog: true });
  skill(repo, 'beta');
  skill(repo, 'dup-a', { description: '一模一样的说明', version: '3.0.1' });
  skill(repo, 'dup-b', { description: '一模一样的说明', version: '1.0.1' });
  skill(repo, 'idle', { version: '1.0.0' });
  fs.writeFileSync(path.join(repo, 'links.tsv'), [
    '# 注释行',
    'alpha\t~/.claude/skills', 'alpha\t~/.agents/skills',
    'beta\t~/.claude/skills',
    'dup-a\t~/.codex/skills', 'dup-b\t~/.codex/skills',
    'idle\t~/.agents/skills',
  ].join('\n'));

  const usage = path.join(root, 'skill-usage.jsonl');
  fs.writeFileSync(usage, [
    line({ time: '2026-11-05T10:00:00Z', session: 's1', cwd: '/x', skill: 'alpha' }),
    line({ time: '2026-11-06T17:30:00Z', session: 's2', cwd: '/x', skill: 'alpha' }), // 北京时间已是 11-07
    line({ time: '2026-09-01T10:00:00Z', session: 's0', cwd: '/x', skill: 'beta' }), // 窗口外
    line({ time: '2026-11-05T10:00:00Z', session: 's3', cwd: '/x', skill: 'other-plugin:tdd' }), // 不是自建
    '{坏行',
    '',
  ].join('\n'));

  const codex = path.join(root, 'sessions');
  const day = path.join(codex, '2026', '11', '04');
  fs.mkdirSync(day, { recursive: true });
  // 会话 1：读了两次 alpha（只算一次），读了 dup-a；系统提示里的 skill 清单不算。
  fs.writeFileSync(path.join(day, 'rollout-1.jsonl'), [
    line({ timestamp: '2026-11-04T01:00:00Z', type: 'session_meta', payload: { id: '1', base_instructions: { text: '- idle: file: /u/.agents/skills/idle/SKILL.md' } } }),
    line({ timestamp: '2026-11-04T01:00:01Z', type: 'response_item', payload: { type: 'message', role: 'developer', content: [{ text: 'skills/beta/SKILL.md' }] } }),
    toolCall('2026-11-04T01:01:00Z', 'sed -n 1,200p /u/.agents/skills/alpha/SKILL.md'),
    toolCall('2026-11-04T01:02:00Z', 'cat /u/.agents/skills/alpha/SKILL.md'),
    toolCall('2026-11-04T01:03:00Z', 'cat /u/.codex/skills/dup-a/SKILL.md'),
  ].join('\n'));
  // 会话 2：zst 压缩，custom_tool_call 读 alpha。
  const zst = [
    line({ timestamp: '2026-11-04T05:00:00Z', type: 'session_meta', payload: { id: '2' } }),
    line({ timestamp: '2026-11-04T05:01:00Z', type: 'response_item', payload: { type: 'custom_tool_call', name: 'exec', input: 'await read("/u/.agents/skills/alpha/SKILL.md")' } }),
  ].join('\n');
  fs.writeFileSync(path.join(day, 'rollout-2.jsonl.zst'), zlib.zstdCompressSync(Buffer.from(zst)));
  // 坏的 zst 文件：跳过并计数，不中断。
  fs.writeFileSync(path.join(day, 'rollout-3.jsonl.zst'), 'not zstd');
  // 窗口外的日期目录不扫。
  const old = path.join(codex, '2026', '08', '01');
  fs.mkdirSync(old, { recursive: true });
  fs.writeFileSync(path.join(old, 'rollout-old.jsonl'), toolCall('2026-08-01T01:00:00Z', 'cat /u/skills/idle/SKILL.md'));

  return { root, repo, usage, codex };
}

test('统计 Claude 按次、Codex 按会话，并只认工具调用', () => {
  const f = fixture();
  const md = run({ ...parseArgs(['--repo', f.repo, '--usage', f.usage, '--codex', f.codex]) }, NOW);
  assert.match(md, /\| alpha \| Claude、Codex \| 2 \| 2 \| 2026-11-07 \| 1\.0\.0 \| 有 \| 有 \|/);
  assert.match(md, /\| beta \| Claude \| 0 \| 0 \| — \| — \| 无 \| 无 \|/);
  assert.match(md, /\| dup-a \| Codex \| 0 \| 1 \| 2026-11-04 \| 3\.0\.1 \|/);
  assert.match(md, /\| idle \| Codex \| 0 \| 0 \| — \|/);
  assert.match(md, /1 行读不了已跳过/);
  assert.match(md, /扫了 2 个会话（1 个读不了）/);
});

test('提案：重复拷贝提合并，有数据的 0 调用提观察去留', () => {
  const f = fixture();
  const md = run(parseArgs(['--repo', f.repo, '--usage', f.usage, '--codex', f.codex]), NOW);
  assert.match(md, /\*\*合并\*\*：`dup-a`（v3\.0\.1，近 30 天 1 次）、`dup-b`（v1\.0\.1，近 30 天 0 次）/);
  assert.match(md, /\*\*观察去留\*\*：`idle` 近 30 天 0 调用/);
  assert.match(md, /\*\*观察去留\*\*：`beta`/);
  assert.match(md, /\*\*观察去留\*\*：`dup-b`/);
  assert.doesNotMatch(md, /观察去留\*\*：`alpha`/);
  assert.match(md, /`beta`：缺 版本号、evals、CHANGELOG/);
  assert.doesNotMatch(md, /`alpha`：缺/);
});

test('skill-usage.jsonl 不存在时照常出报告，Claude 侧的 0 调用不提去留', () => {
  const f = fixture();
  const md = run(parseArgs(['--repo', f.repo, '--usage', path.join(f.root, 'missing.jsonl'), '--codex', f.codex]), NOW);
  assert.match(md, /Claude：\*\*没有数据\*\*/);
  assert.doesNotMatch(md, /观察去留\*\*：`beta`/);
  assert.match(md, /数据不足、这次不提去留的：.*`beta`/);
  assert.match(md, /观察去留\*\*：`idle`/); // 只链接到 Codex，有数据
});

test('--days 放宽窗口后能看到更早的使用', () => {
  const f = fixture();
  const md = run(parseArgs(['--repo', f.repo, '--usage', f.usage, '--codex', f.codex, '--days', '120']), NOW);
  assert.match(md, /\| beta \| Claude \| 1 \|/);
  assert.match(md, /\| idle \| Codex \| 0 \| 1 \| 2026-08-01 \|/);
});

test('codexHitsInText 不把对话正文和系统提示里的路径算作调用', () => {
  const text = [
    line({ timestamp: '2026-11-04T01:00:00Z', type: 'response_item', payload: { type: 'message', content: 'skills/alpha/SKILL.md' } }),
    line({ timestamp: '2026-11-04T01:00:00Z', type: 'event_msg', payload: { type: 'exec_command_end', stdout: 'skills/alpha/SKILL.md' } }),
  ].join('\n');
  assert.equal(codexHitsInText(text, new Set(['alpha'])).size, 0);
});

test('codexHitsInText 认 workdir 写法，不认沙盒里的测试拷贝', () => {
  const names = new Set(['excel-aura', 'ai-landing-method']);
  const viaWorkdir = line({ timestamp: '2026-11-04T01:00:00Z', type: 'response_item', payload: { type: 'custom_tool_call', input: 'tools.exec_command({cmd:"cat SKILL.md",workdir:"/u/.agents/skills/excel-aura"})' } });
  const viaArgs = line({ timestamp: '2026-11-04T01:00:00Z', type: 'response_item', payload: { type: 'function_call', arguments: JSON.stringify({ cmd: 'cat SKILL.md', workdir: '/u/.claude/skills/ai-landing-method/' }) } });
  const sandbox = line({ timestamp: '2026-11-04T01:00:00Z', type: 'response_item', payload: { type: 'custom_tool_call', input: 'tools.exec_command({cmd:"cat SKILL.md",workdir:"/u/Sandbox/2026-11-05-ai-landing-method/verify2/skill"})' } });
  assert.deepEqual([...codexHitsInText([viaWorkdir, viaArgs, sandbox].join('\n'), names).keys()].sort(), ['ai-landing-method', 'excel-aura']);
  assert.equal(codexHitsInText(sandbox, names).size, 0);
});

test('日期按北京时间显示，跨日和跨年', () => {
  assert.equal(fmtDate(Date.parse('2026-11-06T16:30:00Z')), '2026-11-07');
  assert.equal(fmtDate(Date.parse('2026-12-31T17:00:00Z')), '2027-01-01');
  assert.equal(fmtDate(null), '—');
});

test('命令行：参数错误退出码 2，--help 正常', () => {
  assert.throws(() => execFileSync('node', [SCRIPT, '--days', '0'], { stdio: 'pipe' }), (e) => e.status === 2);
  assert.throws(() => execFileSync('node', [SCRIPT, '--bogus'], { stdio: 'pipe' }), (e) => e.status === 2);
  assert.match(execFileSync('node', [SCRIPT, '--help']).toString(), /用法/);
});
