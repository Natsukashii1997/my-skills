// ui-preflight 的四项断言。上半部分是纯函数（只吃数字，node 里能直接测）；
// domChecks 在页面里跑，buildPageScript 把纯函数和 domChecks 拼成一段表达式交给 page.evaluate。

// 同一组框的某条边（left / right / center）彼此差多少以内算「齐」
export const EDGE_TOL = 1.5;
// 表头和本列数据的对应边差多少以内算对齐
export const HEADER_TOL = 2;
// 纵向排的同级元素左边缘差在 (NEAR_MIN, NEAR_MAX] 之间算「差一点没对齐」；差更多一般是有意的缩进
export const NEAR_MIN = 0.5;
export const NEAR_MAX = 4;

function edge(r, m) { return m === 'left' ? r.left : m === 'right' ? r.right : (r.left + r.right) / 2; }

// 一组框在哪几种对齐方式下是齐的：返回 ['left'] / ['right'] / ['left','right','center'] / []
export function alignModes(rects, tol = EDGE_TOL) {
  if (!rects.length) return [];
  return ['left', 'right', 'center'].filter(m => {
    const xs = rects.map(r => edge(r, m));
    return Math.max(...xs) - Math.min(...xs) <= tol;
  });
}

// 表头文字框和本列数据是否对齐：数据齐在哪条边，表头就要落在那条边上（任一条对上即可）。
// 返回 { ok, mode, diff }：不齐时 mode / diff 报数据实际的对齐方式（prefer，取自单元格的 text-align）和差值（px），
// prefer 不在可选范围里就报差得最少的那种
export function headerAlignment(bodyRects, headRect, tol = HEADER_TOL, prefer = null) {
  const modes = alignModes(bodyRects);
  if (!modes.length) return { ok: true, mode: null, diff: 0 };
  const diffs = modes.map(m => ({ mode: m, diff: Math.abs(edge(headRect, m) - bodyRects.reduce((s, r) => s + edge(r, m), 0) / bodyRects.length) }));
  const best = diffs.reduce((a, b) => (b.diff < a.diff ? b : a));
  const shown = best.diff <= tol ? best : diffs.find(d => d.mode === prefer) ?? best;
  return { ok: best.diff <= tol, mode: shown.mode, diff: Math.round(shown.diff * 10) / 10 };
}

// 一组框按纵向重叠分行，返回行数：下一个框的上沿在当前行下沿之下才算新起一行
// （同一行里高矮不同、垂直居中的框，上沿不同但互相重叠，不算折行）
export function countLines(rects) {
  const rs = rects.filter(r => r.width > 0 && r.height > 0).sort((a, b) => a.top - b.top);
  let lines = 0, bottom = -Infinity;
  for (const r of rs) {
    if (r.top >= bottom - Math.min(2, r.height / 2)) { lines++; bottom = r.bottom; } else bottom = Math.max(bottom, r.bottom);
  }
  return lines;
}

// 纵向排的一列同级框里，左边缘和多数差一点（NEAR_MIN～NEAR_MAX）的那几个的下标和差值
export function nearMisses(lefts, min = NEAR_MIN, max = NEAR_MAX) {
  if (lefts.length < 2) return [];
  const count = new Map();
  for (const x of lefts) { const k = Math.round(x); count.set(k, (count.get(k) ?? 0) + 1); }
  const [base, n] = [...count].sort((a, b) => b[1] - a[1] || a[0] - b[0])[0];
  if (n < 2) return [];
  const out = [];
  lefts.forEach((x, i) => { const d = Math.abs(x - base); if (d > min && d <= max) out.push({ i, diff: Math.round(d * 10) / 10 }); });
  return out;
}

// 卡头、工具栏这类「本该一行」的横排容器：看类名、标签和是否直接含标题
export const HEADERISH = /(^|[-_\s])(head|header|heading|title|toolbar|tools|bar|actions|extra|meta|tabs)([-_\s]|$)/i;

// —— 以下在页面里运行 ——
export function domChecks(opts) {
  const MAX_HITS = 50;
  const hits = { overflow: [], align: [], clip: [], zero: [] };
  const els = (window.__uipEls = []);
  const root = (opts.scope && document.querySelector(opts.scope)) || document.body;
  const ignore = (opts.ignore || []).join(',');
  const SKIP = new Set(['script', 'style', 'noscript', 'template', 'head', 'meta', 'link', 'br', 'wbr', 'option', 'title']);
  const cache = new Map();
  const st = el => { let s = cache.get(el); if (!s) { s = getComputedStyle(el); cache.set(el, s); } return s; };
  const rect = el => el.getBoundingClientRect();
  const R = r => ({ x: Math.round(r.left), y: Math.round(r.top + scrollY), w: Math.round(r.width), h: Math.round(r.height) });
  const text = el => (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ');
  const cssPath = el => {
    const parts = [];
    for (let e = el, i = 0; e && e.nodeType === 1 && e !== document.documentElement && i < 4; i++, e = e.parentElement) {
      let s = e.tagName.toLowerCase();
      if (e.id) { parts.unshift(`${s}#${CSS.escape(e.id)}`); break; }
      const cls = [...e.classList].filter(c => !c.startsWith('uip-')).slice(0, 2);
      if (cls.length) s += '.' + cls.map(c => CSS.escape(c)).join('.');
      const p = e.parentElement;
      if (p) { const same = [...p.children].filter(c => c.tagName === e.tagName); if (same.length > 1) s += `:nth-of-type(${same.indexOf(e) + 1})`; }
      parts.unshift(s);
    }
    return parts.join(' > ');
  };
  // level：fail 不通过；warn 提示（多半是有意的设计：省略号 / 限行截断、容器内横向滚动），要人逐条确认
  const add = (kind, el, detail, level = 'fail') => {
    if (hits[kind].length >= MAX_HITS) return;
    if (hits[kind].some(h => els[h.id] === el)) return;
    els.push(el);
    hits[kind].push({ id: els.length - 1, level, selector: cssPath(el), text: text(el).slice(0, 40), rect: R(rect(el)), detail });
  };
  const inkRect = el => { const rg = document.createRange(); rg.selectNodeContents(el); return rg.getBoundingClientRect(); };
  const lineRects = el => { const rg = document.createRange(); rg.selectNodeContents(el); return [...rg.getClientRects()]; };
  const hasDirectText = el => [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
  const visible = el => el.checkVisibility({ opacityProperty: true, visibilityProperty: true }) && !el.closest('[aria-hidden="true"],[inert]');
  const srOnly = el => {
    const r = rect(el), s = st(el);
    return (r.width <= 2 && r.height <= 2 && s.position === 'absolute') || (s.clip && s.clip !== 'auto') || /inset\(50%|circle\(0/.test(s.clipPath || '');
  };
  const inSvg = el => el.tagName.toLowerCase() !== 'svg' && !!el.closest('svg');
  const all = [...root.querySelectorAll('*')].filter(el =>
    !SKIP.has(el.tagName.toLowerCase()) && !inSvg(el) && !el.closest('[data-uip-overlay]') && !(ignore && el.closest(ignore)) && st(el).display !== 'contents');
  const vis = all.filter(visible);
  const vw = document.documentElement.clientWidth;
  const isPageBox = p => p === document.body || p === document.documentElement;
  const clipsX = s => s.overflowX !== 'visible';
  const scrollsX = s => s.overflowX === 'auto' || s.overflowX === 'scroll';
  const inFlow = el => !['absolute', 'fixed'].includes(st(el).position);

  // ① 横向溢出：整页横向滚动 + 超出视口的元素（只报最外层）+ 桌面宽度下出现横向滚动条的容器
  const pageOverflow = Math.max(0, document.documentElement.scrollWidth - vw);
  const beyond = new Set();
  for (const el of vis) {
    const r = rect(el);
    if (r.width <= 0 || (r.right <= vw + 0.5 && r.left >= -0.5)) continue;
    let contained = false;
    for (let p = el.parentElement; p && !isPageBox(p); p = p.parentElement) {
      const ps = st(p);
      if (scrollsX(ps)) { contained = true; break; }
      if (clipsX(ps)) { const pr = rect(p); if (pr.right <= vw + 0.5 && pr.left >= -0.5) { contained = true; break; } }
    }
    if (!contained) beyond.add(el);
  }
  for (const el of beyond) {
    let outer = true;
    for (let p = el.parentElement; p; p = p.parentElement) if (beyond.has(p)) { outer = false; break; }
    const r = rect(el);
    if (outer) add('overflow', el, r.right > vw ? `右边超出视口 ${Math.round(r.right - vw)}px` : `左边超出视口 ${Math.round(-r.left)}px`);
  }
  for (const el of vis) {
    const s = st(el);
    if (scrollsX(s) && el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0) add('overflow', el, `容器内出现横向滚动：内容宽 ${el.scrollWidth}px，只显示 ${el.clientWidth}px`, 'warn');
  }

  // ② 同列对齐：表格每列的表头和数据；纵向排的同级元素左边缘差一点
  for (const table of vis.filter(el => el.tagName === 'TABLE')) {
    const rows = [...table.rows].filter(visible);
    if (rows.some(r => [...r.cells].some(c => c.rowSpan > 1))) continue;
    const grid = rows.map(r => { const out = []; let c = 0; for (const cell of r.cells) { if (cell.colSpan === 1) out[c] = cell; c += cell.colSpan; } return out; });
    let headIdx = rows.map((r, i) => (r.parentElement.tagName === 'THEAD' ? i : -1)).filter(i => i >= 0);
    if (!headIdx.length && rows.length && [...rows[0].cells].every(c => c.tagName === 'TH')) headIdx = [0];
    if (!headIdx.length) continue;
    const head = grid[headIdx[headIdx.length - 1]];
    const body = grid.filter((_, i) => !headIdx.includes(i) && rows[i].parentElement.tagName !== 'TFOOT');
    head.forEach((th, c) => {
      if (!th || !text(th)) return;
      const cells = body.map(r => r[c]).filter(td => td && text(td) && visible(td));
      if (!cells.length) return;
      const ta = { start: 'left', end: 'right', left: 'left', right: 'right', center: 'center', '-webkit-right': 'right', '-webkit-center': 'center' }[st(cells[0]).textAlign] ?? null;
      const res = headerAlignment(cells.map(inkRect), inkRect(th), HEADER_TOL, ta);
      if (!res.ok) {
        const name = { left: '左', right: '右', center: '居中' }[res.mode];
        add('align', th, `表头「${text(th).slice(0, 12)}」和本列数据没对齐：数据${name === '居中' ? '居中' : name + '对齐'}，表头差 ${res.diff}px（数据 ${cells.length} 格）`);
      }
    });
  }
  for (const el of vis) {
    const kids = [...el.children].filter(k => vis.includes(k) && inFlow(k) && !/^inline/.test(st(k).display) && rect(k).width > 0 && rect(k).height > 0);
    if (kids.length < 2) continue;
    const rs = kids.map(rect);
    let stacked = true;
    for (let i = 1; i < rs.length; i++) if (rs[i].top < rs[i - 1].bottom - 1) { stacked = false; break; }
    if (!stacked) continue;
    for (const m of nearMisses(rs.map(r => r.left))) add('align', kids[m.i], `和同一列其他元素的左边缘差 ${m.diff}px`);
  }

  // ③ 截断与折行
  for (const el of vis) {
    if (!hasDirectText(el) || srOnly(el)) continue;
    const s = st(el);
    const ellipsis = s.textOverflow === 'ellipsis';
    if ((clipsX(s) && !scrollsX(s) || ellipsis) && el.scrollWidth > el.clientWidth + 1) {
      add('clip', el, `文字被截断：内容宽 ${el.scrollWidth}px，只显示 ${el.clientWidth}px${ellipsis ? '（省略号，确认是有意的、能看到全文）' : ''}`, ellipsis ? 'warn' : 'fail'); continue;
    }
    const clampY = s.webkitLineClamp && s.webkitLineClamp !== 'none';
    if ((clampY || (s.overflowY !== 'visible' && s.overflowY !== 'auto' && s.overflowY !== 'scroll')) && el.scrollHeight > el.clientHeight + 1) {
      add('clip', el, `文字被截断：内容高 ${el.scrollHeight}px，只显示 ${el.clientHeight}px${clampY ? `（限 ${s.webkitLineClamp} 行，确认是有意的、能看到全文）` : ''}`, clampY ? 'warn' : 'fail'); continue;
    }
    const ir = inkRect(el);
    for (let p = el.parentElement, i = 0; p && !isPageBox(p) && i < 6; p = p.parentElement, i++) {
      const ps = st(p);
      if (ps.overflowX === 'visible' && ps.overflowY === 'visible') continue;
      if (srOnly(p)) break;
      const pr = rect(p);
      const outX = !scrollsX(ps) && clipsX(ps) && (ir.right > pr.right + 1 || ir.left < pr.left - 1);
      const outY = !['visible', 'auto', 'scroll'].includes(ps.overflowY) && (ir.bottom > pr.bottom + 1 || ir.top < pr.top - 1);
      if (outX || outY) { add('clip', el, `文字超出外层 ${cssPath(p).split(' > ').pop()} 被裁掉`); break; }
      if (scrollsX(ps) || ['auto', 'scroll'].includes(ps.overflowY)) break;
    }
  }
  const tagLike = el => {
    const s = st(el);
    if (!/^inline/.test(s.display) || !hasDirectText(el)) return false;
    const bg = s.backgroundColor && !/rgba\(0, 0, 0, 0\)|transparent/.test(s.backgroundColor);
    return bg || parseFloat(s.borderTopWidth) > 0;
  };
  for (const el of vis) {
    const tag = el.tagName;
    const t = text(el);
    if (!t) continue;
    let limit = 0;
    if (/^H[1-6]$/.test(tag)) limit = 40;
    else if (tag === 'BUTTON' || tag === 'TH' || el.getAttribute('role') === 'button' || el.getAttribute('role') === 'tab' || tagLike(el)) limit = 30;
    if (!limit || t.length > limit) continue;
    // 结构上就是多行的（含 <br>、块级子元素、纵向排的 flex / grid）不算折行
    const es = st(el);
    if ((/flex$/.test(es.display) && es.flexDirection.startsWith('column')) || /grid$/.test(es.display)) continue;
    if (el.querySelector('br') || [...el.querySelectorAll('*')].some(d => !/^(inline|contents|none)/.test(st(d).display))) continue;
    const n = countLines(lineRects(el));
    if (n > 1) add('clip', el, `「${t.slice(0, 16)}」折成了 ${n} 行`);
  }
  for (const el of vis) {
    const s = st(el);
    if (!/flex$/.test(s.display) || !s.flexDirection.startsWith('row')) continue;
    const kids = [...el.children].filter(k => vis.includes(k) && inFlow(k) && rect(k).width > 0);
    if (kids.length < 2) continue;
    const headerish = HEADERISH.test(typeof el.className === 'string' ? el.className : '') || el.tagName === 'HEADER' || kids.some(k => /^H[1-6]$/.test(k.tagName));
    if (!headerish) continue;
    const n = countLines(kids.map(rect));
    if (n > 1) add('clip', el, `本该一行的横排（${kids.length} 个元素）折成了 ${n} 行`);
  }

  // ④ 0 高：图形 0 高 / 0 宽；里面有内容、自己 0 高又把内容裁掉的容器
  for (const el of vis) {
    const r = rect(el);
    if (r.height >= 1 && r.width >= 1) continue;
    if (srOnly(el)) continue;
    const tag = el.tagName.toLowerCase();
    if (['svg', 'canvas', 'img', 'video', 'iframe'].includes(tag)) {
      if (tag === 'svg' && !el.querySelector(':scope > :not(defs):not(symbol):not(title):not(desc):not(style)')) continue;
      if (st(el).position === 'absolute' && r.width < 1 && r.height < 1) continue;
      add('zero', el, `${tag} 的${r.height < 1 ? '高' : '宽'}是 0，画不出来`);
      continue;
    }
    const s = st(el);
    const hidesY = r.height < 1 && s.overflowY !== 'visible';
    const hidesX = r.width < 1 && s.overflowX !== 'visible';
    if (!(hidesY || hidesX)) continue;
    if (!text(el) && !el.querySelector('img,svg,canvas,video,iframe')) continue;
    add('zero', el, `容器${r.height < 1 ? '高' : '宽'}是 0，里面的内容看不见`);
  }

  return { width: vw, pageOverflow, hits };
}

// 页面里执行的完整表达式：纯函数 + 常量 + domChecks(opts)
export function buildPageScript(opts) {
  const fns = [edge, alignModes, headerAlignment, countLines, nearMisses, domChecks].map(f => f.toString()).join('\n');
  const consts = `const EDGE_TOL = ${EDGE_TOL}, HEADER_TOL = ${HEADER_TOL}, NEAR_MIN = ${NEAR_MIN}, NEAR_MAX = ${NEAR_MAX}, HEADERISH = ${HEADERISH};`;
  return `(() => { ${consts}\n${fns}\nreturn domChecks(${JSON.stringify(opts)}); })()`;
}
