#!/usr/bin/env python3
"""Offline PR evidence checks, not an approval or a GitHub client.

Read a trusted API snapshot, not markers embedded in PR prose. The caller must
collect complete API data and establish reviewer authority independently.
Exit: 0 READY, 1 BLOCKED, 2 WAITING, 3 invalid input. No writes or network.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import unicodedata

SHA = re.compile(r'^[0-9a-f]{40}$')
FAILED = {'FAILURE', 'ERROR', 'TIMED_OUT', 'CANCELLED', 'ACTION_REQUIRED', 'STARTUP_FAILURE'}


def markdown_sections(text):
    """Headings outside comments and both fence dialects; nested text counts."""
    result, fence, stack, comment = {}, None, [], False
    for line in text.splitlines():
        if fence is None:
            visible = []
            while line:
                if comment:
                    end = line.find('-->')
                    if end < 0:
                        line = ''
                    else:
                        line, comment = line[end + 3:], False
                else:
                    start = line.find('<!--')
                    if start < 0:
                        visible.append(line)
                        break
                    visible.append(line[:start])
                    line, comment = line[start + 4:], True
            line = ''.join(visible)
        m = re.match(r'^\s{0,3}(`{3,}|~{3,})(.*)$', line)
        if m:
            marker = m.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence) and not m.group(2).strip():
                fence = None
            continue
        m = None if fence else re.match(r'^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$', line)
        if m:
            title = unicodedata.normalize('NFKC', m.group(2)).casefold().rstrip(':').strip()
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            result.setdefault(title, [])
        elif line.strip():
            for _, title in stack:
                result[title].append(line.strip())
    return result


def template_problems(template, body):
    required, actual = markdown_sections(template), markdown_sections(body)
    return [f'TEMPLATE_SECTION_MISSING: {name}' if name not in actual
            else f'TEMPLATE_SECTION_EMPTY: {name}'
            for name in required if not actual.get(name)]


def object_list(data, key, missing_ok=False):
    value = data.get(key)
    if value is None and missing_ok:
        return None
    if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
        raise ValueError(f'{key} must be a list of objects')
    return value


def check_checks(checks, head, required):
    blocked, pending = [], []
    for name in sorted(set(required)):
        matches = [c for c in checks if c.get('name') == name and c.get('head') == head]
        if not matches:
            pending.append(f'no current check: {name}')
            continue
        # Ambiguous reruns are not guessed: the collector supplies the current run.
        if len(matches) != 1:
            pending.append(f'ambiguous current check: {name}')
            continue
        c = matches[0]
        if c.get('conclusion') in FAILED:
            blocked.append(f'failed check: {name}')
        elif c.get('status') != 'COMPLETED' or c.get('conclusion') != 'SUCCESS':
            pending.append(f'check not successful: {name}')
    # A different reported failing job is still a failure, not something to hide
    # by choosing only a successful --check name.
    for c in checks:
        if c.get('head') == head and c.get('conclusion') in FAILED:
            reason = f'failed check: {c.get("name", "unknown")}'
            if reason not in blocked:
                blocked.append(reason)
    return blocked, pending


def review(data, reviewers, required):
    if not isinstance(data, dict) or not isinstance(data.get('head'), str) or not SHA.fullmatch(data['head']):
        raise ValueError('head must be a full lowercase commit SHA')
    if not isinstance(data.get('author'), str) or not data['author']:
        raise ValueError('author must be a login')
    rounds = data.get('round')
    if type(rounds) is not int or rounds < 1:
        raise ValueError('round must be a positive integer')
    reviews = object_list(data, 'reviews')
    checks = object_list(data, 'checks')
    threads = object_list(data, 'threads', missing_ok=True)
    blocked, pending = check_checks(checks, data['head'], required)
    if rounds > 2:
        blocked.append('two rounds exhausted: owner decision required')
    author = data['author'].casefold()
    reviewers = sorted({r.casefold() for r in reviewers})
    if author in reviewers:
        blocked.append('the author cannot supply independent approval')
    latest, sequences = {}, set()
    for r in reviews:
        if not isinstance(r.get('author'), str) or not r['author']:
            raise ValueError('every review needs an author login')
        seq = r.get('sequence')
        if type(seq) is not int or seq < 1 or seq in sequences:
            raise ValueError('review sequences must be unique positive integers from API order')
        sequences.add(seq)
        who = r['author'].casefold()
        if who not in reviewers or who == author:
            continue
        if who not in latest or seq > latest[who]['sequence']:
            latest[who] = r
    for who in reviewers:
        if who == author:
            continue
        r = latest.get(who)
        if r is None or r.get('head') != data['head']:
            pending.append(f'no current independent review: {who}')
        elif r.get('state') == 'CHANGES_REQUESTED':
            blocked.append(f'changes requested: {who}')
        elif r.get('state') != 'APPROVED':
            pending.append(f'review not approved: {who}')
    if threads is None:
        pending.append('review threads not collected')
    elif any(t.get('resolved') is not True for t in threads):
        pending.append('unresolved review threads')
    state = 'BLOCKED' if blocked else 'WAITING' if pending else 'READY'
    return {'state': state, 'head': data['head'], 'blocked': blocked, 'pending': pending}


def read(path):
    return sys.stdin.read() if path == '-' else Path(path).read_text(encoding='utf-8')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    t = sub.add_parser('template', help='check each repository template heading is answered')
    t.add_argument('--template', required=True)
    t.add_argument('--body', required=True)
    r = sub.add_parser('review', help='judge a complete trusted review snapshot; never post it')
    r.add_argument('snapshot', help='JSON file or - for stdin; see references/snapshot.md')
    r.add_argument('--reviewer', action='append', required=True, help='owner-designated reviewer login')
    r.add_argument('--check', action='append', required=True, help='required check name; repeatable')
    args = p.parse_args()
    try:
        if args.command == 'template':
            problems = template_problems(read(args.template), read(args.body))
            print(json.dumps({'state': 'BLOCKED' if problems else 'READY', 'problems': problems}))
            return 1 if problems else 0
        if any(not x.strip() for x in args.reviewer + args.check):
            raise ValueError('reviewer and check names cannot be blank')
        result = review(json.loads(read(args.snapshot)), args.reviewer, args.check)
        print(json.dumps(result, sort_keys=True))
        return {'READY': 0, 'BLOCKED': 1, 'WAITING': 2}[result['state']]
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        print(f'INPUT_ERROR: {exc}', file=sys.stderr)
        return 3


if __name__ == '__main__':
    sys.exit(main())
