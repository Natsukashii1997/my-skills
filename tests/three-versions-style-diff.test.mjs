// three-versions 的样式比对：纯函数在任何环境都跑；真浏览器那组要 Playwright，
// 本机用 UI_PREFLIGHT_PLAYWRIGHT=<装了 @playwright/test 的项目目录> 指过去，或在 ~/Documents/ChatGPT/个人/work/*/ 找到一份；没有就跳过（CI 上没装）。
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { main, newValues, parseArgs, render, wrap } from '../skills/three-versions/scripts/style-diff.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const vals = (o) => Object.fromEntries(Object.entries(o).map(([k, vs]) => [k, Object.fromEntries(vs.map((v) => [v, { n: 1, sample: 'x' }]))]));

test('原页面没有的值才算新值：16px 原有、15px 新出现', () => {
  const res = newValues(vals({ 字号: ['16px', '12px'] }), vals({ 字号: ['16px', '15px'], 文字颜色: ['rgb(1, 2, 3)'] }));
  assert.deepEqual(res.字号.map((e) => e.value), ['15px']);
  assert.deepEqual(res.文字颜色.map((e) => e.value), ['rgb(1, 2, 3)']);
});

test('三版和原页面用的值一样：没有新值', () => {
  const same = vals({ 字号: ['16px'], 圆角: ['4px'] });
  assert.deepEqual(newValues(same, same), {});
});

test('没给原页面（新页面）：只列用到的值，不说「原页面没有」', () => {
  const md = render({ page: 'p.html', original: null, versions: { A: vals({ 字号: ['14px'] }) } });
  assert.match(md, /方案 A 用到的值/);
  assert.match(md, /字号：14px/);
  assert.doesNotMatch(md, /原页面没有的值/);
});

test('从 <title> 写起的页面包上 doctype；已有 doctype 的不动', () => {
  assert.match(wrap('<title>x</title><p>y</p>'), /^<!doctype html>.*<body><title>x<\/title>/s);
  assert.equal(wrap('<!doctype html><p>y</p>'), '<!doctype html><p>y</p>');
});

test('参数解析：不写 --original 时页面路径照样认出来（第五轮盲测 E2 撞上的错），顺序随意', () => {
  assert.deepEqual(parseArgs(['p.html', '--out', 'o']), { page: 'p.html', out: 'o', original: null, error: null });
  assert.deepEqual(parseArgs(['--out', 'o', 'p.html']), { page: 'p.html', out: 'o', original: null, error: null });
  assert.deepEqual(parseArgs(['p.html', '--original', 'old.html', '--out', 'o']), { page: 'p.html', out: 'o', original: 'old.html', error: null });
  assert.equal(parseArgs(['--out', 'o']).page, null);
});

test('参数解析：写了 --original 或 --out 却没给值，报错，不当成没写（审查 TV151-P1-03）', () => {
  assert.match(parseArgs(['p.html', '--out', 'o', '--original']).error, /--original 后面要跟一个值/);
  assert.match(parseArgs(['p.html', '--original', '--out', 'o']).error, /--original 后面要跟一个值/);
  assert.match(parseArgs(['p.html', '--out']).error, /--out 后面要跟一个值/);
});

test('check.mjs 写了 --original 却没给值：退出码 2，不悄悄跳过样式比对', () => {
  const page = path.join(os.homedir(), '.cache', 'tv-page.html');
  fs.mkdirSync(path.dirname(page), { recursive: true });
  fs.writeFileSync(page, '<title>x</title>');
  const r = spawnSync(process.execPath, [path.join(here, '..', 'skills', 'three-versions', 'scripts', 'check.mjs'), page, '--out', path.join(os.homedir(), '.cache', 'tv-none'), '--original'], { encoding: 'utf8' });
  assert.equal(r.status, 2);
  assert.match(r.stderr, /--original 后面要跟一个值/);
});

test('check.mjs 不写 --original 时不报用法错误', () => {
  const r = spawnSync(process.execPath, [path.join(here, '..', 'skills', 'three-versions', 'scripts', 'check.mjs'), path.join(here, 'no-such.html'), '--out', path.join(os.homedir(), '.cache', 'tv-none')], { encoding: 'utf8' });
  assert.equal(r.status, 2);
  assert.match(r.stderr, /找不到页面/);
  assert.doesNotMatch(r.stderr, /用法/);
});

function hasPlaywright() {
  if (process.env.UI_PREFLIGHT_PLAYWRIGHT) return true;
  const work = path.join(os.homedir(), 'Documents', 'ChatGPT', '个人', 'work');
  return fs.existsSync(work) && fs.readdirSync(work).some((d) => fs.existsSync(path.join(work, d, 'node_modules', '@playwright', 'test')));
}

test('真浏览器：类名重名把字号从 16 改成 15，脚本列出 15px', { skip: !hasPlaywright() && '本机没有 Playwright' }, async () => {
  const base = /^\/(private\/)?tmp(\/|$)/.test(os.tmpdir()) ? path.join(os.homedir(), '.cache') : os.tmpdir();
  fs.mkdirSync(base, { recursive: true });
  const dir = fs.mkdtempSync(path.join(base, 'tv-diff-test-'));
  try {
    fs.writeFileSync(path.join(dir, 'orig.html'), '<!doctype html><style>body{font:16px sans-serif;color:#222}</style><p>张小雨</p><p style="font-size:12px">咨询</p>');
    const board = (id, css) => `<div class="board" id="${id}"><style>#${id} .name{${css}}</style><p class="name">张小雨</p><p style="font-size:12px">咨询</p></div>`;
    fs.writeFileSync(path.join(dir, 'three.html'), '<title>三版</title><style>body{font:16px sans-serif;color:#222}</style>'
      + board('va', 'font-size:16px') + board('vb', 'font-size:15px') + board('vc', 'font-size:16px;color:#c00'));
    const out = path.join(dir, 'out');
    const code = await main([path.join(dir, 'three.html'), '--out', out, '--original', path.join(dir, 'orig.html')]);
    assert.equal(code, 0);
    const md = fs.readFileSync(path.join(out, 'style-diff.md'), 'utf8');
    assert.match(md, /## 方案 A：原页面没有的值（没有）/);
    assert.match(md, /## 方案 B：原页面没有的值（1 个）\n\n- 字号 15px：1 处，如「张小雨」/);
    assert.match(md, /## 方案 C：原页面没有的值（1 个）\n\n- 文字颜色 rgb\(204, 0, 0\)/);
    assert.match(md, /这张清单不全/);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test('真浏览器：渐变、阴影、四个角的圆角、伪元素、SVG 填色都列出；祖先透明的不收', { skip: !hasPlaywright() && '本机没有 Playwright' }, async () => {
  const base = /^\/(private\/)?tmp(\/|$)/.test(os.tmpdir()) ? path.join(os.homedir(), '.cache') : os.tmpdir();
  fs.mkdirSync(base, { recursive: true });
  const dir = fs.mkdtempSync(path.join(base, 'tv-diff-test-'));
  try {
    fs.writeFileSync(path.join(dir, 'orig.html'), '<!doctype html><style>body{font:16px sans-serif;color:#222}</style><p>原页面</p>');
    const vd = '<p style="background:linear-gradient(#ff0,#fff)">渐变</p><p style="box-shadow:0 1px 2px #000">阴影</p>'
      + '<p style="border-radius:0 6px 0 0">右上角</p><p class="tip">伪元素</p><style>.tip::after{content:"!";color:#0a0}</style>'
      + '<svg width="10" height="10"><path d="M0 0h10v10z" fill="#00f"/></svg><div style="opacity:0"><p style="color:#f0f">藏起来</p></div>';
    const board = (id, inner) => `<div class="board" id="${id}">${inner}</div>`;
    fs.writeFileSync(path.join(dir, 'three.html'), '<title>三版</title><style>body{font:16px sans-serif;color:#222}</style>'
      + board('va', vd) + board('vb', '<p>原页面</p>') + board('vc', '<p>原页面</p>'));
    const out = path.join(dir, 'out');
    assert.equal(await main([path.join(dir, 'three.html'), '--out', out, '--original', path.join(dir, 'orig.html')]), 0);
    const a = fs.readFileSync(path.join(out, 'style-diff.md'), 'utf8').split('## 方案 B')[0];
    assert.match(a, /渐变底 linear-gradient/);
    assert.match(a, /阴影 rgb\(0, 0, 0\) 0px 1px 2px/);
    assert.match(a, /圆角 6px/);
    assert.match(a, /文字颜色 rgb\(0, 170, 0\).*::after/);
    assert.match(a, /SVG 填色 rgb\(0, 0, 255\)/);
    assert.doesNotMatch(a, /rgb\(255, 0, 255\)/);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
