#!/usr/bin/env node
// Code <-> Figma motion bridge (skill `design-bridge`). No dependencies.
//
//   motion-figma.mjs export <animations.json> [prefix...]
//   motion-figma.mjs compare <animations.json> <read-back.json> [prefix...]   (exits 1 on divergence)
//
// <animations.json> is what the project's ADAPTER prints (contract in
// references/project-template.md): keyframes in the Web Animations API format,
// `transform` and `opacity` only. The code is the source of the values; this
// script only translates. Values come out in DRAWING UNITS (drawing px or % of
// the box); converting them to Figma pixels is the job of the `use_figma`
// script, which knows the size of the node.

import { readFileSync, realpathSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const round = (v, places = 4) => Number(v.toFixed(places));

// CSS named curves, as the specification defines them.
const NAMED = {
  ease: [0.25, 0.1, 0.25, 1],
  'ease-in': [0.42, 0, 1, 1],
  'ease-out': [0, 0, 0.58, 1],
  'ease-in-out': [0.42, 0, 0.58, 1],
};
const CB = /^cubic-bezier\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)$/;

export function easing(css) {
  const v = (css ?? 'linear').trim();
  if (v === 'linear') return { type: 'LINEAR' };
  if (v === 'step-start' || v === 'steps(1, start)' || v === 'steps(1,start)') return { type: 'HOLD' };
  const m = CB.exec(v);
  const p = m ? m.slice(1).map(Number) : NAMED[v];
  if (!p) throw new Error(`easing the bridge cannot translate: ${css}`);
  const [x1, y1, x2, y2] = p;
  return { type: 'CUSTOM_CUBIC_BEZIER', easingFunctionCubicBezier: { x1, y1, x2, y2 } };
}

const degrees = (n, u) => (u === 'turn' ? n * 360 : u === 'rad' ? (n * 180) / Math.PI : n);

// "translate(1px, 2px) scale(1.1) rotate(5deg)" -> values per Figma field.
export function transformToFields(tf) {
  const out = {};
  let unit = null;
  const length = (s) => {
    const m = /^(-?[\d.]+)(px|%)?$/.exec(s.trim());
    if (!m) throw new Error(`length the bridge cannot translate: ${s} in "${tf}"`);
    const u = m[2] ?? (Number(m[1]) === 0 ? null : 'px');
    if (u && unit && u !== unit) throw new Error(`px and % mixed in "${tf}"`);
    if (u) unit = u;
    return Number(m[1]);
  };
  const re = /([a-zA-Z]+)\(([^)]*)\)/g;
  let rest = tf.trim();
  for (const [, fn, args] of tf.matchAll(re)) {
    const a = args.split(',').map((s) => s.trim());
    switch (fn) {
      case 'translate':
        out.TRANSLATION_X = length(a[0]);
        out.TRANSLATION_Y = a[1] !== undefined ? length(a[1]) : 0;
        break;
      case 'translateX': out.TRANSLATION_X = length(a[0]); break;
      case 'translateY': out.TRANSLATION_Y = length(a[0]); break;
      case 'scale':
        out.SCALE_X = Number(a[0]);
        out.SCALE_Y = a[1] !== undefined ? Number(a[1]) : Number(a[0]);
        break;
      case 'scaleX': out.SCALE_X = Number(a[0]); break;
      case 'scaleY': out.SCALE_Y = Number(a[0]); break;
      case 'rotate': {
        const m = /^(-?[\d.]+)(deg|turn|rad)?$/.exec(a[0]);
        if (!m) throw new Error(`rotation the bridge cannot translate: ${a[0]}`);
        // CSS turns clockwise for a positive angle; Figma, counter-clockwise.
        out.ROTATION = -degrees(Number(m[1]), m[2] ?? 'deg');
        break;
      }
      default:
        throw new Error(`transform function with no Figma field: ${fn}() in "${tf}"`);
    }
    rest = rest.replace(`${fn}(${args})`, '');
  }
  if (rest.trim() !== '' && rest.trim() !== 'none') throw new Error(`unrecognised transform: "${tf}"`);
  return { fields: out, unit };
}

const NEUTRAL = { TRANSLATION_X: 0, TRANSLATION_Y: 0, SCALE_X: 1, SCALE_Y: 1, ROTATION: 0, OPACITY: 1 };

export function toFigma(a, { layerPrefix = '', easings = {} } = {}) {
  const durS = a.durationMs / 1000;
  const delayS = (a.delayMs ?? 0) / 1000;
  const iter = a.iterations ?? 1;
  const loops = iter === 'infinite' ? 1 : iter;
  if (!Number.isInteger(loops) || loops < 1) throw new Error(`${a.name}: fractional iterations do not become keyframes`);
  let unit = null;
  const perFrame = a.frames.map((q) => {
    const v = {};
    if (q.transform !== undefined) {
      const t = transformToFields(q.transform);
      if (t.unit && unit && t.unit !== unit) throw new Error(`${a.name}: px and % mixed across frames`);
      unit = t.unit ?? unit;
      Object.assign(v, t.fields);
    }
    if (q.opacity !== undefined) v.OPACITY = q.opacity;
    return v;
  });
  const used = new Set(perFrame.flatMap((v) => Object.keys(v)));
  const seriesOf = (field) => perFrame.map((v) => v[field] ?? NEUTRAL[field]);
  // A scale that is uniform in every frame becomes a single track.
  if (used.has('SCALE_X') || used.has('SCALE_Y')) {
    const sx = seriesOf('SCALE_X');
    const sy = seriesOf('SCALE_Y');
    if (sx.every((v, i) => v === sy[i])) {
      used.delete('SCALE_X');
      used.delete('SCALE_Y');
      perFrame.forEach((v, i) => { v.SCALE_XY = sx[i]; });
      used.add('SCALE_XY');
    }
  }
  const curve = (i) => a.frames[i]?.easing ?? a.defaultEasing;
  const tracks = {};
  for (const field of [...used].sort()) {
    const series = perFrame.map((v) => v[field] ?? (field === 'SCALE_XY' ? 1 : NEUTRAL[field]));
    if (series.every((v) => v === series[0])) continue; // a constant track does not become keyframes
    const keyframes = [];
    for (let loop = 0; loop < loops; loop++) {
      a.frames.forEach((q, i) => {
        keyframes.push({
          timelinePosition: round(delayS + (loop + q.offset) * durS),
          value: { type: 'FLOAT', value: series[i] },
          // WAAPI: a frame's curve applies to the segment that STARTS at it.
          // Figma: a keyframe's curve applies to the segment that ENDS at it.
          ...(i > 0 ? { easing: easing(curve(i - 1)) } : {}),
        });
      });
    }
    tracks[field] = { keyframes };
  }
  const origin = a.origin ?? '50% 50%';
  const box = a.box ?? 'fill-box';
  const tokenName = (css) => {
    const v = css ?? 'linear';
    const found = Object.entries(easings).find(([, x]) => x === v);
    return found ? found[0] : v === 'linear' ? 'linear' : `NO TOKEN: ${v}`;
  };
  return {
    layer: `${layerPrefix}${a.name}`,
    animation: a.name,
    unit,
    // Figma rotates and scales around the node's visual centre.
    pivot: box === 'fill-box' && origin === '50% 50%' ? null : { box, origin },
    loopMode: iter === 'infinite' ? 'loop' : 'once',
    endS: round(delayS + loops * durS),
    tracks,
    tokens: [...new Set(a.frames.slice(0, -1).map((_, i) => tokenName(curve(i))))],
  };
}

function select(input, prefixes) {
  const list = input.animations.filter((a) => prefixes.length === 0 || prefixes.some((p) => a.name.startsWith(p)));
  if (list.length === 0) throw new Error(`no animation starts with ${prefixes.join(', ')}`);
  return list.map((a) => toFigma(a, input));
}

const bez = (x) => (x ? [x.x1, x.y1, x.x2, x.y2].map((n) => round(n, 3)).join(',') : '');

export function compare(readBack, expected, { tolS = 0.005, tolV = 0.01 } = {}) {
  const errors = [];
  for (const e of expected) {
    const readTracks = readBack[e.layer];
    if (!readTracks) {
      if (Object.keys(e.tracks).length > 0) errors.push(`${e.layer}: layer missing in Figma`);
      continue;
    }
    for (const field of new Set([...Object.keys(e.tracks), ...Object.keys(readTracks)])) {
      const want = e.tracks[field]?.keyframes;
      const got = readTracks[field]?.keyframes;
      if (!want || !got) {
        errors.push(`${e.layer}.${field}: ${want ? 'missing in Figma' : 'extra in Figma (not in the code)'}`);
        continue;
      }
      if (want.length !== got.length) {
        errors.push(`${e.layer}.${field}: ${got.length} keyframes in Figma, ${want.length} in the code`);
        continue;
      }
      want.forEach((k, i) => {
        const g = got[i];
        const where = `${e.layer}.${field}[${i}]`;
        if (Math.abs(g.timelinePosition - k.timelinePosition) > tolS)
          errors.push(`${where}: time ${g.timelinePosition}s != ${k.timelinePosition}s`);
        if (Math.abs(g.value.value - k.value.value) > tolV * Math.max(1, Math.abs(k.value.value)))
          errors.push(`${where}: value ${g.value.value} != ${k.value.value}`);
        if (i === 0) return;
        const ge = g.easing ?? { type: 'LINEAR' };
        const ke = k.easing ?? { type: 'LINEAR' };
        if (ge.type !== ke.type || bez(ge.easingFunctionCubicBezier) !== bez(ke.easingFunctionCubicBezier))
          errors.push(`${where}: easing ${ge.type}(${bez(ge.easingFunctionCubicBezier)}) != ${ke.type}(${bez(ke.easingFunctionCubicBezier)})`);
      });
    }
  }
  for (const layer of Object.keys(readBack))
    if (!expected.some((e) => e.layer === layer)) errors.push(`${layer}: in Figma with no animation in the code`);
  return errors;
}

export function main(args, read = (f) => readFileSync(f, 'utf8'), out = console.log) {
  const [command, file, ...rest] = args;
  if ((command !== 'export' && command !== 'compare') || !file) {
    out('usage: motion-figma.mjs export <animations.json> [prefix...] | compare <animations.json> <read-back.json> [prefix...]');
    return 2;
  }
  const input = JSON.parse(read(file));
  if (command === 'export') {
    out(JSON.stringify({ source: input.source ?? file, layers: select(input, rest) }, null, 2));
    return 0;
  }
  const [readFile, ...prefixes] = rest;
  if (!readFile) {
    out('usage: compare <animations.json> <read-back.json> [prefix...]');
    return 2;
  }
  const errors = compare(JSON.parse(read(readFile)), select(input, prefixes));
  if (errors.length === 0) {
    out('equal: Figma and code match');
    return 0;
  }
  out(`DIVERGES (${errors.length}):\n${errors.map((e) => `- ${e}`).join('\n')}`);
  return 1;
}

// By the REAL path: the skill is called through a link in ~/.claude/skills,
// and import.meta.url points at the real file.
const calledDirectly = () => {
  try {
    return import.meta.url === pathToFileURL(realpathSync(process.argv[1] ?? '')).href;
  } catch {
    return false;
  }
};
if (calledDirectly()) process.exitCode = main(process.argv.slice(2));
