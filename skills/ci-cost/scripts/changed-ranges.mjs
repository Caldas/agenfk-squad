#!/usr/bin/env node
// The changed LINES of a branch, as StrykerJS `--mutate` entries.
//
//   node changed-ranges.mjs <merge-base> <file>...
//
// Prints one entry per line: `path:start-end` for each changed hunk of a modified file, or the bare
// `path` for a file the branch added (all of it is new). `mutation-since.sh` joins them with commas.
//
// Why lines and not files: a PR mutation job that mutates every line of every changed FILE makes a
// three-line fix in a 900-line service pay for the other 897 lines' mutants. Measured on a real
// project: 322 mutants / 252 s for a 3-line change, 10 mutants / 75 s once scoped to the lines. The
// question the PR gate answers is "is the code THIS branch wrote tested?"; the lines it did not touch
// are a scheduled full run's job.
//
// Stryker 10 reads `file:start-end` (1-based, inclusive) in `--mutate` — `MUTATION_RANGE_REGEX` in
// @stryker-mutator/core `dist/src/fs/project-reader.js` — unions several ranges on one file, and
// still lets a later `!glob` drop the whole file. A mutant is placed only when its node lies wholly
// inside a range (`locationIncluded` in the instrumenter's babel-transformer), so a mutant that spans
// unchanged lines too, such as a whole-function block mutant, is not this gate's business.
//
// A hunk that only REMOVES lines (`+c,0`) still yields a range: lines c..c+1 of the new file, the
// code on both sides of the cut. Deleting a guard is a change, and the code it guarded is what a
// test has to notice.
//
// Plain Node, no dependencies, so it can run in a CI job that pays for no install.

import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const HUNK = /^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@/;

/**
 * Turns `git diff -U0` output into `{ file -> 'whole' | [{ start, end }] }`, 1-based inclusive.
 * Files whose diff carries no hunk (a pure rename, a mode change) are absent: nothing to mutate.
 */
export function parseDiff(text) {
  const files = new Map();
  let current = null;
  let added = false;
  // `---`/`+++` are file headers only before a file's first hunk: inside a hunk, a removed line
  // that read `-- x` or an added one that read `++ x` looks exactly like them. (`diff --git` and
  // `@@` cannot be content: every content line starts with `+`, `-`, a space or `\`.)
  let inHeader = false;
  for (const line of text.split('\n')) {
    const match = HUNK.exec(line);
    if (line.startsWith('diff --git ')) {
      current = null;
      added = false;
      inHeader = true;
    } else if (match) {
      inHeader = false;
      if (!current || files.get(current) === 'whole') continue;
      const start = Number(match[1]);
      const count = match[2] === undefined ? 1 : Number(match[2]);
      const range =
        count === 0
          ? { start: Math.max(1, start), end: start + 1 }
          : { start, end: start + count - 1 };
      const ranges = files.get(current) ?? [];
      ranges.push(range);
      files.set(current, ranges);
    } else if (inHeader && line.startsWith('--- ')) {
      added = line === '--- /dev/null';
    } else if (inHeader && line.startsWith('+++ ')) {
      const target = line.slice(4);
      current = target === '/dev/null' ? null : target.replace(/^b\//, '');
      if (current && added) files.set(current, 'whole');
    }
  }
  for (const [file, ranges] of files) {
    if (ranges !== 'whole') files.set(file, mergeRanges(ranges));
  }
  return files;
}

/** Sorts and merges overlapping or touching ranges, so Stryker gets the shortest list. */
export function mergeRanges(ranges) {
  const sorted = [...ranges].sort((a, b) => a.start - b.start);
  const merged = [];
  for (const range of sorted) {
    const last = merged.at(-1);
    if (last && range.start <= last.end + 1) last.end = Math.max(last.end, range.end);
    else merged.push({ ...range });
  }
  return merged;
}

/** `{ file -> ranges }` → Stryker `--mutate` entries, in the order the files were given. */
export function toMutateEntries(files) {
  const entries = [];
  for (const [file, ranges] of files) {
    if (ranges === 'whole') entries.push(file);
    else for (const { start, end } of ranges) entries.push(`${file}:${start}-${end}`);
  }
  return entries;
}

export function main(argv, run = execFileSync) {
  const [base, ...paths] = argv;
  if (!base || paths.length === 0) {
    process.stderr.write('usage: changed-ranges.mjs <merge-base> <file>...\n');
    return 2;
  }
  const diff = run(
    'git',
    [
      '-c',
      'core.quotePath=false',
      'diff',
      '-U0',
      '--no-color',
      '--diff-filter=d',
      base,
      'HEAD',
      '--',
      ...paths,
    ],
    { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 },
  );
  const entries = toMutateEntries(parseDiff(diff));
  if (entries.length > 0) process.stdout.write(`${entries.join('\n')}\n`);
  return 0;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  process.exitCode = main(process.argv.slice(2));
}
