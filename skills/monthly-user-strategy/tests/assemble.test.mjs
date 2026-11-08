// assemble.mjs 的预检与机械字段。运行：node --test skills/monthly-user-strategy/tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { assemble, defaultPriority } from '../scripts/assemble.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const M = '2026-12';
const cov = (value, ratio) => ({ value, status: value === 'unknown' ? 'unknown' : 'inferred', ratio, dateQuality: { verified: 1, ruled: 0, source: 2, guess: 0 }, coverage: { schools: 3, calculable: 3, active: 2, notCovered: 1, insufficient: 0 }, byCountry: null });
const facts = (extra = {}) => ({
  month: M, schemaVersion: '2.1', inputFingerprint: 'fp0000000000abcd', baseRevision: null,
  rules: { versions: { lifecycle: 'lifecycle-v0.2' } },
  coverage: { uk: cov('高', 0.6), us: cov('中', 0.3), hk: cov('低', 0.1), au: cov('高', 0.5), ca: cov('unknown', null), other: { ...cov('高', 0.45), byCountry: { sg: cov('高', 0.5) } } },
  evidence: [
    { evidenceId: 'EV-ver', evidenceVersion: 'v1', kind: 'timeline', country: 'uk', school: '爱丁堡大学', eventType: 'Final', verification: 'verified', dates: { from: '2026-12-09', to: '2026-12-21', precision: 'day' }, ambiguous: false },
    { evidenceId: 'EV-src', evidenceVersion: 'v2', kind: 'timeline', country: 'uk', school: '格拉斯哥大学', eventType: 'Final', verification: 'source', dates: { from: '2026-12-07', to: '2026-12-18', precision: 'day' }, ambiguous: false },
  ],
  windows: [], anomalies: [], bizcard: null, revision: null, ...extra,
});
const SELF = ['事实与来源核验', '地区与人群覆盖', '任务与需求推导', '购买障碍论证', '机会排序合理性', '章节一致性与反例检查', '跨部门发布完整性'].map(item => ({ item, result: '通过' }))
  .concat({ item: '促销匹配及适用性（批 2 起）', result: '不适用（批 2 起）' });
const empty = { priority: undefined, emptyReason: '当前没有足够证据形成独立情境（测试）' };
const unknownRenew = { status: 'unknown', evidenceStrength: 'none', evidenceRefs: [], gap: '缺少存量学员下一阶段任务与续报信息', route: { status: 'available', source: 'SRC-bizcard' } };
const draft = (patch = {}) => ({
  month: M, declared: { executor: 'Claude', model: 'test' },
  judgement: { text: '英国 Final 季集中，需求以复习规划为主。', claims: ['CLM-2026-12-001'] },
  brief: { common: [{ text: '本月未提供业务背景，用户需求与购买判断均基于学校时间线推断', status: 'inferred', evidenceStrength: 'weak', evidenceRefs: [], limitations: '没有业务证据' }] },
  regions: { uk: { priority: '主战场' }, us: empty, hk: empty, au: { priority: undefined, emptyReason: '测试' }, ca: { priority: '平稳', reason: '覆盖率未知，样本不足', emptyReason: '测试' }, other: empty },
  scenarios: [{ id: 'SCN-2026-12-uk-01', region: 'uk', countries: ['uk'], schools: ['爱丁堡大学'], academicStage: 'undergraduate', phase: 'Term 1 Final', keyTask: '准备 Final', targetRelation: '通用', observedRelation: { value: 'unknown', evidenceRefs: [] }, evidenceRefs: ['EV-ver', 'EV-src'] }],
  claims: [
    { id: 'CLM-2026-12-001', scenario: 'SCN-2026-12-uk-01', claimType: 'task', text: '12 月中旬进入 Final 考试', status: 'known', evidenceStrength: 'strong', evidenceRefs: ['EV-ver'] },
    { id: 'CLM-2026-12-002', scenario: 'SCN-2026-12-uk-01', claimType: 'barrier', barrierCode: 'BR-M3', targetRelation: '新签', barrierRole: 'primary', text: '可能怀疑辅导效果', status: 'inferred', evidenceStrength: 'weak', evidenceRefs: [], limitations: '缺少用户决策行为证据', rule: '常识推断' },
    { id: 'CLM-2026-12-003', scenario: 'SCN-2026-12-uk-01', claimType: 'barrier', barrierCode: 'BR-R2', targetRelation: '续费', barrierRole: 'primary', text: '续费障碍待查', ...unknownRenew },
    { id: 'CLM-2026-12-004', scenario: 'SCN-2026-12-uk-01', claimType: 'readiness', targetRelation: '续费', text: '续费准备度未知', level: null, ...unknownRenew },
  ],
  research: { selfCheck: SELF },
  ...patch,
});
const withClaim = (i, change) => { const d = draft(); d.claims[i] = { ...d.claims[i], ...change }; return d; };
const hasError = (r, text) => r.errors.some(e => e.includes(text));

test('通过时补齐机械字段', () => {
  const r = assemble(facts(), draft(), { version: '9.9.9' });
  assert.deepEqual(r.errors, []);
  const d = r.document;
  assert.equal(d.regions.length, 6);
  assert.deepEqual(d.regions.map(x => x.key), ['uk', 'us', 'hk', 'au', 'ca', 'other']);
  assert.equal(d.regions[0].activity.ratio, 0.6);
  assert.deepEqual(d.regions[0].scenarios, ['SCN-2026-12-uk-01']);
  assert.equal(d.regions[1].priority.value, '主战场'); // us 中 → 默认主战场
  assert.equal(d.regions[5].activity.byCountry.sg.value, '高');
  assert.deepEqual(d.claims[0].refVersions, { 'EV-ver': 'v1' });
  assert.ok(d.claims.every(c => c.origin === 'skill'));
  assert.deepEqual(d.opportunities, []);
  assert.equal(d.producedBy.declared.skillVersion, '9.9.9');
  assert.equal(d.window.to, '2026-12-31');
  assert.equal(d.window.preheatTo, '2027-01-14');
  assert.ok(d.research.notes.some(n => n.startsWith('自检｜事实与来源核验｜通过')));
  assert.equal(r.submitArgs.inputFingerprint, 'fp0000000000abcd');
  assert.match(r.submitArgs.idempotencyKey, /^mus-2026-12-fp0000000000abcd-[0-9a-f]{12}$/);
});

test('幂等键由内容决定：同内容同键，改内容换键', () => {
  const a = assemble(facts(), draft(), { version: '1' }).submitArgs.idempotencyKey;
  assert.equal(assemble(facts(), draft(), { version: '1' }).submitArgs.idempotencyKey, a);
  assert.notEqual(assemble(facts(), withClaim(0, { text: '改一个字' }), { version: '1' }).submitArgs.idempotencyKey, a);
});

test('默认优先级矩阵', () => {
  assert.equal(defaultPriority('uk', '低'), '次要');
  assert.equal(defaultPriority('hk', '中'), '次要');
  assert.equal(defaultPriority('other', '高'), '次要');
  assert.equal(defaultPriority('ca', 'unknown'), null);
});

test('09 #2：没有行为证据的障碍不能 known，M2 只能 unknown', () => {
  assert.ok(hasError(assemble(facts(), withClaim(1, { status: 'known', evidenceStrength: 'strong', evidenceRefs: ['EV-ver'] })), '最高 inferred + weak'));
  assert.ok(hasError(assemble(facts(), withClaim(1, { barrierCode: 'BR-M2' })), '须为 unknown'));
  assert.ok(hasError(assemble(facts(), withClaim(1, { evidenceStrength: 'partial' })), '最高 inferred + weak'));
});

test('09 #4：没有存量用户情况时续费判断须 unknown 且 route 指向背景卡', () => {
  assert.ok(hasError(assemble(facts(), withClaim(2, { status: 'inferred', evidenceStrength: 'weak', limitations: 'x' })), '续费的障碍'));
  assert.ok(hasError(assemble(facts(), withClaim(3, { route: { status: 'unavailable', source: 'SRC-crm' } })), 'SRC-bizcard'));
  const card = { 存量用户情况: [{ id: 'B-00000001', text: '…', type: '业务观察' }] };
  assert.ok(!hasError(assemble(facts({ bizcard: card }), withClaim(2, { status: 'inferred', evidenceStrength: 'weak', limitations: 'x' })), '续费的障碍'));
});

test('09 #21：原表日期不能支撑 known', () => {
  assert.ok(hasError(assemble(facts(), withClaim(0, { evidenceRefs: ['EV-src'] })), '没有一条到 strong'));
});

test('09 #22：空地区必须写 emptyReason', () => {
  const d = draft(); d.regions.us = { priority: undefined };
  assert.ok(hasError(assemble(facts(), d), 'regions.us'));
});

test('其他拦截：主障碍个数、编造 Evidence、manual、续费专属障碍用于新签、缺自检', () => {
  assert.ok(hasError(assemble(facts(), withClaim(1, { barrierRole: 'secondary' })), '主障碍须恰好一个'));
  assert.ok(hasError(assemble(facts(), withClaim(0, { evidenceRefs: ['EV-madeup'] })), '不在事实底稿里'));
  assert.ok(hasError(assemble(facts(), withClaim(0, { origin: 'manual' })), 'origin=manual'));
  assert.ok(hasError(assemble(facts(), withClaim(1, { barrierCode: 'BR-R1' })), '不适用于新签'));
  assert.ok(hasError(assemble(facts(), draft({ research: {} })), '缺少自检项'));
  assert.ok(hasError(assemble(facts(), withClaim(3, { route: { status: 'available', source: 'SRC-wechat' } })), '不在来源登记表内'));
});

test('正式版本里常浩手写的 Claim 原样带上，不能同号', () => {
  const manual = { id: 'CLM-2026-12-090', scenario: 'SCN-2026-12-uk-01', claimType: 'pain', painKind: 'typical', text: '常浩写的', status: 'inferred', evidenceStrength: 'weak', evidenceRefs: [], limitations: 'x', origin: 'manual', refVersions: {} };
  const r = assemble(facts({ revision: { claims: [manual] } }), draft());
  assert.deepEqual(r.document.claims.find(c => c.id === manual.id), manual);
  const clash = draft(); clash.claims.push({ ...manual, origin: undefined, text: '冒名' });
  assert.ok(hasError(assemble(facts({ revision: { claims: [manual] } }), clash), '同号'));
});

test('命令行：预检不过时退出码 2 且不写提交参数；digest 能读同一份底稿', () => {
  const dir = mkdtempSync(join(tmpdir(), 'mus-'));
  writeFileSync(join(dir, 'facts.json'), JSON.stringify(facts()));
  writeFileSync(join(dir, 'bad.json'), JSON.stringify(withClaim(0, { evidenceRefs: ['EV-madeup'] })));
  writeFileSync(join(dir, 'good.json'), JSON.stringify(draft()));
  const script = join(here, '..', 'scripts', 'assemble.mjs');
  assert.throws(() => execFileSync('node', [script, join(dir, 'facts.json'), join(dir, 'bad.json'), '--out-dir', join(dir, 'bad')], { stdio: 'pipe' }), e => e.status === 2);
  execFileSync('node', [script, join(dir, 'facts.json'), join(dir, 'good.json'), '--out-dir', join(dir, 'good')], { stdio: 'pipe' });
  assert.equal(JSON.parse(readFileSync(join(dir, 'good', 'submit-args.json'), 'utf8')).month, M);
  const md = execFileSync('node', [join(here, '..', 'scripts', 'digest.mjs'), join(dir, 'facts.json')], { encoding: 'utf8' });
  assert.match(md, /## 英国（uk）/);
  assert.match(md, /EV-ver/);
  assert.match(md, /默认优先级（05 §7）：主战场/);
});

test('换新底稿重组装：依据版本变化或消失时拦截，不静默更新 refVersions', () => {
  const changed = facts(); changed.evidence = changed.evidence.map(e => e.evidenceId === 'EV-ver' ? { ...e, evidenceVersion: 'v1b' } : e);
  assert.ok(hasError(assemble(changed, draft(), { prevFacts: facts() }), '版本已变化'));
  const gone = facts(); gone.evidence = gone.evidence.filter(e => e.evidenceId !== 'EV-src');
  assert.ok(hasError(assemble(gone, draft(), { prevFacts: facts() }), '已不存在'));
  const same = facts({ inputFingerprint: 'fp_new_snapshot0' });
  const r = assemble(same, draft(), { prevFacts: facts() });
  assert.deepEqual(r.errors, []);
  assert.match(r.submitArgs.idempotencyKey, /fp_new_snapshot0/);
});
