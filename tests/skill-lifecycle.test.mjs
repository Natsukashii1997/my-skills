import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadSkills } from '../scripts/monthly-health.mjs';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

// AGENTS.md：此次修改的存量 Skill 必须同时补版本、CHANGELOG 和 evals。
for (const name of ['skill-governance-audit', 'vault-backup', 'business-notice', 'three-versions']) {
  test(`${name} 的版本、修订记录和评估材料符合生命周期约定`, () => {
    const entry = loadSkills(REPO).find((skill) => skill.name === name);
    assert.match(entry.version ?? '', /^\d+\.\d+\.\d+$/);
    assert.equal(entry.evals, true);
    assert.equal(entry.changelog, true);
    const dir = path.join(REPO, 'skills', name);
    const skill = fs.readFileSync(path.join(dir, 'SKILL.md'), 'utf8');
    assert.match(skill, new RegExp(`^  version: "${entry.version.replaceAll('.', '\\.')}"$`, 'm'));
    const changelog = fs.readFileSync(path.join(dir, 'CHANGELOG.md'), 'utf8');
    assert.equal(changelog.match(/^## (\d+\.\d+\.\d+) - /m)?.[1], entry.version);
    const evals = fs.readFileSync(path.join(dir, 'evals.md'), 'utf8');
    const cases = evals.match(/^## E\d+ /gm) ?? [];
    assert.ok(cases.length >= 3 && cases.length <= 5);
    for (const label of ['请求', '给的材料', '期望行为', '判定标准', '不该出现']) {
      assert.equal(evals.match(new RegExp(`\\*\\*${label}\\*\\*`, 'g'))?.length, cases.length);
    }
    assert.match(evals, /不该用/);
    assert.match(evals, /## 盲测记录/);
  });
}
