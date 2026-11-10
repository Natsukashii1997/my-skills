#!/usr/bin/env node
// 把 strategy_facts 的结果压成按地区的事实表（Markdown），供阶段 01–04 研判时阅读。只读输入文件，不调用任何接口。
//   node digest.mjs <facts.json> [--out <digest.md>]
// 证据强度上限按 01 来源登记表 sources-v1.1：verified / ruled → strong；source → partial；guess / conflict → weak；
// 业务背景卡：事实记录 strong、业务观察 partial、管理判断 weak。窗口取自工作台按 05 lifecycle-v0.2 算好的结果，这里不重算。
import { readFileSync, writeFileSync } from 'node:fs';

const args = process.argv.slice(2);
const outIndex = args.indexOf('--out');
const out = outIndex >= 0 ? args.splice(outIndex, 2)[1] : null;
const f = JSON.parse(readFileSync(args[0], 'utf8'));

const REGIONS = [['uk', '英国'], ['us', '美国'], ['hk', '香港'], ['au', '澳洲'], ['ca', '加拿大'], ['other', '其他']];
const OWN = new Set(['uk', 'us', 'hk', 'au', 'ca']);
const REGION_NAME = Object.fromEntries(REGIONS);
const STRENGTH = { verified: 'strong', ruled: 'strong', source: 'partial', guess: 'weak', conflict: 'weak' };
const BIZ = { 事实记录: 'strong', 业务观察: 'partial', 管理判断: 'weak' };
// 05 第 7 节默认矩阵。
const MATRIX = { 高: ['主战场', '主战场', '次要'], 中: ['主战场', '次要', '平稳'], 低: ['次要', '平稳', '平稳'] };
const defaultPriority = (key, value) => MATRIX[value]?.[['uk', 'us'].includes(key) ? 0 : key === 'other' ? 2 : 1] ?? null;
const regionOf = country => OWN.has(country) ? country : 'other';
const dateText = d => d.precision === 'day' ? (d.from === d.to ? d.from : `${d.from}～${d.to}`) : d.precision === 'month' ? `仅月份 ${d.months?.join('、')}` : '无日期';
const span = w => w ? `${w.from}～${w.to}` : '—';
const cell = s => String(s ?? '').replace(/\|/g, '／').replace(/\n/g, ' ');
// 原格原文（截 40 字）：用来发现同一格多个日期、跨年日期段被解析成月份等疑点；换行显示为「⏎」。
const raw = e => { const t = String(e.source?.raw ?? '').replace(/\|/g, '／').replace(/\n/g, '⏎'); return t.length > 40 ? `${t.slice(0, 40)}…` : t; };

const windows = new Map(f.windows.map(w => [w.evidenceId, w]));
const timeline = f.evidence.filter(e => e.kind === 'timeline');
const business = f.evidence.filter(e => e.kind === 'business');
const card = f.bizcard || {};
const filled = field => (card[field] || []).length > 0;
const manual = (f.revision?.claims || []).filter(c => c.origin === 'manual');

const lines = [];
const p = s => lines.push(s);
p(`# 事实底稿摘要 ${f.month}`);
p('');
p(`- inputFingerprint：\`${f.inputFingerprint}\`；baseRevision：\`${f.baseRevision ?? 'null'}\`；schemaVersion：${f.schemaVersion}`);
p(`- 规则版本：${Object.entries(f.rules?.versions || {}).map(([k, v]) => `${k}=${v}`).join('，')}`);
p(`- 时间线 Evidence ${timeline.length} 条，业务 Evidence ${business.length} 条，同步异常 ${f.anomalies?.length ?? 0} 条`);
p(`- 业务背景卡：${f.bizcard ? ['本月重要变化', '用户观察', '存量用户情况', '产品与资源约束', '负责人特别判断'].map(k => `${k}${filled(k) ? `✓${card[k].length}` : '空'}`).join('，') : '整张未填'}`);
p(`- 当前正式版本：${f.revision ? `有（手写 Claim ${manual.length} 条${manual.length ? `：${manual.map(c => c.id).join('、')}` : ''}）` : '无'}`);
p('');

p('## 业务背景卡条目');
p('');
if (!business.length) p('（无）');
else {
  // 适用国家、适用人群、来源（GPT 2.0.0 审核 P1-03）：洞察的适用范围不能比证据宽，没填就明写范围不明。
  const UNSET = '未填（范围不明）';
  const countries = e => (e.countries || []).length ? e.countries.map(c => REGION_NAME[c] ? `${REGION_NAME[c]}（${c}）` : c).join('、') : UNSET;
  p('| evidenceId | 字段 | 类型 | 强度上限 | 适用国家 | 适用人群 | 原文 | 依据 | 来源 |');
  p('|---|---|---|---|---|---|---|---|---|');
  for (const e of business) p(`| ${e.evidenceId} | ${e.field} | ${e.bizType} | ${BIZ[e.bizType] ?? '?'} | ${countries(e)} | ${e.relation || UNSET} | ${cell(e.text)} | ${cell(e.basis) || '未写'} | ${cell(e.source?.ref) || '未写'} |`);
}
p('');

for (const [key, name] of REGIONS) {
  const c = f.coverage[key] || {};
  const cv = c.coverage || {};
  p(`## ${name}（${key}）`);
  p('');
  p(`- 需求活跃度：${c.value}（status ${c.status}，ratio ${c.ratio ?? '无'}）；学校 ${cv.schools}，可计算 ${cv.calculable}，活跃 ${cv.active}，窗口未覆盖 ${cv.notCovered}，数据不足 ${cv.insufficient}`);
  p(`- 日期质量：${Object.entries(c.dateQuality || {}).map(([k, v]) => `${k} ${v}`).join('，')}；统计范围 ${c.range ? span(c.range) : '—'}`);
  p(`- 默认优先级（05 §7）：${defaultPriority(key, c.value) ?? '无默认（活跃度未知，须研判给出并写理由）'}`);
  if (c.byCountry) p(`- 分国贡献：${Object.entries(c.byCountry).map(([k, v]) => `${k} ${v.value}/${v.ratio ?? '无'}（学校 ${v.coverage.schools}，活跃 ${v.coverage.active}）`).join('；')}`);
  const events = timeline.filter(e => regionOf(e.country) === key)
    .sort((a, b) => (a.dates.from || a.dates.months?.[0] || '').localeCompare(b.dates.from || b.dates.months?.[0] || '') || a.school.localeCompare(b.school));
  p('');
  if (!events.length) { p('（本月没有相关时间线事件）'); p(''); continue; }
  p('| evidenceId | 国家 | 学校 | 事件（原列名） | 日期 | 核验 → 强度上限 | 锚点 | 适用 | 行动窗口 | 窗口状态 / 不计算原因 | 原格原文 |');
  p('|---|---|---|---|---|---|---|---|---|---|---|');
  // 只作情境信息的（八类以外、假期）按「事件 + 日期」归并成一行，节省篇幅；其余逐条列表。
  const context = events.filter(e => /不属于八类|假期/.test(windows.get(e.evidenceId)?.skipped || ''));
  for (const e of events.filter(x => !context.includes(x))) {
    const w = windows.get(e.evidenceId) || {};
    const flags = [e.ambiguous && 'ambiguous'].filter(Boolean).join(' ');
    const state = w.skipped ? `不计算：${w.skipped}` : `${w.status}（${w.ruleVersion}${w.limitations?.length ? `；${w.limitations.join('；')}` : ''}）`;
    p(`| ${e.evidenceId} | ${e.country} | ${cell(e.school)} | ${e.eventType}（${cell(e.header)}） | ${dateText(e.dates)} | ${e.verification} → ${STRENGTH[e.verification] ?? '?'}${flags ? ` ${flags}` : ''} | ${e.anchorType} | ${cell(e.scope ?? '')} | ${span(w.action)} | ${cell(state)} | ${raw(e)} |`);
  }
  if (context.length) {
    p('');
    p('只作情境信息（不生成默认窗口，05 §2、§4）：');
    const groups = new Map();
    for (const e of context) {
      const k = `${e.eventType}（${e.header}）${dateText(e.dates)}`;
      groups.set(k, [...(groups.get(k) || []), `${e.school}·${e.country}·${e.verification} ${e.evidenceId}`]);
    }
    for (const [k, list] of groups) p(`- ${cell(k)}：${list.map(cell).join('；')}`);
  }
  // 结束日分旬：写「上旬 / 中旬 / 下旬考完」之前对照这里（GPT 1.1.0 定向验收 P1-05）。只算本月精确到日、生成窗口的事件。
  const xunGroups = new Map();
  for (const e of events.filter(x => !context.includes(x) && x.dates.precision === 'day' && (x.dates.to || x.dates.from || '').startsWith(f.month))) {
    const end = e.dates.to || e.dates.from, d = Number(end.slice(8, 10));
    const g = xunGroups.get(e.eventType) || [[], [], []];
    g[d <= 10 ? 0 : d <= 20 ? 1 : 2].push(`${e.school} ${end.slice(5)}`);
    xunGroups.set(e.eventType, g);
  }
  if (xunGroups.size) {
    p('');
    p('结束日分旬（本月精确到日的事件；写「上旬 / 中旬 / 下旬」前逐校对照）：');
    for (const [type, g] of xunGroups) p(`- ${type}：${['上旬（1–10 日）', '中旬（11–20 日）', '下旬（21 日起）'].map((n, i) => `${n}${g[i].length} 所${g[i].length ? `：${g[i].map(cell).join('、')}` : ''}`).join('｜')}`);
  }
  const doubts = events.filter(e => e.dates.precision !== 'day' || ['guess', 'conflict'].includes(e.verification) || e.anchorType === 'anchor_unknown' || e.ambiguous);
  p('');
  p(`不确定性：仅月份 ${events.filter(e => e.dates.precision === 'month').length}，推测 ${events.filter(e => e.verification === 'guess').length}，冲突未决 ${events.filter(e => e.verification === 'conflict').length}，锚点不明 ${events.filter(e => e.anchorType === 'anchor_unknown').length}，ambiguous ${events.filter(e => e.ambiguous).length}（共 ${doubts.length} 条，见上表）`);
  p('');
}

const text = `${lines.join('\n')}\n`;
if (out) { writeFileSync(out, text); process.stdout.write(`已写入 ${out}（${lines.length} 行）\n`); } else process.stdout.write(text);
