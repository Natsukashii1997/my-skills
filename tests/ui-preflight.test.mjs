// ui-preflight：纯函数和参数解析在任何环境都跑；真浏览器那组要 Playwright，
// 本机用 UI_PREFLIGHT_PLAYWRIGHT=<装了 @playwright/test 的项目目录> 指过去，没有就跳过（CI 上没装）。
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { alignModes, blend, buildPageScript, contrastRatio, countLines, fontLeak, headerAlignment, isGlyphIcon, isLargeText, isSqueezed, nearMisses, parseColor, primaryFamily } from '../skills/ui-preflight/scripts/checks.mjs';
import { assertEvidenceDir, CHECKS, main, mark, parseArgs, renderReport, resolvePlan } from '../skills/ui-preflight/scripts/ui-preflight.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const fixtures = path.join(here, 'fixtures', 'ui-preflight');
const box = (left, right, top = 0, bottom = 20) => ({ left, right, top, bottom, width: right - left, height: bottom - top });
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'uip-test-'));
// 证据目录不许在 /tmp（脚本按 G-01 拒绝），Linux 上 os.tmpdir() 就是 /tmp：要当证据目录用的临时目录放到家目录的缓存里
const outTmp = () => {
  const base = /^\/(private\/)?tmp(\/|$)/.test(os.tmpdir()) ? path.join(os.homedir(), '.cache') : os.tmpdir();
  fs.mkdirSync(base, { recursive: true });
  return fs.mkdtempSync(path.join(base, 'uip-test-'));
};

test('数值右对齐、表头左对齐：判为没对齐，按数据实际的右对齐报差值', () => {
  const body = [box(200, 340), box(250, 340)];
  assert.deepEqual(alignModes(body), ['right']);
  const res = headerAlignment(body, box(108, 140), 2, 'right');
  assert.equal(res.ok, false);
  assert.equal(res.mode, 'right');
  assert.equal(res.diff, 200);
  assert.equal(headerAlignment(body, box(300, 340)).ok, true);
});

test('数据宽度都一样时三种对齐都算齐：表头落在任一条边上就算对齐，不齐时按 prefer 报', () => {
  const body = [box(200, 340), box(200, 340)];
  assert.deepEqual(alignModes(body), ['left', 'right', 'center']);
  assert.equal(headerAlignment(body, box(200, 230)).ok, true);
  const res = headerAlignment(body, box(110, 140), 2, 'right');
  assert.deepEqual([res.ok, res.mode, res.diff], [false, 'right', 200]);
});

test('本列数据自己就不齐时不判表头', () => {
  assert.equal(headerAlignment([box(0, 50), box(30, 100)], box(500, 520)).ok, true);
});

test('countLines：垂直居中、高矮不同的框算一行，掉到下面的才算新一行', () => {
  assert.equal(countLines([box(0, 50, 0, 24), box(60, 90, 4, 20)]), 1);
  assert.equal(countLines([box(0, 50, 0, 24), box(0, 90, 28, 46)]), 2);
  assert.equal(countLines([box(0, 0, 0, 0)]), 0);
});

test('nearMisses：差 0.5～4px 才报，有意缩进和完全对齐都不报', () => {
  assert.deepEqual(nearMisses([16, 18, 16]), [{ i: 1, diff: 2 }]);
  assert.deepEqual(nearMisses([16, 32, 16]), []);
  assert.deepEqual(nearMisses([16, 16.3, 16]), []);
  assert.deepEqual(nearMisses([16]), []);
});

test('isSqueezed：8 个字以上、折 3 行以上、每行不到 4 个字宽才算挤成窄栏', () => {
  assert.equal(isSqueezed({ chars: 18, lines: 6, width: 42, fontSize: 14 }), true);
  assert.equal(isSqueezed({ chars: 18, lines: 2, width: 42, fontSize: 14 }), false, '只折两行不算');
  assert.equal(isSqueezed({ chars: 6, lines: 3, width: 28, fontSize: 14 }), false, '字太少不算');
  assert.equal(isSqueezed({ chars: 40, lines: 4, width: 200, fontSize: 14 }), false, '栏够宽，正常折行不算');
  assert.equal(isSqueezed({ chars: 18, lines: 3, width: 56, fontSize: 14 }), false, '正好 4 个字宽不算');
});

test('fontLeak：字体族或字号还是浏览器默认值、又和容器不一样判不通过；自己另定了字体族判提示', () => {
  const body = { family: '"Noto Sans SC", system-ui, sans-serif', size: 14 };
  const ua = { family: 'Arial', size: 13.3333 };
  assert.equal(fontLeak({ family: 'Arial', size: 13.3333 }, body, ua), 'fail');
  assert.equal(fontLeak({ family: 'Arial', size: 12 }, body, ua), 'fail', '字号写了、字体族还是浏览器默认的');
  assert.equal(fontLeak({ family: 'system-ui', size: 13.3333 }, { family: 'system-ui', size: 14 }, { family: 'system-ui', size: 13.3333 }), 'fail', '字体族碰巧和页面一样，字号仍是默认值');
  assert.equal(fontLeak({ family: 'Georgia', size: 14 }, body, ua), 'warn');
  assert.equal(fontLeak({ family: "'Noto Sans SC', x", size: 12 }, body, ua), null, '继承了字体族、字号是自己定的');
  assert.equal(fontLeak({ family: 'Arial', size: 13.3333 }, { family: 'Arial', size: 13.3333 }, ua), null, '整页就是浏览器默认字体');
  assert.equal(fontLeak({ family: 'Arial', size: 13.3333 }, body), 'fail', '量不到默认字体时按 13.33px 判');
  assert.equal(primaryFamily('"Barlow Condensed", sans-serif'), 'barlow condensed');
});

test('isGlyphIcon：整个元素只有箭头、符号、emoji 才算，字里夹一个箭头不算', () => {
  for (const t of ['✎', '▶', '↻', '✕', '↗', '→', '🚀', ' ✓ ', '⚠️']) assert.equal(isGlyphIcon(t), true, t);
  for (const t of ['→ Codex', '下一步 →', 'A', '3', '·', '×', '审', '']) assert.equal(isGlyphIcon(t), false, t);
});

test('对比度：认 rgb / rgba / color(srgb)，半透明先叠到底色上；大字只要求 3', () => {
  const white = { r: 255, g: 255, b: 255, a: 1 };
  assert.deepEqual(parseColor('rgb(153, 153, 153)'), { r: 153, g: 153, b: 153, a: 1 });
  assert.deepEqual(parseColor('rgba(236, 231, 220, 0.5)'), { r: 236, g: 231, b: 220, a: 0.5 });
  assert.deepEqual(parseColor('color(srgb 1 0 0 / 0.5)'), { r: 255, g: 0, b: 0, a: 0.5 });
  assert.equal(parseColor('oklch(0.6 0.1 20)'), null, '认不出的写法不猜');
  assert.equal(contrastRatio({ r: 0, g: 0, b: 0 }, white), 21);
  assert.equal(Math.floor(contrastRatio(parseColor('rgb(153, 153, 153)'), white) * 100) / 100, 2.84);
  // 半透明的黑字叠在白底上是灰：对比度跟着降
  const half = blend({ r: 0, g: 0, b: 0, a: 0.5 }, white);
  assert.deepEqual(half, { r: 127.5, g: 127.5, b: 127.5, a: 1 });
  assert.ok(contrastRatio(half, white) < 4.5);
  assert.equal(isLargeText(24, 400), true);
  assert.equal(isLargeText(19, 700), true);
  assert.equal(isLargeText(19, 400), false);
  assert.equal(isLargeText(14, 700), false);
});

test('buildPageScript：拼出来的页面脚本语法正确，新加的函数和常量都带上了', () => {
  const src = buildPageScript({ ignore: ['#x'] });
  assert.doesNotThrow(() => new Function(`return ${src.replace('return domChecks(', 'return 0 && domChecks(')}`));
  for (const name of ['isSqueezed', 'fontLeak', 'isGlyphIcon', 'contrastRatio', 'SQUEEZE_EMS', 'UA_CONTROL_SIZE', 'GLYPH', 'CONTRAST_MIN_LARGE']) assert.ok(src.includes(name), name);
});

test('parseArgs：不接受别的宽度，--url 和 --name 可写多次', () => {
  assert.throws(() => parseArgs(['--width', '375']), /1280 和 1440/);
  assert.throws(() => parseArgs(['--url']), /要跟一个值/);
  assert.throws(() => parseArgs(['--foo']), /不认识/);
  const o = parseArgs(['--url', 'a', '--url', 'b', '--name', 'x', '--name', 'y', '--no-details', '--no-baseline']);
  assert.deepEqual([o.urls, o.names, o.details, o.baseline], [['a', 'b'], ['x', 'y'], false, false]);
});

test('证据目录不能在 /tmp', () => {
  assert.throws(() => assertEvidenceDir('/tmp/x'), /G-01/);
  assert.throws(() => assertEvidenceDir('/private/tmp/x'), /G-01/);
  assert.equal(assertEvidenceDir('/Users/a/Library/Application Support/p/evidence'), '/Users/a/Library/Application Support/p/evidence');
});

test('resolvePlan：读 pages.json 的页面、ready、ignore、setup；--page 过滤；缺证据目录报错', () => {
  const root = tmp();
  fs.mkdirSync(path.join(root, 'docs', 'design'), { recursive: true });
  fs.mkdirSync(path.join(root, 'scripts'));
  fs.writeFileSync(path.join(root, 'scripts', 'ui-baseline.mjs'), '');
  fs.writeFileSync(path.join(root, 'docs', 'design', 'pages.json'), JSON.stringify({
    evidence: '/srv/uip-evidence', setup: 'scripts/setup.mjs', ready: 'main', preflight: { ignore: ['.wall'] },
    pages: [{ name: 'a', url: 'http://x/a' }, { name: 'b', url: 'http://x/b', ready: '#b', preflight: { openDetails: false, ignore: ['.c'] } }],
  }));
  const plan = resolvePlan(parseArgs(['--root', root, '--ignore', '.z']));
  assert.equal(plan.evidence, '/srv/uip-evidence');
  assert.equal(plan.setup, path.join(root, 'scripts', 'setup.mjs'));
  assert.equal(plan.baseline, path.join(root, 'scripts', 'ui-baseline.mjs'));
  assert.deepEqual(plan.pages.map(p => [p.name, p.ready, p.ignore, p.openDetails]), [['a', 'main', ['.wall', '.z'], true], ['b', '#b', ['.c', '.z'], false]]);
  assert.deepEqual(resolvePlan(parseArgs(['--root', root, '--page', 'b'])).pages.map(p => p.name), ['b']);
  assert.throws(() => resolvePlan(parseArgs(['--root', root, '--page', 'nope'])), /没有这几页/);
  assert.equal(resolvePlan(parseArgs(['--root', root, '--no-baseline'])).baseline, null);
  // --url 指的是已经在跑的地址：不起 setup
  const byUrl = resolvePlan(parseArgs(['--root', root, '--url', 'http://y/', '--out', '/srv/o']));
  assert.equal(byUrl.evidence, '/srv/o');
  assert.equal(byUrl.setup, null);
  assert.deepEqual(byUrl.pages.map(p => p.name), ['page-1']);
  assert.throws(() => resolvePlan(parseArgs(['--root', tmp(), '--url', 'http://y/'])), /证据放哪/);
  assert.throws(() => resolvePlan(parseArgs(['--root', tmp()])), /二选一/);
  assert.throws(() => resolvePlan(parseArgs(['--root', root, '--url', 'a', '--url', 'b', '--name', 'x'])), /一样多/);
});

test('mark / renderReport：不通过、提示分开写，提示不影响通过', () => {
  const hit = (n, level) => ({ n, level, selector: 'th', text: '实收金额', rect: { x: 1, y: 2, w: 3, h: 4 }, detail: 'd|x' });
  assert.equal(mark({ pass: true, hits: [] }), '✅ 通过');
  assert.equal(mark({ pass: true, hits: [hit(1, 'warn')] }), '✅ 通过 ⚠️ 提示 1 处 #1');
  assert.equal(mark({ pass: false, hits: [hit(1, 'fail'), hit(2, 'warn')] }), '❌ 不通过（1 处 #1） ⚠️ 提示 1 处 #2');
  assert.equal(mark({ pass: false, note: '整页横向可滚动 8px', hits: [] }), '❌ 不通过（整页横向可滚动 8px）');
  const ok = { pass: true, hits: [] };
  const md = renderReport({
    root: '/p', run: '/e/run', time: 't', source: 's', pass: false, baseline: null, baselineSkipped: '没有',
    rows: [{ page: 'biz', width: 1280, screenshot: '/e/run/biz-1280.png', annotated: '/e/run/biz-1280-标注.png',
      checks: { overflow: ok, align: { pass: false, hits: [hit(1, 'fail')] }, clip: { pass: true, hits: [hit(2, 'warn')] }, zero: ok, squeeze: ok, font: ok, glyph: ok, contrast: { pass: true, hits: [hit(3, 'warn')] } },
      styles: { fontSizes: [['14px', 120], ['12px', 30]], fontWeights: [['400', 150]], fontFamilies: [['system-ui', 150]], spacings: Array.from({ length: 14 }, (_, i) => [`${i + 1}px`, 14 - i]), radii: [] } },
    { page: 'x', width: 1440, error: '打不开' }],
  });
  assert.deepEqual(CHECKS.map(c => c[0]), ['overflow', 'align', 'clip', 'zero', 'squeeze', 'font', 'glyph', 'contrast']);
  assert.match(md, /\| biz \| 1280 \| ✅ 通过 \| ❌ 不通过（1 处 #1） \| ✅ 通过 ⚠️ 提示 1 处 #2 \| ✅ 通过 \| ✅ 通过 \| ✅ 通过 \| ✅ 通过 \| ✅ 通过 ⚠️ 提示 1 处 #3 \| \[biz-1280\.png\]\(biz-1280\.png\) · \[biz-1280-标注\.png\]/);
  assert.match(md, /## 样式清单（只供参考，不计入通过 \/ 不通过）/);
  assert.match(md, /\| 字号 \| 2 \| 14px（120 字符）、12px（30 字符） \|/);
  assert.match(md, /\| 间距 \| 14 \| 1px（14 处）.*12px（3 处），另有 2 种 \|/);
  assert.match(md, /\| 圆角 \| 0 \| — \|/);
  assert.match(md, /页面没能查完：打不开/);
  assert.match(md, /另有 2 条 ⚠️ 提示/);
  assert.match(md, /d\\\|x/);
  assert.match(md, /^- 排除项：无$/m, '行里没有 ignore 字段（旧报告）也按没有排除写');
});

test('renderReport：排除项写进报告头部，带匹配到的元素数；没匹配到的标出来；各页不一样时分页列', () => {
  const ok = { pass: true, hits: [] };
  const checks = Object.fromEntries(CHECKS.map(([k]) => [k, ok]));
  const row = (page, width, ignore, extra = {}) => ({ page, width, checks, ignore, ...extra });
  const render = rows => renderReport({ root: '/p', run: '/e/run', time: 't', source: 's', pass: true, baseline: null, baselineSkipped: '没有', rows });
  const line = md => md.split('\n').find(l => l.startsWith('- 排除项'));
  assert.equal(line(render([row('a', 1280, []), row('a', 1440, [])])), '- 排除项：无');
  assert.equal(line(render([row('a', 1280, [{ selector: '#scroll', matched: 1 }, { selector: '.wall', matched: 3 }]), row('a', 1440, [{ selector: '#scroll', matched: 1 }, { selector: '.wall', matched: 3 }])])),
    '- 排除项（这些元素和它们里面的内容没有查）：`#scroll`（1 个元素）、`.wall`（3 个元素）');
  assert.equal(line(render([row('a', 1280, [{ selector: '.nope', matched: 0 }])])),
    '- 排除项（这些元素和它们里面的内容没有查）：`.nope`（没匹配到元素，检查选择器）');
  assert.equal(line(render([row('a', 1280, [{ selector: '.wall', matched: 2 }]), row('b', 1280, [])])),
    '- 排除项（这些元素和它们里面的内容没有查）：a：`.wall`（2 个元素）；b：无');
  // 页面没能查完时数不出元素，只列选择器
  assert.equal(line(render([row('a', 1280, [{ selector: '.wall', matched: null }], { error: '打不开' })])),
    '- 排除项（这些元素和它们里面的内容没有查）：`.wall`（页面没查完，没数）');
});

test('经符号链接调用（~/.claude/skills 里就是链接）也会执行：--width 375 报错退出 2', () => {
  const dir = tmp();
  const link = path.join(dir, 'skill');
  fs.symlinkSync(path.join(here, '..', 'skills', 'ui-preflight'), link);
  const r = spawnSync(process.execPath, [path.join(link, 'scripts', 'ui-preflight.mjs'), '--width', '375'], { encoding: 'utf8' });
  assert.equal(r.status, 2, `stdout=${r.stdout} stderr=${r.stderr}`);
  assert.match(r.stderr, /1280 和 1440/);
});

// —— 真浏览器 ——
const pwRoot = process.env.UI_PREFLIGHT_PLAYWRIGHT;
let hasPw = false;
if (pwRoot) { try { createRequire(path.join(pwRoot, 'package.json')).resolve('@playwright/test'); hasPw = true; } catch {} }
const skip = hasPw ? false : '没设 UI_PREFLIGHT_PLAYWRIGHT（装了 @playwright/test 的目录），跳过真浏览器测试';
const url = f => pathToFileURL(path.join(fixtures, f)).href;
const hitsOf = (row, k) => row.checks[k].hits;

test('反例页：八项都查得出，省略号、对比度、字符图标只算提示；收起的 <details> 默认展开再查', { skip }, async () => {
  const out = outTmp();
  const { pass, run } = await main(['--url', url('bad.html'), '--name', 'bad', '--out', out, '--no-baseline']);
  assert.equal(pass, false);
  const rep = JSON.parse(fs.readFileSync(path.join(run, 'report.json'), 'utf8'));
  for (const width of [1280, 1440]) {
    const row = rep.rows.find(r => r.width === width);
    assert.equal(row.error, null);
    assert.ok(row.pageOverflow > 0, '整页横向溢出');
    assert.ok(hitsOf(row, 'overflow').some(h => h.selector.includes('#wide')));
    const align = hitsOf(row, 'align');
    assert.equal(align.filter(h => /表头「实收金额」.*右对齐/.test(h.detail)).length, 1);
    assert.equal(align.filter(h => /表头「占比」/.test(h.detail)).length, 1, '<details> 里的表也查到了');
    assert.ok(align.some(h => h.selector.includes('#off') && /差 2px/.test(h.detail)));
    const clip = hitsOf(row, 'clip');
    assert.ok(clip.some(h => h.selector.includes('#head') && /折成了 2 行/.test(h.detail)), '卡头折行');
    assert.ok(clip.some(h => h.selector.includes('#cut') && h.level === 'fail'));
    assert.ok(clip.some(h => h.selector.includes('#dots') && h.level === 'warn'));
    const zero = hitsOf(row, 'zero');
    assert.ok(zero.some(h => h.selector.includes('#zero')));
    assert.ok(zero.some(h => h.selector.includes('#flat')));
    const squeeze = hitsOf(row, 'squeeze');
    assert.deepEqual(squeeze.map(h => [h.selector, h.level]), [['p#narrow', 'fail'], ['p#gridrow', 'fail']], '窄栏那一段，和掉进 grid 窄格子的那一段');
    assert.match(squeeze[0].detail, /被挤成 \d+ 行.*不到 4 个字/);
    const font = hitsOf(row, 'font');
    assert.ok(font.some(h => h.selector.includes('#head') && h.level === 'fail' && /浏览器默认字体.*13\.33px/.test(h.detail)), '没继承字体的按钮');
    assert.ok(font.some(h => h.selector.includes('#famb') && h.level === 'warn' && /georgia/.test(h.detail)), '只换了字体族的按钮是提示');
    assert.ok(!font.some(h => h.selector.includes('#ico')), 'font: inherit 的按钮不报');
    const glyph = hitsOf(row, 'glyph');
    assert.deepEqual(glyph.map(h => h.selector.split(' > ').pop()).sort(), ['button#ico', 'span#emo']);
    assert.ok(glyph.every(h => h.level === 'warn'));
    const contrast = hitsOf(row, 'contrast');
    assert.ok(contrast.every(h => h.level === 'warn'), '对比度先只出提示');
    assert.ok(contrast.some(h => h.selector === 'p#low' && /对比度 2\.84，要求不低于 4\.5/.test(h.detail)));
    assert.ok(contrast.some(h => h.selector === 'p#grad' && /渐变或图片，量不准/.test(h.detail)));
    assert.equal(row.checks.contrast.pass, true, '提示不影响这一项通过');
    assert.equal(row.checks.glyph.pass, true);
    assert.ok(row.styles.fontSizes.length >= 2 && row.styles.fontFamilies.some(([f]) => f === 'georgia'));
    assert.ok(fs.existsSync(row.screenshot) && fs.existsSync(row.annotated));
  }
  const md = fs.readFileSync(path.join(run, 'report.md'), 'utf8');
  assert.match(md, /## 命中明细/);
  assert.match(md, /## 样式清单/);
  const folded = await main(['--url', url('bad.html'), '--out', out, '--no-baseline', '--no-details']);
  const rep2 = JSON.parse(fs.readFileSync(path.join(folded.run, 'report.json'), 'utf8'));
  assert.equal(hitsOf(rep2.rows[0], 'align').filter(h => /表头「占比」/.test(h.detail)).length, 0, '--no-details 时不展开');
});

test('正例页：全部通过；有意的横向滚动区只算提示，--ignore 后连提示也没有', { skip }, async () => {
  const out = outTmp();
  const r1 = await main(['--url', url('good.html'), '--out', out, '--no-baseline']);
  assert.equal(r1.pass, true, r1.md);
  const rep = JSON.parse(fs.readFileSync(path.join(r1.run, 'report.json'), 'utf8'));
  for (const row of rep.rows) {
    assert.deepEqual(hitsOf(row, 'overflow').map(h => h.level), ['warn']);
    for (const k of ['align', 'clip', 'zero', 'squeeze', 'font', 'glyph', 'contrast']) assert.deepEqual(hitsOf(row, k), [], `${row.width} ${k}`);
    assert.equal(row.annotated !== null, true);
    assert.deepEqual(row.ignore, [], '没有排除时是空数组');
  }
  assert.match(r1.md, /^- 排除项：无$/m);
  const r2 = await main(['--url', url('good.html'), '--out', out, '--no-baseline', '--ignore', '#scroll']);
  const rep2 = JSON.parse(fs.readFileSync(path.join(r2.run, 'report.json'), 'utf8'));
  assert.ok(rep2.rows.every(row => Object.values(row.checks).every(c => c.hits.length === 0)));
  for (const row of rep2.rows) assert.deepEqual(row.ignore, [{ selector: '#scroll', matched: 1 }], `${row.width} 排除项记进 report.json`);
  assert.match(r2.md, /^- 排除项（这些元素和它们里面的内容没有查）：`#scroll`（1 个元素）$/m);
  // 选择器写错、一个元素都没匹配到：照常查（提示还在），报告里标出来
  const r3 = await main(['--url', url('good.html'), '--out', out, '--no-baseline', '--ignore', '#scrol']);
  const rep3 = JSON.parse(fs.readFileSync(path.join(r3.run, 'report.json'), 'utf8'));
  for (const row of rep3.rows) {
    assert.deepEqual(row.ignore, [{ selector: '#scrol', matched: 0 }]);
    assert.deepEqual(hitsOf(row, 'overflow').map(h => h.level), ['warn']);
  }
  assert.match(r3.md, /`#scrol`（没匹配到元素，检查选择器）/);
});

test('读 pages.json：先跑 setup、查完调 teardown，再调项目的 ui-baseline.mjs compare 并入报告', { skip }, async () => {
  const root = outTmp();
  fs.mkdirSync(path.join(root, 'docs', 'design'), { recursive: true });
  fs.mkdirSync(path.join(root, 'scripts'));
  const marker = path.join(root, 'teardown.txt');
  fs.writeFileSync(path.join(root, 'scripts', 'setup.mjs'),
    `import fs from 'node:fs';\nexport default async function () { return async () => fs.writeFileSync(${JSON.stringify(marker)}, 'done'); }\n`);
  fs.writeFileSync(path.join(root, 'scripts', 'ui-baseline.mjs'),
    `if (!require('node:fs').existsSync(${JSON.stringify(marker)})) { console.log('teardown 还没跑'); process.exit(3); }\nconsole.log('和基线不一致或缺基线，差异图在 /e/ui-baseline-1');\nprocess.exit(1);\n`.replace("require('node:fs')", '(await import("node:fs")).default'));
  fs.writeFileSync(path.join(root, 'docs', 'design', 'pages.json'), JSON.stringify({
    evidence: 'evidence', setup: 'scripts/setup.mjs', pages: [{ name: 'good', url: url('good.html'), preflight: { ignore: ['#scroll'] } }],
  }));
  const r = await main(['--root', root]);
  const rep = JSON.parse(fs.readFileSync(path.join(r.run, 'report.json'), 'utf8'));
  assert.ok(r.run.startsWith(path.join(root, 'evidence')));
  assert.equal(rep.baseline.status, 1, rep.baseline.tail);
  assert.deepEqual(rep.rows.map(row => row.ignore), [[{ selector: '#scroll', matched: 1 }], [{ selector: '#scroll', matched: 1 }]], 'pages.json 里的排除项也记进报告');
  assert.match(r.md, /`#scroll`（1 个元素）/);
  assert.equal(rep.baseline.dir, '/e/ui-baseline-1');
  assert.equal(r.pass, false, '基线不一致也算不通过');
  assert.match(r.md, /❌ 和基线不一致或缺基线（退出码 1）；差异图在 `\/e\/ui-baseline-1`/);
});
