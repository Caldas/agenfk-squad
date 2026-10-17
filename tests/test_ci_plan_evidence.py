#!/usr/bin/env python3
"""Check recorded CI evidence, never Terraform or a cloud account."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/ci-plan-evidence/scripts/ci_plan_check.py'
SHA = 'a' * 40


def evidence(actions=None):
    changes = [] if actions is None else [{'address': 'aws_s3_bucket.data', 'change': {'actions': actions}}]
    return {'head': SHA, 'checks': [
        {'name': 'plan', 'head': SHA, 'status': 'COMPLETED', 'conclusion': 'SUCCESS'}],
        'plans': [{'environment': 'dev', 'head': SHA, 'actor': 'trusted-bot',
                   'workflow': 'plan.yml', 'complete': True,
                   'plan': {'format_version': '1.2', 'resource_changes': changes}}]}


class PlanTests(unittest.TestCase):
    def run_check(self, data, *extra):
        return subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), '-',
            '--expect-env', 'dev', '--trusted-actor', 'trusted-bot', '--workflow', 'plan.yml',
            '--check', 'plan', *extra], input=json.dumps(data), text=True, capture_output=True)

    def test_current_empty_or_additive_plan(self):
        for actions in (None, ['create'], ['update'], ['read'], ['no-op']):
            p = self.run_check(evidence(actions))
            self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
            self.assertEqual(json.loads(p.stdout)['state'], 'PR_READY')

    def test_loss_and_replacement_need_exact_approval(self):
        for actions in (['delete'], ['delete', 'create'], ['create', 'delete'], ['forget']):
            self.assertEqual(self.run_check(evidence(actions)).returncode, 1)
            p = self.run_check(evidence(actions), '--allow-loss', 'dev::aws_s3_bucket.data')
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertEqual(self.run_check(evidence(actions), '--allow-loss', '*').returncode, 1)

    def test_approval_is_scoped_to_environment(self):
        s = evidence(['delete'])
        prod = copy.deepcopy(s['plans'][0]); prod['environment'] = 'prod'
        s['plans'].append(prod)
        p = self.run_check(s, '--expect-env', 'prod', '--allow-loss', 'dev::aws_s3_bucket.data')
        self.assertEqual(p.returncode, 1)
        self.assertIn('prod: unapproved loss', p.stdout)
        p = self.run_check(s, '--expect-env', 'prod', '--allow-loss', 'dev::aws_s3_bucket.data',
                           '--allow-loss', 'prod::aws_s3_bucket.data')
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_stale_untrusted_and_missing_are_not_ready(self):
        for key, value in [('head', 'b' * 40), ('actor', 'another[bot]'), ('workflow', 'other.yml')]:
            s = evidence(); s['plans'][0][key] = value
            self.assertEqual(self.run_check(s).returncode, 2, (key, value))
        s = evidence(); s['plans'] = []
        self.assertEqual(self.run_check(s).returncode, 2)
        self.assertEqual(self.run_check(evidence(), '--expect-env', 'prod').returncode, 2)

    def test_failed_pending_skipped_or_stale_checks(self):
        for key, value, code in [('conclusion', 'FAILURE', 1), ('conclusion', 'CANCELLED', 1),
                                 ('conclusion', 'SKIPPED', 2), ('status', 'IN_PROGRESS', 2),
                                 ('head', 'b' * 40, 2)]:
            s = evidence(); s['checks'][0][key] = value
            self.assertEqual(self.run_check(s).returncode, code, (key, value))
        s = evidence(); s['checks'] = []
        self.assertEqual(self.run_check(s).returncode, 2)

    def test_incomplete_errored_deferred_or_unknown_plan_blocks(self):
        for key, value in [('complete', False), ('complete', 'true')]:
            s = evidence(); s['plans'][0][key] = value
            self.assertEqual(self.run_check(s).returncode, 1)
        for key, value in [('errored', True), ('complete', False), ('deferred_changes', [{'x': 1}]),
                           ('resource_changes', None), ('format_version', '2.0')]:
            s = evidence(); s['plans'][0]['plan'][key] = value
            self.assertEqual(self.run_check(s).returncode, 1, (key, value))
        self.assertEqual(self.run_check(evidence(['future-action'])).returncode, 1)

    def test_environment_cannot_alias_an_approval_key(self):
        s = evidence(['delete']); s['plans'][0]['environment'] = 'a::b'
        self.assertEqual(self.run_check(s, '--allow-loss', 'a::b::aws_s3_bucket.data').returncode, 3)

    def test_duplicate_environment_or_resource_blocks(self):
        s = evidence(); s['plans'].append(copy.deepcopy(s['plans'][0]))
        self.assertEqual(self.run_check(s).returncode, 1)
        s = evidence(['delete']); change = copy.deepcopy(s['plans'][0]['plan']['resource_changes'][0])
        s['plans'][0]['plan']['resource_changes'].append(change)
        self.assertEqual(self.run_check(s, '--allow-loss', 'dev::aws_s3_bucket.data').returncode, 1)

    def test_missing_address_or_actions_blocks(self):
        for change in ({}, {'address': 'x'}, {'address': 'x', 'change': {'actions': []}}):
            s = evidence(); s['plans'][0]['plan']['resource_changes'] = [change]
            self.assertEqual(self.run_check(s).returncode, 1)

    def test_invalid_input_and_help(self):
        for data in ([], {'head': 'short'}, dict(evidence(), plans='wrong')):
            self.assertEqual(self.run_check(data).returncode, 3)
        p = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), '--help'], capture_output=True)
        self.assertEqual(p.returncode, 0)
        source = SCRIPT.read_text()
        self.assertNotIn('import subprocess', source)
        self.assertNotIn('import urllib', source)


if __name__ == '__main__':
    unittest.main()
