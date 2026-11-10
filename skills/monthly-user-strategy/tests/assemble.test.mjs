// assemble.mjs 的预检与机械字段。运行：node --test skills/monthly-user-strategy/tests/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { existsSync, mkdtempSync, writeFileSync, readFileSync } from 'node:fs';
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
SELF[0].regionCheck = { uk: '逐校核过 2 所，无例外' };
const empty = { priority: undefined, emptyReason: '当前没有足够证据形成独立情境（测试）' };
const unknownRenew = { status: 'unknown', evidenceStrength: 'none', evidenceRefs: [], gap: '缺少存量学员下一阶段任务与续报信息', route: { status: 'available', source: 'SRC-bizcard' } };
const draft = (patch = {}) => ({
  month: M, basedOnFingerprint: 'fp0000000000abcd', declared: { executor: 'Claude', model: 'test' },
  judgement: { text: '英国 Final 季集中，需求以复习规划为主。', claims: ['CLM-2026-12-001'] },
  brief: { common: [{ text: '本月未提供业务背景，用户需求与购买判断均基于学校时间线推断', status: 'inferred', evidenceStrength: 'weak', evidenceRefs: [], limitations: '没有业务证据' }] },
  regions: { uk: { priority: '主战场' }, us: empty, hk: empty, au: { priority: undefined, emptyReason: '测试' }, ca: { priority: '平稳', reason: '覆盖率未知，样本不足', emptyReason: '测试' }, other: empty },
  scenarios: [{ id: 'SCN-2026-12-uk-01', region: 'uk', countries: ['uk'], schools: ['爱丁堡大学'], academicStage: 'undergraduate', phase: 'Term 1 Final', keyTask: '准备 Final', targetRelation: '通用', observedRelation: { value: 'unknown', evidenceRefs: [] }, evidenceRefs: ['EV-ver', 'EV-src'] }],
  claims: [
    { id: 'CLM-2026-12-001', scenario: 'SCN-2026-12-uk-01', claimType: 'task', text: '12 月中旬进入 Final 考试', status: 'known', evidenceStrength: 'strong', evidenceRefs: ['EV-ver'] },
    { id: 'CLM-2026-12-002', scenario: 'SCN-2026-12-uk-01', claimType: 'barrier', barrierCode: 'BR-M3', targetRelation: '新签', barrierRole: 'primary', text: '可能怀疑辅导效果', status: 'inferred', evidenceStrength: 'weak', evidenceRefs: [], limitations: '缺少用户决策行为证据', rule: '常识推断；暂定研究重点' },
    { id: 'CLM-2026-12-003', scenario: 'SCN-2026-12-uk-01', claimType: 'barrier', barrierCode: 'BR-R2', targetRelation: '续费', barrierRole: 'primary', text: '续费障碍待查', rule: '暂定研究重点', ...unknownRenew },
    { id: 'CLM-2026-12-004', scenario: 'SCN-2026-12-uk-01', claimType: 'readiness', targetRelation: '续费', text: '续费准备度未知', level: null, ...unknownRenew },
    { id: 'CLM-2026-12-005', scenario: 'SCN-2026-12-uk-01', claimType: 'academic_need', text: '考试节点可能带动复习规划需求', status: 'inferred', evidenceStrength: 'weak', evidenceRefs: ['EV-src'], limitations: '只有时间线' },
    { id: 'CLM-2026-12-006', scenario: 'SCN-2026-12-uk-01', claimType: 'pain', painKind: 'typical', text: '多门考试叠加难以排期', status: 'inferred', evidenceStrength: 'weak', evidenceRefs: [], limitations: '典型困难' },
    { id: 'CLM-2026-12-007', scenario: 'SCN-2026-12-uk-01', claimType: 'need_strength', level: '中', text: '需求强度中', status: 'inferred', evidenceStrength: 'partial', evidenceRefs: ['EV-src'], limitations: '日历推断', rule: 'lifecycle-v0.2/Final' },
    { id: 'CLM-2026-12-008', scenario: 'SCN-2026-12-uk-01', claimType: 'readiness', targetRelation: '新签', text: '新签准备度未知', level: null, status: 'unknown', evidenceStrength: 'none', evidenceRefs: [], gap: '缺少咨询、成交等行为证据', route: { status: 'available', source: 'SRC-bizcard' } },
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
  // 默认只写 document.json，不留能直接提交的参数；带 --submit-args 才写
  execFileSync('node', [script, join(dir, 'facts.json'), join(dir, 'good.json'), '--out-dir', join(dir, 'plain')], { stdio: 'pipe' });
  assert.ok(existsSync(join(dir, 'plain', 'document.json')));
  assert.ok(!existsSync(join(dir, 'plain', 'submit-args.json')));
  execFileSync('node', [script, join(dir, 'facts.json'), join(dir, 'good.json'), '--out-dir', join(dir, 'good'), '--submit-args'], { stdio: 'pipe' });
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

// —— GPT 验收（2026-11-08）P1-01～04、P2-01 的反例与正例 ——
// 业务证据的适用范围只看背景卡条目上的结构化字段 countries、relation（#78，和 niuma-home 服务端同一判法）；原文不参与判断。
const BIZ = [
  { evidenceId: 'EV-obs', evidenceVersion: 'o1', kind: 'business', field: '用户观察', bizType: '业务观察', countries: ['uk'], relation: '新签', text: '英国学生 11 月下旬咨询集中在 Final 复习规划，多数问能不能只约考前几次课', ambiguous: false },
  { evidenceId: 'EV-fact', evidenceVersion: 'f1', kind: 'business', field: '用户观察', bizType: '事实记录', countries: ['uk'], relation: '新签', text: '11 月英国新签咨询 46 条，其中 19 条明确说想等 1 月 Final 考完再决定报不报', ambiguous: false },
  { evidenceId: 'EV-mgmt', evidenceVersion: 'g1', kind: 'business', field: '负责人特别判断', bizType: '管理判断', countries: ['uk'], relation: '通用', text: '我觉得英国学生今年对价格更敏感', ambiguous: false },
  // 原文写明了英国、新签，但没填字段：仍是范围不明
  { evidenceId: 'EV-nowhere', evidenceVersion: 'n1', kind: 'business', field: '用户观察', bizType: '事实记录', text: '11 月英国新签咨询 46 条，其中 19 条明确说想等考完再决定报不报', ambiguous: false },
  { evidenceId: 'EV-school', evidenceVersion: 's1', kind: 'business', field: '用户观察', bizType: '业务观察', countries: ['uk'], relation: '通用', text: '爱丁堡大学的学生多数问能不能只约考前几次课', ambiguous: false },
  { evidenceId: 'EV-renew', evidenceVersion: 'r1', kind: 'business', field: '存量用户情况', bizType: '业务观察', countries: ['uk'], relation: '续费', text: '英国在读老学员多数 1 月考完，还没想好下学期要不要继续', ambiguous: false },
  { evidenceId: 'EV-all', evidenceVersion: 'a1', kind: 'business', field: '用户观察', bizType: '事实记录', countries: ['hk', 'uk'], relation: '通用', text: '11 月咨询台账：考前冲刺类咨询 52 条', ambiguous: false },
  { evidenceId: 'EV-half', evidenceVersion: 'h1', kind: 'business', field: '用户观察', bizType: '事实记录', countries: ['uk'], text: '11 月英国咨询 30 条', ambiguous: false },
];
const bizFacts = () => { const f = facts({ bizcard: { 用户观察: [{ id: 'B-00000001' }, { id: 'B-00000002' }], 负责人特别判断: [{ id: 'B-00000003' }], 存量用户情况: [{ id: 'B-00000004' }] } }); f.evidence = [...f.evidence, ...BIZ]; return f; };
// 把唯一的情境改成美国（GPT 1.1.0 定向验收的跨地区误用测试用）
const toUS = d => { d.scenarios[0] = { ...d.scenarios[0], id: 'SCN-2026-12-us-01', region: 'us', countries: ['us'], schools: ['加州大学洛杉矶分校'] }; d.claims.forEach(c => { c.scenario = 'SCN-2026-12-us-01'; }); return d; };
const newSign = { claimType: 'readiness', targetRelation: '新签', level: '高', text: '新签准备度' };

test('E6 已核实考试日期不能冒充购买准备度证据；有事实记录时可以 known', () => {
  assert.ok(hasError(assemble(bizFacts(), withClaim(7, { ...newSign, status: 'known', evidenceStrength: 'strong', evidenceRefs: ['EV-ver'] })), '最高 inferred + weak'));
  assert.deepEqual(assemble(bizFacts(), withClaim(7, { ...newSign, status: 'known', evidenceStrength: 'strong', evidenceRefs: ['EV-fact'] })).errors, []);
  assert.deepEqual(assemble(bizFacts(), withClaim(7, { ...newSign, level: '中', status: 'inferred', evidenceStrength: 'partial', evidenceRefs: ['EV-obs'], limitations: '一条顾问观察' })).errors, []);
  assert.ok(hasError(assemble(bizFacts(), withClaim(7, { ...newSign, status: 'known', evidenceStrength: 'strong', evidenceRefs: ['EV-obs', 'EV-ver'] })), '须有 strong 的行为证据'));
});

test('E7 校历加无关管理判断不能把障碍提上去；管理判断单独最高 inferred + weak', () => {
  assert.ok(hasError(assemble(bizFacts(), withClaim(1, { barrierCode: 'BR-M2', status: 'known', evidenceStrength: 'strong', evidenceRefs: ['EV-ver', 'EV-mgmt'] })), '须为 unknown'));
  assert.ok(hasError(assemble(bizFacts(), withClaim(1, { barrierCode: 'BR-C1', status: 'inferred', evidenceStrength: 'partial', evidenceRefs: ['EV-mgmt'] })), '最高 inferred + weak'));
  assert.deepEqual(assemble(bizFacts(), withClaim(1, { barrierCode: 'BR-C1', status: 'inferred', evidenceStrength: 'weak', evidenceRefs: ['EV-mgmt'], limitations: '管理判断，待检验假设' })).errors, []);
  assert.deepEqual(assemble(bizFacts(), withClaim(1, { barrierCode: 'BR-F1', status: 'inferred', evidenceStrength: 'partial', evidenceRefs: ['EV-obs'], rule: '证据最强' })).errors, []);
});

test('E8 没有对应用户观察不能标 observed；引用了就可以', () => {
  assert.ok(hasError(assemble(bizFacts(), withClaim(5, { painKind: 'observed' })), '须引用对应的用户观察'));
  assert.ok(hasError(assemble(bizFacts(), withClaim(5, { painKind: 'observed', evidenceRefs: ['EV-mgmt'] })), '须引用对应的用户观察'));
  assert.deepEqual(assemble(bizFacts(), withClaim(5, { painKind: 'observed', evidenceRefs: ['EV-school'], evidenceStrength: 'partial' })).errors, []);
  // 学业需求、痛点只拦人群相反的（常浩 2026-11-09 定）：「通用」情境可以用只适用新签的用户观察；续费情境不行
  assert.deepEqual(assemble(bizFacts(), withClaim(5, { painKind: 'observed', evidenceRefs: ['EV-obs'], evidenceStrength: 'partial' })).errors, []);
  const renewScn = withClaim(5, { painKind: 'observed', evidenceRefs: ['EV-obs'], evidenceStrength: 'partial' }); renewScn.scenarios[0].targetRelation = '续费';
  assert.ok(hasError(assemble(bizFacts(), renewScn), '适用人群 新签，本处 续费'));
  const renewNeed = withClaim(4, { evidenceStrength: 'partial', evidenceRefs: ['EV-src', 'EV-fact'] }); renewNeed.scenarios[0].targetRelation = '续费';
  assert.ok(hasError(assemble(bizFacts(), renewNeed), 'academic_need 引用的业务证据适用范围没填或对不上'));
  assert.deepEqual(assemble(bizFacts(), withClaim(4, { evidenceStrength: 'partial', evidenceRefs: ['EV-src', 'EV-fact'] })).errors, []);
});

test('E9 研判稿绑定底稿：指纹变了又没给研判时底稿就拦截，不静默换版本', () => {
  const moved = facts({ inputFingerprint: 'fp_new_snapshot0' });
  assert.ok(hasError(assemble(moved, draft()), '须用 --prev-facts'));
  assert.ok(hasError(assemble(moved, draft(), { prevFacts: facts({ inputFingerprint: 'fp_other' }) }), '不符'));
  assert.ok(hasError(assemble(facts(), draft({ basedOnFingerprint: undefined })), '须写研判时所用底稿'));
  const changed = facts({ inputFingerprint: 'fp_new_snapshot0' }); changed.evidence = changed.evidence.map(e => e.evidenceId === 'EV-ver' ? { ...e, evidenceVersion: 'v9' } : e);
  assert.ok(hasError(assemble(changed, draft(), { prevFacts: facts() }), '版本已变化'));
});

test('P1-04 最低完整性：缺需求 Claim、缺某一人群的 readiness、unknown 写了强度都拦截', () => {
  const noNeed = draft(); noNeed.claims = noNeed.claims.filter(c => c.claimType !== 'academic_need');
  assert.ok(hasError(assemble(facts(), noNeed), '缺少 academic_need'));
  const noReady = draft(); noReady.claims = noReady.claims.filter(c => c.id !== 'CLM-2026-12-008');
  assert.ok(hasError(assemble(facts(), noReady), '缺少新签的 readiness'));
  assert.ok(hasError(assemble(facts(), withClaim(7, { evidenceStrength: 'strong' })), 'evidenceStrength 须为 none'));
  const onlyNew = draft(); onlyNew.scenarios[0].targetRelation = '新签'; onlyNew.claims = onlyNew.claims.filter(c => c.targetRelation !== '续费');
  assert.deepEqual(assemble(facts(), onlyNew).errors, []);
});

test('P2-01 只有弱证据的主障碍须标暂定研究重点', () => {
  assert.ok(hasError(assemble(facts(), withClaim(1, { rule: '常识推断' })), '暂定研究重点'));
});

test('E10 同一目录先成功再失败：不留下可误用的旧参数', () => {
  const dir = mkdtempSync(join(tmpdir(), 'mus-e10-'));
  writeFileSync(join(dir, 'facts.json'), JSON.stringify(facts()));
  writeFileSync(join(dir, 'good.json'), JSON.stringify(draft()));
  writeFileSync(join(dir, 'bad.json'), JSON.stringify(withClaim(0, { evidenceRefs: ['EV-madeup'] })));
  const script = join(here, '..', 'scripts', 'assemble.mjs');
  execFileSync('node', [script, join(dir, 'facts.json'), join(dir, 'good.json'), '--out-dir', join(dir, 'out'), '--submit-args'], { stdio: 'pipe' });
  assert.ok(existsSync(join(dir, 'out', 'submit-args.json')));
  assert.throws(() => execFileSync('node', [script, join(dir, 'facts.json'), join(dir, 'bad.json'), '--out-dir', join(dir, 'out')], { stdio: 'pipe' }), e => e.status === 2);
  assert.ok(!existsSync(join(dir, 'out', 'submit-args.json')));
  assert.ok(!existsSync(join(dir, 'out', 'document.json')));
  assert.match(readFileSync(join(dir, 'out', 'assemble-errors.txt'), 'utf8'), /EV-madeup/);
});

test('国家代码：须在归一化表或底稿里，并属于情境所在地区', () => {
  const gb = draft(); gb.scenarios[0].countries = ['gb'];
  assert.ok(hasError(assemble(facts(), gb), '不在归一化表里'));
  const wrong = draft(); wrong.scenarios[0].countries = ['sg'];
  assert.ok(hasError(assemble(facts(), wrong), '不属于地区 uk'));
});

test('学业需求、痛点只有时间线证据时最高 weak；有业务观察可以到 partial', () => {
  assert.ok(hasError(assemble(facts(), withClaim(4, { evidenceStrength: 'partial' })), '最高 inferred + weak'));
  assert.deepEqual(assemble(bizFacts(), withClaim(4, { evidenceStrength: 'partial', evidenceRefs: ['EV-src', 'EV-school'] })).errors, []);
  assert.ok(hasError(assemble(bizFacts(), withClaim(4, { evidenceStrength: 'partial', evidenceRefs: ['EV-src', 'EV-nowhere'] })), '没填适用国家'));
});

test('自检「事实与来源核验」须逐个有情境的地区写明核过的例外（GPT P1-05，盲测 E6 第 2 轮）', () => {
  const noCheck = draft({ research: { selfCheck: SELF.map(r => r.item === '事实与来源核验' ? { item: r.item, result: '通过' } : r) } });
  const r1 = assemble(facts(), noCheck);
  assert.ok(hasError(r1, 'regionCheck'), r1.errors.join('\n'));
  assert.ok(hasError(r1, 'uk'), r1.errors.join('\n'));
  const blank = draft({ research: { selfCheck: SELF.map(r => r.item === '事实与来源核验' ? { ...r, regionCheck: { uk: '  ' } } : r) } });
  assert.ok(hasError(assemble(facts(), blank), 'regionCheck'));
  // 正例：写了就过，并转进 notes；没有情境的地区不用写
  const ok = assemble(facts(), draft());
  assert.deepEqual(ok.errors, []);
  assert.ok(ok.document.research.notes.some(n => n.includes('地区概括核对') && n.includes('uk：逐校核过 2 所，无例外')));
});

test('P1-01 业务证据的适用范围：国家要对得上情境，人群要对得上 Claim（GPT 1.1.0 定向验收 测试 A、B）', () => {
  // 测试 A：英国新签的事实记录不能当美国新签准备度的依据
  const a = assemble(bizFacts(), toUS(withClaim(7, { ...newSign, status: 'known', evidenceStrength: 'strong', evidenceRefs: ['EV-fact'] })));
  assert.ok(hasError(a, '适用范围'), a.errors.join('\n'));
  // 测试 B：英国的用户观察不能撑美国的 observed 痛点
  const b = assemble(bizFacts(), toUS(withClaim(5, { text: '美国学生普遍反映辅导时间冲突', painKind: 'observed', evidenceRefs: ['EV-obs'], evidenceStrength: 'partial' })));
  assert.ok(hasError(b, '适用范围'), b.errors.join('\n'));
  // 没填范围：范围不明，购买判断最高 inferred + weak，也不能撑 observed
  assert.ok(hasError(assemble(bizFacts(), withClaim(7, { ...newSign, level: '中', status: 'inferred', evidenceStrength: 'partial', evidenceRefs: ['EV-nowhere'] })), '适用范围'));
  assert.ok(hasError(assemble(bizFacts(), withClaim(5, { painKind: 'observed', evidenceRefs: ['EV-nowhere'], evidenceStrength: 'partial' })), '适用范围'));
  assert.deepEqual(assemble(bizFacts(), withClaim(7, { ...newSign, level: '中', status: 'inferred', evidenceStrength: 'weak', evidenceRefs: ['EV-nowhere'], limitations: '背景卡条目没填适用范围' })).errors, []);
  // 人群：存量用户情况只适用续费，不能撑新签
  assert.ok(hasError(assemble(bizFacts(), withClaim(7, { ...newSign, level: '中', status: 'inferred', evidenceStrength: 'partial', evidenceRefs: ['EV-renew'] })), '适用范围'));
  assert.deepEqual(assemble(bizFacts(), withClaim(2, { status: 'inferred', evidenceStrength: 'partial', evidenceRefs: ['EV-renew'], gap: undefined, route: undefined, limitations: '一条顾问观察', rule: '证据最强' })).errors, []);
  // 情境的实际商业关系也要对得上
  const obs = withClaim(0, {}); obs.scenarios[0].observedRelation = { value: '新签', evidenceRefs: ['EV-renew'] };
  assert.ok(hasError(assemble(bizFacts(), obs), '适用范围'));
  // 正例：填了范围的英国证据用于英国情境
  assert.deepEqual(assemble(bizFacts(), withClaim(7, { ...newSign, status: 'known', evidenceStrength: 'strong', evidenceRefs: ['EV-fact'] })).errors, []);
  assert.deepEqual(assemble(bizFacts(), withClaim(5, { painKind: 'observed', evidenceRefs: ['EV-school'], evidenceStrength: 'partial' })).errors, []);
});

test('#78 适用范围只读结构化字段：填了且对得上可以撑 partial / known，没填或对不上最高 inferred + weak', () => {
  const ready = (refs, change = {}) => withClaim(7, { ...newSign, status: 'known', evidenceStrength: 'strong', evidenceRefs: refs, ...change });
  const partial = { level: '中', status: 'inferred', evidenceStrength: 'partial', limitations: '一条顾问观察' };
  // 填了且对得上：事实记录撑 known，业务观察撑 partial
  assert.deepEqual(assemble(bizFacts(), ready(['EV-fact'])).errors, []);
  assert.deepEqual(assemble(bizFacts(), ready(['EV-obs'], partial)).errors, []);
  // 没填：原文写了英国、新签也不算；只填国家没填人群同样范围不明
  const none = assemble(bizFacts(), ready(['EV-nowhere']));
  assert.ok(hasError(none, '没填适用国家，没填适用人群'), none.errors.join('\n'));
  assert.ok(hasError(assemble(bizFacts(), ready(['EV-half'], partial)), '没填适用人群'));
  assert.deepEqual(assemble(bizFacts(), ready(['EV-nowhere'], { ...partial, evidenceStrength: 'weak' })).errors, []);
  // 对不上：国家没有交集；人群不同
  assert.ok(hasError(assemble(bizFacts(), toUS(ready(['EV-fact']))), '适用国家 uk，本处 us'));
  assert.ok(hasError(assemble(bizFacts(), ready(['EV-renew'], partial)), '适用人群 续费，本处 新签'));
  // 国家有一个相同就算对得上
  assert.deepEqual(assemble(bizFacts(), ready(['EV-all'])).errors, []);
  // M2 没有适用的行为证据时仍须 unknown
  assert.ok(hasError(assemble(bizFacts(), withClaim(1, { barrierCode: 'BR-M2', status: 'inferred', evidenceStrength: 'weak', evidenceRefs: ['EV-nowhere'], limitations: 'x' })), '须为 unknown'));
});

test('#78 人群「通用」的三种情况', () => {
  // 1. 「通用」条目撑新签的判断
  assert.deepEqual(assemble(bizFacts(), withClaim(7, { ...newSign, status: 'known', evidenceStrength: 'strong', evidenceRefs: ['EV-all'] })).errors, []);
  // 2. 「通用」条目撑续费的判断
  assert.deepEqual(assemble(bizFacts(), withClaim(2, { status: 'known', evidenceStrength: 'strong', evidenceRefs: ['EV-all'], gap: undefined, route: undefined, rule: '证据最强' })).errors, []);
  // 3. Claim 本身是「通用」：只接受「通用」条目，新签、续费条目都不行
  const general = refs => withClaim(1, { targetRelation: '通用', barrierCode: 'BR-C1', status: 'inferred', evidenceStrength: 'partial', evidenceRefs: refs, limitations: 'x', rule: '证据最强' });
  assert.ok(hasError(assemble(bizFacts(), general(['EV-obs'])), '适用人群 新签，本处 通用'));
  assert.ok(hasError(assemble(bizFacts(), general(['EV-renew'])), '适用人群 续费，本处 通用'));
  assert.deepEqual(assemble(bizFacts(), general(['EV-school'])).errors, []);
});

test('#78 缺范围提示：引用了没填范围的事实记录、业务观察，写明补哪条、补了能到什么强度，并记进 research.notes', () => {
  const r = assemble(bizFacts(), withClaim(7, { ...newSign, level: '中', status: 'inferred', evidenceStrength: 'weak', evidenceRefs: ['EV-nowhere', 'EV-half'], limitations: '背景卡条目没填适用范围' }));
  assert.deepEqual(r.errors, []);
  assert.equal(r.scopeGaps.length, 2);
  assert.ok(r.warnings.some(w => w.includes('EV-nowhere') && w.includes('没填适用国家、适用人群') && w.includes('known + strong') && w.includes('CLM-2026-12-008')), r.warnings.join('\n'));
  assert.ok(r.warnings.some(w => w.includes('EV-half') && w.includes('没填适用人群')));
  assert.ok(r.document.research.notes.some(n => n.startsWith('背景卡待补范围｜EV-nowhere')));
  // 填全了不提示；管理判断补了范围也提不上去，不提示
  const f = bizFacts(); f.evidence = f.evidence.map(e => e.evidenceId === 'EV-mgmt' ? { ...e, countries: undefined, relation: undefined } : e);
  const clean = assemble(f, withClaim(1, { barrierCode: 'BR-C1', status: 'inferred', evidenceStrength: 'weak', evidenceRefs: ['EV-mgmt', 'EV-obs'], limitations: 'x' }));
  assert.deepEqual(clean.errors, []);
  assert.deepEqual(clean.scopeGaps, []);
});

test('#78 Voice 按自带强度算，没有时按 partial（和服务端一致）', () => {
  const f = bizFacts(); f.evidence.push({ evidenceId: 'EV-voice', evidenceVersion: 'vo1', kind: 'voice', ambiguous: false }, { evidenceId: 'EV-voice-s', evidenceVersion: 'vo2', kind: 'voice', strength: 'strong', ambiguous: false });
  assert.deepEqual(assemble(f, withClaim(7, { ...newSign, level: '中', status: 'inferred', evidenceStrength: 'partial', evidenceRefs: ['EV-voice'], limitations: '一条原话' })).errors, []);
  assert.ok(hasError(assemble(f, withClaim(7, { ...newSign, status: 'known', evidenceStrength: 'strong', evidenceRefs: ['EV-voice'] })), '须有 strong 的行为证据'));
  assert.deepEqual(assemble(f, withClaim(7, { ...newSign, status: 'known', evidenceStrength: 'strong', evidenceRefs: ['EV-voice-s'] })).errors, []);
});

test('P1-03 输入不是合法 JSON：先清掉旧产出，写错误文件，非零退出（GPT 1.1.0 定向验收）', () => {
  const dir = mkdtempSync(join(tmpdir(), 'mus-json-'));
  writeFileSync(join(dir, 'facts.json'), JSON.stringify(facts()));
  writeFileSync(join(dir, 'good.json'), JSON.stringify(draft()));
  writeFileSync(join(dir, 'broken.json'), '{ "month": "2026-12", ');
  const script = join(here, '..', 'scripts', 'assemble.mjs');
  execFileSync('node', [script, join(dir, 'facts.json'), join(dir, 'good.json'), '--out-dir', join(dir, 'out'), '--submit-args'], { stdio: 'pipe' });
  assert.ok(existsSync(join(dir, 'out', 'submit-args.json')));
  assert.throws(() => execFileSync('node', [script, join(dir, 'facts.json'), join(dir, 'broken.json'), '--out-dir', join(dir, 'out')], { stdio: 'pipe' }), e => e.status !== 0);
  assert.ok(!existsSync(join(dir, 'out', 'submit-args.json')));
  assert.ok(!existsSync(join(dir, 'out', 'document.json')));
  assert.match(readFileSync(join(dir, 'out', 'assemble-errors.txt'), 'utf8'), /broken\.json/);
});

test('P1-05 digest 按事件列出各校结束日落在上 / 中 / 下旬（GPT 1.1.0 定向验收：「UC 四校上旬考完」）', () => {
  const dir = mkdtempSync(join(tmpdir(), 'mus-xun-'));
  writeFileSync(join(dir, 'facts.json'), JSON.stringify(facts()));
  const md = execFileSync('node', [join(here, '..', 'scripts', 'digest.mjs'), join(dir, 'facts.json')], { encoding: 'utf8' });
  assert.match(md, /结束日分旬/);
  assert.match(md, /- Final：上旬（1–10 日）0 所｜中旬（11–20 日）1 所：格拉斯哥大学 12-18｜下旬（21 日起）1 所：爱丁堡大学 12-21/);
});
