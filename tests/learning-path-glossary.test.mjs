// AI 学习路径的共用词典（docs/learning-path/index.html）和各站讲解页的术语表要一致：
// 各站术语表里的每一条都要原样出现在共用词典里，并标对所属站。
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const read = (p) => fs.readFileSync(path.join(REPO, p), 'utf8');

// 页面脚本里的 `var NAME=[ ... ];` 是纯数据字面量，取出来求值
function arrayOf(html, name) {
  const m = html.match(new RegExp(`var ${name}=\\[\\n([\\s\\S]*?)\\n\\];`));
  assert.ok(m, `没找到 var ${name}=[...]`);
  return new Function(`return [${m[1]}];`)();
}

const LP = read('docs/learning-path/index.html');
const DICT = arrayOf(LP, 'GL');
const STATIONS = arrayOf(LP, 'STATIONS');

// 有自己术语表的站：站 id → 讲解页源文件
const SOURCES = { matt: 'docs/matt-guide/index.html' };

test('共用词典每条 7 项，所属站都登记在路线里', () => {
  const ids = new Set(STATIONS.map((s) => s.id));
  for (const g of DICT) {
    assert.equal(g.length, 7, `「${g[1]}」不是 7 项`);
    assert.ok(ids.has(g[6]), `「${g[1]}」的所属站 ${g[6]} 不在 STATIONS 里`);
  }
});

test('共用词典里术语不重名', () => {
  const seen = new Set();
  for (const g of DICT) {
    assert.ok(!seen.has(g[1]), `术语重复：${g[1]}`);
    seen.add(g[1]);
  }
});

test('站序号从 1 连续编号', () => {
  STATIONS.forEach((s, i) => assert.equal(s.n, i + 1, `${s.id} 的序号应为 ${i + 1}`));
});

for (const [id, file] of Object.entries(SOURCES)) {
  test(`${file} 的术语表原样收进共用词典，所属站 ${id}`, () => {
    const own = arrayOf(read(file), 'GL');
    assert.ok(own.length > 0);
    const inDict = DICT.filter((g) => g[6] === id).map((g) => JSON.stringify(g.slice(0, 6)));
    const inPage = own.map((g) => JSON.stringify(g));
    assert.deepEqual(inDict, inPage, '两边条目、文字或顺序不一致');
  });
}
