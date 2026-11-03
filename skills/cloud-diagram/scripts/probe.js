// cloud-diagram probe: runs inside the page (injected by render.sh) and writes its
// result as JSON into a pre element (id probe-out) for --dump-dom to read.
// It measures what the eye misses: the body scrolling sideways, label over label,
// a label cut by an arrow, an arrow crossing an icon and an arrow crossing an arrow.
(function () {
  function bboxOfUse(u) {
    const n = a => parseFloat(u.getAttribute(a) || "0");
    return { x: n("x"), y: n("y"), w: n("width"), h: n("height") };
  }
  function bboxOfText(t) {
    const b = t.getBBox();
    return { x: b.x, y: b.y, w: b.width, h: b.height };
  }
  function shrink(b, d) { return { x: b.x + d, y: b.y + d, w: b.w - 2 * d, h: b.h - 2 * d }; }
  function hit(a, b) { return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h; }
  function segs(d) {
    const out = []; const re = /([MLHV])\s*([-\d.]+)(?:[\s,]+([-\d.]+))?/gi; let m, x = 0, y = 0;
    while ((m = re.exec(d))) {
      const c = m[1].toUpperCase(), a = parseFloat(m[2]), b = parseFloat(m[3]);
      let nx = x, ny = y;
      if (c === "M") { x = a; y = b; continue; }
      if (c === "H") nx = a; else if (c === "V") ny = a; else { nx = a; ny = b; }
      out.push({ x1: x, y1: y, x2: nx, y2: ny }); x = nx; y = ny;
    }
    return out;
  }
  function segBox(s) { return { x: Math.min(s.x1, s.x2) - .5, y: Math.min(s.y1, s.y2) - .5, w: Math.abs(s.x2 - s.x1) + 1, h: Math.abs(s.y2 - s.y1) + 1 }; }
  function label(el) { return (el.textContent || el.getAttribute("href") || el.tagName).trim().slice(0, 40); }

  function probeSvg(svg) {
    const texts = [...svg.querySelectorAll("text")].filter(t => !t.closest(".st") && !t.closest("defs"));
    const uses = [...svg.querySelectorAll("use")].filter(u => !u.closest("defs"));
    const balloons = [...svg.querySelectorAll(".st circle")].map(c => {
      const r = +c.getAttribute("r"), cx = +c.getAttribute("cx"), cy = +c.getAttribute("cy");
      return { el: c.closest(".st"), b: { x: cx - r, y: cy - r, w: 2 * r, h: 2 * r } };
    });
    const arrows = [...svg.querySelectorAll("path.ar")].map(p => ({ el: p, s: segs(p.getAttribute("d") || "") }));
    const joins = [...svg.querySelectorAll(".jn")].map(c => [+c.getAttribute("cx"), +c.getAttribute("cy")]);
    const T = texts.map(t => ({ el: t, b: bboxOfText(t) }));
    const U = uses.map(u => ({ el: u, b: bboxOfUse(u) }));
    const issues = [];
    // label over label
    for (let i = 0; i < T.length; i++) for (let j = i + 1; j < T.length; j++)
      if (hit(shrink(T[i].b, 1), shrink(T[j].b, 1))) issues.push(["label x label", label(T[i].el), label(T[j].el)]);
    // label over icon, and balloon over label or icon
    T.forEach(t => U.forEach(u => { if (hit(shrink(t.b, 1), shrink(u.b, 1))) issues.push(["label x icon", label(t.el), label(u.el)]); }));
    balloons.forEach(bl => {
      T.forEach(t => { if (hit(shrink(t.b, 1), bl.b)) issues.push(["balloon x label", "step " + bl.el.dataset.s, label(t.el)]); });
      U.forEach(u => { if (hit(shrink(u.b, 1), bl.b)) issues.push(["balloon x icon", "step " + bl.el.dataset.s, label(u.el)]); });
    });
    // arrow cutting a label or crossing an icon (touching the icon's edge to arrive is fine)
    arrows.forEach(a => a.s.forEach(s => {
      const sb = segBox(s);
      T.forEach(t => { if (hit(sb, shrink(t.b, 1))) issues.push(["arrow x label", a.el.getAttribute("d"), label(t.el)]); });
      U.forEach(u => { if (hit(sb, shrink(u.b, 3))) issues.push(["arrow x icon", a.el.getAttribute("d"), label(u.el)]); });
    }));
    // arrow crossing arrow: perpendicular segments that cut each other away from a marked junction
    const all = arrows.flatMap(a => a.s.map(s => ({ a, s })));
    for (let i = 0; i < all.length; i++) for (let j = i + 1; j < all.length; j++) {
      if (all[i].a === all[j].a) continue;
      const p = all[i].s, q = all[j].s;
      const ph = p.y1 === p.y2, qh = q.y1 === q.y2;
      if (ph === qh) continue;
      const h = ph ? p : q, v = ph ? q : p;
      const x = v.x1, y = h.y1;
      const inH = x > Math.min(h.x1, h.x2) && x < Math.max(h.x1, h.x2);
      const inV = y > Math.min(v.y1, v.y2) && y < Math.max(v.y1, v.y2);
      if (inH && inV && !joins.some(([jx, jy]) => Math.abs(jx - x) < 1 && Math.abs(jy - y) < 1))
        issues.push(["arrow x arrow", all[i].a.el.getAttribute("d"), all[j].a.el.getAttribute("d")]);
    }
    return { id: svg.id || "(no id)", texts: T.length, icons: U.length, arrows: arrows.length, problems: issues };
  }

  // The drawing's status in the stamp: CURRENT with a date (YYYY-MM-DD) or PROPOSED. Without it
  // the reader takes the proposal for the system that is running. The words are matched in
  // English and Portuguese, the two languages the stamp has been written in.
  function status() {
    const flat = t => t.normalize("NFD").replace(/[̀-ͯ]/g, "").trim().toLowerCase();
    const dts = [...document.querySelectorAll(".stamp dt")].filter(dt => /^(status|situacao)$/.test(flat(dt.textContent)));
    if (!dts.length) return { ok: false, text: "", reason: "stamp has no Status cell" };
    const dd = dts[0].nextElementSibling;
    const text = dd ? dd.textContent.trim() : "";
    const t = flat(text);
    if (/\bproposed\b|\bpropost[oa]\b/.test(t)) return { ok: true, text };
    if (/\b(current|atual)\b/.test(t)) {
      return /\b\d{4}-\d{2}-\d{2}\b/.test(t) ? { ok: true, text }
        : { ok: false, text, reason: "Status says CURRENT with no YYYY-MM-DD date" };
    }
    return { ok: false, text, reason: "Status says neither CURRENT as of YYYY-MM-DD nor PROPOSED" };
  }

  function run() {
    const vw = document.documentElement.clientWidth;
    const outside = [...document.body.querySelectorAll("*")].filter(e => {
      if (e.closest("svg") && e.tagName.toLowerCase() !== "svg") return false;
      let p = e.parentElement;
      while (p && p !== document.body) { const o = getComputedStyle(p).overflowX; if (o === "auto" || o === "scroll" || o === "hidden") return false; p = p.parentElement; }
      const r = e.getBoundingClientRect(); return r.width > 0 && r.right > vw + 1;
    }).slice(0, 8).map(e => e.tagName.toLowerCase() + (e.className && typeof e.className === "string" ? "." + e.className.split(" ")[0] : ""));
    const svgs = [...document.querySelectorAll("svg[data-diagram], .dia svg, svg#dia")];
    const out = {
      viewport: vw,
      body_scrolls_sideways: document.documentElement.scrollWidth > vw + 1,
      past_the_window: outside,
      fonts: [...document.fonts].filter(f => f.status === "loaded").map(f => f.family).filter((v, i, a) => a.indexOf(v) === i),
      diagrams: [...new Set(svgs)].map(probeSvg),
    };
    out.status = out.diagrams.length ? status() : { ok: true, text: "", reason: "no diagram on the page" };
    let pre = document.getElementById("probe-out");
    if (!pre) { pre = document.createElement("pre"); pre.id = "probe-out"; pre.hidden = true; document.body.appendChild(pre); }
    pre.textContent = JSON.stringify(out);
    if (window.parent !== window) window.parent.postMessage({ probe: pre.textContent }, "*");
  }
  (document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve()).then(() => setTimeout(run, 300));
})();
