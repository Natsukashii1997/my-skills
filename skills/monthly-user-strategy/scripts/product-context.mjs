#!/usr/bin/env node
// 取月度报告第五、六章要用的产品与活动输入（规格 report-v2.1 第 8.2 节），只读。
// 摘要（products.md）带能力卡逐项原文和打法卡索引（阶段、障碍、机制、定位），第 3 轮只读摘要也拿得到产品事实（GPT 2.0.0 审核 P1-01、P1-02）。
// 试写期直接读本机工作台的三个只读接口（常浩 2026-11-09 同意）；正式版本会改成 workdesk 智能体工具。
//
//   node product-context.mjs --month YYYY-MM --out-dir <工作目录> [--card <产品能力卡.md>] [--playbook <打法库目录>]
//
// 产出：<工作目录>/products.json（原始返回）、products.md（摘要）。
// 环境变量：WORKDESK_URL（默认 http://127.0.0.1:5280，只允许本机）。
// 退出码：0 成功（某个来源取不到会写进摘要，不算失败）；1 参数错误。
import { readFileSync, writeFileSync, readdirSync, existsSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { SKUS } from './report-check.mjs';

export const LINE = '大学辅导';
const CARD_FIELDS = ['交付什么', '匹配到老师多快', '能否加急', '课时形式与最小购买单位', '明确不提供什么'];

// 产品能力卡：「## <SKU>」下的「- 字段：值」，值非空算填了
export function parseCard(text) {
  const out = {};
  let sku = null;
  for (const line of String(text || '').split('\n')) {
    const h = line.match(/^##\s+(.+?)\s*$/);
    if (h) { sku = SKUS.includes(h[1]) ? h[1] : null; if (sku) out[sku] = {}; continue; }
    const f = sku && line.match(/^-\s*([^：:]+)[：:]\s*(.*)$/);
    if (f) {
      const key = CARD_FIELDS.find(k => f[1].startsWith(k.slice(0, 4)));
      if (key) out[sku][key] = f[2].trim();
    }
  }
  return out;
}

// 能力卡的版本行和「跨 SKU 的共同能力」：共同能力只列填了的
export function parseCardExtras(text) {
  const lines = String(text || '').split('\n');
  const version = lines.map(l => l.match(/^\*\*版本\*\*[：:]\s*(.*)$/)).find(Boolean)?.[1].trim().replace(/[。.]$/, '') || '未写';
  const at = lines.findIndex(l => /^##\s+跨 SKU/.test(l));
  const common = [];
  if (at >= 0) for (const line of lines.slice(at + 1)) {
    if (/^##\s/.test(line)) break;
    const f = line.match(/^-\s*([^：:]+)[：:]\s*(.*)$/);
    if (f && f[2].trim()) common.push([f[1].trim(), f[2].trim()]);
  }
  return { version, common };
}

// 打法卡：首行「# 名称 · 类别名」，第二行元信息「<!-- P0901 | 类别 9 | 阶段 续费 | 障碍 B1 ; A2 | 机制 M19 M16 -->」，「**定位**：」取第一句
export const BARRIERS = { A1: '没意识到需要', A2: '觉得还来得及', A3: '不信任效果', A4: '有替代品', B1: '嫌贵', B2: '怕选错', B3: '没时间', B4: '需要家长同意', C1: '没被触达' };
// 打法卡元信息仍用旧编号；对应的 v2 编码按 niuma-home 规则 02（barrier-v2.1）第 1、3 节，「近似」只用于续费栏
export const BARRIERS_V2 = { A1: 'BR-M1；续费近似 BR-R2', A2: 'BR-M2', A3: 'BR-M3；续费近似 BR-R1', A4: 'BR-M4', B1: 'BR-C1；续费近似 BR-R5', B2: 'BR-C2', B3: 'BR-C3', B4: 'BR-C4', C1: 'BR-O1' };
export function parsePlaybookCard(text, file = '') {
  const lines = String(text || '').split('\n');
  const name = (lines.find(l => /^#\s/.test(l)) || '').replace(/^#\s+/, '').split(' · ')[0].trim();
  const meta = (lines.find(l => /^<!--\s*P\d+/.test(l)) || '').replace(/^<!--|-->$/g, '').split('|').map(x => x.trim());
  const field = key => (meta.find(x => x.startsWith(key)) || '').slice(key.length).trim();
  const id = meta[0] || (file.match(/^P\d+/) || [''])[0];
  const pos = (lines.find(l => /^\*\*定位\*\*/.test(l)) || '').replace(/^\*\*定位\*\*[：:]\s*/, '');
  const first = pos.match(/^.*?。/)?.[0] || pos;
  return {
    id, name, file,
    stage: field('阶段') || '未标',
    barriers: field('障碍').split(/[;；\s]+/).filter(Boolean),
    mechanisms: field('机制').split(/\s+/).filter(Boolean),
    position: first.replace(/\*\*/g, '').trim(),
    // 全文指纹：名称、元信息、定位句不变而正文条款（叠加、期限、边界）变了，交付前 diff products.md 也看得出来（Codex 审查 PR #81 ⑤）
    sha: createHash('sha256').update(String(text || '')).digest('hex').slice(0, 12),
  };
}

// 活动基线：目标月有录入就用目标月，否则用不晚于目标月的最近一个月
export function baseMonth(promos, month) {
  const months = [...new Set((promos || []).filter(p => p.line === LINE).map(p => p.month))].filter(m => m <= month).sort();
  return months.at(-1) ?? null;
}

const cellText = v => String(v ?? '').replace(/\n/g, ' ').replace(/\|/g, '／');

export function summarize({ month, promos, plan, skus, card, cardExtras = { version: '未写', common: [] }, playbook, playbookDir = '<niuma-home>/docs/打法库', errors = {} }) {
  const base = baseMonth(promos, month);
  const lines = [`# 产品与活动输入 · ${month}`, '', '来源：本机工作台只读接口（/api/promos、/api/plans、/api/v3/price/skus）、产品能力卡、打法库。只作第五、六章的输入；价格金额归价格模块，报告里不编金额。', ''];
  lines.push('## 当月活动基线', '');
  if (errors.promos) lines.push(`- 促销表读取失败：${errors.promos}。第六章按「现行活动未知」处理。`);
  else if (!base) lines.push(`- ${LINE}没有不晚于 ${month} 的促销录入。第六章按「现行活动未知」处理。`);
  else {
    lines.push(base === month ? `- 本月（${month}）已录入。` : `- **本月（${month}）未录入**，以最近一个月 ${base} 为基线；它不是本月已生效的活动，跨月权益要按「当月即时可用 / 跨月预告 / 满足条件后适用」核对。`, '');
    lines.push('| SKU | 试听 | 正价 | 新签活动 | 续费活动 | 特殊活动 |', '|---|---|---|---|---|---|');
    for (const s of SKUS) {
      const p = promos.find(x => x.line === LINE && x.month === base && x.sku === s);
      const cell = v => String(v ?? '—').replace(/\n/g, ' ').replace(/\|/g, '／');
      lines.push(p ? `| ${s} | ${cell(p.trial)} | ${cell(p.price)} | ${cell(p.newDeal)} | ${cell(p.renewal)} | ${cell(p.special)} |` : `| ${s} | （${base} 未录入） | | | | |`);
    }
    lines.push('', `整月特殊活动（${base}）：${errors.plan ? `读取失败：${errors.plan}` : String(plan?.special ?? '无').replace(/\n/g, '；')}`);
  }
  lines.push('', '## 价格档案', '');
  if (errors.skus) lines.push(`- 读取失败：${errors.skus}`);
  else {
    const uni = (skus || []).filter(s => s.line === LINE);
    if (!uni.length) lines.push('- 没有大学辅导的价格档案。');
    for (const s of uni) lines.push(`- ${s.name}：单价原价 ${s.unitOrig ?? '—'}，档位 ${(s.tiers || []).join(' / ') || '—'}，来源 ${s.origin}${s.origin === 'demo' ? '（**演示数据，不能引用**）' : ''}`);
    const lack = SKUS.filter(n => !uni.some(s => s.name === n));
    if (lack.length) lines.push(`- 没有价格档案：${lack.join('、')}`);
  }
  lines.push('', '## 产品能力卡', '');
  if (card === null) lines.push('- **没有产品能力卡**。第五章所有卖点写「需确认产品能力：……」，第八章把产品能力列为首要验证事项。');
  else {
    lines.push(`能力卡版本：${cardExtras.version}。下面是常浩填写的原文，卖点和交付条件只能从这里取；「未填」的能力在报告里一律写「需确认产品能力」，不替常浩补。`);
    for (const s of SKUS) {
      const f = card[s] || {};
      const filled = CARD_FIELDS.filter(k => f[k]);
      lines.push('', `### ${s}（已填 ${filled.length}/${CARD_FIELDS.length}）`, '');
      for (const k of CARD_FIELDS) lines.push(`- ${k}：${f[k] ? cellText(f[k]) : '未填'}`);
    }
    lines.push('', '### 跨 SKU 的共同能力', '');
    if (cardExtras.common.length) for (const [k, v] of cardExtras.common) lines.push(`- ${k}：${cellText(v)}`);
    else lines.push('- 未填');
  }
  lines.push('', '## 打法库', '');
  if (!playbook?.length) lines.push('- 没有读到打法库。第六章只能用通用机制名，写明未对照打法卡。');
  else {
    lines.push(`${playbook.length} 张卡，是第六章的候选机制池（按 references/design.md 第 4 节选用）。下表只是索引：**进入候选的卡必须读原文**（\`${playbookDir}/<文件>\`），在 design.md 的「候选卡核对表」写清适用人群、期限、产品条件、叠加限制、业务边界和生效 / 失效条件；只看这张表不能定方案。`, '');
    lines.push('| 卡号 | 名称 | 阶段（适用人群） | 针对的障碍 | 机制 | 定位 | 文件 | 全文指纹 |', '|---|---|---|---|---|---|---|---|');
    for (const c of playbook) lines.push(`| ${c.id} | ${cellText(c.name)} | ${c.stage} | ${c.barriers.map(b => `${b} ${BARRIERS[b] ?? ''}${BARRIERS_V2[b] ? `（${BARRIERS_V2[b]}）` : ''}`.trim()).join('；') || '未标'} | ${c.mechanisms.join(' ') || '未标'} | ${cellText(c.position) || '（没有定位句）'} | ${c.file} | ${c.sha ?? '—'} |`);
    lines.push('', '阶段「新签」的卡不能用于续费，「续费」的卡不能用于新签；「通用」两者都可，但仍要过六个匹配条件。', '「针对的障碍」是卡片上的旧编号，括号里是对应的 v2 编码（规则 02 第 3 节）；BR-M5、BR-F1、BR-R3、BR-R4 没有对应旧编号，没有自动候选卡，要手工提名并写明作用方式，或判断促销不是主要解法。');
  }
  return { base, text: lines.join('\n') + '\n' };
}

async function get(base, path) {
  const res = await fetch(`${base}${path}`, { signal: AbortSignal.timeout(30_000) });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  const flag = name => { const i = args.indexOf(name); return i >= 0 ? args.splice(i, 2)[1] : undefined; };
  const month = flag('--month'), outDir = flag('--out-dir'), cardPath = flag('--card'), playbookDir = flag('--playbook');
  const die = m => { process.stderr.write(`${m}\n`); process.exit(1); };
  if (!/^\d{4}-\d{2}$/.test(month || '') || !outDir) die('用法：node product-context.mjs --month YYYY-MM --out-dir <工作目录> [--card <产品能力卡.md>] [--playbook <打法库目录>]');
  const base = (process.env.WORKDESK_URL || 'http://127.0.0.1:5280').replace(/\/$/, '');
  if (!/^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(base)) die(`WORKDESK_URL 只能是本机地址，现在是 ${base}`);
  const errors = {};
  const safe = async (key, fn) => { try { return await fn(); } catch (e) { errors[key] = e.message; return null; } };
  const promos = await safe('promos', () => get(base, '/api/promos'));
  const bm = baseMonth(promos, month);
  const plan = bm ? await safe('plan', () => get(base, `/api/plans/${bm}/${encodeURIComponent(LINE)}`)) : null;
  const skus = await safe('skus', () => get(base, '/api/v3/price/skus'));
  const cardText = cardPath && existsSync(cardPath) ? readFileSync(cardPath, 'utf8') : null;
  const card = cardText === null ? null : parseCard(cardText);
  const cardExtras = parseCardExtras(cardText);
  const playbook = playbookDir && existsSync(playbookDir)
    ? readdirSync(playbookDir).filter(f => /^P\d+.*\.md$/.test(f)).sort().map(f => parsePlaybookCard(readFileSync(join(playbookDir, f), 'utf8'), f))
    : null;
  const { text } = summarize({ month, promos, plan, skus, card, cardExtras, playbook, playbookDir, errors });
  mkdirSync(outDir, { recursive: true });
  writeFileSync(join(outDir, 'products.json'), JSON.stringify({ month, baseMonth: bm, promos, plan: plan && { month: plan.month, line: plan.line, special: plan.special, savedAt: plan.savedAt }, skus, card, cardExtras, playbook, errors }, null, 2) + '\n');
  writeFileSync(join(outDir, 'products.md'), text);
  process.stdout.write(`已写入 ${join(outDir, 'products.md')}${Object.keys(errors).length ? `（取不到：${Object.keys(errors).join('、')}）` : ''}\n`);
}
