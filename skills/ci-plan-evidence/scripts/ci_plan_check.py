#!/usr/bin/env python3
"""Judge a recorded CI plan evidence envelope, never run Terraform or a cloud API.

Exit: 0 PR_READY, 1 BLOCKED, 2 PR_OPEN (missing/stale evidence), 3 invalid input.
This checks consistency, not authenticity. Collect JSON plans and metadata from
trusted CI artifacts; a person can forge a JSON file. See references/envelope.md.
"""
import argparse
import json
from pathlib import Path
import re
import sys

SHA = re.compile(r'^[0-9a-f]{40}$')
ACTIONS = {('no-op',), ('create',), ('read',), ('update',), ('delete',),
           ('delete', 'create'), ('create', 'delete'), ('forget',)}
FAILED = {'FAILURE', 'ERROR', 'TIMED_OUT', 'CANCELLED', 'ACTION_REQUIRED', 'STARTUP_FAILURE'}


def objects(data, key):
    value = data.get(key)
    if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
        raise ValueError(f'{key} must be a list of objects')
    return value


def judge(data, environments, actors, workflows, required_checks, allowed_loss):
    if not isinstance(data, dict) or not isinstance(data.get('head'), str) or not SHA.fullmatch(data['head']):
        raise ValueError('head must be a full lowercase commit SHA')
    checks, plans = objects(data, 'checks'), objects(data, 'plans')
    head = data['head']
    blocked, pending, losses = [], [], []
    for name in sorted(set(required_checks)):
        matches = [c for c in checks if c.get('name') == name and c.get('head') == head]
        if len(matches) != 1:
            pending.append(f'missing or ambiguous current check: {name}')
            continue
        c = matches[0]
        if c.get('conclusion') in FAILED:
            blocked.append(f'failed check: {name}')
        elif c.get('status') != 'COMPLETED' or c.get('conclusion') != 'SUCCESS':
            pending.append(f'check not successful: {name}')
    for c in checks:
        if c.get('head') == head and c.get('conclusion') in FAILED:
            reason = f'failed check: {c.get("name", "unknown")}'
            if reason not in blocked:
                blocked.append(reason)
    seen = set()
    for record in plans:
        env = record.get('environment')
        if not isinstance(env, str) or not env.strip() or '::' in env:
            raise ValueError('environment must be a nonempty label without the reserved :: delimiter')
        if env in seen:
            blocked.append(f'duplicate plan environment: {env}')
        seen.add(env)
        if record.get('head') != head or record.get('actor') not in actors or record.get('workflow') not in workflows:
            pending.append(f'{env}: stale or untrusted CI provenance')
            continue
        plan = record.get('plan')
        if record.get('complete') is not True or not isinstance(plan, dict):
            blocked.append(f'{env}: missing or truncated plan')
            continue
        if (not re.fullmatch(r'1\.\d+', str(plan.get('format_version', '')))
                or plan.get('errored', False) is not False
                or plan.get('complete', True) is not True or plan.get('deferred_changes')):
            blocked.append(f'{env}: errored, deferred or unsupported plan')
            continue
        changes = plan.get('resource_changes')
        if not isinstance(changes, list):
            blocked.append(f'{env}: resource_changes is missing or invalid')
            continue
        addresses = set()
        for resource in changes:
            if not isinstance(resource, dict):
                blocked.append(f'{env}: invalid resource change')
                continue
            address, change = resource.get('address'), resource.get('change')
            actions = change.get('actions') if isinstance(change, dict) else None
            if (not isinstance(address, str) or not address or address in addresses
                    or not isinstance(actions, list) or not all(isinstance(a, str) for a in actions)
                    or tuple(actions) not in ACTIONS):
                blocked.append(f'{env}: duplicate, unnamed or unsupported resource change')
                continue
            addresses.add(address)
            if 'delete' in actions or 'forget' in actions:
                losses.append({'environment': env, 'address': address, 'actions': actions})
                # Exact environment::address only: approval in dev cannot
                # silently authorize destruction of the same address in prod.
                if f'{env}::{address}' not in allowed_loss:
                    blocked.append(f'{env}: unapproved loss or replacement: {address}')
    for env in sorted(set(environments) - seen):
        pending.append(f'missing plan: {env}')
    if not plans:
        pending.append('no CI plan collected')
    state = 'BLOCKED' if blocked else 'PR_OPEN' if pending else 'PR_READY'
    return {'state': state, 'head': head, 'blocked': blocked, 'pending': pending, 'losses': losses}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('evidence', help='JSON envelope file or - for stdin')
    p.add_argument('--expect-env', action='append', required=True, help='required environment; repeatable')
    p.add_argument('--trusted-actor', action='append', required=True, help='CI actor read from repository policy')
    p.add_argument('--workflow', action='append', required=True, help='allowed CI workflow; repeatable')
    p.add_argument('--check', action='append', required=True, help='required check name; repeatable')
    p.add_argument('--allow-loss', action='append', default=[], help='exact environment::resource-address approved by the owner')
    args = p.parse_args()
    try:
        if any(not x.strip() for x in args.expect_env + args.trusted_actor + args.workflow + args.check):
            raise ValueError('policy names cannot be blank')
        raw = sys.stdin.read() if args.evidence == '-' else Path(args.evidence).read_text(encoding='utf-8')
        result = judge(json.loads(raw), args.expect_env, args.trusted_actor, args.workflow, args.check, args.allow_loss)
        print(json.dumps(result, sort_keys=True))
        return {'PR_READY': 0, 'BLOCKED': 1, 'PR_OPEN': 2}[result['state']]
    except (OSError, UnicodeError, ValueError, TypeError) as exc:
        print(f'INPUT_ERROR: {exc}', file=sys.stderr)
        return 3


if __name__ == '__main__':
    sys.exit(main())
