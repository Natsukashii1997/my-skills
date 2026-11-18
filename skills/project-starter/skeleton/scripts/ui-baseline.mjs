// 网页项目的基线截图：用户验收界面的当轮拍基线，之后每次改界面都和基线逐页比，防止已定的界面被一点点改偏。
// 用 Playwright 自带的 toHaveScreenshot 比较，不另装图像库：每张截图先等页面加载完、字体加载完，再连拍到前后两张一样才算画完
// （全局坑 G-11）；CSS 动画和过渡停在初始状态，光标隐藏；脚本驱动的动画、时钟这类停不住的区域用 mask 遮掉。
// 先装：npm i -D @playwright/test && npx playwright install chromium（@playwright/test 已在 check-rules.mjs 的 ALLOWED_DEPS 里）。
// 页面清单 docs/design/pages.json：
//   { "evidence": "~/Library/Application Support/<项目>/evidence",
//     "pages": [ { "name": "home", "url": "http://127.0.0.1:3000/", "widths": [1280, 1440], "mask": [".clock"] } ] }
//   evidence 是项目约定的证据目录（AGENTS.md「规则」），不能在 /tmp；name 当截图文件名用，不能重复；widths 不写默认 1280 和 1440；mask 可不写。
// 用法：node scripts/ui-baseline.mjs shoot     拍基线到 docs/design/baseline/<name>-<宽>.png，再登记进 docs/DECIDED.md
//       node scripts/ui-baseline.mjs compare   逐页和基线比；有一页差异超过 MAX_DIFF_RATIO 或缺基线就以非零退出，
//                                              差异图（-diff / -actual / -expected.png）写到 <evidence>/ui-baseline-<时间>-<随机>/
// 本文件同时是 Playwright 的配置文件（shoot / compare 用 -c 指向自己），每页怎么截写在 ui-baseline.spec.mjs。
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// 差异像素占整张图的比例超过它就算不一致
const MAX_DIFF_RATIO = 0.001;
const WIDTHS = [1280, 1440];
const SELF = fileURLToPath(import.meta.url);
export const ROOT = path.resolve(process.env.UI_BASELINE_ROOT ?? path.join(path.dirname(SELF), '..'));

export function readPages(root) {
  const file = path.join(root, 'docs', 'design', 'pages.json');
  if (!fs.existsSync(file)) throw new Error(`没有 ${path.relative(root, file)}，格式见 scripts/ui-baseline.mjs 开头`);
  const { evidence, pages } = JSON.parse(fs.readFileSync(file, 'utf8'));
  if (typeof evidence !== 'string' || !evidence) throw new Error('pages.json 缺 evidence（项目约定的证据目录）');
  const dir = path.resolve(root, evidence.replace(/^~(?=\/|$)/, os.homedir()));
  if (/^\/(private\/)?tmp(\/|$)/.test(dir)) throw new Error(`证据目录不能放 /tmp，会被系统清理（全局坑 G-01）：${dir}`);
  if (!Array.isArray(pages) || !pages.length) throw new Error('pages.json 的 pages 是空的');
  const names = new Set();
  for (const p of pages) {
    if (!p.name || !p.url) throw new Error(`每页都要有 name 和 url：${JSON.stringify(p)}`);
    if (names.has(p.name)) throw new Error(`name 重复：${p.name}`);
    names.add(p.name);
  }
  return { evidence: dir, pages: pages.map(p => ({ ...p, widths: p.widths ?? WIDTHS, mask: p.mask ?? [] })) };
}

// action：shoot 拍基线 / compare 对比。返回 Playwright 的退出码和本次输出目录
export function uiBaseline(root, action, stdio = 'inherit') {
  const { evidence } = readPages(root);
  let cli;
  try { cli = createRequire(SELF).resolve('@playwright/test/cli'); } catch { throw new Error('没装 @playwright/test：npm i -D @playwright/test && npx playwright install chromium'); }
  const stamp = new Date().toLocaleString('sv-SE', { timeZone: 'Asia/Shanghai' }).replace(/[-:]/g, '').replace(' ', '-');
  // 每次单开一个新目录：Playwright 开跑前会清空输出目录，不能指向整个证据目录，同一秒跑两次也不能共用
  fs.mkdirSync(evidence, { recursive: true });
  const out = fs.mkdtempSync(path.join(evidence, `ui-baseline-${stamp}-`));
  const update = action === 'shoot' ? 'all' : 'none';
  const r = spawnSync(process.execPath, [cli, 'test', '-c', SELF, `--output=${out}`, `--update-snapshots=${update}`], {
    cwd: root, stdio, encoding: 'utf8', env: { ...process.env, UI_BASELINE_ROOT: root },
  });
  return { status: r.status ?? 1, out, output: `${r.stdout ?? ''}${r.stderr ?? ''}` };
}

export default {
  testDir: path.dirname(SELF),
  testMatch: 'ui-baseline.spec.mjs',
  snapshotPathTemplate: path.join(ROOT, 'docs', 'design', 'baseline', '{arg}{ext}'),
  reporter: 'list',
  retries: 0,
  use: { browserName: 'chromium' },
  expect: { toHaveScreenshot: { maxDiffPixelRatio: MAX_DIFF_RATIO, animations: 'disabled', caret: 'hide' } },
};

if (process.argv[1] && path.resolve(process.argv[1]) === SELF) {
  const action = process.argv[2];
  if (!['shoot', 'compare'].includes(action)) {
    console.error('用法：node scripts/ui-baseline.mjs shoot | compare');
    process.exit(2);
  }
  let status, out;
  try { ({ status, out } = uiBaseline(ROOT, action)); } catch (e) { console.error(e.message); process.exit(2); }
  if (action === 'shoot') console.log(status === 0 ? '基线已写到 docs/design/baseline/，记得登记进 docs/DECIDED.md' : `拍基线失败，看上面的报错；输出在 ${out}`);
  else console.log(status === 0 ? '和基线一致' : `和基线不一致或缺基线，差异图在 ${out}`);
  process.exitCode = status;
}
