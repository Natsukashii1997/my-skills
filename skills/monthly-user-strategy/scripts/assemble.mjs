#!/usr/bin/env node
// 把研判稿（draft.json）组装成 schema 2.1 月度文档，补齐机械字段，做本地预检，写出 strategy_submit 的参数。只读写本地文件，不调用接口。
//   node assemble.mjs <facts.json> <draft.json> --out-dir <目录> [--prev-facts <研判时用的旧底稿>]
// 产出：全部通过才写 <目录>/document.json、<目录>/submit-args.json；每次开始先删掉这两个旧文件，
// 预检有拦截项时只写 <目录>/assemble-errors.txt，退出码 2（不会留下看起来能提交的旧参数）。
//
// 机械字段（不要在研判稿里手写）：schemaVersion、window、inputs、producedBy、regions[].activity（照抄服务端覆盖率）、
// regions[].priority.default（05 §7 矩阵）、regions[].scenarios（按情境的 region 归集）、Claim 的 refVersions 与 origin、
// 空的 opportunities / strategies（批 1 只接受空数组）、正式版本里常浩手写（origin=manual）的 Claim 原样带上。
// 预检只覆盖生成时最常犯的规则；以服务端 strategy_submit 的校验为准（它会重算覆盖率、逐条校验全部不变量）。
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const REGION_KEYS = ['uk', 'us', 'hk', 'au', 'ca', 'other'];
const MATRIX = { 高: ['主战场', '主战场', '次要'], 中: ['主战场', '次要', '平稳'], 低: ['次要', '平稳', '平稳'] };
export const defaultPriority = (key, value) => MATRIX[value]?.[['uk', 'us'].includes(key) ? 0 : key === 'other' ? 2 : 1] ?? null;
const nextMonth = m => { const [y, n] = m.split('-').map(Number); return n === 12 ? `${y + 1}-01` : `${y}-${String(n + 1).padStart(2, '0')}`; };
const lastDay = m => { const [y, n] = m.split('-').map(Number); return new Date(Date.UTC(y, n, 0)).toISOString().slice(0, 10); };
// 计字：中文一字一单位，英文单词、数字串各算一个（近似工作台 units()，只用于提示）。
const units = s => (String(s).match(/[一-鿿]|[A-Za-z0-9]+|[^\s一-鿿A-Za-z0-9]/g) || []).length;
const CODE_IN_PROSE = /BR-[A-Z]\d|\bP\d{4}\b|\b[A-C]\d\b/;
const STRENGTH_CAP = { verified: 'strong', ruled: 'strong', source: 'partial', guess: 'weak', conflict: 'weak' };
const BIZ_CAP = { 事实记录: 'strong', 业务观察: 'partial', 管理判断: 'weak' };
const RANK = { none: 0, weak: 1, partial: 2, strong: 3 };
const SELF_CHECK = ['事实与来源核验', '地区与人群覆盖', '任务与需求推导', '购买障碍论证', '机会排序合理性', '促销匹配及适用性（批 2 起）', '章节一致性与反例检查', '跨部门发布完整性'];
const KNOWN_COUNTRIES = ['us', 'uk', 'hk', 'au', 'ca', 'sg', 'my', 'nz', 'mo', 'ie'];
const SOURCE_IDS = ['SRC-timeline', 'SRC-official', 'SRC-ruling', 'SRC-bizcard', 'SRC-playbook', 'SRC-voice', 'SRC-crm', 'SRC-service'];
const ONLY_NEW = ['BR-M1', 'BR-O1'], ONLY_RENEW = ['BR-R1', 'BR-R2', 'BR-R3', 'BR-R4', 'BR-R5'];
const ALL_BARRIERS = ['BR-M1', 'BR-M2', 'BR-M3', 'BR-M4', 'BR-M5', 'BR-C1', 'BR-C2', 'BR-C3', 'BR-C4', 'BR-O1', 'BR-F1', ...ONLY_RENEW];

export function skillVersion() {
  const here = dirname(fileURLToPath(import.meta.url));
  return (readFileSync(join(here, '..', 'SKILL.md'), 'utf8').match(/^\s*version:\s*"([^"]+)"/m) || [])[1] ?? 'unknown';
}

/** @returns {{ document, submitArgs, errors: string[], warnings: string[] }} */
export function assemble(facts, draft, { version = skillVersion(), prevFacts = null } = {}) {
  const errors = [], warnings = [];
  const err = (at, m) => errors.push(`${at}：${m}`), warn = (at, m) => warnings.push(`${at}：${m}`);
  const month = facts.month;
  if (draft.month !== month) err('draft.month', `须与事实底稿的月份 ${month} 一致`);
  const ev = new Map(facts.evidence.map(e => [e.evidenceId, e]));
  const card = facts.bizcard || {};
  const hasField = k => (card[k] || []).length > 0;
  // 用户决策行为证据（02 §2.3）：背景卡的事实记录、业务观察，或 Voice。管理判断只是待检验的假设，学校日历只是情境依据，都不算。
  const isBehavioral = id => { const e = ev.get(id); return e?.kind === 'voice' || (e?.kind === 'business' && ['事实记录', '业务观察'].includes(e.bizType)); };
  const cap = id => { const e = ev.get(id); return !e ? 'none' : e.kind === 'business' ? BIZ_CAP[e.bizType] ?? 'weak' : STRENGTH_CAP[e.verification] ?? 'weak'; };

  // 研判稿绑定底稿（I-06）：draft.basedOnFingerprint 是研判时底稿的 inputFingerprint。和当前底稿不同，就必须给出那份旧底稿逐条比对；
  // 研判稿引用的 Evidence 版本变了或不见了，对应对象须重新研判，不能静默换成新版本。
  if (!draft.basedOnFingerprint) err('draft.basedOnFingerprint', '须写研判时所用底稿的 inputFingerprint（digest.md 顶部）');
  else if (draft.basedOnFingerprint !== facts.inputFingerprint) {
    if (!prevFacts) err('draft.basedOnFingerprint', `研判稿基于底稿 ${draft.basedOnFingerprint}，当前底稿是 ${facts.inputFingerprint}：须用 --prev-facts 给出研判时的底稿，逐条比对依据版本`);
    else if (prevFacts.inputFingerprint !== draft.basedOnFingerprint) err('draft.basedOnFingerprint', `--prev-facts 的底稿指纹 ${prevFacts.inputFingerprint} 与研判稿的 ${draft.basedOnFingerprint} 不符`);
  }
  if (prevFacts) {
    const before = new Map(prevFacts.evidence.map(e => [e.evidenceId, e.evidenceVersion]));
    for (const o of [...(draft.scenarios || []), ...(draft.claims || []), ...['common', 'diff', 'external'].flatMap(k => (draft.brief?.[k] || []).map((x, i) => ({ ...x, id: `brief.${k}[${i}]` })))])
      for (const id of o.evidenceRefs || []) {
        if (!ev.has(id)) err(o.id, `依据 ${id} 在新底稿里已不存在，须重新研判`);
        else if (before.has(id) && before.get(id) !== ev.get(id).evidenceVersion) err(o.id, `依据 ${id} 的版本已变化，须重新研判`);
      }
  }
  const scenarios = (draft.scenarios || []).map(s => ({ ...s, schools: s.schools ?? [] }));
  const manual = (facts.revision?.claims || []).filter(c => c.origin === 'manual');
  const claims = (draft.claims || []).map(c => {
    if (c.origin === 'manual') err(c.id, 'skill 不能写 origin=manual');
    const refVersions = Object.fromEntries((c.evidenceRefs || []).filter(id => ev.has(id)).map(id => [id, ev.get(id).evidenceVersion]));
    return { ...c, refVersions, origin: 'skill' };
  });
  for (const m of manual) {
    if (claims.some(c => c.id === m.id)) err(m.id, '与常浩手写的 Claim 同号；skill 的 Claim 换一个编号，手写内容由脚本原样带上');
    else claims.push(m);
    if (!scenarios.some(s => s.id === m.scenario)) warn(m.id, `常浩手写的 Claim 指向的情境 ${m.scenario} 不在本稿里，服务端会拦截；保留该情境或请常浩处理`);
  }

  const regions = REGION_KEYS.map(key => {
    const d = draft.regions?.[key];
    const c = facts.coverage[key];
    if (!d) err(`regions.${key}`, '研判稿缺少这个地区（六个地区都要写）');
    const ids = scenarios.filter(s => s.region === key).map(s => s.id);
    const def = defaultPriority(key, c?.value);
    const value = d?.priority === undefined ? def : d.priority;
    if (value !== null && value !== def && !d?.reason) err(`regions.${key}`, `优先级 ${value} 与默认 ${def ?? '无'} 不同，须写 reason`);
    if (value === null && !String(d?.reason || '').includes('待研判')) err(`regions.${key}`, '优先级为 null 时 reason 须写「待研判」及原因');
    if (!ids.length && !d?.emptyReason) err(`regions.${key}`, '没有情境时须写 emptyReason（原因 + 覆盖情况）');
    if (ids.length && d?.emptyReason) warn(`regions.${key}`, '有情境却写了 emptyReason，已忽略');
    if (ids.length > 4) warn(`regions.${key}`, '情境超过 4 个，可能拆得过细');
    return {
      key,
      priority: { value, default: def, reason: d?.reason ?? null },
      activity: c ? { value: c.value, status: c.status, ratio: c.ratio, dateQuality: c.dateQuality, coverage: c.coverage, byCountry: c.byCountry ?? null } : { value: 'unknown', status: 'unknown', ratio: null },
      scenarios: ids,
      emptyReason: ids.length ? null : d?.emptyReason ?? null,
    };
  });

  // —— 预检 ——
  const seen = new Set();
  for (const o of [...scenarios, ...claims]) { if (seen.has(o.id)) err(o.id, '对象 ID 重复'); seen.add(o.id); }
  const scenarioIds = new Set(scenarios.map(s => s.id)), claimIds = new Set(claims.map(c => c.id));
  const refsOk = (list, at) => (list || []).forEach(id => { if (!ev.has(id)) err(at, `引用的 Evidence ${id} 不在事实底稿里（不要自己编 ID）`); });
  const judged = (o, at) => {
    refsOk(o.evidenceRefs, at);
    const refs = (o.evidenceRefs || []).filter(id => ev.has(id));
    const best = refs.reduce((m, id) => Math.max(m, RANK[cap(id)]), 0);
    if (o.status === 'known') {
      if (o.evidenceStrength !== 'strong' || !refs.length) err(at, 'known 须 evidenceStrength=strong 且有 evidenceRefs');
      else if (best < 3) err(at, 'known 引用的证据没有一条到 strong（原表日期最高 partial，推测 weak）');
      if (refs.some(id => ev.get(id).ambiguous)) err(at, 'ambiguous 的 Evidence 不能作 known 的依据');
    } else if (o.status === 'inferred') {
      if (!['partial', 'weak'].includes(o.evidenceStrength) || !o.limitations) err(at, 'inferred 须 partial / weak，且写 limitations');
      if (o.evidenceStrength === 'partial' && best < 2) err(at, 'partial 引用的证据没有一条到 partial');
    } else if (o.status === 'unknown') {
      if (o.evidenceStrength !== 'none') err(at, 'unknown 的 evidenceStrength 须为 none');
      if (!o.gap || !['available', 'unavailable', 'research'].includes(o.route?.status)) err(at, 'unknown 须写 gap 和 route.status');
      if (o.route?.source && !SOURCE_IDS.includes(o.route.source)) err(at, `route.source ${o.route.source} 不在来源登记表内`);
      if (o.route?.status === 'available' && !o.route?.source) err(at, 'route.status=available 时须写 route.source');
    } else if (o.status === 'not_applicable') {
      if (!o.limitations) err(at, 'not_applicable 须在 limitations 写原因');
    } else err(at, `status ${o.status} 不合法`);
    if (CODE_IN_PROSE.test(o.text || '')) warn(at, '正文里出现障碍编码或打法编号（I-15，只提示）');
  };

  const brief = draft.brief || {};
  if (!draft.judgement?.text) err('judgement', '缺少一句话月度判断');
  else {
    if (units(draft.judgement.text) > 100) warn('judgement', '月度判断超过 100 字');
    if (!(draft.judgement.claims || []).length) err('judgement', 'claims 不能为空');
    for (const id of draft.judgement.claims || []) if (!claimIds.has(id)) err('judgement', `引用的 Claim ${id} 不存在`);
    if (CODE_IN_PROSE.test(draft.judgement.text)) warn('judgement', '正文里出现障碍编码或打法编号（I-15）');
  }
  for (const k of ['common', 'diff', 'external']) (brief[k] || []).forEach((item, i) => judged(item, `brief.${k}[${i}]`));

  for (const s of scenarios) {
    const at = s.id || 'scenario';
    if (!new RegExp(`^SCN-${month}-${s.region}-\\d{2}$`).test(s.id || '')) err(at, `id 须为 SCN-${month}-<地区>-<两位序号>，且地区与 region 一致`);
    if (!REGION_KEYS.includes(s.region)) err(at, 'region 不是地区 key');
    if (!(s.countries || []).length || s.countries.some(c => !/^[a-z]{2}$/.test(c) || c === 'other')) err(at, 'countries 须为小写具体国家代码，不能写 other');
    // 国家代码要对得上 schema 2.1 的归一化表（或底稿里实际出现的国家），并且属于情境所在地区（如英国是 uk，不是 gb）。
    for (const c of s.countries || []) {
      if (!KNOWN_COUNTRIES.includes(c) && !facts.evidence.some(e => e.country === c)) err(at, `countries 里的 ${c} 不在归一化表里，也没在底稿出现（英国写 uk）`);
      else if ((['uk', 'us', 'hk', 'au', 'ca'].includes(c) ? c : 'other') !== s.region) err(at, `国家 ${c} 不属于地区 ${s.region}`);
    }
    if (!['undergraduate', 'postgraduate'].includes(s.academicStage)) err(at, 'academicStage 须为 undergraduate / postgraduate');
    if (!s.phase || !s.keyTask) err(at, '须写 phase 与 keyTask');
    if (!['新签', '续费', '通用'].includes(s.targetRelation)) err(at, 'targetRelation 须为 新签 / 续费 / 通用');
    if (!(s.evidenceRefs || []).length) err(at, 'evidenceRefs 至少一个');
    refsOk(s.evidenceRefs, at);
    const obs = s.observedRelation || {};
    if (!['新签', '续费', 'unknown'].includes(obs.value)) err(at, 'observedRelation.value 须为 新签 / 续费 / unknown');
    refsOk(obs.evidenceRefs, `${at}.observedRelation`);
    if (obs.value && obs.value !== 'unknown' && !(obs.evidenceRefs || []).some(id => ev.get(id)?.kind === 'business')) err(at, '实际商业关系须有 business 类 Evidence（I-05）');
    if (s.targetRelation === '续费' && !hasField('存量用户情况') && obs.value !== 'unknown') err(at, '没有存量用户情况时，续费情境的 observedRelation 须为 unknown（07 §3）');
  }

  const primaries = new Map();
  for (const c of claims.filter(x => x.origin === 'skill')) {
    const at = c.id || 'claim';
    if (!new RegExp(`^CLM-${month}-\\d+$`).test(c.id || '')) err(at, `id 须为 CLM-${month}-<序号>`);
    if (!scenarioIds.has(c.scenario)) err(at, `引用的 Scenario ${c.scenario} 不存在`);
    if (!['task', 'academic_need', 'pain', 'need_strength', 'readiness', 'barrier'].includes(c.claimType)) err(at, 'claimType 不合法');
    if (!c.text) err(at, '缺少 text'); else if (units(c.text) > 40) warn(at, '正文超过 40 字');
    judged(c, at);
    for (const id of c.dependsOn || []) if (!claimIds.has(id)) err(at, `依赖的 Claim ${id} 不存在`);
    // 学业需求、痛点只有时间线证据时最高 inferred + weak：考试存在只证明有任务，不证明需求或困难（06 阶段 03）。
    if (['academic_need', 'pain'].includes(c.claimType) && ['known', 'inferred'].includes(c.status) && c.evidenceStrength !== 'weak'
      && !(c.evidenceRefs || []).some(id => ['business', 'voice'].includes(ev.get(id)?.kind))) err(at, `${c.claimType} 只有时间线证据时最高 inferred + weak`);
    if (c.claimType === 'pain') {
      if (!['typical', 'observed'].includes(c.painKind)) err(at, 'pain 须写 painKind');
      if (c.painKind === 'observed' && !hasField('用户观察')) err(at, '没有用户观察时痛点只能是 typical（07 §3）');
      else if (c.painKind === 'observed' && !(c.evidenceRefs || []).some(id => ev.get(id)?.kind === 'voice' || (ev.get(id)?.kind === 'business' && ev.get(id).field === '用户观察'))) err(at, 'observed 痛点须引用对应的用户观察条目（或 Voice），否则只能 typical');
    }
    if (['need_strength', 'readiness'].includes(c.claimType) && (c.status === 'unknown' ? c.level != null : !['高', '中', '低'].includes(c.level))) err(at, 'level 须为 高 / 中 / 低，unknown 时为 null');
    if (['barrier', 'readiness'].includes(c.claimType)) {
      if (!['新签', '续费', '通用'].includes(c.targetRelation)) err(at, 'targetRelation 须为 新签 / 续费 / 通用');
      if (c.targetRelation === '续费' && !hasField('存量用户情况')) {
        if (c.status !== 'unknown') err(at, '没有存量用户情况时，续费的障碍、购买准备度须为 unknown（07 §3）');
        else if (c.route?.status !== 'available' || c.route?.source !== 'SRC-bizcard') err(at, '续费缺存量用户情况时 route 须为 { status: available, source: SRC-bizcard }（07 §3）');
      }
    }
    // 购买判断（障碍、购买准备度）的强度只由行为证据决定：校历再强也不能证明购买行为，管理判断也不能把它往上提（02 §2.3）。
    if (['barrier', 'readiness'].includes(c.claimType) && !['unknown', 'not_applicable'].includes(c.status)) {
      const behavior = (c.evidenceRefs || []).filter(isBehavioral).reduce((m, id) => Math.max(m, RANK[cap(id)]), 0);
      if (!behavior) {
        if (c.claimType === 'barrier' && ['BR-M2', 'BR-M5'].includes(c.barrierCode)) err(at, `${c.barrierCode} 没有用户决策行为证据时须为 unknown（02 §2.3）`);
        else if (!(c.status === 'inferred' && c.evidenceStrength === 'weak')) err(at, `没有用户决策行为证据（事实记录、业务观察、Voice）时，${c.claimType === 'barrier' ? '障碍' : '购买准备度'}最高 inferred + weak；校历和管理判断都不算（02 §2.3）`);
      } else if (c.status === 'known' && behavior < 3) err(at, '购买判断 known 须有 strong 的行为证据（事实记录）；业务观察最高 inferred + partial');
      else if (c.evidenceStrength === 'partial' && behavior < 2) err(at, '购买判断 partial 须有业务观察以上的行为证据');
    }
    if (c.claimType === 'barrier') {
      if (!ALL_BARRIERS.includes(c.barrierCode)) err(at, `barrierCode ${c.barrierCode} 不在障碍体系 v2 内`);
      else if ((c.targetRelation === '新签' && ONLY_RENEW.includes(c.barrierCode)) || (c.targetRelation === '续费' && ONLY_NEW.includes(c.barrierCode))) err(at, `${c.barrierCode} 不适用于${c.targetRelation}（I-11）`);
      else if (c.targetRelation === '通用' && [...ONLY_NEW, ...ONLY_RENEW].includes(c.barrierCode)) err(at, `${c.barrierCode} 只适用于一类人群，不能用于通用（I-11）`);
      if (!['primary', 'secondary'].includes(c.barrierRole)) err(at, 'barrierRole 须为 primary / secondary');
      // 只有弱证据或未知的主障碍只是暂定研究重点（02 §2.1），rule 里写明，免得后续当成确定的主导原因。
      if (c.barrierRole === 'primary' && (c.status === 'unknown' || c.evidenceStrength === 'weak') && !String(c.rule || '').includes('暂定研究重点')) err(at, '主障碍只有弱证据或未知时，rule 须写明「暂定研究重点」');
      const k = `${c.scenario} · ${c.targetRelation}`;
      primaries.set(k, (primaries.get(k) || 0) + (c.barrierRole === 'primary' ? 1 : 0));
    }
  }
  for (const [k, n] of primaries) if (n !== 1) err(k, `同一情境、同一人群下主障碍须恰好一个，现在 ${n} 个（I-11）`);
  // 最低完整性（SKILL.md 第 3、4 步）：每个情境四类需求 Claim 齐全；按目标人群，新签、续费各有一条购买准备度（可以是 unknown）。
  for (const s of scenarios) {
    const mine = claims.filter(c => c.scenario === s.id);
    for (const t of ['task', 'academic_need', 'pain', 'need_strength']) if (!mine.some(c => c.claimType === t)) err(s.id, `缺少 ${t} Claim（每个情境四类需求都要写）`);
    for (const rel of s.targetRelation === '通用' ? ['新签', '续费'] : [s.targetRelation])
      if (!mine.some(c => c.claimType === 'readiness' && c.targetRelation === rel)) err(s.id, `缺少${rel}的 readiness Claim（判断不了就写 unknown）`);
  }

  // 08 §3 自检记录：八项逐条写结论；待确认 / 失败的写位置、问题类别、修复动作。批 1 没有 review 接口，转成文字存进 research.notes。
  const selfCheck = draft.research?.selfCheck || [];
  for (const item of SELF_CHECK) {
    const r = selfCheck.find(x => x.item === item);
    if (!r) err('research.selfCheck', `缺少自检项「${item}」`);
    else if (!['通过', '待确认', '失败', '不适用（批 2 起）'].includes(r.result)) err('research.selfCheck', `「${item}」的结果须为 通过 / 待确认 / 失败${item.includes('批 2') ? ' / 不适用（批 2 起）' : ''}`);
    else if (['待确认', '失败'].includes(r.result) && !(r.at && r.category && r.fix)) err('research.selfCheck', `「${item}」判为${r.result}，须写 at（对象 ID）、category、fix`);
    else if (r.result === '失败') err('research.selfCheck', `「${item}」失败：按 08 §3 须返修后再提交`);
  }
  const selfCheckNotes = selfCheck.map(r => `自检｜${r.item}｜${r.result}${r.at ? `｜位置 ${r.at}` : ''}${r.category ? `｜${r.category}` : ''}${r.fix ? `｜处理：${r.fix}` : ''}${r.review ? `｜复审：${r.review}` : ''}`);
  const document = {
    schemaVersion: facts.schemaVersion || '2.1',
    month,
    window: { from: `${month}-01`, to: lastDay(month), preheatTo: `${nextMonth(month)}-14` },
    inputs: { timelineSnapshot: null, evidenceVersions: Object.fromEntries([...new Set(claims.flatMap(c => c.evidenceRefs || []).concat(scenarios.flatMap(s => s.evidenceRefs || [])))].filter(id => ev.has(id)).map(id => [id, ev.get(id).evidenceVersion])),
      bizcard: null, rules: facts.rules?.versions ?? {} },
    producedBy: { declared: { executor: draft.declared?.executor ?? 'unknown', model: draft.declared?.model ?? 'unknown', skillVersion: version } },
    brief: { judgement: draft.judgement, common: brief.common || [], diff: brief.diff || [], external: brief.external || [] },
    regions, scenarios, claims, opportunities: [], strategies: [],
    research: { rejected: draft.research?.rejected || [], assumptions: draft.research?.assumptions || [], notes: [...(draft.research?.notes || []), ...selfCheckNotes] },
  };
  const hash = createHash('sha256').update(JSON.stringify(document)).digest('hex').slice(0, 12);
  const idempotencyKey = `mus-${month}-${facts.inputFingerprint}-${hash}`;
  const submitArgs = { month, document, idempotencyKey, inputFingerprint: facts.inputFingerprint, baseRevision: facts.baseRevision ?? null, declared: document.producedBy.declared };
  return { document, submitArgs, errors, warnings };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  const take = name => { const i = args.indexOf(name); return i >= 0 ? args.splice(i, 2)[1] : null; };
  const dir = take('--out-dir'), prev = take('--prev-facts');
  if (args.length < 2 || !dir) { console.error('用法：node assemble.mjs <facts.json> <draft.json> --out-dir <目录> [--prev-facts <研判时用的旧底稿>]'); process.exit(1); }
  const [facts, draft] = args.map(f => JSON.parse(readFileSync(f, 'utf8')));
  const { document, submitArgs, errors, warnings } = assemble(facts, draft, { prevFacts: prev ? JSON.parse(readFileSync(prev, 'utf8')) : null });
  mkdirSync(dir, { recursive: true });
  for (const f of ['document.json', 'submit-args.json', 'assemble-errors.txt']) rmSync(join(dir, f), { force: true });
  for (const w of warnings) console.log(`提示 ${w}`);
  if (errors.length) {
    for (const e of errors) console.log(`拦截 ${e}`);
    writeFileSync(join(dir, 'assemble-errors.txt'), `${[...errors.map(e => `拦截 ${e}`), ...warnings.map(w => `提示 ${w}`)].join('\n')}\n`);
    console.log(`\n预检未通过：拦截 ${errors.length} 条、提示 ${warnings.length} 条。改研判稿后重跑；没有写 document.json 和 submit-args.json（旧的已删除）。`);
    process.exit(2);
  }
  writeFileSync(join(dir, 'document.json'), `${JSON.stringify(document, null, 2)}\n`);
  writeFileSync(join(dir, 'submit-args.json'), `${JSON.stringify(submitArgs, null, 2)}\n`);
  console.log(`预检通过（提示 ${warnings.length} 条）。情境 ${document.scenarios.length}、Claim ${document.claims.length}。\nidempotencyKey：${submitArgs.idempotencyKey}\n已写 ${join(dir, 'document.json')}、${join(dir, 'submit-args.json')}`);
}
