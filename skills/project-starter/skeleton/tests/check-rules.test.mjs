import { test } from 'node:test';
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { checkRules } from '../scripts/check-rules.mjs';

test('仓库符合通用规则（scripts/check-rules.mjs）', () => {
  assert.deepEqual(checkRules(process.cwd()), []);
});

test('通用规则能抓到违规样本，合规样本不误报', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'check-rules-'));
  const write = (file, text) => {
    fs.mkdirSync(path.dirname(path.join(root, file)), { recursive: true });
    fs.writeFileSync(path.join(root, file), text);
  };
  try {
    write('src/a.js', 'show(item.createdAt.slice(0, 16));\nshow(beijingTime(item.createdAt));\nshow(item.updatedAt.slice(11, 16)); // 北京时间\n');
    write('server/index.mjs', "server.listen(port);\nserver.listen(port, '127.0.0.1');\n");
    write('server/safe.mjs', "const ok = req => req.headers.origin === undefined;\nserver.listen(port, '127.0.0.1');\n");
    write('scripts/run.sh', 'set -euo pipefail\nif [ -n "$DRY_RUN" ]; then echo dry; fi\nif [ -n "${VERBOSE:-}" ]; then echo v; fi\n# [ -z "$X" ] 注释不算\n');
    write('scripts/loose.sh', 'if [ -z "$X" ]; then echo x; fi\n');
    write('package.json', JSON.stringify({ dependencies: { 'left-pad': '1.0.0' } }, null, 2));
    assert.deepEqual(checkRules(root).map(v => `${v.file}:${v.line} ${v.kind}`), ['src/a.js:1 time', 'server/index.mjs:1 listen', 'server/index.mjs:1 origin', 'scripts/run.sh:2 optvar', 'package.json:3 deps']);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('LESSONS 每条要有以层级词开头的「升级」行：真实条目会报错，合规条目和格式样例不误报', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'check-rules-'));
  // 前三条摘自 postpane docs/LESSONS.md（2026-11 复盘：50 条里 13 条没有升级行，另有写法不带层级词），只留标题和结构
  const lessons = [
    '# 开发实录与坑', '', '## 怎么写', '', '- 格式样例：', '', '```markdown', '## L-01 <一句话现象>（<YYYY-MM-DD>）', '', '- 升级：未升级。', '```', '', '---', '',
    '## L-01 新目录直接跑 cargo test，桌面程序编译失败（2026-11-04）', '', '- 现象：略。', '- 升级：已写进 AGENTS.md「运行」。', '',
    '## L-16 Chrome 扩展测试 8 条全挂：Playwright 浏览器缓存被本机清理删掉了（2026-11-07）', '', '- 现象：略。', '- 升级：无（环境问题，测试本身的报错已经说清楚了）。', '',
    '## L-29 内置浏览器面板隐藏时截到「卡在半路」的侧栏，误以为布局错乱（2026-11-08）', '', '- 现象：略。', '- 正确做法：略。', '',
    // 剪藏插件 L-02 的真实标题：反引号里的 <all_urls> 不是占位，0.3.0 把整条当格式样例跳过了（漏报）
    '## L-02 声明了 `<all_urls>` 仍无法调用 `captureVisibleTab`（2026-11-02）', '', '- 现象：略。', '',
    '## L-51 合规：未升级的也要带层级词（2026-11-18）', '', '- 现象：略。', '- 升级：〔提醒〕未升级。', '',
    '## L-52 合规：已升级写明去处（2026-11-18）', '', '- 现象：略。', '- 升级：〔机检〕已升级（2026-11-18，#1）：scripts/check-rules.mjs 的 lessons 规则。', '',
  ].join('\n');
  try {
    fs.mkdirSync(path.join(root, 'docs'));
    fs.writeFileSync(path.join(root, 'docs/LESSONS.md'), lessons);
    assert.deepEqual(checkRules(root).map(v => `${v.file}:${v.line} ${v.kind} ${v.text}`), [
      'docs/LESSONS.md:18 lessons L-01 的「升级」没以层级词开头：- 升级：已写进 AGENTS.md「运行」。',
      'docs/LESSONS.md:23 lessons L-16 的「升级」没以层级词开头：- 升级：无（环境问题，测试本身的报错已经说清楚了）。',
      'docs/LESSONS.md:25 lessons L-29 缺「- 升级：」一行',
      'docs/LESSONS.md:30 lessons L-02 缺「- 升级：」一行',
    ]);
    assert.match(checkRules(root)[0].rule, /〔提醒〕未升级/);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('大改动没写改前改后对照会报错；没到阈值、已新增对照、没有 origin/main 时不报', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'check-rules-git-'));
  const git = (...args) => execFileSync('git', ['-c', 'user.name=t', '-c', 'user.email=t@example.com', '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null', ...args], { cwd: root, stdio: 'pipe' });
  const write = (file, text) => { fs.mkdirSync(path.dirname(path.join(root, file)), { recursive: true }); fs.writeFileSync(path.join(root, file), text); };
  const big = () => checkRules(root).filter(v => v.kind === 'bigchange').map(v => v.text);
  const range = (n, from = 0) => Array.from({ length: n }, (_, i) => `src/m${from + i}.js`);
  try {
    git('init', '-q', '-b', 'main');
    // 改前已有一节旧的对照：只有本分支新增的才算
    write('CURRENT.md', '# 当前状态\n\n## 起步（2026-11-01）\n\n- 改前改后功能对照：无。\n');
    for (const f of range(136)) write(f, 'export const v = 1;\n');
    git('add', '-A'); git('commit', '-q', '-m', 'base');
    // 规模照 digiworld 提交 0f03467：改 136 个、新增 624 个，共 760 个文件；其中 24 个还没提交
    for (const f of range(136)) write(f, 'export const v = 2;\n');
    for (const f of range(624, 136)) write(f, 'export const v = 1;\n');
    assert.deepEqual(big(), [], '没有 origin/main 时跳过');
    git('update-ref', 'refs/remotes/origin/main', 'HEAD');
    git('add', '-A', '--', ...range(600)); git('commit', '-q', '-m', 'big');
    assert.deepEqual(big(), ['本分支相对 origin/main 改了 760 个文件（阈值 100），CURRENT.md 没有新增「改前改后功能对照」一节']);
    write('CURRENT.md', '# 当前状态\n\n## 大改（2026-11-18）\n\n### 改前改后功能对照\n\n| 原有功能 | 改后 | 怎么核对的 |\n|---|---|---|\n| 首页四块 | 还在 | 截图对比 |\n\n## 起步（2026-11-01）\n\n- 改前改后功能对照：无。\n');
    assert.deepEqual(big(), [], '新增了对照就通过');
    // 新的起点：对照已在 origin/main 上，再改 99 个不报，到 100 个报
    git('add', '-A'); git('commit', '-q', '-m', 'all');
    git('update-ref', 'refs/remotes/origin/main', 'HEAD');
    for (const f of range(99, 1000)) write(f, 'export const v = 1;\n');
    assert.deepEqual(big(), [], '99 个文件不报');
    write('src/m1099.js', 'export const v = 1;\n');
    assert.deepEqual(big(), ['本分支相对 origin/main 改了 100 个文件（阈值 100），CURRENT.md 没有新增「改前改后功能对照」一节'], '旧对照不算本次的');
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});
