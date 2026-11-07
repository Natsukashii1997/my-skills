#!/usr/bin/env node
// 截图自检：给单文件 HTML 包一层 doctype，用无头 Chrome 按指定宽度截整页长图，并报告横向溢出。
// 用法：node shot.mjs <页面.html> [输出目录] [--widths 1440,400] [--hash ch] [--motion]
//   --hash   截图前把地址的 #后缀 设成这个值（页面靠 #ch 之类切换时用）
//   --motion 不模拟「减少动态效果」；默认模拟，演示和进场动画直接显示最终态，截图稳定
// 输出：<输出目录>/<文件名>[-<hash>]-<宽度>.png（高于 8000px 的页面分段：-p1、-p2…）；每个宽度打印一行 JSON：宽度、页面高度、scrollWidth、是否横向溢出、控制台报错数。
// 有横向溢出或页面报错时退出码为 1。只写输出目录和系统临时目录；网络只连本机的 Chrome 调试端口（页面自己会加载 Google Fonts）。
import { spawn } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, join, resolve } from 'node:path';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const args = process.argv.slice(2);
const opt = (name, dflt) => { const i = args.indexOf(name); if (i < 0) return dflt; const v = args[i + 1]; args.splice(i, 2); return v; };
const flag = (name) => { const i = args.indexOf(name); if (i < 0) return false; args.splice(i, 1); return true; };
const widths = opt('--widths', '1440,400').split(',').map(Number);
const hash = opt('--hash', '');
const motion = flag('--motion');
const [input, outDir = '.'] = args;
if (!input) { console.error('用法：node shot.mjs <页面.html> [输出目录] [--widths 1440,400] [--hash ch] [--motion]'); process.exit(2); }

const work = mkdtempSync(join(tmpdir(), 'shot-'));
const src = readFileSync(input, 'utf8');
const page = /^\s*<!doctype/i.test(src) ? src
  : '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">' + src + '</body></html>';
const preview = join(work, 'preview.html');
writeFileSync(preview, page);
mkdirSync(outDir, { recursive: true });

// 端口交给 Chrome 自己挑（=0），再从配置目录的 DevToolsActivePort 读出来：几个截图同时跑也不会撞端口
const profile = join(work, 'profile');
const chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
  `--user-data-dir=${profile}`, '--remote-debugging-port=0', 'about:blank'], { stdio: 'ignore' });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const killTimer = setTimeout(() => { console.error('超时：120 秒内没截完'); chrome.kill('SIGKILL'); process.exit(3); }, 120000);

let wsUrl;
for (let i = 0; i < 150 && !wsUrl; i++) { // 最多等 30 秒：机器忙时 Chrome 起得慢
  await sleep(200);
  try {
    const port = readFileSync(join(profile, 'DevToolsActivePort'), 'utf8').split('\n')[0].trim();
    wsUrl = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === 'page')?.webSocketDebuggerUrl;
  } catch {}
}
if (!wsUrl) { console.error('连不上无头 Chrome（等了 30 秒）'); chrome.kill(); process.exit(3); }

const ws = new WebSocket(wsUrl);
await new Promise((r) => ws.addEventListener('open', r, { once: true }));
let seq = 0; const pending = new Map(); let errors = 0;
ws.addEventListener('message', (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  if (m.method === 'Runtime.exceptionThrown') errors++;
  if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') errors++;
});
const send = (method, params = {}) => new Promise((r, j) => { const id = ++seq; pending.set(id, (m) => (m.error ? j(new Error(m.error.message)) : r(m.result))); ws.send(JSON.stringify({ id, method, params })); });
const evaluate = async (expr) => (await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })).result.value;

await send('Page.enable'); await send('Runtime.enable');
if (!motion) await send('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
const url = 'file://' + resolve(preview) + (hash ? '#' + hash : '');
const name = basename(input).replace(/\.html?$/i, '') + (hash ? '-' + hash : '');
let bad = false;
for (const w of widths) {
  errors = 0;
  await send('Emulation.setDeviceMetricsOverride', { width: w, height: 900, deviceScaleFactor: 1, mobile: w < 768 });
  await send('Page.navigate', { url });
  await sleep(800);
  // 等字体加载完、页面画完再量（G-11）
  await evaluate('document.fonts.ready.then(() => new Promise((r) => setTimeout(r, 1500)))');
  const m = await evaluate('({h: document.documentElement.scrollHeight, sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth})');
  // 一张图超过约 16000px 时 Chrome 会卡住，所以按 TILE 高度分段截：<名>-<宽>.png，长页依次是 -p1、-p2…
  const TILE = 8000, parts = Math.ceil(m.h / TILE), files = [];
  for (let i = 0; i < parts; i++) {
    const y = i * TILE, h = Math.min(TILE, m.h - y);
    const png = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip: { x: 0, y, width: w, height: h, scale: 1 } });
    const file = join(outDir, parts === 1 ? `${name}-${w}.png` : `${name}-${w}-p${i + 1}.png`);
    writeFileSync(file, Buffer.from(png.data, 'base64'));
    files.push(file);
  }
  const overflow = m.sw > m.cw;
  if (overflow || errors) bad = true;
  console.log(JSON.stringify({ width: w, height: m.h, scrollWidth: m.sw, overflow, consoleErrors: errors, files }));
}
clearTimeout(killTimer);
ws.close(); chrome.kill();
// 预览副本和临时 Chrome 配置留在系统临时目录（work），由系统清理；脚本不删任何文件。
process.exit(bad ? 1 : 0);
