// ui-preflight：纯函数和参数解析在任何环境都跑；真浏览器那组要 Playwright，
// 本机用 UI_PREFLIGHT_PLAYWRIGHT=<装了 @playwright/test 的项目目录> 指过去，没有就跳过（CI 上没装）。
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { alignModes, countLines, headerAlignment, nearMisses } from '../skills/ui-preflight/scripts/checks.mjs';
import { assertEvidenceDir, main, mark, parseArgs, renderReport, resolvePlan } from '../skills/ui-preflight/scripts/ui-preflight.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const fixtures = path.join(here, 'fixtures', 'ui-preflight');
const box = (left, right, top = 0, bottom = 20) => ({ left, right, top, bottom, width: right - left, height: bottom - top });
const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), 'uip-test-'));

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
    evidence: 'evidence', setup: 'scripts/setup.mjs', ready: 'main', preflight: { ignore: ['.wall'] },
    pages: [{ name: 'a', url: 'http://x/a' }, { name: 'b', url: 'http://x/b', ready: '#b', preflight: { openDetails: false, ignore: ['.c'] } }],
  }));
  const plan = resolvePlan(parseArgs(['--root', root, '--ignore', '.z']));
  assert.equal(plan.evidence, path.join(root, 'evidence'));
  assert.equal(plan.setup, path.join(root, 'scripts', 'setup.mjs'));
  assert.equal(plan.baseline, path.join(root, 'scripts', 'ui-baseline.mjs'));
  assert.deepEqual(plan.pages.map(p => [p.name, p.ready, p.ignore, p.openDetails]), [['a', 'main', ['.wall', '.z'], true], ['b', '#b', ['.c', '.z'], false]]);
  assert.deepEqual(resolvePlan(parseArgs(['--root', root, '--page', 'b'])).pages.map(p => p.name), ['b']);
  assert.throws(() => resolvePlan(parseArgs(['--root', root, '--page', 'nope'])), /没有这几页/);
  assert.equal(resolvePlan(parseArgs(['--root', root, '--no-baseline'])).baseline, null);
  // --url 指的是已经在跑的地址：不起 setup
  const byUrl = resolvePlan(parseArgs(['--root', root, '--url', 'http://y/', '--out', path.join(root, 'o')]));
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
      checks: { overflow: ok, align: { pass: false, hits: [hit(1, 'fail')] }, clip: { pass: true, hits: [hit(2, 'warn')] }, zero: ok } },
    { page: 'x', width: 1440, error: '打不开' }],
  });
  assert.match(md, /\| biz \| 1280 \| ✅ 通过 \| ❌ 不通过（1 处 #1） \| ✅ 通过 ⚠️ 提示 1 处 #2 \| ✅ 通过 \| \[biz-1280\.png\]\(biz-1280\.png\) · \[biz-1280-标注\.png\]/);
  assert.match(md, /页面没能查完：打不开/);
  assert.match(md, /另有 1 条 ⚠️ 提示/);
  assert.match(md, /d\\\|x/);
});

// —— 真浏览器 ——
const pwRoot = process.env.UI_PREFLIGHT_PLAYWRIGHT;
let hasPw = false;
if (pwRoot) { try { createRequire(path.join(pwRoot, 'package.json')).resolve('@playwright/test'); hasPw = true; } catch {} }
const skip = hasPw ? false : '没设 UI_PREFLIGHT_PLAYWRIGHT（装了 @playwright/test 的目录），跳过真浏览器测试';
const url = f => pathToFileURL(path.join(fixtures, f)).href;
const hitsOf = (row, k) => row.checks[k].hits;

test('反例页：四项都查得出，省略号只算提示；收起的 <details> 默认展开再查', { skip }, async () => {
  const out = tmp();
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
    assert.ok(fs.existsSync(row.screenshot) && fs.existsSync(row.annotated));
  }
  const md = fs.readFileSync(path.join(run, 'report.md'), 'utf8');
  assert.match(md, /## 命中明细/);
  const folded = await main(['--url', url('bad.html'), '--out', out, '--no-baseline', '--no-details']);
  const rep2 = JSON.parse(fs.readFileSync(path.join(folded.run, 'report.json'), 'utf8'));
  assert.equal(hitsOf(rep2.rows[0], 'align').filter(h => /表头「占比」/.test(h.detail)).length, 0, '--no-details 时不展开');
});

test('正例页：全部通过；有意的横向滚动区只算提示，--ignore 后连提示也没有', { skip }, async () => {
  const out = tmp();
  const r1 = await main(['--url', url('good.html'), '--out', out, '--no-baseline']);
  assert.equal(r1.pass, true, r1.md);
  const rep = JSON.parse(fs.readFileSync(path.join(r1.run, 'report.json'), 'utf8'));
  for (const row of rep.rows) {
    assert.deepEqual(hitsOf(row, 'overflow').map(h => h.level), ['warn']);
    for (const k of ['align', 'clip', 'zero']) assert.deepEqual(hitsOf(row, k), [], `${row.width} ${k}`);
    assert.equal(row.annotated !== null, true);
  }
  const r2 = await main(['--url', url('good.html'), '--out', out, '--no-baseline', '--ignore', '#scroll']);
  const rep2 = JSON.parse(fs.readFileSync(path.join(r2.run, 'report.json'), 'utf8'));
  assert.ok(rep2.rows.every(row => Object.values(row.checks).every(c => c.hits.length === 0)));
});

test('读 pages.json：先跑 setup、查完调 teardown，再调项目的 ui-baseline.mjs compare 并入报告', { skip }, async () => {
  const root = tmp();
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
  assert.equal(rep.baseline.dir, '/e/ui-baseline-1');
  assert.equal(r.pass, false, '基线不一致也算不通过');
  assert.match(r.md, /❌ 和基线不一致或缺基线（退出码 1）；差异图在 `\/e\/ui-baseline-1`/);
});
