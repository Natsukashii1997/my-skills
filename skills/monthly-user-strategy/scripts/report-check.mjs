#!/usr/bin/env node
// 月度用户策略报告（report.md）的机械检查。规则出处：niuma-home docs/策略规则/10-报告内容规格.md（report-v2.1）。
// 只查结构和硬性写法，不判断洞察质量；洞察质量由第 5 轮独立审核和常浩按 references/quality-content.md 打分。
// 机械检查通过离报告合格还很远（GPT 2.0.0 审核 P1-05）：它只挡住缺项、空格、灌水重复和等级虚标。
//
//   node report-check.mjs <report.md> [--month YYYY-MM] [--synthesis synthesis.md] [--design design.md]
//                         [--digest digest.md] [--products products.md] [--out <结果文件>]
//
// --design（配 --synthesis 更全）：核对 design.md 的决策追溯表与候选卡核对表（P1-04、P1-02）。
// --digest + --products：按输入判断报告最高能写到哪一级，等级虚标就拦（规格 report-v2.1 第 8.4 节）。
//
// 退出码：0 通过（可能带提示）；2 有拦截项；1 读不了输入。
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

export const CHAPTERS = [
  ['第一章 月度策略总览', 0.08],
  ['第二章 月度时间线与需求节奏', 0.12],
  ['第三章 六地区用户需求深度分析', 0.32],
  ['第四章 地区优先级与机会判断', 0.10],
  ['第五章 SKU 与产品价值策略', 0.14],
  ['第六章 营销主张与促销策略', 0.12],
  ['第七章 月度执行方针', 0.09],
  ['第八章 关键假设与验证事项', 0.03],
];
export const APPENDIX = '附录 研究依据';
export const REGIONS = ['英国', '美国', '香港', '澳洲', '加拿大', '其他'];
export const SKUS = ['灵活学Lite', '安心学Max', '学考无忧Pass', '补考护航Pass', '选课指导', '论文稳Pass', '先修班课'];
export const PROMO_ITEMS = ['促销目标', '适用人群', '核心机制', '选择依据', '商业约束', '验证指标'];
export const PRIORITIES = ['主攻', '培育', '观察'];
export const ROLES = ['主推', '辅推', '条件性承接', '本月不推'];
export const GRADES = ['研究假设版', '条件性策略版', '可执行策略版'];
export const TRACE_HEADER = ['编号', '用户情境', '需求洞察', '可信程度', '商业机会', '产品选择', '价值主张', '促销方案', '执行行动', '验证指标'];
export const CARD_HEADER = ['卡号', '适用人群 / 阶段', '期限与时间条件', '产品条件', '叠加限制', '业务边界', '生效 / 失效条件', '是否采用及理由'];
const ROLE_HEADER = ['SKU', '本月角色', '理由'];
const LABELS = ['〔已验证〕', '〔有依据的判断〕', '〔待验证假设〕'];
const HEDGE = /可能|或许|也许|尚待验证|有待验证|尚需验证/g;
const EMPTY_WORDS = ['赋能', '抓手', '闭环', '全方位', '打造', '助力', '持续发力', '深度赋能'];
const CODES = [
  [/\b(CLM|EV|SCN|REV|SUB)-[A-Za-z0-9-]+/g, '研究对象编号'],
  [/\bBR-[MCOFR]\d\b/g, '障碍编码'],
  [/\b(inferred|unknown|known|partial|not_applicable|evidenceStrength)\b/g, '状态码'],
];

// 不计空白和 Markdown 标记的字数
export const size = text => text.replace(/[\s*_`>#|-]/g, '').length;

export function splitSections(text) {
  const lines = text.split('\n');
  const heads = [];
  lines.forEach((line, i) => { const m = line.match(/^## (.+?)\s*$/); if (m) heads.push({ title: m[1], line: i }); });
  return heads.map((h, k) => ({ title: h.title, body: lines.slice(h.line + 1, k + 1 < heads.length ? heads[k + 1].line : lines.length).join('\n') }));
}

// Markdown 表格：连续的「|」行，第二行是分隔行
export function tables(text) {
  const out = [];
  const lines = String(text || '').split('\n');
  const cells = l => l.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map(c => c.trim());
  for (let i = 0; i < lines.length; i++) {
    if (!/^\s*\|/.test(lines[i]) || !/^\s*\|[\s|:-]+\|?\s*$/.test(lines[i + 1] || '')) continue;
    const t = { header: cells(lines[i]), rows: [] };
    let j = i + 2;
    for (; j < lines.length && /^\s*\|/.test(lines[j]); j++) t.rows.push(cells(lines[j]));
    out.push(t);
    i = j - 1;
  }
  return out;
}
const findTable = (text, header) => tables(text).find(t => header.every((h, k) => t.header[k] === h));

// 「#### 方案 N：标题」及其下的「- 项：内容」
export function promoPlans(body) {
  const lines = body.split('\n');
  const plans = [];
  let cur = null;
  for (const line of lines) {
    const h = line.match(/^####\s*方案\s*\S*?[：:]\s*(.+?)\s*$/);
    if (h) { cur = { title: h[1], items: {} }; plans.push(cur); continue; }
    if (/^#{2,4}\s/.test(line)) { cur = null; continue; }
    const f = cur && line.match(/^\s*[-*]\s*([^：:]+?)[：:]\s*(.*)$/);
    if (f) cur.items[f[1].trim()] = f[2].trim();
  }
  return plans;
}

// 灌水检测：同一句话（12 字以上）在正文出现多次，重复部分占正文的比例
export function repetition(body) {
  const counts = new Map();
  for (const raw of body.split(/[。！？!?\n]/)) {
    const s = raw.replace(/^[\s>*#|-]+|[\s|*]+$/g, '');
    if (size(s) >= 12) counts.set(s, (counts.get(s) || 0) + 1);
  }
  const repeated = [...counts].filter(([, n]) => n > 1).sort((a, b) => (b[1] - 1) * size(b[0]) - (a[1] - 1) * size(a[0]));
  const dup = repeated.reduce((n, [s, k]) => n + (k - 1) * size(s), 0);
  const total = size(body);
  return { share: total ? dup / total : 0, top: repeated.slice(0, 3).map(([s, n]) => `「${s.length > 30 ? `${s.slice(0, 30)}…` : s}」×${n}`) };
}

// 按输入判断报告最高能写到哪一级（规格 report-v2.1 第 8.4 节）
export function allowedGrade({ digest, products, mainSkus = [] }) {
  const why = [];
  const biz = (digest.match(/^- 业务背景卡：(.*)$/m) || [])[1] || '';
  const has = k => new RegExp(`${k}✓`).test(biz);
  const obs = has('用户观察'), stock = has('存量用户情况');
  const noCard = /没有产品能力卡/.test(products);
  const filled = {};
  for (const m of products.matchAll(/^### (\S+?)（已填 (\d)\/5）/gm)) filled[m[1]] = Number(m[2]);
  const empty = SKUS.filter(s => !filled[s]).length;
  const current = /本月（\d{4}-\d{2}）已录入/.test(products);
  if (!obs && !stock) why.push('业务背景卡「用户观察」「存量用户情况」都没填');
  if (noCard) why.push('没有产品能力卡');
  else if (empty >= 4) why.push(`产品能力卡 ${empty} 个 SKU 一项没填`);
  if (why.length) return { grade: GRADES[0], why };
  if (!obs) why.push('「用户观察」没填');
  if (!stock) why.push('「存量用户情况」没填');
  const partial = mainSkus.filter(s => (filled[s] ?? 0) < 5);
  if (!mainSkus.length) why.push('第五章没有主推 SKU');
  if (partial.length) why.push(`主推 SKU 能力卡没填满：${partial.join('、')}`);
  if (!current) why.push('活动基线不是本月');
  return why.length ? { grade: GRADES[1], why } : { grade: GRADES[2], why: [] };
}

// design.md 的决策追溯表与候选卡核对表（P1-04、P1-02）
export function checkTrace(design, { synthesis, mainSkus = [], planTitles = [] } = {}) {
  const errors = [];
  const trace = findTable(design, TRACE_HEADER);
  if (!trace) return [`design.md 缺「决策追溯」表，表头应为：| ${TRACE_HEADER.join(' | ')} |`];
  if (!trace.rows.length) errors.push('决策追溯表没有内容');
  const col = name => TRACE_HEADER.indexOf(name);
  trace.rows.forEach((r, i) => {
    const id = r[0] || `第 ${i + 1} 行`;
    const blank = TRACE_HEADER.filter((h, k) => !(r[k] || '').trim());
    if (blank.length) errors.push(`决策追溯 ${id}：这些格是空的：${blank.join('、')}`);
    if (r[col('需求洞察')] && !/I-\d+/.test(r[col('需求洞察')])) errors.push(`决策追溯 ${id}：「需求洞察」要引用 synthesis.md 的洞察编号（I-01 这类）`);
  });
  if (synthesis !== undefined) {
    const defined = new Set([...synthesis.matchAll(/^\|\s*(I-\d+)\s*\|/gm)].map(m => m[1]));
    const used = [...new Set(trace.rows.flatMap(r => (r[col('需求洞察')] || '').match(/I-\d+/g) || []))];
    const missing = used.filter(id => !defined.has(id));
    if (missing.length) errors.push(`决策追溯引用的洞察编号在 synthesis.md 关键洞察清单里找不到：${missing.join('、')}`);
  }
  const products = trace.rows.map(r => r[col('产品选择')] || '').join('\n');
  const untraced = mainSkus.filter(s => !products.includes(s));
  if (untraced.length) errors.push(`报告第五章的主推 SKU 在决策追溯表里追不到：${untraced.join('、')}`);
  const promos = trace.rows.map(r => r[col('促销方案')] || '');
  const lost = planTitles.filter(t => !promos.some(p => p.includes(t)));
  if (lost.length) errors.push(`报告第六章的促销方案在决策追溯表里追不到：${lost.join('、')}`);
  const cards = findTable(design, CARD_HEADER);
  const adopted = new Set((cards?.rows || []).filter(r => /^(采用|附条件采用)/.test(r[7] || '')).map(r => r[0]));
  for (const p of promos.filter(Boolean)) {
    const ids = p.match(/P\d{4}/g) || [];
    if (!ids.length && !/非打法库|不额外促销/.test(p)) errors.push(`决策追溯「促销方案」要写对应卡号，或注明「非打法库机制」「本月不额外促销」：${p}`);
    const bad = ids.filter(id => !adopted.has(id));
    if (bad.length) errors.push(`促销方案用到的卡不在候选卡核对表里，或没标「采用 / 附条件采用」：${bad.join('、')}`);
  }
  if (promos.some(p => /P\d{4}/.test(p)) && !cards) errors.push(`design.md 缺「候选卡核对表」，表头应为：| ${CARD_HEADER.join(' | ')} |`);
  (cards?.rows || []).forEach(r => {
    const blank = CARD_HEADER.filter((h, k) => !(r[k] || '').trim());
    if (blank.length) errors.push(`候选卡核对表 ${r[0] || '某行'}：这些格是空的（原文没写就填「卡片未写」）：${blank.join('、')}`);
  });
  return errors;
}

const firstParagraph = (body, heading) => {
  const lines = body.split('\n');
  const start = lines.findIndex(l => l.startsWith(heading));
  if (start < 0) return null;
  const para = [];
  for (const line of lines.slice(start + 1)) {
    if (line.startsWith('#')) break;
    if (!line.trim()) { if (para.length) break; continue; }
    para.push(line);
  }
  return para.join('');
};

export function checkReport(text, { month, synthesis, design, digest, products } = {}) {
  const errors = [], warnings = [];
  const title = text.split('\n').find(l => l.startsWith('# '));
  const tm = title?.match(/^# (\d{4}-\d{2}) 月度用户策略报告\s*$/);
  if (!tm) errors.push('第一行标题应为「# YYYY-MM 月度用户策略报告」');
  else if (month && tm[1] !== month) errors.push(`标题月份 ${tm[1]} 和目标月份 ${month} 不一致`);

  const head = text.split('\n').slice(0, 8).filter(l => l.startsWith('>')).join('\n');
  const grade = (head.match(/报告等级[：:]\s*(研究假设版|条件性策略版|可执行策略版)/) || [])[1] || null;
  if (!grade) errors.push(`报告头（标题下的「>」引用行）要写「报告等级：${GRADES.join(' / ')}」`);

  const sections = splitSections(text);
  const expected = [...CHAPTERS.map(c => c[0]), APPENDIX];
  const titles = sections.map(s => s.title);
  const missing = expected.filter(t => !titles.includes(t));
  if (missing.length) errors.push(`缺少章节（二级标题须一字不差）：${missing.join('、')}`);
  const order = titles.filter(t => expected.includes(t));
  if (!missing.length && order.join('|') !== expected.join('|')) errors.push(`章节顺序不对：${order.join(' → ')}`);
  const extra = titles.filter(t => !expected.includes(t));
  if (extra.length) warnings.push(`有规格以外的二级标题（会挤占正文结构）：${extra.join('、')}`);
  const get = name => sections.find(s => s.title === name)?.body ?? '';

  // 第一章
  const ch1 = get(CHAPTERS[0][0]);
  if (ch1) {
    const para = firstParagraph(ch1, '### 1.1');
    if (para === null) errors.push('第一章缺「### 1.1 月度整体定性」');
    else {
      const n = size(para);
      if (n < 150 || n > 250) errors.push(`第一章 1.1 月度整体定性应是一段 150–250 字的连贯文字，现在 ${n} 字`);
    }
    if (!/^### 1\.2/m.test(ch1)) errors.push('第一章缺「### 1.2 本月核心策略判断」');
    if (!/^### 1\.3/m.test(ch1)) errors.push('第一章缺「### 1.3 本月经营目标」');
    const tradeoff = ch1.split('\n').find(l => /^\|\s*关键取舍\s*\|/.test(l));
    if (!tradeoff || !(tradeoff.split('|')[2] || '').trim()) errors.push('第一章 1.2 表格的「关键取舍」一行没写：要写本月哪些方向暂不重点投入、为什么');
  }

  // 第三章：六个地区都要检查
  const ch3 = get(CHAPTERS[2][0]);
  if (ch3) {
    const heads = ch3.split('\n').filter(l => /^###\s/.test(l)).join('\n');
    const lack = REGIONS.filter(r => !heads.includes(r));
    if (lack.length) errors.push(`第三章缺地区小节（三级标题里要有地区名）：${lack.join('、')}`);
  }

  // 第四章：投入优先级
  const ch4 = get(CHAPTERS[3][0]);
  if (ch4) {
    const t = tables(ch4).find(x => x.header[0] === '地区' && x.header.includes('推荐优先级'));
    if (!t) errors.push('第四章缺地区决策表（第一列「地区」，含「推荐优先级」列）');
    else {
      const k = t.header.indexOf('推荐优先级');
      const lack = [], bad = [], blank = [];
      for (const r of REGIONS) {
        const row = t.rows.find(x => (x[0] || '').startsWith(r));
        if (!row) { lack.push(r); continue; }
        const cell = row[k] || '';
        if (!PRIORITIES.some(p => cell.startsWith(p)) || PRIORITIES.filter(p => cell.includes(p)).length > 1) bad.push(`${r}「${cell || '空'}」`);
        const empty = t.header.filter((h, i) => !(row[i] || '').trim());
        if (empty.length) blank.push(`${r}（${empty.join('、')}）`);
      }
      if (lack.length) errors.push(`第四章地区决策表缺这些地区的行：${lack.join('、')}`);
      if (bad.length) errors.push(`第四章推荐优先级只能选一个：${PRIORITIES.join(' / ')}：${bad.join('、')}`);
      if (blank.length) errors.push(`第四章地区决策表有空格：${blank.join('；')}`);
    }
  }

  // 第五章：七个 SKU 都要表态
  const ch5 = get(CHAPTERS[4][0]);
  let mainSkus = [];
  if (ch5) {
    const t = findTable(ch5, ROLE_HEADER);
    if (!t) errors.push(`第五章缺七个 SKU 的角色表，表头应为：| ${ROLE_HEADER.join(' | ')} |`);
    else {
      const lack = [], bad = [], noReason = [];
      for (const s of SKUS) {
        const row = t.rows.find(x => x[0] === s);
        if (!row) { lack.push(s); continue; }
        if (!ROLES.some(r => (row[1] || '').startsWith(r)) || ROLES.filter(r => (row[1] || '').includes(r)).length > 1) bad.push(`${s}「${row[1] || '空'}」`);
        if (!(row[2] || '').trim()) noReason.push(s);
        if ((row[1] || '').startsWith('主推')) mainSkus.push(s);
      }
      if (lack.length) errors.push(`第五章角色表没有对这些 SKU 表态：${lack.join('、')}`);
      if (bad.length) errors.push(`第五章 SKU 角色只能是 ${ROLES.join(' / ')}：${bad.join('、')}`);
      if (noReason.length) errors.push(`第五章这些 SKU 的角色没写理由：${noReason.join('、')}`);
    }
  }

  // 第六章：促销方案六件事，或明确不额外促销
  const ch6 = get(CHAPTERS[5][0]);
  const plans = ch6 ? promoPlans(ch6) : [];
  if (ch6) {
    const prose = ch6.split('\n').filter(l => !/^#/.test(l)).join('\n');
    if (!plans.length && !prose.includes('本月不额外促销')) errors.push('第六章既没有「#### 方案 N：标题」，也没在正文写明「本月不额外促销」及理由');
    for (const p of plans) {
      const lack = PROMO_ITEMS.filter(i => !p.items[i]);
      if (lack.length) errors.push(`第六章「${p.title}」缺论证项（「- 项：内容」逐项写）：${lack.join('、')}`);
      if (grade === GRADES[0] && !p.title.includes('候选待确认')) errors.push(`研究假设版不出正式促销方案：「${p.title}」标题要标「候选待确认」，或改写为本月不额外促销`);
      if (grade === GRADES[1] && !p.items['前提条件']) errors.push(`条件性策略版的促销方案要写「- 前提条件：」：「${p.title}」`);
    }
  }

  // 第八章：3–5 项
  const ch8 = get(CHAPTERS[7][0]);
  if (ch8) {
    const rows = ch8.split('\n').filter(l => /^\|/.test(l.trim()) && !/^\|\s*-/.test(l.trim()));
    const n = Math.max(0, rows.length - 1);
    if (n < 3 || n > 5) errors.push(`第八章应是 3–5 项关键假设（表格行），现在 ${n} 项；其余未知放附录`);
  }

  // 正文（附录之前）不出现研究层编号和状态码
  const appendixAt = text.indexOf(`## ${APPENDIX}`);
  const body = appendixAt >= 0 ? text.slice(0, appendixAt) : text;
  for (const [re, what] of CODES) {
    const hits = [...new Set(body.match(re) || [])];
    if (hits.length) errors.push(`正文里出现${what}（只能放附录）：${hits.slice(0, 5).join('、')}${hits.length > 5 ? ' 等' : ''}`);
  }

  // 决策追溯（内部文件）
  if (design !== undefined) errors.push(...checkTrace(design, { synthesis, mainSkus, planTitles: plans.map(p => p.title) }));
  else warnings.push('没给 --design：没核对决策追溯表和候选卡核对表');

  // 报告等级不能高于输入能支撑的等级
  if (grade && digest !== undefined && products !== undefined) {
    const allowed = allowedGrade({ digest, products, mainSkus });
    const rank = g => GRADES.indexOf(g);
    if (rank(grade) > rank(allowed.grade)) errors.push(`报告等级写成「${grade}」，输入只够「${allowed.grade}」：${allowed.why.join('；')}`);
    else if (rank(grade) < rank(allowed.grade)) warnings.push(`输入够「${allowed.grade}」，报告写成「${grade}」：保守可以，但要在第一章说明为什么`);
  } else if (grade) warnings.push('没给 --digest 和 --products：没核对报告等级和输入是否相符');

  // 提示
  const total = size(body.replace(title || '', ''));
  const rep = repetition(body);
  if (rep.share > 0.25) errors.push(`正文 ${(rep.share * 100).toFixed(0)}% 是重复的句子，像在灌水：${rep.top.join('、')}`);
  else if (rep.share > 0.05) warnings.push(`正文 ${(rep.share * 100).toFixed(0)}% 是重复的句子：${rep.top.join('、')}`);
  if (total < 6000 || total > 15000) warnings.push(`正文约 ${total} 字，参考范围 8,000–12,000（6,000 以下多半没展开，15,000 以上多半在罗列）`);
  const shares = CHAPTERS.map(([name, target]) => {
    const n = size(get(name));
    const share = total ? n / total : 0;
    if (total && (share < target * 0.5 || share > target * 1.8)) warnings.push(`「${name}」占正文 ${(share * 100).toFixed(0)}%，规格建议约 ${(target * 100).toFixed(0)}%`);
    return { name, chars: n, share: Number(share.toFixed(3)), target };
  });
  const hedges = (body.match(HEDGE) || []).length;
  const density = total ? (hedges / total) * 1000 : 0;
  if (density > 5) warnings.push(`「可能 / 尚待验证」类说法每千字 ${density.toFixed(1)} 次：边界应集中写在节末和第八章，正文敢下判断并标可信程度`);
  const labels = LABELS.reduce((n, l) => n + body.split(l).length - 1, 0);
  if (!labels) warnings.push(`正文没有可信程度标注（${LABELS.join(' ')}），关键判断旁要标`);
  const empties = EMPTY_WORDS.filter(w => body.includes(w));
  if (empties.length) warnings.push(`正文出现空话：${empties.join('、')}`);

  return { errors, warnings, stats: { total, shares, hedgesPerThousand: Number(density.toFixed(1)), confidenceLabels: labels, repeatShare: Number(rep.share.toFixed(3)), grade, mainSkus } };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  const flag = name => { const i = args.indexOf(name); return i >= 0 ? args.splice(i, 2)[1] : undefined; };
  const out = flag('--out'), month = flag('--month');
  const paths = Object.fromEntries(['synthesis', 'design', 'digest', 'products'].map(k => [k, flag(`--${k}`)]));
  const [file] = args;
  if (!file) { process.stderr.write('用法：node report-check.mjs <report.md> [--month YYYY-MM] [--synthesis f] [--design f] [--digest f] [--products f] [--out 结果文件]\n'); process.exit(1); }
  const read = f => { try { return readFileSync(f, 'utf8'); } catch (e) { process.stderr.write(`读不了 ${f}：${e.message}\n`); process.exit(1); } };
  const text = read(file);
  const inputs = Object.fromEntries(Object.entries(paths).filter(([, f]) => f).map(([k, f]) => [k, read(f)]));
  const r = checkReport(text, { month, ...inputs });
  const lines = [
    r.errors.length ? `拦截 ${r.errors.length} 条：` : '机械检查通过。',
    ...r.errors.map(e => `  ✗ ${e}`),
    r.warnings.length ? `提示 ${r.warnings.length} 条：` : '提示 0 条。',
    ...r.warnings.map(w => `  · ${w}`),
    `报告等级：${r.stats.grade ?? '未写'}；主推 SKU：${r.stats.mainSkus.join('、') || '无'}`,
    `正文约 ${r.stats.total} 字；可信程度标注 ${r.stats.confidenceLabels} 处；「可能」类每千字 ${r.stats.hedgesPerThousand} 次；重复句子占 ${(r.stats.repeatShare * 100).toFixed(0)}%`,
    ...r.stats.shares.map(s => `  ${s.name}：${s.chars} 字，${(s.share * 100).toFixed(0)}%（建议约 ${(s.target * 100).toFixed(0)}%）`),
  ];
  const report = lines.join('\n') + '\n';
  process.stdout.write(report);
  if (out) writeFileSync(out, report);
  process.exit(r.errors.length ? 2 : 0);
}
