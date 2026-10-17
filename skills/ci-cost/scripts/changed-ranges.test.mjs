#!/usr/bin/env node
// Tests for the changed-lines helper behind `mutation-since.sh`.
//   node --test changed-ranges.test.mjs
//
// Node's own runner, no install. Run it in CI with a floor on the pass count: `node --test` exits 0
// on a file with ZERO tests. The `main` block drives a real throwaway git repository, because a
// parser fed hand-written diffs can agree with itself and still disagree with git.

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, describe, test } from 'node:test';

import { main, mergeRanges, parseDiff, toMutateEntries } from './changed-ranges.mjs';

const diff = (...lines) => lines.join('\n');
const modified = (file, ...hunks) =>
  diff(
    `diff --git a/${file} b/${file}`,
    'index 1111111..2222222 100644',
    `--- a/${file}`,
    `+++ b/${file}`,
    ...hunks,
  );

describe('parseDiff', () => {
  test('a hunk with a count covers start..start+count-1', () => {
    const files = parseDiff(modified('a.ts', '@@ -10,2 +12,3 @@ fn()', '+x', '+y', '+z'));
    assert.deepEqual(files.get('a.ts'), [{ start: 12, end: 14 }]);
  });

  test('a hunk without a count is one line', () => {
    const files = parseDiff(modified('a.ts', '@@ -7 +7 @@', '-old', '+new'));
    assert.deepEqual(files.get('a.ts'), [{ start: 7, end: 7 }]);
  });

  test('a removed-lines-only hunk still yields the lines around the cut', () => {
    const files = parseDiff(modified('a.ts', '@@ -20,3 +19,0 @@', '-a', '-b', '-c'));
    assert.deepEqual(files.get('a.ts'), [{ start: 19, end: 20 }]);
  });

  test('a removal at the top of the file clamps to line 1', () => {
    const files = parseDiff(modified('a.ts', '@@ -1,2 +0,0 @@', '-a', '-b'));
    assert.deepEqual(files.get('a.ts'), [{ start: 1, end: 1 }]);
  });

  test('several hunks in one file are kept apart when they do not touch', () => {
    const files = parseDiff(modified('a.ts', '@@ -3 +3 @@', '@@ -40,0 +41,2 @@', '+p', '+q'));
    assert.deepEqual(files.get('a.ts'), [
      { start: 3, end: 3 },
      { start: 41, end: 42 },
    ]);
  });

  test('an added file is mutated whole', () => {
    const text = diff(
      'diff --git a/n.ts b/n.ts',
      'new file mode 100644',
      '--- /dev/null',
      '+++ b/n.ts',
      '@@ -0,0 +1,3 @@',
      '+a',
      '+b',
      '+c',
    );
    assert.equal(parseDiff(text).get('n.ts'), 'whole');
  });

  test('a file whose diff has no hunk (pure rename, mode change) is absent', () => {
    const text = diff(
      'diff --git a/x.ts b/y.ts',
      'similarity index 100%',
      'rename from x.ts',
      'rename to y.ts',
    );
    assert.equal(parseDiff(text).size, 0);
  });

  test('a renamed and edited file is keyed by its new path', () => {
    const text = diff(
      'diff --git a/x.ts b/y.ts',
      'similarity index 90%',
      'rename from x.ts',
      'rename to y.ts',
      '--- a/x.ts',
      '+++ b/y.ts',
      '@@ -5 +5 @@',
    );
    assert.deepEqual([...parseDiff(text).keys()], ['y.ts']);
  });

  test('a deleted file contributes nothing', () => {
    const text = diff(
      'diff --git a/d.ts b/d.ts',
      'deleted file mode 100644',
      '--- a/d.ts',
      '+++ /dev/null',
      '@@ -1,2 +0,0 @@',
    );
    assert.equal(parseDiff(text).size, 0);
  });

  test('two files keep their own ranges and their order', () => {
    const text = diff(modified('a.ts', '@@ -1 +1 @@'), modified('b.ts', '@@ -9,0 +10,1 @@'));
    const files = parseDiff(text);
    assert.deepEqual([...files.keys()], ['a.ts', 'b.ts']);
    assert.deepEqual(files.get('b.ts'), [{ start: 10, end: 10 }]);
  });

  test('a hunk-looking line outside any file is ignored', () => {
    assert.equal(parseDiff('@@ -1 +1 @@').size, 0);
  });

  test('a changed line that reads "-- x" or "++ x" is content, not a file header', () => {
    // An SQL comment inside a template string, removed and added: `--- ` and `+++ ` in the diff.
    const text = diff(
      modified('q.ts', '@@ -4 +4 @@', '--- old note', '+++ new note', '@@ -9 +9 @@', '-a', '+b'),
      modified('r.ts', '@@ -2 +2 @@'),
    );
    const files = parseDiff(text);
    assert.deepEqual([...files.keys()], ['q.ts', 'r.ts']);
    assert.deepEqual(files.get('q.ts'), [
      { start: 4, end: 4 },
      { start: 9, end: 9 },
    ]);
  });

  test('an added file whose content holds "++ x" stays one whole file', () => {
    const text = diff(
      'diff --git a/n.ts b/n.ts',
      'new file mode 100644',
      '--- /dev/null',
      '+++ b/n.ts',
      '@@ -0,0 +1,2 @@',
      '+++ not a header',
      '+x',
    );
    assert.deepEqual([...parseDiff(text)], [['n.ts', 'whole']]);
  });
});

describe('mergeRanges', () => {
  test('overlapping ranges merge', () => {
    assert.deepEqual(
      mergeRanges([
        { start: 5, end: 9 },
        { start: 1, end: 6 },
      ]),
      [{ start: 1, end: 9 }],
    );
  });

  test('touching ranges merge', () => {
    assert.deepEqual(
      mergeRanges([
        { start: 1, end: 4 },
        { start: 5, end: 6 },
      ]),
      [{ start: 1, end: 6 }],
    );
  });

  test('a gap of one line keeps them apart', () => {
    assert.deepEqual(
      mergeRanges([
        { start: 1, end: 4 },
        { start: 6, end: 6 },
      ]),
      [
        { start: 1, end: 4 },
        { start: 6, end: 6 },
      ],
    );
  });

  test('a range inside another keeps the outer end', () => {
    assert.deepEqual(
      mergeRanges([
        { start: 1, end: 20 },
        { start: 3, end: 4 },
      ]),
      [{ start: 1, end: 20 }],
    );
  });

  test('the input is not mutated', () => {
    const input = [
      { start: 1, end: 2 },
      { start: 3, end: 4 },
    ];
    mergeRanges(input);
    assert.deepEqual(input, [
      { start: 1, end: 2 },
      { start: 3, end: 4 },
    ]);
  });
});

describe('toMutateEntries', () => {
  test('ranges become file:start-end and a whole file stays bare', () => {
    const files = new Map([
      [
        'a.ts',
        [
          { start: 2, end: 2 },
          { start: 8, end: 11 },
        ],
      ],
      ['n.ts', 'whole'],
    ]);
    assert.deepEqual(toMutateEntries(files), ['a.ts:2-2', 'a.ts:8-11', 'n.ts']);
  });

  test('every entry matches the range syntax Stryker 10 parses', () => {
    // MUTATION_RANGE_REGEX from @stryker-mutator/core dist/src/fs/project-reader.js.
    const STRYKER = /(.*?):((\d+)(?::(\d+))?-(\d+)(?::(\d+))?)$/;
    for (const entry of toMutateEntries(
      parseDiff(modified('src/x.ts', '@@ -4,0 +4,0 @@', '@@ -9,2 +9,3 @@')),
    )) {
      const match = STRYKER.exec(entry);
      assert.ok(match, entry);
      assert.equal(match[1], 'src/x.ts');
      assert.ok(Number(match[3]) >= 1 && Number(match[3]) <= Number(match[5]), entry);
    }
  });
});

describe('main', () => {
  test('without a base or files it refuses with 2', () => {
    assert.equal(main([]), 2);
    assert.equal(main(['HEAD']), 2);
  });

  const repo = mkdtempSync(join(tmpdir(), 'changed-ranges-'));
  after(() => rmSync(repo, { recursive: true, force: true }));
  const git = (...args) =>
    execFileSync(
      'git',
      [
        '-C',
        repo,
        '-c',
        'user.name=t',
        '-c',
        'user.email=t@t',
        '-c',
        'commit.gpgsign=false',
        ...args,
      ],
      {
        encoding: 'utf8',
      },
    );
  const lines = (n, mark = '') =>
    Array.from({ length: n }, (_, i) => `const v${i + 1} = ${i + 1};${mark}`).join('\n') + '\n';

  test('a real branch: an edit, a removal and a new file', () => {
    git('init', '-q', '-b', 'main');
    writeFileSync(join(repo, 'big.ts'), lines(100));
    writeFileSync(join(repo, 'cut.ts'), lines(10));
    git('add', '.');
    git('commit', '-q', '-m', 'base');
    const base = git('rev-parse', 'HEAD').trim();

    const big = lines(100).split('\n');
    big[49] = 'const v50 = 5000;';
    big[50] = 'const v51 = 5100;';
    big[51] = 'const v52 = 5200;';
    writeFileSync(join(repo, 'big.ts'), big.join('\n'));
    const cut = lines(10).split('\n');
    cut.splice(4, 2);
    writeFileSync(join(repo, 'cut.ts'), cut.join('\n'));
    writeFileSync(join(repo, 'fresh.ts'), lines(3));
    git('add', '.');
    git('commit', '-q', '-m', 'branch');

    const run = (cmd, args, opts) => execFileSync(cmd, args, { ...opts, cwd: repo });
    const written = [];
    const original = process.stdout.write.bind(process.stdout);
    process.stdout.write = (chunk) => (written.push(String(chunk)), true);
    let code;
    try {
      code = main([base, 'big.ts', 'cut.ts', 'fresh.ts'], run);
    } finally {
      process.stdout.write = original;
    }
    assert.equal(code, 0);
    assert.deepEqual(written.join('').trim().split('\n').sort(), [
      'big.ts:50-52',
      'cut.ts:4-5',
      'fresh.ts',
    ]);
  });

  test('a real branch: a non-ASCII path comes back as written, not git-quoted', () => {
    // Without core.quotePath=false git prints "caf\303\251.ts" in quotes, which Stryker cannot match.
    const dir = mkdtempSync(join(tmpdir(), 'changed-ranges-utf8-'));
    try {
      const g = (...args) =>
        execFileSync(
          'git',
          [
            '-C',
            dir,
            '-c',
            'user.name=t',
            '-c',
            'user.email=t@t',
            '-c',
            'commit.gpgsign=false',
            ...args,
          ],
          { encoding: 'utf8' },
        );
      g('init', '-q', '-b', 'main');
      writeFileSync(join(dir, 'café.ts'), lines(5));
      g('add', '.');
      g('commit', '-q', '-m', 'base');
      const base = g('rev-parse', 'HEAD').trim();
      writeFileSync(join(dir, 'café.ts'), lines(5).replace('const v3 = 3;', 'const v3 = 30;'));
      g('commit', '-q', '-am', 'branch');

      const run = (cmd, args, opts) => execFileSync(cmd, args, { ...opts, cwd: dir });
      const written = [];
      const original = process.stdout.write.bind(process.stdout);
      process.stdout.write = (chunk) => (written.push(String(chunk)), true);
      try {
        assert.equal(main([base, 'café.ts'], run), 0);
      } finally {
        process.stdout.write = original;
      }
      assert.deepEqual(written.join('').trim().split('\n'), ['café.ts:3-3']);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
