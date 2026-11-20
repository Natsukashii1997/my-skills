import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { buildIndex, SCHEMA_VERSION, UNVERIFIED } from '../scripts/export-skill-index.mjs';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function fixture() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'skill-index-'));
  const sh = (...a) => execFileSync('git', ['-C', dir, ...a], { stdio: 'ignore' });
  sh('init', '-q');
  sh('config', 'user.email', 't@example.com');
  sh('config', 'user.name', 't');
  const w = (p, s) => { fs.mkdirSync(path.dirname(path.join(dir, p)), { recursive: true }); fs.writeFileSync(path.join(dir, p), s); };
  w('skills/full/SKILL.md', '---\nname: full\ndescription: 完整的样例\nmetadata:\n  version: "1.2.0"\n  governance:\n    network: none\n---\n正文\n');
  w('skills/full/CHANGELOG.md', '# CHANGELOG\n\n## 1.2.0 - 2026-11-07\n\n## 1.1.0 - 2026-11-01\n');
  w('skills/full/evals.md', '# evals\n');
  w('skills/bare/SKILL.md', '---\nname: other-name\ndescription: 只有名字和说明\n---\n');
  w('skills/not-a-skill/README.md', '没有 SKILL.md\n');
  w('links.tsv', '# 注释\nfull\t~/.claude/skills\nfull\t~/.agents/skills\n');
  sh('add', '-A');
  sh('commit', '-q', '-m', 'init');
  return dir;
}

test('字段齐全、缺项为 null、只认有 SKILL.md 的目录', () => {
  const idx = buildIndex(fixture());
  assert.equal(idx.schema_version, SCHEMA_VERSION);
  assert.equal(idx.source_repo, 'Natsukashii1997/my-skills');
  assert.match(idx.source_commit, /^[0-9a-f]{40}$/);
  assert.equal(idx.source_dirty, false);
  assert.deepEqual(idx.skills.map((s) => s.id), ['bare', 'full']);
  const [bare, full] = idx.skills;
  assert.equal(full.version, '1.2.0');
  assert.deepEqual(full.changelog_versions, ['1.2.0', '1.1.0']);
  assert.equal(full.has_evals, true);
  assert.deepEqual(full.link_targets, ['~/.claude/skills', '~/.agents/skills']);
  assert.deepEqual(full.metadata_missing, []);
  assert.equal(bare.version, null);
  assert.equal(bare.changelog_versions, null);
  assert.equal(bare.has_changelog, false);
  assert.deepEqual(bare.link_targets, []);
  assert.deepEqual(bare.metadata_missing, ['version', 'changelog', 'evals', 'governance']);
  assert.equal(bare.name_matches_dir, false);
  for (const s of idx.skills) {
    assert.equal(s.release_status, UNVERIFIED);
    assert.equal(s.install_status, UNVERIFIED);
    assert.match(s.last_commit.sha, /^[0-9a-f]{40}$/);
  }
});

test('同一来源两次生成，除 generated_at 外完全一致；改动未提交时标 source_dirty', () => {
  const dir = fixture();
  const a = buildIndex(dir, { now: new Date('2026-01-01T00:00:00Z') });
  const b = buildIndex(dir, { now: new Date('2026-02-01T00:00:00Z') });
  assert.notEqual(a.generated_at, b.generated_at);
  assert.deepEqual({ ...a, generated_at: null }, { ...b, generated_at: null });
  fs.appendFileSync(path.join(dir, 'skills/bare/SKILL.md'), '改了\n');
  assert.equal(buildIndex(dir).source_dirty, true);
});

test('本仓库真实索引：ID 唯一、不含绝对路径、每个 skill 都在 README 表格里', () => {
  const idx = buildIndex(REPO);
  const ids = idx.skills.map((s) => s.id);
  assert.ok(ids.length > 0);
  assert.equal(new Set(ids).size, ids.length);
  const text = JSON.stringify(idx);
  assert.ok(!text.includes(os.homedir()), '索引里出现了本机绝对路径');
  assert.ok(!/"\/(Users|home)\//.test(text), '索引里出现了绝对路径');
  const readme = fs.readFileSync(path.join(REPO, 'README.md'), 'utf8');
  for (const id of ids) assert.ok(readme.includes(`(skills/${id}/SKILL.md)`), `README 表格缺 ${id}`);
});

test('无版本号的多行 metadata 在限时内完成索引', () => {
  const dir = fixture();
  try {
    fs.writeFileSync(path.join(dir, 'skills/bare/SKILL.md'), `---
name: bare
description: 合法的无版本元数据
metadata:
  governance:
    dependencies:
${Array.from({ length: 40 }, (_, i) => `      - dependency-${i}`).join('\n')}
---
`);
    const code = `import { buildIndex } from ${JSON.stringify(path.join(REPO, 'scripts/export-skill-index.mjs'))};
      console.log(JSON.stringify(buildIndex(process.argv[1]).skills.find(s => s.id === 'bare')));`;
    const result = JSON.parse(execFileSync(process.execPath, ['--input-type=module', '-e', code, dir],
      { encoding: 'utf8', timeout: 5000 }));
    assert.equal(result.version, null);
    assert.deepEqual(result.metadata_missing, ['version', 'changelog', 'evals']);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('metadata 只读取直接子字段，支持治理块后的版本号', () => {
  const dir = fixture();
  try {
    for (const [metadata, version, governance] of [
      ['metadata:\n    governance:\n      dependencies:\n        - demo\n    version: "2.3.4"', '2.3.4', true],
      ['metadata:\n  nested:\n    version: "9.9.9"\n    governance: {}\nother:\n  version: "8.8.8"\n  governance: {}', null, false],
    ]) {
      fs.writeFileSync(path.join(dir, 'skills/bare/SKILL.md'), `---\nname: bare\ndescription: 样例\n${metadata}\n---\n`);
      const item = buildIndex(dir).skills.find(s => s.id === 'bare');
      assert.equal(item.version, version);
      assert.equal(!item.metadata_missing.includes('governance'), governance);
    }
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
