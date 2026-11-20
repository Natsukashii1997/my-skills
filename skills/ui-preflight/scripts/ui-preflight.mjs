// 界面交付前自查：用项目自己装的 Playwright（Chromium）在 1280、1440 两个桌面宽度打开每个页面，
// 查横向溢出、同列对齐、文字截断与折行、0 高容器、正文挤成窄栏、默认字体漏出、字符当图标、文字对比度八项，
// 出一张表（report.md / report.json）、一张只供参考的样式清单和整页截图、标注截图。报告头部写明这次排除了哪些元素。
// 项目有 scripts/ui-baseline.mjs（起步骨架的基线截图）时，自查完直接调它的 compare，结果并进同一张表。
//
// 用法（在项目根目录跑，或用 --root 指过去）：
//   node <skill>/scripts/ui-preflight.mjs                       读 docs/design/pages.json（和基线截图共用一份页面清单）
//   node <skill>/scripts/ui-preflight.mjs --url http://127.0.0.1:5173/#/home --name home --out "~/Library/Application Support/<项目>/evidence"
// 选项：
//   --root <目录>     项目根目录，默认当前目录；Playwright 从这里解析（npm i -D @playwright/test && npx playwright install chromium）
//   --url <地址>      要查的页面，可写多次；写了就不读 pages.json 的页面
//   --name <名字>     和 --url 按顺序配对，当截图文件名；不写就是 page-1、page-2
//   --page <名字>     只查 pages.json 里这几页，可写多次
//   --out <目录>      证据目录（不能在 /tmp）；不写就用 pages.json 的 evidence
//   --ready <选择器>  等它出现再查（单页应用异步读数据时用）；不写就用 pages.json 的 ready
//   --clock <时间>    浏览器里的固定时间（ISO）；不写就用 pages.json 的 clock
//   --ignore <选择器> 不查这些元素和它们里面的内容，可写多次（有意的横向滚动区、故意截断的地方）
//   --no-details      不展开 <details>（默认全部展开再查，折叠里的表格、列表最容易漏看）
//   --no-baseline     不调基线对比
// pages.json 里可加 "preflight": { "ignore": [...], "openDetails": false }，写在顶层对所有页生效，写在某页里只管那页。
// 退出码：0 全部通过；1 有不通过（含基线不一致、页面打不开）；2 用法或环境错误。
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { buildPageScript } from './checks.mjs';

export const WIDTHS = [1280, 1440];
export const HEIGHT = 900;
export const CHECKS = [
  ['overflow', '横向溢出'],
  ['align', '同列对齐'],
  ['clip', '截断与折行'],
  ['zero', '0 高容器'],
  ['squeeze', '正文挤成窄栏'],
  ['font', '默认字体漏出'],
  ['glyph', '字符当图标'],
  ['contrast', '文字对比度'],
];
// 样式清单的五行：只列出来给人看，不计入通过 / 不通过
export const STYLE_ROWS = [
  ['fontSizes', '字号', '字符'],
  ['fontWeights', '字重', '字符'],
  ['fontFamilies', '字体族', '字符'],
  ['spacings', '间距', '处'],
  ['radii', '圆角', '处'],
];
const STYLE_SHOW = 12;
const SELF = fileURLToPath(import.meta.url);
const home = p => p.replace(/^~(?=\/|$)/, os.homedir());

export function parseArgs(argv) {
  const o = { urls: [], names: [], pages: [], ignore: [], details: true, baseline: true };
  const multi = { '--url': 'urls', '--name': 'names', '--page': 'pages', '--ignore': 'ignore' };
  const single = { '--root': 'root', '--out': 'out', '--ready': 'ready', '--clock': 'clock' };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--no-details') o.details = false;
    else if (a === '--no-baseline') o.baseline = false;
    else if (a in multi || a in single) {
      const v = argv[++i];
      if (v === undefined || v.startsWith('--')) throw new Error(`${a} 后面要跟一个值`);
      if (a in multi) o[multi[a]].push(v); else o[single[a]] = v;
    } else if (a === '--width' || a === '--widths') throw new Error('宽度固定查 1280 和 1440（产品界面只做电脑版），不接受别的宽度');
    else throw new Error(`不认识的参数：${a}`);
  }
  return o;
}

export function assertEvidenceDir(dir) {
  if (/^\/(private\/)?tmp(\/|$)/.test(dir)) throw new Error(`证据目录不能放 /tmp，会被系统清理（全局坑 G-01）：${dir}`);
  return dir;
}

// 把命令行参数和 pages.json 合成一份执行计划：查哪些页、证据放哪、要不要起隔离服务、要不要调基线对比
export function resolvePlan(opts, cwd = process.cwd()) {
  const root = path.resolve(cwd, home(opts.root ?? '.'));
  const file = path.join(root, 'docs', 'design', 'pages.json');
  const cfg = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) : null;
  const base = { ignore: [], openDetails: true, ...(cfg?.preflight ?? {}) };
  let pages;
  if (opts.urls.length) {
    if (opts.names.length && opts.names.length !== opts.urls.length) throw new Error('--name 要和 --url 一样多（按顺序配对）');
    pages = opts.urls.map((url, i) => ({ name: opts.names[i] ?? `page-${i + 1}`, url, ready: opts.ready, pre: base }));
  } else {
    if (!cfg) throw new Error(`没有 --url，也没有 ${path.relative(root, file) || file}：二选一`);
    if (!Array.isArray(cfg.pages) || !cfg.pages.length) throw new Error('pages.json 的 pages 是空的');
    pages = cfg.pages.map(p => ({ name: p.name, url: p.url, ready: opts.ready ?? p.ready ?? cfg.ready, pre: { ...base, ...(p.preflight ?? {}) } }));
    if (opts.pages.length) {
      const miss = opts.pages.filter(n => !pages.some(p => p.name === n));
      if (miss.length) throw new Error(`pages.json 里没有这几页：${miss.join('、')}`);
      pages = pages.filter(p => opts.pages.includes(p.name));
    }
  }
  const names = new Set();
  for (const p of pages) {
    if (!p.name || !p.url) throw new Error(`每页都要有 name 和 url：${JSON.stringify(p)}`);
    if (names.has(p.name)) throw new Error(`name 重复：${p.name}`);
    names.add(p.name);
    p.ignore = [...(p.pre.ignore ?? []), ...opts.ignore];
    p.openDetails = opts.details && p.pre.openDetails !== false;
    delete p.pre;
  }
  const evidence = opts.out ?? cfg?.evidence;
  if (!evidence) throw new Error('不知道证据放哪：加 --out，或在 pages.json 写 evidence');
  const clock = opts.clock ?? cfg?.clock;
  if (clock !== undefined && Number.isNaN(Date.parse(clock))) throw new Error(`clock 不是合法时间：${clock}`);
  // 起隔离服务只在用 pages.json 的页面时做：--url 指的是已经跑着的地址
  const setup = !opts.urls.length && cfg?.setup ? path.resolve(root, cfg.setup) : null;
  const baselineScript = path.join(root, 'scripts', 'ui-baseline.mjs');
  const baseline = opts.baseline && cfg && fs.existsSync(baselineScript) ? baselineScript : null;
  return { root, pages, evidence: assertEvidenceDir(path.resolve(root, home(evidence))), clock, setup, baseline };
}

async function loadChromium(root) {
  const from = process.env.UI_PREFLIGHT_PLAYWRIGHT ? path.resolve(home(process.env.UI_PREFLIGHT_PLAYWRIGHT)) : root;
  const req = createRequire(path.join(from, 'package.json'));
  for (const id of ['@playwright/test', 'playwright']) {
    let file;
    try { file = req.resolve(id); } catch { continue; }
    const mod = await import(pathToFileURL(file).href);
    const chromium = mod.chromium ?? mod.default?.chromium;
    if (chromium) return chromium;
  }
  throw new Error(`在 ${from} 找不到 Playwright：npm i -D @playwright/test && npx playwright install chromium`);
}

// 等页面画完：加载完、ready 出现、字体加载完、网络静下来，再连续两次量到的版面一样（全局坑 G-11）
async function settle(page, ready) {
  if (ready) await page.waitForSelector(ready, { state: 'visible', timeout: 20000 });
  await page.waitForLoadState('networkidle', { timeout: 8000 }).catch(() => {});
  await page.evaluate(() => document.fonts.ready.then(() => document.fonts.status));
  const sig = () => page.evaluate(() => [document.documentElement.scrollWidth, document.documentElement.scrollHeight, document.querySelectorAll('*').length, (document.body.innerText || '').length].join(','));
  let last = await sig(), same = 0;
  for (let i = 0; i < 40 && same < 2; i++) {
    await page.waitForTimeout(250);
    const now = await sig();
    same = now === last ? same + 1 : 0;
    last = now;
  }
  // 有限次的动画直接跳到终态；无限循环的 finish 会抛错，留着不管
  await page.evaluate(() => { for (const a of document.getAnimations()) { try { a.finish(); } catch {} } });
}

async function annotate(page, ids) {
  await page.evaluate(list => {
    for (const [n, id] of list) {
      const el = window.__uipEls[id];
      if (!el) continue;
      const r = el.getBoundingClientRect();
      const box = document.createElement('div');
      box.setAttribute('data-uip-overlay', '');
      box.style.cssText = `position:absolute;left:${r.left + scrollX}px;top:${r.top + scrollY}px;width:${Math.max(r.width, 4)}px;height:${Math.max(r.height, 4)}px;outline:2px solid #e5484d;background:rgba(229,72,77,.08);z-index:2147483647;pointer-events:none;`;
      const tag = document.createElement('span');
      tag.textContent = n;
      tag.style.cssText = 'position:absolute;left:-2px;top:-18px;background:#e5484d;color:#fff;font:600 11px/16px system-ui;padding:0 4px;border-radius:2px;';
      box.appendChild(tag);
      document.body.appendChild(box);
    }
  }, ids);
}

async function checkPage(browser, page0, width, run, plan) {
  const ctx = await browser.newContext({ viewport: { width, height: HEIGHT }, deviceScaleFactor: 1, reducedMotion: 'reduce', ...(plan.state ? { storageState: plan.state } : {}) });
  const page = await ctx.newPage();
  // ignore：这次排除了哪些选择器、各匹配到几个元素，写进报告好核对；页面没查完时数不出来，matched 留 null
  const row = { page: page0.name, url: page0.url, width, error: null, ignore: page0.ignore.map(selector => ({ selector, matched: null })), checks: {}, screenshot: null, annotated: null };
  try {
    if (plan.clock) await page.clock.setFixedTime(new Date(plan.clock));
    await page.goto(page0.url, { waitUntil: 'load', timeout: 30000 });
    await settle(page, page0.ready);
    if (page0.openDetails) {
      const opened = await page.evaluate(() => { const ds = [...document.querySelectorAll('details:not([open])')]; ds.forEach(d => { d.open = true; }); return ds.length; });
      if (opened) await settle(page, null);
      row.openedDetails = opened;
    }
    row.ignore = await page.evaluate(sels => sels.map(selector => { try { return { selector, matched: document.querySelectorAll(selector).length }; } catch { return { selector, matched: null }; } }), page0.ignore);
    const res = await page.evaluate(buildPageScript({ ignore: page0.ignore }));
    row.pageOverflow = res.pageOverflow;
    row.styles = res.styles;
    let n = 0;
    const numbered = [];
    for (const [key] of CHECKS) {
      const hits = res.hits[key].map(h => ({ ...h, n: ++n }));
      hits.forEach(h => numbered.push([h.n, h.id]));
      const pass = !hits.some(h => h.level === 'fail') && !(key === 'overflow' && res.pageOverflow > 0);
      row.checks[key] = { pass, hits };
    }
    if (res.pageOverflow > 0) row.checks.overflow.note = `整页横向可滚动 ${res.pageOverflow}px`;
    const base = `${page0.name}-${width}`;
    row.screenshot = path.join(run, `${base}.png`);
    await page.screenshot({ path: row.screenshot, fullPage: true });
    if (numbered.length) {
      await annotate(page, numbered);
      row.annotated = path.join(run, `${base}-标注.png`);
      await page.screenshot({ path: row.annotated, fullPage: true });
    }
  } catch (e) {
    row.error = e.message.split('\n')[0];
  } finally {
    await ctx.close();
  }
  return row;
}

export function runBaseline(script, root) {
  const r = spawnSync(process.execPath, [script, 'compare'], { cwd: root, encoding: 'utf8' });
  const output = `${r.stdout ?? ''}${r.stderr ?? ''}`;
  const dir = output.match(/差异图在 (.+)$/m)?.[1]?.trim() ?? null;
  return { pass: r.status === 0, status: r.status, dir, tail: output.trim().split('\n').slice(-6).join('\n') };
}

const nums = hs => hs.map(h => `#${h.n}`).join(' ');
export function mark(c) {
  const fail = c.hits.filter(h => h.level === 'fail'), warn = c.hits.filter(h => h.level === 'warn');
  const parts = [];
  if (c.pass) parts.push('✅ 通过');
  else parts.push(`❌ 不通过（${[c.note, fail.length ? `${fail.length} 处 ${nums(fail)}` : ''].filter(Boolean).join('；')}）`);
  if (warn.length) parts.push(`⚠️ 提示 ${warn.length} 处 ${nums(warn)}`);
  return parts.join(' ');
}
const cell = s => String(s ?? '').replace(/\|/g, '\\|').replace(/\n/g, ' ');

// 报告头部的「排除项」一行：每页取查完的那一行；各页一样就只写一遍，不一样分页列
function ignoreLine(rows) {
  const count = i => (i.matched == null ? '页面没查完，没数' : i.matched === 0 ? '没匹配到元素，检查选择器' : `${i.matched} 个元素`);
  const fmt = list => (list?.length ? list.map(i => `\`${cell(i.selector)}\`（${count(i)}）`).join('、') : '无');
  const byPage = new Map();
  for (const r of rows) if (!byPage.has(r.page) || (byPage.get(r.page).error && !r.error)) byPage.set(r.page, r);
  const parts = [...byPage].map(([page, r]) => [page, fmt(r.ignore)]);
  if (parts.every(([, t]) => t === '无')) return '- 排除项：无';
  const same = parts.every(([, t]) => t === parts[0][1]);
  return `- 排除项（这些元素和它们里面的内容没有查）：${same ? parts[0][1] : parts.map(([page, t]) => `${cell(page)}：${t}`).join('；')}`;
}

export function renderReport(report) {
  const rel = p => (p ? `[${path.basename(p)}](${encodeURI(path.relative(report.run, p))})` : '—');
  const L = [];
  L.push('# 界面交付前自查（ui-preflight）', '');
  L.push(`- 项目：\`${report.root}\``);
  L.push(`- 时间：${report.time}；宽度：${WIDTHS.join('、')}（高 ${HEIGHT}，只查电脑版）；引擎：Playwright Chromium（无头），截图只作自查参考，不单独当验收（G-11）`);
  L.push(`- 页面来源：${report.source}；证据目录：\`${report.run}\``);
  L.push(ignoreLine(report.rows));
  const warns = report.rows.reduce((n, r) => n + (r.error ? 0 : CHECKS.reduce((m, [k]) => m + r.checks[k].hits.filter(h => h.level === 'warn').length, 0)), 0);
  L.push(`- 结论：**${report.pass ? '全部通过' : '有不通过'}**${warns ? `；另有 ${warns} 条 ⚠️ 提示，逐条处理：有意的设计确认后可写进 ignore；对比度不够的该改就改，这一项先只提示、不拦` : ''}`, '');
  L.push(`| 页面 | 宽度 | ${CHECKS.map(c => c[1]).join(' | ')} | 截图 |`);
  L.push(`|---|---|${CHECKS.map(() => '---').join('|')}|---|`);
  for (const r of report.rows) {
    if (r.error) { L.push(`| ${cell(r.page)} | ${r.width} | ❌ 页面没能查完：${cell(r.error)} |${CHECKS.slice(1).map(() => ' — |').join('')} — |`); continue; }
    L.push(`| ${cell(r.page)} | ${r.width} | ${CHECKS.map(([k]) => mark(r.checks[k])).join(' | ')} | ${rel(r.screenshot)}${r.annotated ? ' · ' + rel(r.annotated) : ''} |`);
  }
  L.push('');
  if (report.baseline) {
    const b = report.baseline;
    L.push('## 基线对比（项目的 scripts/ui-baseline.mjs compare）', '');
    L.push(`- 结果：${b.pass ? '✅ 和基线一致' : `❌ 和基线不一致或缺基线（退出码 ${b.status}）`}${b.dir ? `；差异图在 \`${b.dir}\`` : ''}`);
    L.push('', '```', b.tail, '```', '');
  } else {
    L.push('## 基线对比', '', `- 没跑：${report.baselineSkipped}`, '');
  }
  const failed = report.rows.filter(r => !r.error && CHECKS.some(([k]) => r.checks[k].hits.length));
  if (failed.length) {
    L.push('## 命中明细', '');
    for (const r of failed) {
      L.push(`### ${r.page} · ${r.width}`, '');
      L.push('| # | 检查项 | 级别 | 元素 | 文字 | 位置（x,y 宽×高） | 说明 |', '|---|---|---|---|---|---|---|');
      for (const [k, label] of CHECKS) for (const h of r.checks[k].hits) {
        L.push(`| ${h.n} | ${label} | ${h.level === 'warn' ? '⚠️ 提示' : '❌ 不通过'} | \`${cell(h.selector)}\` | ${cell(h.text)} | ${h.rect.x},${h.rect.y} ${h.rect.w}×${h.rect.h} | ${cell(h.detail)} |`);
      }
      L.push('');
    }
  }
  const listed = report.rows.filter(r => !r.error && r.styles);
  if (listed.length) {
    L.push('## 样式清单（只供参考，不计入通过 / 不通过）', '');
    L.push('本页实际用到的值，按用量从多到少排。种类多不等于有问题；用来看有没有相近的值（12px 和 12.5px）、有没有不在这次设计层级表和刻度里的值。', '');
    for (const r of listed) {
      L.push(`### ${r.page} · ${r.width}`, '');
      L.push('| 项目 | 种类 | 取值（括号里是用量） |', '|---|---|---|');
      for (const [k, label, unit] of STYLE_ROWS) {
        const vals = r.styles[k] ?? [];
        const shown = vals.slice(0, STYLE_SHOW).map(([v, n]) => `${cell(v)}（${n} ${unit}）`).join('、');
        L.push(`| ${label} | ${vals.length} | ${shown || '—'}${vals.length > STYLE_SHOW ? `，另有 ${vals.length - STYLE_SHOW} 种` : ''} |`);
      }
      L.push('');
    }
  }
  return L.join('\n');
}

export async function main(argv) {
  const plan = resolvePlan(parseArgs(argv));
  const chromium = await loadChromium(plan.root);
  fs.mkdirSync(plan.evidence, { recursive: true });
  const stamp = new Date().toLocaleString('sv-SE', { timeZone: 'Asia/Shanghai' }).replace(/[-:]/g, '').replace(' ', '-');
  const run = fs.mkdtempSync(path.join(plan.evidence, `ui-preflight-${stamp}-`));
  // 要登录的项目：setup 按骨架约定把登录状态写到 UI_BASELINE_STATE 指的文件。这个文件由调用的人在命令前指定、跑完自己删，
  // 本脚本只读它，不建也不删（脚本不做任何删除）
  const state = process.env.UI_BASELINE_STATE;
  let teardown = null;
  const rows = [];
  try {
    if (plan.setup) teardown = await (await import(pathToFileURL(plan.setup).href)).default();
    if (state && fs.existsSync(state) && fs.statSync(state).size > 0) plan.state = state;
    const browser = await chromium.launch();
    try {
      for (const p of plan.pages) for (const w of WIDTHS) rows.push(await checkPage(browser, p, w, run, plan));
    } finally { await browser.close(); }
  } finally {
    if (typeof teardown === 'function') await teardown();
  }
  // 基线对比自己会起隔离服务，所以放在上面的服务收掉之后
  const baseline = plan.baseline ? runBaseline(plan.baseline, plan.root) : null;
  const pass = rows.every(r => !r.error && CHECKS.every(([k]) => r.checks[k].pass)) && (!baseline || baseline.pass);
  const report = {
    root: plan.root, run, time: new Date().toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }),
    source: argv.includes('--url') ? '命令行 --url' : 'docs/design/pages.json', pass, rows, baseline,
    baselineSkipped: plan.baseline ? null : (argv.includes('--no-baseline') ? '加了 --no-baseline' : '项目没有 scripts/ui-baseline.mjs 或 docs/design/pages.json'),
  };
  fs.writeFileSync(path.join(run, 'report.json'), JSON.stringify(report, null, 2));
  const md = renderReport(report);
  fs.writeFileSync(path.join(run, 'report.md'), md);
  return { pass, run, md };
}

// 经 ~/.claude/skills 的符号链接调用时，argv[1] 是链接路径、SELF 是真实路径：两边都解析成真实路径再比（G-38）
const isMain = () => { try { return !!process.argv[1] && fs.realpathSync(process.argv[1]) === fs.realpathSync(SELF); } catch { return false; } };
if (isMain()) {
  main(process.argv.slice(2)).then(({ pass, run, md }) => {
    console.log(md);
    console.log(`\n报告：${path.join(run, 'report.md')}`);
    process.exitCode = pass ? 0 : 1;
  }, e => { console.error(e.message); process.exitCode = 2; });
}
