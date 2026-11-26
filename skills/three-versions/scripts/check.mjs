#!/usr/bin/env node
// 三版预览页的交付前自查：一次跑完，不靠记得。
//   1. 页面结构：三块画板（#va #vb #vc）都有内容，模板里的 {{占位}} 都换掉了；
//   2. 每版产品界面：借 ui-preflight 的脚本，按 #bare-a / #bare-b / #bare-c 单独打开画板，在 1280、1440 查八项；
//   3. 外壳：借 ui-styles 的 shot.mjs，每版在 1440 和 390 宽各截一张整页图，查横向溢出和页面报错。
// 用法：node check.mjs <三版页面.html> --out <证据目录>
//   Playwright 从 UI_PREFLIGHT_PLAYWRIGHT 指的目录解析；没设就在 ~/Documents/ChatGPT/个人/work/*/ 里找第一个装了 @playwright/test 的项目借用。
// 退出码：0 全部通过；1 有不通过；2 用法或环境错误。证据目录不能在 /tmp（全局坑 G-01）。
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const here = path.dirname(fs.realpathSync(fileURLToPath(import.meta.url)));
const skills = path.resolve(here, '..', '..');
const PREFLIGHT = path.join(skills, 'ui-preflight', 'scripts', 'ui-preflight.mjs');
const SHOT = path.join(skills, 'ui-styles', 'scripts', 'shot.mjs');

const args = process.argv.slice(2);
const oi = args.indexOf('--out');
const out = oi >= 0 ? args[oi + 1] : null;
const page = args.find((a, i) => !a.startsWith('--') && i !== oi + 1);
const die = (msg) => { console.error(msg); process.exit(2); };
if (!page || !out) die('用法：node check.mjs <三版页面.html> --out <证据目录>');
const file = path.resolve(page);
const outDir = path.resolve(out.replace(/^~(?=\/)/, os.homedir()));
if (!fs.existsSync(file)) die(`找不到页面：${file}`);
if (/^\/(private\/)?tmp\//.test(outDir)) die('证据目录不能在 /tmp（G-01），换成项目约定的持久目录');
for (const f of [PREFLIGHT, SHOT]) if (!fs.existsSync(f)) die(`找不到依赖脚本：${f}（three-versions 要和 ui-preflight、ui-styles 放在同一个 skills 目录下）`);

function findPlaywright() {
  if (process.env.UI_PREFLIGHT_PLAYWRIGHT) return process.env.UI_PREFLIGHT_PLAYWRIGHT;
  const work = path.join(os.homedir(), 'Documents', 'ChatGPT', '个人', 'work');
  for (const d of fs.existsSync(work) ? fs.readdirSync(work) : []) {
    if (fs.existsSync(path.join(work, d, 'node_modules', '@playwright', 'test'))) return path.join(work, d);
  }
  return null;
}

const rows = [];
const add = (item, pass, note) => rows.push({ item, pass, note });

// 1. 结构
const html = fs.readFileSync(file, 'utf8');
const holes = [...new Set(html.match(/\{\{[^}]{1,40}\}\}/g) ?? [])];
add('模板占位都换掉了', holes.length === 0, holes.length ? `还有：${holes.slice(0, 5).join('、')}` : '');
for (const v of ['a', 'b', 'c']) {
  const m = html.match(new RegExp(`<div class="board"[^>]*id="v${v}"[^>]*>([\\s\\S]*?)<\\/div>\\s*(?=<div class="board"|<\\/div>\\s*<\\/div>)`));
  const body = m ? m[1].replace(/<!--[\s\S]*?-->/g, '').trim() : '';
  add(`方案 ${v.toUpperCase()} 画板有内容`, body.length > 200, m ? `${body.length} 字符` : '没找到 #v' + v);
}

fs.mkdirSync(outDir, { recursive: true });

// 2. 每版产品界面：ui-preflight（1280、1440）
const pw = findPlaywright();
if (!pw) die('找不到 Playwright：设 UI_PREFLIGHT_PLAYWRIGHT=<装了 @playwright/test 的项目目录>');
const url = pathToFileURL(file).href;
const pre = spawnSync(process.execPath, [PREFLIGHT,
  '--url', `${url}#bare-a`, '--name', 'A', '--url', `${url}#bare-b`, '--name', 'B', '--url', `${url}#bare-c`, '--name', 'C',
  '--out', outDir, '--no-baseline'], { encoding: 'utf8', env: { ...process.env, UI_PREFLIGHT_PLAYWRIGHT: pw }, cwd: path.dirname(file) });
const preOut = (pre.stdout || '') + (pre.stderr || '');
const reportDir = fs.readdirSync(outDir).filter((d) => d.startsWith('ui-preflight-')).sort().pop();
const report = reportDir ? path.join(outDir, reportDir, 'report.md') : '';
add('三版产品界面 ui-preflight（1280、1440）', pre.status === 0, pre.status === 2 ? `环境错误：${preOut.trim().split('\n').slice(-3).join(' ')}` : (report || preOut.trim().split('\n').slice(-2).join(' ')));

// 3. 外壳：shot.mjs（1440、390），每版各截一次
const shotDir = path.join(outDir, 'shell');
for (const v of ['a', 'b', 'c']) {
  const r = spawnSync(process.execPath, [SHOT, file, shotDir, '--widths', '1440,390', '--hash', v], { encoding: 'utf8' });
  const lines = (r.stdout || '').trim().split('\n').filter((l) => l.startsWith('{'));
  const bad = lines.map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter((j) => j && (j.overflow || j.errors));
  add(`外壳 · 方案 ${v.toUpperCase()}（1440、390）`, r.status === 0, r.status === 0 ? '无横向溢出、无报错' : (bad.map((j) => JSON.stringify(j)).join('；') || (r.stderr || '').trim().split('\n').pop()));
}

const md = ['# 三版预览自查', '', `页面：${file}`, `时间：${new Date().toISOString()}`, '', '| 检查 | 结果 | 说明 |', '|---|---|---|',
  ...rows.map((r) => `| ${r.item} | ${r.pass ? '通过' : '**不通过**'} | ${r.note || ''} |`), '',
  `截图：${shotDir}（外壳）；ui-preflight 的整页和标注截图在它自己的报告目录里。截图要自己打开看，脚本过了不等于好看。`].join('\n');
fs.writeFileSync(path.join(outDir, 'three-versions-check.md'), md + '\n');
console.log(md);
process.exit(rows.every((r) => r.pass) ? 0 : 1);
