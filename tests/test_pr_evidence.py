#!/usr/bin/env python3
"""Offline entry-point tests; no GitHub writes or real network."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/pr-evidence/scripts/pr_evidence.py'
SHA = 'a' * 40


def snapshot():
    return {'head': SHA, 'author': 'writer', 'reviews': [
        {'author': 'peer', 'head': SHA, 'state': 'APPROVED', 'sequence': 1}],
        'checks': [{'name': 'suite', 'head': SHA, 'status': 'COMPLETED', 'conclusion': 'SUCCESS'}],
        'threads': [], 'round': 1}


class ReviewTests(unittest.TestCase):
    def run_check(self, value, *extra):
        return subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), 'review', '-',
            '--reviewer', 'peer', '--check', 'suite', *extra], input=json.dumps(value),
            text=True, capture_output=True)

    def test_current_independent_review_is_ready(self):
        p = self.run_check(snapshot())
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertEqual(json.loads(p.stdout)['state'], 'READY')

    def test_author_cannot_approve_itself(self):
        s = snapshot(); s['author'] = 'peer'
        self.assertEqual(self.run_check(s).returncode, 1)

    def test_stale_approval_cannot_authorize_head(self):
        s = snapshot(); s['reviews'][0]['head'] = 'b' * 40
        self.assertEqual(self.run_check(s).returncode, 2)

    def test_untrusted_reviewer_cannot_authorize(self):
        s = snapshot(); s['reviews'][0]['author'] = 'stranger'
        self.assertEqual(self.run_check(s).returncode, 2)

    def test_later_changes_request_overrides_approval(self):
        s = snapshot(); r = copy.deepcopy(s['reviews'][0])
        r.update(sequence=2, state='CHANGES_REQUESTED'); s['reviews'].append(r)
        self.assertEqual(self.run_check(s).returncode, 1)
        s['reviews'].reverse()
        self.assertEqual(self.run_check(s).returncode, 1)

    def test_threads_and_checks_must_be_known_and_green(self):
        for field, value in [('threads', None), ('threads', [{'resolved': False}]), ('checks', [])]:
            s = snapshot(); s[field] = value
            self.assertEqual(self.run_check(s).returncode, 2, (field, value))
        for conclusion in ('FAILURE', 'CANCELLED', 'TIMED_OUT'):
            s = snapshot(); s['checks'][0]['conclusion'] = conclusion
            self.assertEqual(self.run_check(s).returncode, 1)
        for conclusion in ('SKIPPED', 'NEUTRAL', ''):
            s = snapshot(); s['checks'][0]['conclusion'] = conclusion
            self.assertEqual(self.run_check(s).returncode, 2)
        s = snapshot(); s['checks'][0]['head'] = 'b' * 40
        self.assertEqual(self.run_check(s).returncode, 2)

    def test_two_round_circuit_breaker(self):
        s = snapshot(); s['round'] = 3
        self.assertEqual(self.run_check(s).returncode, 1)

    def test_invalid_input_is_not_a_verdict(self):
        for s in ([], {'head': 'bad'}, dict(snapshot(), round=True)):
            self.assertEqual(self.run_check(s).returncode, 3)
        s = snapshot(); s['reviews'][0]['sequence'] = True
        self.assertEqual(self.run_check(s).returncode, 3)

    def test_template_headings_are_required_and_answered(self):
        with tempfile.TemporaryDirectory() as d:
            t = Path(d) / 'template.md'; b = Path(d) / 'body.md'
            t.write_text('## Summary\n<!-- instructions -->\n## Evidence\n')
            def run(body):
                b.write_text(body)
                return subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), 'template',
                    '--template', str(t), '--body', str(b)], capture_output=True, text=True)
            self.assertEqual(run('## Summary\nA change.\n## Evidence\nA command.\n').returncode, 0)
            self.assertEqual(run('## Summary\nA change.\n').returncode, 1)
            self.assertEqual(run('## Summary\nA change.\n## Evidence\n<!-- TODO -->').returncode, 1)
            self.assertEqual(run('## Summary\nA change.\n<!--\n## Evidence\nHidden answer.').returncode, 1)
            self.assertEqual(run('## Summary\n```html\n<!-- literal comment\n```\n## Evidence\nA real answer.').returncode, 0)
            self.assertEqual(run('## Summary\nA change.\n~~~md\n## Evidence\nA fake answer.\n~~~').returncode, 1)
            t.write_text('## Summary\n```md\n## Example only\n```\n')
            self.assertEqual(run('## Summary\nA real answer.\n').returncode, 0)

    def test_nested_sections_and_code_answers_are_not_empty(self):
        with tempfile.TemporaryDirectory() as d:
            t = Path(d) / 'template.md'; b = Path(d) / 'body.md'
            t.write_text('## Evidence\n### Command\n')
            b.write_text('## Evidence\n### Command\n```sh\npython3 tests/test_x.py\n```\n')
            p = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), 'template',
                '--template', str(t), '--body', str(b)], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_help_and_no_write_dependencies(self):
        p = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), '--help'], capture_output=True)
        self.assertEqual(p.returncode, 0)
        source = SCRIPT.read_text()
        self.assertNotIn('import subprocess', source)
        self.assertNotIn('import urllib', source)


if __name__ == '__main__':
    unittest.main()
