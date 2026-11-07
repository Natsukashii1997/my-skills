#!/usr/bin/env node
// 自建 skill 的机器可读索引：数码世界等只读消费方从这里拿 skill 清单，不各自解析仓库。
// 只读：不改 skill、不改 links.tsv、不碰 ~/.claude、~/.agents、~/.codex。
//
// 用法：node scripts/export-skill-index.mjs            写 catalog/skills.json（不入库）
//       node scripts/export-skill-index.mjs --stdout   只打印
//
// 口径（《项目体系重构 V1.3》第 7 节）：
// - release_status、install_status 一律「未核定」：有 version、CHANGELOG、links.tsv 只说明元数据齐不齐，
//   不等于正式发布；是否真装上要核对链接目标，本脚本不做。
// - 缺的字段写 null，不猜。
// - 不写绝对路径：路径一律相对仓库，links.tsv 的目标保留它原本的 ~ 写法。

import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const SCHEMA_VERSION = 1;
export const UNVERIFIED = '未核定';
const SOURCE_REPO = 'Natsukashii1997/my-skills';

function frontmatter(text) {
  const m = text.match(/^---\n([\s\S]*?)\n---/);
  if (!m) return {};
  const fm = m[1];
  const field = (re) => (fm.match(re) || [])[1]?.trim() ?? null;
  return {
    name: field(/^name:\s*(.+)$/m),
    description: field(/^description:\s*(.+)$/m),
    version: field(/^metadata:\s*\n(?:[ \t]+.*\n)*?[ \t]+version:\s*["']?([^"'\s]+)["']?/m),
    governance: /^metadata:\s*\n(?:[ \t]+.*\n)*?[ \t]+governance:/m.test(fm),
  };
}

function git(repo, args) {
  try {
    return execFileSync('git', ['-C', repo, ...args], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
  } catch {
    return '';
  }
}

function readLinks(repo) {
  const links = {};
  const file = path.join(repo, 'links.tsv');
  if (!fs.existsSync(file)) return links;
  for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
    if (!line.trim() || line.startsWith('#')) continue;
    const [name, target] = line.split('\t').map((s) => s?.trim());
    if (name && target) (links[name] ||= []).push(target);
  }
  return links;
}

function changelogVersions(file) {
  if (!fs.existsSync(file)) return null;
  return [...fs.readFileSync(file, 'utf8').matchAll(/^##\s+v?(\d+\.\d+\.\d+)/gm)].map((m) => m[1]);
}

export function buildIndex(repo, { now = new Date() } = {}) {
  const links = readLinks(repo);
  const skillsDir = path.join(repo, 'skills');
  const skills = fs.readdirSync(skillsDir, { withFileTypes: true })
    .filter((d) => d.isDirectory() && fs.existsSync(path.join(skillsDir, d.name, 'SKILL.md')))
    .map((d) => d.name)
    .sort()
    .map((id) => {
      const dir = path.join(skillsDir, id);
      const fm = frontmatter(fs.readFileSync(path.join(dir, 'SKILL.md'), 'utf8'));
      const changelog = changelogVersions(path.join(dir, 'CHANGELOG.md'));
      const hasEvals = fs.existsSync(path.join(dir, 'evals.md')) || fs.existsSync(path.join(dir, 'evals'));
      const [sha, date] = git(repo, ['log', '-1', '--format=%H%x09%cI', '--', `skills/${id}`]).split('\t');
      const missing = [
        fm.version ? null : 'version',
        changelog ? null : 'changelog',
        hasEvals ? null : 'evals',
        fm.governance ? null : 'governance',
      ].filter(Boolean);
      return {
        id,
        name: fm.name ?? null,
        name_matches_dir: fm.name === id,
        summary: fm.description ?? null,
        version: fm.version ?? null,
        has_changelog: changelog !== null,
        changelog_versions: changelog,
        has_evals: hasEvals,
        link_targets: links[id] ?? [],
        source_path: `skills/${id}`,
        last_commit: sha ? { sha, date } : null,
        metadata_missing: missing,
        release_status: UNVERIFIED,
        install_status: UNVERIFIED,
      };
    });
  const ids = skills.map((s) => s.id);
  if (new Set(ids).size !== ids.length) throw new Error('skill id 重复');
  return {
    schema_version: SCHEMA_VERSION,
    generated_at: now.toISOString(),
    source_repo: SOURCE_REPO,
    source_commit: git(repo, ['rev-parse', 'HEAD']) || null,
    source_dirty: git(repo, ['status', '--porcelain', '--', 'skills', 'links.tsv']) !== '',
    skills,
  };
}

function main() {
  const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  const json = JSON.stringify(buildIndex(repo), null, 2) + '\n';
  if (process.argv.includes('--stdout')) {
    process.stdout.write(json);
    return;
  }
  const out = path.join(repo, 'catalog', 'skills.json');
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, json);
  console.log(`已写 catalog/skills.json（${JSON.parse(json).skills.length} 个 skill）`);
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? '').href) main();
