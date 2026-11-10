// report-check.mjs 与 product-context.mjs 的单元测试。运行：node --test skills/monthly-user-strategy/tests/*.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { checkReport, size, SKUS, REGIONS, PROMO_ITEMS, TRACE_HEADER, CARD_HEADER, repetition, allowedGrade } from '../scripts/report-check.mjs';
import { parseCard, baseMonth, summarize } from '../scripts/product-context.mjs';

const here = dirname(fileURLToPath(import.meta.url));
// 每句带序号，互不相同，不触发灌水检测
let serial = 0;
const fill = (n, seed = '学生在剩余时间里需要找到最值得投入的复习内容') => {
  let out = '';
  while (size(out) < n) out += `${seed}，第${++serial}点。`;
  return out;
};
const OVERVIEW = fill(200, '本月是秋季学期收官月，北美与香港集中考试，英国多数学校一月才考');
const ROLES7 = { 灵活学Lite: '辅推', 安心学Max: '主推', 学考无忧Pass: '主推', 补考护航Pass: '条件性承接', 选课指导: '辅推', 论文稳Pass: '本月不推', 先修班课: '本月不推' };
const PLAN = { title: '考后衔接续报', items: Object.fromEntries([...PROMO_ITEMS, '前提条件'].map(k => [k, `${k}的具体写法`])) };

const report = (patch = {}) => {
  const p = { title: '# 2026-12 月度用户策略报告', grade: '条件性策略版', overview: OVERVIEW, ch1Extra: '| 关键取舍 | 澳洲本月不重点投入〔有依据的判断〕 |', regions: ['英国', '美国', '香港', '澳洲', '加拿大', '其他地区'],
    priorities: { 英国: '主攻', 美国: '主攻', 香港: '培育', 澳洲: '观察', 加拿大: '培育', 其他: '观察' }, roles: ROLES7, plans: [PLAN], ch6: '', ch8Rows: 4, body: '', appendix: 'EV-0123 CLM-2026-12-001 inferred', ...patch };
  return [
    p.title, '', `> 目标月份 2026-12｜${p.grade ? `报告等级：${p.grade}` : ''}｜范围：本科大学辅导`, '',
    '## 第一章 月度策略总览', '### 1.1 月度整体定性', '', p.overview, '', '### 1.2 本月核心策略判断', '', '| 判断维度 | 本月判断 |', '|---|---|', p.ch1Extra, '', '### 1.3 本月经营目标', '', fill(300), '',
    '## 第二章 月度时间线与需求节奏', '', fill(1100), '',
    '## 第三章 六地区用户需求深度分析', '', ...p.regions.flatMap(r => [`### 3.x ${r}`, '', fill(500)]), p.body, '',
    '## 第四章 地区优先级与机会判断', '', '### 4.1 地区决策表', '', '| 地区 | 本月主要机会 | 关键窗口 | 推荐优先级 | 机会阶段 | 经营动作 |', '|---|---|---|---|---|---|',
    ...Object.entries(p.priorities).map(([r, v]) => `| ${r} | 机会 | 窗口 | ${v} | 集中准备 | 动作 |`), '', fill(900), '',
    '## 第五章 SKU 与产品价值策略', '', fill(1300), '', '### 5.3 产品策略表与七个 SKU 的本月角色', '', '| SKU | 本月角色 | 理由 |', '|---|---|---|',
    ...Object.entries(p.roles).map(([s, r]) => `| ${s} | ${r} | ${r === '' ? '' : '理由'} |`), '',
    '## 第六章 营销主张与促销策略', '', fill(1000), '', '### 6.2 促销方案（或：本月不额外促销）', '', p.ch6,
    ...p.plans.flatMap((x, i) => [`#### 方案 ${i + 1}：${x.title}`, '', ...Object.entries(x.items).map(([k, v]) => `- ${k}：${v}`), '']), '',
    '## 第七章 月度执行方针', '', fill(800), '',
    '## 第八章 关键假设与验证事项', '', '| 待验证问题 | 为什么重要 | 验证方式 |', '|---|---|---|', ...Array.from({ length: p.ch8Rows }, (_, i) => `| 问题${i} | 影响主推 | 查咨询记录 |`), '',
    '## 附录 研究依据', '', p.appendix, '',
  ].join('\n');
};
const errs = r => r.errors.join('\n');

test('合格报告通过，附录里的编号不拦', () => {
  const r = checkReport(report(), { month: '2026-12' });
  assert.deepEqual(r.errors, []);
  assert.ok(r.stats.total > 6000);
  assert.equal(r.stats.grade, '条件性策略版');
  assert.deepEqual(r.stats.mainSkus, ['安心学Max', '学考无忧Pass']);
});

test('标题月份不对、缺章节、顺序错都拦', () => {
  assert.match(errs(checkReport(report(), { month: '2026-11' })), /和目标月份 2026-11 不一致/);
  assert.match(errs(checkReport(report().replace('## 第七章 月度执行方针', '## 第七章 执行'))), /缺少章节.*第七章 月度执行方针/);
  const swapped = report().replace('## 第四章 地区优先级与机会判断', '## TMP').replace('## 第五章 SKU 与产品价值策略', '## 第四章 地区优先级与机会判断').replace('## TMP', '## 第五章 SKU 与产品价值策略');
  assert.match(errs(checkReport(swapped)), /章节顺序不对/);
});

test('第一章总述字数、关键取舍一行要有内容、1.2 / 1.3 小节', () => {
  assert.match(errs(checkReport(report({ overview: '本月以考试为主。' }))), /150–250 字.*现在 \d+ 字/);
  assert.match(errs(checkReport(report({ overview: fill(320) }))), /150–250 字/);
  assert.match(errs(checkReport(report({ ch1Extra: '| 地区选择 | 英国 |' }))), /关键取舍/);
  assert.match(errs(checkReport(report({ ch1Extra: '| 关键取舍 |  |' }))), /「关键取舍」一行没写/);
});

test('第三章缺地区小节拦', () => {
  assert.match(errs(checkReport(report({ regions: ['英国', '美国', '香港', '澳洲', '其他'] }))), /缺地区小节.*加拿大/);
});

test('P2 第四章：地区决策表六个地区各一行，优先级只能是主攻 / 培育 / 观察', () => {
  const five = { 英国: '主攻', 美国: '主攻', 香港: '培育', 澳洲: '观察', 其他: '观察' };
  assert.match(errs(checkReport(report({ priorities: five }))), /缺这些地区的行：加拿大/);
  assert.match(errs(checkReport(report({ priorities: { 英国: '主攻', 美国: '重点', 香港: '', 澳洲: '观察', 加拿大: '培育', 其他: '观察' } }))), /只能选一个：主攻 \/ 培育 \/ 观察：美国「重点」、香港「空」/);
  // 骨架原样留着「主攻 / 培育 / 观察」不算选了
  assert.match(errs(checkReport(report({ priorities: { 英国: '主攻 / 培育 / 观察', 美国: '主攻', 香港: '培育', 澳洲: '观察', 加拿大: '培育', 其他: '观察' } }))), /英国「主攻 \/ 培育 \/ 观察」/);
  assert.match(errs(checkReport(report().replace('| 英国 | 机会 | 窗口 |', '| 英国 |  | 窗口 |'))), /地区决策表有空格：英国（本月主要机会）/);
  assert.deepEqual(checkReport(report({ priorities: { 英国: '主攻〔有依据的判断〕', 美国: '主攻', 香港: '培育', 澳洲: '观察', 加拿大: '培育', 其他: '观察' } })).errors, []);
  // 只在正文提到「主攻」、没有决策表，不再算过
  const noTable = report().replace(/\| 地区 \| 本月主要机会[\s\S]*?\n\n/, '英国主攻。\n\n');
  assert.match(errs(checkReport(noTable)), /第四章缺地区决策表/);
});

test('P2 第五章：七个 SKU 角色表，角色限定四种，理由不能空', () => {
  const { 先修班课, ...six } = ROLES7;
  assert.match(errs(checkReport(report({ roles: six }))), /角色表没有对这些 SKU 表态：先修班课/);
  assert.match(errs(checkReport(report({ roles: { ...ROLES7, 论文稳Pass: '看情况' } }))), /角色只能是 主推 \/ 辅推 \/ 条件性承接 \/ 本月不推：论文稳Pass「看情况」/);
  assert.match(errs(checkReport(report({ roles: { ...ROLES7, 选课指导: '' } }))), /选课指导「空」/);
  assert.match(errs(checkReport(report({ roles: { ...ROLES7, 选课指导: '主推 / 辅推' } }))), /选课指导「主推 \/ 辅推」/);
  // 只在正文罗列 SKU 名、没有角色表，不再算过
  const noTable = report().replace('| SKU | 本月角色 | 理由 |', '| 产品 | 角色 | 说明 |');
  assert.match(errs(checkReport(noTable)), /缺七个 SKU 的角色表/);
});

test('P2 第六章：每个方案六项逐项非空；没有方案时正文要写明本月不额外促销', () => {
  const half = { title: '期末冲刺', items: { 促销目标: '时间促进', 适用人群: '', 核心机制: '限时' } };
  assert.match(errs(checkReport(report({ plans: [PLAN, half] }))), /「期末冲刺」缺论证项.*适用人群、选择依据、商业约束、验证指标/);
  // 只出现六个关键词、没有逐项内容，不再算过
  assert.match(errs(checkReport(report({ plans: [], ch6: '促销目标、适用人群、核心机制、选择依据、商业约束、验证指标各写一段。' }))), /既没有「#### 方案 N：标题」/);
  // 骨架标题里的「本月不额外促销」不算
  assert.match(errs(checkReport(report({ plans: [] }))), /既没有/);
  assert.deepEqual(checkReport(report({ plans: [], ch6: '本月不额外促销，集中提升服务价值表达和转化效率，理由如下。' })).errors, []);
});

test('第八章只能 3–5 项', () => {
  assert.match(errs(checkReport(report({ ch8Rows: 2 }))), /3–5 项.*现在 2 项/);
  assert.match(errs(checkReport(report({ ch8Rows: 7 }))), /现在 7 项/);
  assert.deepEqual(checkReport(report({ ch8Rows: 5 })).errors, []);
});

test('正文出现研究层编号、障碍编码、状态码都拦', () => {
  const r = checkReport(report({ body: '依据 EV-207c82edea34c32a 与 CLM-2026-12-003，主障碍 BR-M2，状态 inferred。' }));
  assert.match(errs(r), /研究对象编号（只能放附录）：EV-207c82edea34c32a、CLM-2026-12-003/);
  assert.match(errs(r), /障碍编码（只能放附录）：BR-M2/);
  assert.match(errs(r), /状态码（只能放附录）：inferred/);
});

test('提示：满篇「可能」、没有可信程度标注、空话、章节比重失衡', () => {
  const r = checkReport(report({ ch1Extra: '| 关键取舍 | 澳洲不投入 |', body: '学生可能需要辅导，或许尚待验证，可能可能可能。'.repeat(20) + '我们要打造闭环。' }));
  assert.deepEqual(r.errors, []);
  const w = r.warnings.join('\n');
  assert.match(w, /每千字/);
  assert.match(w, /没有可信程度标注/);
  assert.match(w, /空话：闭环、打造/);
  assert.match(w, /「第八章 关键假设与验证事项」占正文/);
});

test('P1-05 / P2 灌水反例：各章用同一句话反复填充，结构齐全也拦', () => {
  const pad = '本月我们将围绕用户需求持续优化服务体验并提升转化效率。'.repeat(160);
  const r = checkReport(report({ body: pad }));
  assert.match(errs(r), /重复的句子，像在灌水：「本月我们将围绕用户需求持续优化服务体验并提升转化效率」×160/);
  assert.ok(repetition(pad).share > 0.9);
  assert.equal(repetition('完全不同的第一句话写在这里。另一句也完全不一样的话。').share, 0);
});

test('P2 报告等级：报告头必须写，取值限三种', () => {
  assert.match(errs(checkReport(report({ grade: '' }))), /报告等级：研究假设版 \/ 条件性策略版 \/ 可执行策略版/);
  assert.match(errs(checkReport(report({ grade: '完整版' }))), /报告等级/);
});

test('P2 报告等级：研究假设版的方案标「候选待确认」，条件性策略版的方案写前提条件', () => {
  assert.match(errs(checkReport(report({ grade: '研究假设版' }))), /研究假设版不出正式促销方案：「考后衔接续报」/);
  assert.deepEqual(checkReport(report({ grade: '研究假设版', plans: [{ ...PLAN, title: '考后衔接续报（候选待确认）' }] })).errors, []);
  const { 前提条件, ...six } = PLAN.items;
  assert.match(errs(checkReport(report({ plans: [{ title: '考后衔接续报', items: six }] }))), /条件性策略版的促销方案要写「- 前提条件：」/);
  assert.deepEqual(checkReport(report({ grade: '可执行策略版', plans: [{ title: '考后衔接续报', items: six }] })).errors, []);
});

// 输入摘要（digest.md / products.md）的相关行
const DIGEST = (obs, stock) => `- 业务背景卡：本月重要变化空，用户观察${obs ? '✓2' : '空'}，存量用户情况${stock ? '✓1' : '空'}，产品与资源约束空，负责人特别判断空`;
const PRODUCTS = (filled, current = true) => [current ? '- 本月（2026-12）已录入。' : '- **本月（2026-12）未录入**，以最近一个月 2026-10 为基线', ...SKUS.map(s => `### ${s}（已填 ${filled[s] ?? 0}/5）`)].join('\n');
const FULL = Object.fromEntries(SKUS.map(s => [s, 5]));

test('P2 报告等级按输入判定：缺什么降到哪一级', () => {
  const main = ['安心学Max'];
  assert.equal(allowedGrade({ digest: DIGEST(false, false), products: PRODUCTS(FULL), mainSkus: main }).grade, '研究假设版');
  assert.equal(allowedGrade({ digest: '- 业务背景卡：整张未填', products: PRODUCTS(FULL), mainSkus: main }).grade, '研究假设版');
  assert.match(allowedGrade({ digest: DIGEST(true, true), products: PRODUCTS({ 安心学Max: 5, 灵活学Lite: 3, 选课指导: 1 }), mainSkus: main }).why.join(), /4 个 SKU 一项没填/);
  assert.equal(allowedGrade({ digest: DIGEST(true, true), products: '- **没有产品能力卡**', mainSkus: main }).grade, '研究假设版');
  assert.equal(allowedGrade({ digest: DIGEST(true, false), products: PRODUCTS(FULL), mainSkus: main }).grade, '条件性策略版');
  assert.match(allowedGrade({ digest: DIGEST(true, true), products: PRODUCTS({ ...FULL, 安心学Max: 4 }), mainSkus: main }).why.join(), /主推 SKU 能力卡没填满：安心学Max/);
  assert.match(allowedGrade({ digest: DIGEST(true, true), products: PRODUCTS(FULL, false), mainSkus: main }).why.join(), /活动基线不是本月/);
  assert.equal(allowedGrade({ digest: DIGEST(true, true), products: PRODUCTS(FULL), mainSkus: main }).grade, '可执行策略版');
});

test('P2 报告等级虚标就拦，保守只提示', () => {
  const r = checkReport(report({ grade: '可执行策略版', plans: [{ title: '考后衔接续报', items: PLAN.items }] }), { digest: DIGEST(true, false), products: PRODUCTS(FULL) });
  assert.match(errs(r), /报告等级写成「可执行策略版」，输入只够「条件性策略版」：「存量用户情况」没填/);
  const low = checkReport(report(), { digest: DIGEST(true, true), products: PRODUCTS(FULL) });
  assert.deepEqual(low.errors, []);
  assert.match(low.warnings.join(), /输入够「可执行策略版」/);
});

// design.md / synthesis.md
const SYN = '## 3. 关键洞察清单\n| 编号 | 核心结论 |\n|---|---|\n| I-01 | 结论一 |\n| I-02 | 结论二 |\n';
const traceRow = patch => { const r = { 编号: 'T-01', 用户情境: '英国新签，1 月 Final 前', 需求洞察: 'I-01', 可信程度: '〔有依据的判断〕', 商业机会: '考前冲刺', 产品选择: '安心学Max（主推）', 价值主张: '快速匹配', 促销方案: '考后衔接续报（P0901）', 执行行动: '销售 12 月中旬', 验证指标: '续费率', ...patch }; return `| ${TRACE_HEADER.map(h => r[h]).join(' | ')} |`; };
const cardRow = (id, adopt = '采用：老学员续费') => `| ${id} | 续费 | 结课后 30 天 | 常规课时包 | 不与新签券叠加 | 只对在读学员 | 卡片未写 | ${adopt} |`;
const DESIGN = (rows = [traceRow(), traceRow({ 编号: 'T-02', 产品选择: '学考无忧Pass（主推）', 促销方案: '本月不额外促销', 需求洞察: 'I-02' })], cards = [cardRow('P0901')]) =>
  ['## 4. 促销方案', '### 候选卡核对表', `| ${CARD_HEADER.join(' | ')} |`, `|${'---|'.repeat(CARD_HEADER.length)}`, ...cards, '', '## 9. 决策追溯', `| ${TRACE_HEADER.join(' | ')} |`, `|${'---|'.repeat(TRACE_HEADER.length)}`, ...rows, ''].join('\n');

test('P1-04 决策追溯：完整追溯通过', () => {
  assert.deepEqual(checkReport(report(), { design: DESIGN(), synthesis: SYN }).errors, []);
});

test('P1-04 决策追溯：缺表、空格、编号不存在、主推和方案追不到都拦', () => {
  assert.match(errs(checkReport(report(), { design: '## 9. 决策追溯\n（没写）' })), /缺「决策追溯」表/);
  assert.match(errs(checkReport(report(), { design: DESIGN([traceRow({ 商业机会: '', 验证指标: ' ' }), traceRow({ 编号: 'T-02', 产品选择: '学考无忧Pass' })]) })), /T-01：这些格是空的：商业机会、验证指标/);
  assert.match(errs(checkReport(report(), { design: DESIGN([traceRow({ 需求洞察: '英国学生焦虑' }), traceRow({ 编号: 'T-02', 产品选择: '学考无忧Pass' })]) })), /要引用 synthesis.md 的洞察编号/);
  assert.match(errs(checkReport(report(), { design: DESIGN([traceRow({ 需求洞察: 'I-07' }), traceRow({ 编号: 'T-02', 产品选择: '学考无忧Pass' })]), synthesis: SYN })), /找不到：I-07/);
  assert.match(errs(checkReport(report(), { design: DESIGN([traceRow()]) })), /主推 SKU 在决策追溯表里追不到：学考无忧Pass/);
  assert.match(errs(checkReport(report(), { design: DESIGN([traceRow({ 促销方案: '本月不额外促销' }), traceRow({ 编号: 'T-02', 产品选择: '学考无忧Pass', 促销方案: '本月不额外促销' })]) })), /促销方案在决策追溯表里追不到：考后衔接续报/);
});

test('P1-02 方案要对应核对表里采用的卡，或注明非打法库机制', () => {
  const two = r => DESIGN([r, traceRow({ 编号: 'T-02', 产品选择: '学考无忧Pass', 促销方案: '本月不额外促销' })]);
  assert.match(errs(checkReport(report(), { design: two(traceRow({ 促销方案: '考后衔接续报' })) })), /要写对应卡号，或注明「非打法库机制」/);
  assert.deepEqual(checkReport(report(), { design: two(traceRow({ 促销方案: '考后衔接续报（非打法库机制：服务流程提速）' })) }).errors, []);
  assert.match(errs(checkReport(report(), { design: two(traceRow({ 促销方案: '考后衔接续报（P0303）' })) })), /不在候选卡核对表里.*P0303/);
  assert.match(errs(checkReport(report(), { design: DESIGN(undefined, [cardRow('P0901', '不采用：只适用于老学员')]) })), /没标「采用 \/ 附条件采用」：P0901/);
  assert.match(errs(checkReport(report(), { design: DESIGN(undefined, [cardRow('P0901').replace('卡片未写', ' ')]) })), /候选卡核对表 P0901：这些格是空的.*生效 \/ 失效条件/);
});

test('命令行：通过退出 0，拦截退出 2；带内部文件一起核对', () => {
  const dir = mkdtempSync(join(tmpdir(), 'rc-'));
  const script = join(here, '../scripts/report-check.mjs');
  writeFileSync(join(dir, 'ok.md'), report());
  writeFileSync(join(dir, 'design.md'), DESIGN());
  writeFileSync(join(dir, 'synthesis.md'), SYN);
  writeFileSync(join(dir, 'digest.md'), DIGEST(true, false));
  writeFileSync(join(dir, 'products.md'), PRODUCTS(FULL));
  const out = execFileSync('node', [script, join(dir, 'ok.md'), '--month', '2026-12', '--design', join(dir, 'design.md'), '--synthesis', join(dir, 'synthesis.md'), '--digest', join(dir, 'digest.md'), '--products', join(dir, 'products.md'), '--out', join(dir, 'ok.txt')], { encoding: 'utf8' });
  assert.match(out, /机械检查通过/);
  assert.match(out, /报告等级：条件性策略版；主推 SKU：安心学Max、学考无忧Pass/);
  writeFileSync(join(dir, 'bad.md'), report({ ch8Rows: 9 }));
  assert.throws(() => execFileSync('node', [script, join(dir, 'bad.md')], { encoding: 'utf8', stdio: 'pipe' }), e => e.status === 2);
  assert.throws(() => execFileSync('node', [script, join(dir, 'ok.md'), '--design', join(dir, 'nope.md')], { encoding: 'utf8', stdio: 'pipe' }), e => e.status === 1);
});

// ---------- product-context ----------

const promos = [
  { month: '2026-10', line: '大学辅导', sku: '灵活学Lite', trial: '¥199', price: '¥4100（双11版）', newDeal: '无', renewal: '无', special: '无' },
  { month: '2026-09', line: '大学辅导', sku: '灵活学Lite', trial: '¥99', price: '¥3900', newDeal: '无', renewal: '无', special: '无' },
  { month: '2026-10', line: '国际课程', sku: '灵活学Lite', trial: '¥1', price: '¥1', newDeal: '无', renewal: '无', special: '无' },
];

test('活动基线：本月未录入时取不晚于本月的最近一个月，并在摘要里写明不是本月活动', () => {
  assert.equal(baseMonth(promos, '2026-12'), '2026-10');
  assert.equal(baseMonth(promos, '2026-09'), '2026-09');
  assert.equal(baseMonth(promos, '2026-08'), null);
  const { text } = summarize({ month: '2026-12', promos, plan: { special: '双11活动（10.15-11.11）' }, skus: [], card: null, playbook: [] });
  assert.match(text, /本月（2026-12）未录入\*\*，以最近一个月 2026-10 为基线/);
  assert.match(text, /\| 灵活学Lite \| ¥199 \| ¥4100（双11版）/);
  assert.match(text, /\| 安心学Max \| （2026-10 未录入）/);
  assert.match(text, /没有产品能力卡/);
});

test('价格档案：演示数据标明不能引用；缺档案的 SKU 列出', () => {
  const skus = [{ line: '大学辅导', name: '灵活学Lite', unitOrig: 990, tiers: [5, 10], origin: 'demo' }, { line: '大学辅导', name: '安心学Max', unitOrig: 1350, tiers: [18], origin: 'provided' }];
  const { text } = summarize({ month: '2026-12', promos: [], skus, card: null, playbook: null });
  assert.match(text, /灵活学Lite：单价原价 990.*演示数据，不能引用/);
  assert.doesNotMatch(text, /安心学Max.*演示数据/);
  assert.match(text, /没有价格档案：学考无忧Pass/);
  assert.match(text, /没有读到打法库/);
});

test('产品能力卡：按 SKU 统计已填项，空模板全部算未填', () => {
  const card = parseCard(['## 灵活学Lite', '', '- 交付什么：一对一按需辅导', '- 匹配到老师多快（常规 / 最快）：', '- 能否加急、加急条件：可以，48 小时', '', '## 不认识的', '- 交付什么：x'].join('\n'));
  assert.deepEqual(Object.keys(card), ['灵活学Lite']);
  assert.equal(card['灵活学Lite']['交付什么'], '一对一按需辅导');
  assert.equal(card['灵活学Lite']['匹配到老师多快'], '');
  const { text } = summarize({ month: '2026-12', promos: [], skus: [], card, playbook: [{ id: 'P0101', name: '限时折扣', file: 'P0101-限时折扣.md', stage: '通用', barriers: [], mechanisms: [], position: '' }] });
  assert.match(text, /### 灵活学Lite（已填 2\/5）/);
  assert.match(text, /- 匹配到老师多快：未填/);
  assert.match(text, /### 安心学Max（已填 0\/5）/);
  assert.match(text, /1 张卡/);
});
