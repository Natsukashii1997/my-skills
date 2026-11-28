#!/usr/bin/env node
// 样式比对：列出三版实际显示的字号、字重、颜色、渐变、阴影、边框、圆角、SVG 填色和描边里（含 ::before / ::after），原页面没有的值。\n// 只是一张有限的清单：宽高、间距，同一个值挪到别的元素上，脚本都不比，SKILL 第 5 步要人工补查。
// 人自己列「新出现的值」会漏（1.1.0 盲测里漏过颜色、漏过字号），交给脚本取差集，回复照着列。
// 用法：node style-diff.mjs <三版页面.html> --out <证据目录> [--original <原页面.html 或网址>]
//   页面按 Artifact 的写法从 <title> 写起时，先照 check.mjs 包一层 doctype 和 head 再打开（存成证据目录里的 wrapped/<原文件名>）。
//   没给 --original（新页面）时只列每版用到的值，不比。
//   Playwright 的借法和 check.mjs 一样（UI_PREFLIGHT_PLAYWRIGHT，或 ~/Documents/ChatGPT/个人/work/*/ 里第一个装了的项目）。
// 结果写进 <证据目录>/style-diff.md；退出码：0 跑完（有没有新值都是 0，新值要在回复里交代）；2 用法或环境错误。
import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

export const KINDS = ['字号', '字重', '文字颜色', '底色', '渐变底', '阴影', '边框色', '边框粗细', '圆角', 'SVG 填色', 'SVG 描边'];
// 不比的（SKILL 第 5 步要求人工补查）：元素宽高和间距；同一个值从一个元素挪到另一个元素（比的是整页的值集合，不是逐个元素）；图片和 canvas 里画的东西。

// 在页面里跑：收集 scope 下所有看得见的元素（含 ::before / ::after）实际显示的值。返回 { 种类: { 值: { n, sample } } }
export function collect(scope) {
  const root = scope ? document.querySelector(scope) : document.body;
  const out = {};
  if (!root) return out;
  const add = (kind, value, el, where = '') => {
    const bucket = (out[kind] ??= {});
    const hit = (bucket[value] ??= { n: 0, sample: '' });
    hit.n += 1;
    if (!hit.sample) {
      const text = (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 14);
      hit.sample = (text || el.tagName.toLowerCase() + (el.classList[0] ? '.' + el.classList[0] : '')) + where;
    }
  };
  const clear = (c) => !c || c === 'transparent' || /^rgba\(\d+, \d+, \d+, 0\)$/.test(c);
  // 祖先透明、隐藏的也算看不见：checkVisibility 会往上查
  const visible = (el) => (el.checkVisibility ? el.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })
    : getComputedStyle(el).display !== 'none');
  const box = (cs, el, where, text) => {
    if (text) {
      add('字号', cs.fontSize, el, where);
      add('字重', cs.fontWeight, el, where);
      add('文字颜色', cs.color, el, where);
    }
    if (!clear(cs.backgroundColor)) add('底色', cs.backgroundColor, el, where);
    if (cs.backgroundImage && cs.backgroundImage.includes('gradient')) add('渐变底', cs.backgroundImage, el, where);
    if (cs.boxShadow && cs.boxShadow !== 'none') add('阴影', cs.boxShadow, el, where);
    for (const side of ['Top', 'Right', 'Bottom', 'Left']) {
      if (cs[`border${side}Style`] === 'none' || parseFloat(cs[`border${side}Width`]) === 0) continue;
      if (!clear(cs[`border${side}Color`])) add('边框色', cs[`border${side}Color`], el, where);
      add('边框粗细', cs[`border${side}Width`], el, where);
    }
    for (const corner of ['TopLeft', 'TopRight', 'BottomRight', 'BottomLeft']) {
      const v = cs[`border${corner}Radius`];
      if (v && v !== '0px') add('圆角', v, el, where);
    }
  };
  for (const el of [root, ...root.querySelectorAll('*')]) {
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    const cs = getComputedStyle(el);
    if (el instanceof SVGElement) {
      if (el.tagName.toLowerCase() === 'svg' || el.tagName.toLowerCase() === 'g') continue;
      if (cs.fill && cs.fill !== 'none' && !clear(cs.fill)) add('SVG 填色', cs.fill, el);
      if (cs.stroke && cs.stroke !== 'none' && !clear(cs.stroke)) add('SVG 描边', cs.stroke, el);
      continue;
    }
    box(cs, el, '', [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim()));
    for (const p of ['::before', '::after']) {
      const ps = getComputedStyle(el, p);
      if (!ps.content || ps.content === 'none' || ps.content === 'normal' || ps.display === 'none') continue;
      box(ps, el, ` 的 ${p}`, ps.content !== '""' && ps.content !== "''");
    }
  }
  return out;
}

// 纯函数：方案里有、原页面没有的值，按种类列出
export function newValues(original, version) {
  const res = {};
  for (const kind of KINDS) {
    const have = new Set(Object.keys(original[kind] ?? {}));
    const extra = Object.entries(version[kind] ?? {}).filter(([v]) => !have.has(v));
    if (extra.length) res[kind] = extra.map(([value, { n, sample }]) => ({ value, n, sample }));
  }
  return res;
}

export function render({ page, original, versions }) {
  const lines = ['# 样式比对', '', `三版页面：${page}`, `原页面：${original ? original.src : '没有（新页面，只列用到的值）'}`, `时间：${new Date().toISOString()}`, ''];
  if (original) {
    lines.push('## 原页面用到的值', '');
    for (const kind of KINDS) lines.push(`- ${kind}：${Object.keys(original.values[kind] ?? {}).join('、') || '无'}`);
    lines.push('');
  }
  for (const [name, values] of Object.entries(versions)) {
    if (!original) {
      lines.push(`## 方案 ${name} 用到的值`, '');
      for (const kind of KINDS) lines.push(`- ${kind}：${Object.keys(values[kind] ?? {}).join('、') || '无'}`);
      lines.push('');
      continue;
    }
    const extra = newValues(original.values, values);
    const kinds = Object.keys(extra);
    lines.push(`## 方案 ${name}：原页面没有的值（${kinds.length ? kinds.reduce((s, k) => s + extra[k].length, 0) + ' 个' : '没有'}）`, '');
    for (const kind of kinds) for (const e of extra[kind]) lines.push(`- ${kind} ${e.value}：${e.n} 处，如「${e.sample}」`);
    lines.push('');
  }
  if (original) lines.push('回复里逐个交代上面每个新值：是这一版有意加的（为什么），还是要改回原页面的值。', '', '这张清单不全：元素宽高和间距、同一个值挪到了别的元素上、图片和 canvas 里画的东西，脚本都不比，照 SKILL 第 5 步人工补查。');
  return lines.join('\n') + '\n';
}

function findPlaywright() {
  if (process.env.UI_PREFLIGHT_PLAYWRIGHT) return process.env.UI_PREFLIGHT_PLAYWRIGHT.replace(/^~(?=\/)/, os.homedir());
  const work = path.join(os.homedir(), 'Documents', 'ChatGPT', '个人', 'work');
  for (const d of fs.existsSync(work) ? fs.readdirSync(work) : []) {
    if (fs.existsSync(path.join(work, d, 'node_modules', '@playwright', 'test'))) return path.join(work, d);
  }
  return null;
}

async function loadChromium(from) {
  const req = createRequire(path.join(from, 'package.json'));
  for (const id of ['@playwright/test', 'playwright']) {
    let file;
    try { file = req.resolve(id); } catch { continue; }
    const mod = await import(pathToFileURL(file).href);
    const chromium = mod.chromium ?? mod.default?.chromium;
    if (chromium) return chromium;
  }
  return null;
}

// Artifact 发布时会给页面包上 doctype 和 head；和 check.mjs 同一个写法
export function wrap(html) {
  return /^\s*<!doctype/i.test(html) ? html
    : '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
      + '<style>:root{color-scheme:light;padding-top:env(safe-area-inset-top);padding-bottom:env(safe-area-inset-bottom)}body{margin:0;font:14px system-ui,sans-serif}img{max-width:100%}[hidden]{display:none!important}</style>'
      + '</head><body>' + html + '</body></html>';
}

// 两个脚本共用的参数解析：<页面> --out <目录> [--original <原页面>]，顺序随意。
// 写了选项却没给值（后面没东西，或紧跟着另一个 --选项）时返回 error，不当成没写，免得样式比对被悄悄跳过。
export function parseArgs(argv) {
  const res = { page: null, out: null, original: null, error: null };
  const taken = new Set();
  for (const [flag, key] of [['--out', 'out'], ['--original', 'original']]) {
    const i = argv.indexOf(flag);
    if (i < 0) continue;
    const v = argv[i + 1];
    if (v === undefined || v.startsWith('--')) { res.error ??= `${flag} 后面要跟一个值`; continue; }
    res[key] = v;
    taken.add(i + 1);
  }
  res.page = argv.find((a, i) => !a.startsWith('--') && !taken.has(i)) ?? null;
  return res;
}

export async function main(argv) {
  const die = (msg) => { console.error(msg); return 2; };
  const { page, out, original: orig, error } = parseArgs(argv);
  if (error) return die(error);
  if (!page || !out) return die('用法：node style-diff.mjs <三版页面.html> --out <证据目录> [--original <原页面.html 或网址>]');
  const file = path.resolve(page);
  const outDir = path.resolve(out.replace(/^~(?=\/)/, os.homedir()));
  if (!fs.existsSync(file)) return die(`找不到页面：${file}`);
  if (/^\/(private\/)?tmp\//.test(outDir)) return die('证据目录不能在 /tmp（G-01），换成项目约定的持久目录');
  const origUrl = !orig ? null : /^https?:|^file:/.test(orig) ? orig : fs.existsSync(path.resolve(orig)) ? pathToFileURL(path.resolve(orig)).href : null;
  if (orig && !origUrl) return die(`找不到原页面：${orig}`);
  const pw = findPlaywright();
  const chromium = pw && await loadChromium(pw);
  if (!chromium) return die('找不到 Playwright：设 UI_PREFLIGHT_PLAYWRIGHT=<装了 @playwright/test 的项目目录>');

  fs.mkdirSync(path.join(outDir, 'wrapped'), { recursive: true });
  const wrapped = path.join(outDir, 'wrapped', path.basename(file));
  fs.writeFileSync(wrapped, wrap(fs.readFileSync(file, 'utf8')));
  const url = pathToFileURL(wrapped).href;

  const browser = await chromium.launch();
  try {
    const tab = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    const read = async (target, scope) => {
      await tab.goto(target, { waitUntil: 'load' });
      await tab.evaluate(() => document.fonts?.ready);
      return tab.evaluate(collect, scope);
    };
    const original = origUrl ? { src: orig, values: await read(origUrl, null) } : null;
    const versions = {};
    for (const v of ['a', 'b', 'c']) versions[v.toUpperCase()] = await read(`${url}#bare-${v}`, `#v${v}`);
    const md = render({ page: file, original, versions });
    fs.writeFileSync(path.join(outDir, 'style-diff.md'), md);
    console.log(md);
    return 0;
  } finally {
    await browser.close();
  }
}

if (process.argv[1] && fs.realpathSync(process.argv[1]) === fs.realpathSync(fileURLToPath(import.meta.url))) {
  process.exit(await main(process.argv.slice(2)));
}
