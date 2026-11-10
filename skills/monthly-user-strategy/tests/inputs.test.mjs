// 输入链路：产品能力卡内容、打法卡元信息、业务证据适用范围要传到第 2、3 轮读的摘要里（GPT 2.0.0 审核 P1-01～P1-03）。
// 运行：node --test skills/monthly-user-strategy/tests/*.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, readFileSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseCard, parseCardExtras, parsePlaybookCard, summarize } from '../scripts/product-context.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = join(here, '../evals/fixtures');

// GPT 审核里的复现输入：灵活学Lite 五项都填了
const CARD = [
  '# 产品能力卡（大学辅导 · 7 个 SKU）', '', '**版本**：2026-11-20 常浩填。', '',
  '## 灵活学Lite', '',
  '- 交付什么：课程一对一同步辅导',
  '- 匹配到老师多快（常规 / 最快）：正常 72 小时',
  '- 能否加急、加急条件：不能加急',
  '- 课时形式与最小购买单位：五小时',
  '- 明确不提供什么：不保成绩', '',
  '## 安心学Max', '', '- 交付什么：', '- 匹配到老师多快（常规 / 最快）：', '',
  '## 跨 SKU 的共同能力（可选）', '', '- 师资覆盖（哪些地区、哪些学科强 / 弱）：英国商科强，澳洲理工弱', '- 诊断、模考、学情报告等服务：', '',
  '## 变更记录', '', '| 日期 | 改了什么 |',
].join('\n');

const P0901 = [
  '# 老学员续报价 · 老客与会员类',
  '<!-- P0901 | 类别 9 | 阶段 续费 | 障碍 B1 ; A2 | 机制 M19 M16 -->', '',
  '**定位**：老学员续报价是给在读或刚结课的学员一个低于公开价的专属价格。它是续费打法，不是新签打法。', '',
  '## 一、心理机制',
].join('\n');

test('P1-01 能力卡逐项原文进 products.md，空的写「未填」', () => {
  const card = parseCard(CARD);
  const { text } = summarize({ month: '2026-12', promos: [], skus: [], card, cardExtras: parseCardExtras(CARD), playbook: [] });
  for (const line of ['- 交付什么：课程一对一同步辅导', '- 匹配到老师多快：正常 72 小时', '- 能否加急：不能加急', '- 课时形式与最小购买单位：五小时', '- 明确不提供什么：不保成绩']) assert.ok(text.includes(line), `缺：${line}`);
  assert.match(text, /### 灵活学Lite（已填 5\/5）/);
  assert.match(text, /### 安心学Max（已填 0\/5）\n\n- 交付什么：未填/);
  assert.match(text, /能力卡版本：2026-11-20 常浩填。下面/);
  assert.match(text, /### 跨 SKU 的共同能力\n\n- 师资覆盖（哪些地区、哪些学科强 \/ 弱）：英国商科强，澳洲理工弱/);
  assert.doesNotMatch(text, /诊断、模考/);
});

test('P1-01 没填共同能力、没写版本时照实写', () => {
  const x = parseCardExtras('## 灵活学Lite\n- 交付什么：\n');
  assert.deepEqual(x, { version: '未写', common: [] });
  const { text } = summarize({ month: '2026-12', promos: [], skus: [], card: parseCard(''), cardExtras: x, playbook: [] });
  assert.match(text, /能力卡版本：未写/);
  assert.match(text, /### 跨 SKU 的共同能力\n\n- 未填/);
});

test('P1-02 打法卡解析元信息与定位句，摘要要求读原文', () => {
  const c = parsePlaybookCard(P0901, 'P0901-老学员续报价.md');
  assert.deepEqual(c, { id: 'P0901', name: '老学员续报价', file: 'P0901-老学员续报价.md', stage: '续费', barriers: ['B1', 'A2'], mechanisms: ['M19', 'M16'], position: '老学员续报价是给在读或刚结课的学员一个低于公开价的专属价格。' });
  const { text } = summarize({ month: '2026-12', promos: [], skus: [], card: null, playbook: [c], playbookDir: '/x/打法库' });
  assert.match(text, /\| P0901 \| 老学员续报价 \| 续费 \| B1 嫌贵；A2 觉得还来得及 \| M19 M16 \| 老学员续报价是给在读或刚结课的学员一个低于公开价的专属价格。 \| P0901-老学员续报价.md \|/);
  assert.match(text, /进入候选的卡必须读原文\*\*（`\/x\/打法库\/<文件>`）/);
  assert.match(text, /候选卡核对表/);
});

test('P1-02 元信息缺失的卡不报错，标「未标」', () => {
  const c = parsePlaybookCard('# 某打法\n正文', 'P9999-某打法.md');
  assert.equal(c.id, 'P9999');
  assert.equal(c.stage, '未标');
  assert.deepEqual(c.barriers, []);
  assert.equal(c.position, '');
});

test('P1-01/02 命令行：接口取不到不算失败，能力卡与打法卡都写进 products.md', () => {
  const dir = mkdtempSync(join(tmpdir(), 'pc-'));
  const pb = join(dir, '打法库');
  mkdirSync(pb);
  writeFileSync(join(pb, 'P0901-老学员续报价.md'), P0901);
  writeFileSync(join(pb, 'README.md'), '# 不是卡');
  writeFileSync(join(dir, 'card.md'), CARD);
  // 输出目录不存在时自动建（交付前复核写到 recheck/，2.1.0 模拟试跑发现会 ENOENT）
  const outDir = join(dir, 'recheck');
  const out = execFileSync('node', [join(here, '../scripts/product-context.mjs'), '--month', '2026-12', '--out-dir', outDir, '--card', join(dir, 'card.md'), '--playbook', pb],
    { encoding: 'utf8', env: { ...process.env, WORKDESK_URL: 'http://127.0.0.1:9' } });
  assert.match(out, /取不到：promos、skus/);
  const md = readFileSync(join(outDir, 'products.md'), 'utf8');
  assert.match(md, /促销表读取失败/);
  assert.match(md, /- 明确不提供什么：不保成绩/);
  assert.match(md, /1 张卡/);
  assert.match(md, /\| P0901 \| 老学员续报价 \| 续费 \|/);
  const json = JSON.parse(readFileSync(join(outDir, 'products.json'), 'utf8'));
  assert.equal(json.playbook[0].id, 'P0901');
  assert.equal(json.cardExtras.version, '2026-11-20 常浩填');
});

const digest = file => execFileSync('node', [join(here, '../scripts/digest.mjs'), join(fixtures, file)], { encoding: 'utf8' });

test('P1-03 业务证据表带适用国家、适用人群、依据与来源', () => {
  const text = digest('facts-e7-with-behavior.json');
  assert.match(text, /\| evidenceId \| 字段 \| 类型 \| 强度上限 \| 适用国家 \| 适用人群 \| 原文 \| 依据 \| 来源 \|/);
  assert.match(text, /\| EV-e7b0000000000001 \| 用户观察 \| 事实记录 \| strong \| 英国（uk） \| 新签 \| 11 月英国新签咨询 46 条.* \| 咨询台账 2026-11 \| 2026-12·用户观察·B-7c1d2e3f \|/);
  assert.match(text, /\| EV-e7b0000000000002 \| 存量用户情况 \| 业务观察 \| partial \| 英国（uk） \| 续费 \|/);
});

test('P1-03 没有适用范围的业务证据写「未填（范围不明）」', () => {
  const text = digest('facts-e2-no-renewal.json');
  const rows = text.split('\n').filter(l => /^\| EV-/.test(l) && l.includes('未填（范围不明）'));
  assert.ok(rows.length >= 2, text.slice(0, 1500));
});

test('评测夹具：E9 / E12 / E13 的输入按规格 8.4 分别够到研究假设版、可执行策略版', async () => {
  const { allowedGrade } = await import('../scripts/report-check.mjs');
  const md = f => readFileSync(join(fixtures, f), 'utf8');
  assert.equal(allowedGrade({ digest: digest('facts-e1-timeline-only.json'), products: md('products-e9.md'), mainSkus: ['安心学Max'] }).grade, '研究假设版');
  assert.equal(allowedGrade({ digest: digest('facts-e7-with-behavior.json'), products: md('products-e12.md'), mainSkus: ['安心学Max', '学考无忧Pass'] }).grade, '可执行策略版');
  assert.equal(allowedGrade({ digest: digest('facts-e13-conflict.json'), products: md('products-e13.md'), mainSkus: ['安心学Max'] }).grade, '可执行策略版');
  // E13 的交付限制要在 products 摘要里看得到
  assert.match(md('products-e13.md'), /### 安心学Max（已填 5\/5）[\s\S]*?- 能否加急：不能加急；12 月英国、香港商科老师已排满/);
  // 夹具都是占位内容，打法库只给索引并要求读原文
  for (const f of ['products-e12.md', 'products-e13.md']) assert.match(md(f), /占位/);
  for (const f of ['products-e9.md', 'products-e12.md', 'products-e13.md']) assert.match(md(f), /47 张卡[\s\S]*\| P0901 \| 老学员续报价 \| 续费 \|/);
});

test('结束日分旬按学校计数：同一所学校同一旬两段日期只算一所', () => {
  const f = JSON.parse(readFileSync(join(fixtures, 'facts-e7-with-behavior.json'), 'utf8'));
  const glasgow = f.evidence.find(e => e.evidenceId === 'EV-207c82edea34c32a');
  f.evidence.push({ ...glasgow, evidenceId: 'EV-dup0000000000001', dates: { from: '2026-12-15', to: '2026-12-16', precision: 'day' } });
  const dir = mkdtempSync(join(tmpdir(), 'dg-'));
  writeFileSync(join(dir, 'facts.json'), JSON.stringify(f));
  const text = execFileSync('node', [join(here, '../scripts/digest.mjs'), join(dir, 'facts.json')], { encoding: 'utf8' });
  assert.match(text, /中旬（11–20 日）2 所：格拉斯哥大学 12-18、12-16；布里斯托大学 12-18/);
});
