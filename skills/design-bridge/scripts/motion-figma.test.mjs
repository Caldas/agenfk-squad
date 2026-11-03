#!/usr/bin/env node
// Tests for the code <-> Figma motion bridge.
//   node --test motion-figma.test.mjs
//
// `node --test` exits 0 with ZERO tests: tests/test_design_bridge.py enforces a count floor.

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { compare, easing, main, toFigma, transformToFields } from './motion-figma.mjs';

const anim = (over = {}) => ({
  name: 'a',
  durationMs: 1000,
  iterations: 1,
  delayMs: 0,
  frames: [
    { offset: 0, opacity: 0, transform: 'translate(0px, 10px) scale(0.9) rotate(0deg)', easing: 'cubic-bezier(.2,.8,.2,1)' },
    { offset: 0.5, opacity: 1, transform: 'translate(0px, 0px) scale(1) rotate(10deg)', easing: 'ease-out' },
    { offset: 1, opacity: 1, transform: 'translate(0px, 0px) scale(1) rotate(10deg)' },
  ],
  ...over,
});
const kf = (layer, field) => layer.tracks[field].keyframes;

describe('easing', () => {
  test('linear and absent become LINEAR', () => {
    assert.deepEqual(easing('linear'), { type: 'LINEAR' });
    assert.deepEqual(easing(undefined), { type: 'LINEAR' });
  });
  test('cubic-bezier becomes CUSTOM_CUBIC_BEZIER with the four points', () => {
    assert.deepEqual(easing('cubic-bezier(.17, .85, .28, 1.12)').easingFunctionCubicBezier, { x1: 0.17, y1: 0.85, x2: 0.28, y2: 1.12 });
  });
  test('CSS named curves use the specification definition', () => {
    assert.deepEqual(easing('ease-out').easingFunctionCubicBezier, { x1: 0, y1: 0, x2: 0.58, y2: 1 });
  });
  test('step-start becomes HOLD', () => assert.deepEqual(easing('step-start'), { type: 'HOLD' }));
  test('an unknown curve fails loudly instead of turning linear', () => assert.throws(() => easing('spring(1)'), /cannot translate/));
});

describe('transformToFields', () => {
  test('a positive CSS rotation (clockwise) becomes negative in Figma', () => {
    assert.equal(transformToFields('rotate(30deg)').fields.ROTATION, -30);
    assert.equal(transformToFields('rotate(0.25turn)').fields.ROTATION, -90);
  });
  test('translate with a single coordinate has Y zero; the unit is read', () => {
    assert.deepEqual(transformToFields('translate(12%)'), { fields: { TRANSLATION_X: 12, TRANSLATION_Y: 0 }, unit: '%' });
  });
  test('px and % in the same transform fail', () => assert.throws(() => transformToFields('translate(1px, 2%)'), /mixed/));
  test('a function with no Figma field fails', () => assert.throws(() => transformToFields('skewX(10deg)'), /no Figma field/));
});

describe('toFigma', () => {
  test('the curve of the frame that STARTS a segment goes to the keyframe that ENDS it', () => {
    const c = toFigma(anim());
    const o = kf(c, 'OPACITY');
    assert.equal(o[0].easing, undefined);
    assert.deepEqual(o[1].easing.easingFunctionCubicBezier, { x1: 0.2, y1: 0.8, x2: 0.2, y2: 1 });
    assert.deepEqual(o[2].easing.easingFunctionCubicBezier, { x1: 0, y1: 0, x2: 0.58, y2: 1 });
  });
  test('time in seconds from the offset', () => {
    assert.deepEqual(kf(toFigma(anim()), 'OPACITY').map((k) => k.timelinePosition), [0, 0.5, 1]);
  });
  test('a constant track does not become keyframes', () => {
    const c = toFigma(anim());
    assert.equal(c.tracks.TRANSLATION_X, undefined);
    assert.ok(c.tracks.TRANSLATION_Y);
  });
  test('a uniform scale becomes SCALE_XY; a non-uniform one becomes SCALE_X and SCALE_Y', () => {
    assert.ok(toFigma(anim()).tracks.SCALE_XY);
    const q = [{ offset: 0, transform: 'scale(1, 1)' }, { offset: 1, transform: 'scale(2, 1.5)' }];
    const c = toFigma(anim({ frames: q }));
    assert.equal(c.tracks.SCALE_XY, undefined);
    assert.deepEqual(kf(c, 'SCALE_X').map((k) => k.value.value), [1, 2]);
    assert.deepEqual(kf(c, 'SCALE_Y').map((k) => k.value.value), [1, 1.5]);
  });
  test('finite iterations are unrolled after the delay', () => {
    const c = toFigma(anim({ iterations: 2, delayMs: 500 }));
    assert.deepEqual(kf(c, 'OPACITY').map((k) => k.timelinePosition), [0.5, 1, 1.5, 1.5, 2, 2.5]);
    assert.equal(c.endS, 2.5);
    assert.equal(c.loopMode, 'once');
  });
  test('infinite is one cycle with loopMode loop', () => {
    const c = toFigma(anim({ iterations: 'infinite' }));
    assert.equal(c.loopMode, 'loop');
    assert.equal(kf(c, 'OPACITY').length, 3);
  });
  test('an off-centre origin marks the pivot; a centred one does not', () => {
    assert.equal(toFigma(anim()).pivot, null);
    assert.deepEqual(toFigma(anim({ origin: '50% 100%' })).pivot, { box: 'fill-box', origin: '50% 100%' });
  });
  test('layer prefix and easing token name', () => {
    const c = toFigma(anim(), { layerPrefix: 'ui-', easings: { 'brand/standard': 'cubic-bezier(.2,.8,.2,1)' } });
    assert.equal(c.layer, 'ui-a');
    assert.deepEqual(c.tokens, ['brand/standard', 'NO TOKEN: ease-out']);
  });
  test('px in one frame and % in another fail', () => {
    const q = [{ offset: 0, transform: 'translate(1px, 0px)' }, { offset: 1, transform: 'translate(1%, 0%)' }];
    assert.throws(() => toFigma(anim({ frames: q })), /mixed/);
  });
});

describe('compare', () => {
  const expected = toFigma(anim(), { layerPrefix: 'ui-' });
  const sameRead = () => JSON.parse(JSON.stringify({ [expected.layer]: expected.tracks }));
  test('an equal read-back does not diverge', () => assert.deepEqual(compare(sameRead(), [expected]), []));
  test('value, easing and an extra layer are reported', () => {
    const read = sameRead();
    read['ui-a'].OPACITY.keyframes[1].value.value = 0.5;
    read['ui-a'].OPACITY.keyframes[2].easing = { type: 'EASE_OUT' };
    read['ui-intruder'] = {};
    const errors = compare(read, [expected]);
    assert.equal(errors.length, 3);
    assert.match(errors.join('\n'), /value 0\.5/);
    assert.match(errors.join('\n'), /easing EASE_OUT/);
    assert.match(errors.join('\n'), /ui-intruder: in Figma with no animation/);
  });
  test('a different easing type with no curve (LINEAR x HOLD) diverges', () => {
    const q = [{ offset: 0, opacity: 0 }, { offset: 1, opacity: 1 }];
    const linear = toFigma(anim({ frames: q }));
    const read = { a: JSON.parse(JSON.stringify(linear.tracks)) };
    read.a.OPACITY.keyframes[1].easing = { type: 'HOLD' };
    assert.match(compare(read, [linear]).join(), /easing HOLD\(\) != LINEAR\(\)/);
  });
  test('a missing track and a missing layer are reported', () => {
    const read = sameRead();
    delete read['ui-a'].OPACITY;
    assert.match(compare(read, [expected]).join(), /OPACITY: missing in Figma/);
    assert.match(compare({}, [expected]).join(), /layer missing/);
  });
  test('a difference within tolerance passes', () => {
    const read = sameRead();
    read['ui-a'].OPACITY.keyframes[1].timelinePosition += 0.001;
    assert.deepEqual(compare(read, [expected]), []);
  });
});

describe('main', () => {
  const files = {
    'a.json': JSON.stringify({ layerPrefix: 'ui-', animations: [anim()] }),
    'equal.json': JSON.stringify({ 'ui-a': toFigma(anim()).tracks }),
  };
  const read = (f) => files[f];
  const run = (...args) => {
    const lines = [];
    return { code: main(args, read, (l) => lines.push(l)), output: lines.join('\n') };
  };
  test('export exits 0 with the layers', () => {
    const r = run('export', 'a.json');
    assert.equal(r.code, 0);
    assert.equal(JSON.parse(r.output).layers[0].layer, 'ui-a');
  });
  test('compare equal exits 0; a prefix with no animation fails', () => {
    assert.equal(run('compare', 'a.json', 'equal.json').code, 0);
    assert.throws(() => run('export', 'a.json', 'zzz'), /no animation/);
  });
  test('wrong usage exits 2', () => assert.equal(run('other').code, 2));
});
