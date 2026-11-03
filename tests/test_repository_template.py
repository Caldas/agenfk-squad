#!/usr/bin/env python3
"""The gate the hook already runs also requires the repository template's headings.

Template parsing (fences, comments, nested headings, empty answers) is covered by
tests/test_pr_evidence.py. This file covers what only pull-request owns: the
wiring through `check()`, the refusal to read a template it should not trust, the
missing-helper failure, and the real hook on Bash and MCP.

    python3 tests/test_repository_template.py
"""
import ast
import importlib.util
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.dont_write_bytecode = True  # the skill lives in a versioned repo: no __pycache__
ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/pull-request/scripts/pr_check.py'
HOOK = ROOT / 'skills/pull-request/hooks/pr_gate.py'
spec = importlib.util.spec_from_file_location('bundle_pr_check', SCRIPT)
gate = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = gate
spec.loader.exec_module(gate)


class TemplateGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name) / 'repo'
        self.repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        (self.repo / '.github').mkdir()
        self.template = self.repo / '.github/PULL_REQUEST_TEMPLATE.md'
        self.template.write_text('## Rollback plan\n')

    def codes(self, body):
        return {p.code for p in gate.repository_template_problems(body, self.repo)}

    def test_missing_heading_cannot_pass_the_existing_check(self):
        """check(), the entry point the hook and the CLI call, must carry the repository template's
        TEMPLATE_SECTION_MISSING; a check() that only runs the squad body rules would let the repo's own
        headings go unenforced."""
        problems = gate.check('## Tests\nA result.\n', repo=self.repo, files=[], lang='en')[0]
        self.assertIn('TEMPLATE_SECTION_MISSING', {p.code for p in problems})

    def test_external_symlink_is_not_read(self):
        """A template that is a symlink out of the repo (to any file on the machine) is refused as
        TEMPLATE_UNREADABLE, never read: the repo does not get to point the gate at a file outside itself."""
        self.template.unlink()
        outside = Path(self.tmp.name) / 'private.md'
        outside.write_text('## Private\n')
        self.template.symlink_to(outside)
        self.assertEqual(self.codes('## Rollback plan\nRevert.\n'), {'TEMPLATE_UNREADABLE'})

    def test_missing_helper_has_an_actionable_failure(self):
        """pull-request borrows the template check from pr-evidence. Installed alone, it must say so
        (TEMPLATE_CHECKER_MISSING) instead of crashing or silently passing."""
        fake_script = self.repo / 'skills/pull-request/scripts/pr_check.py'
        with patch.object(gate, '__file__', str(fake_script)):
            self.assertEqual(self.codes('text'), {'TEMPLATE_CHECKER_MISSING'})

    def test_real_bash_and_mcp_hook_enforce_template(self):
        """The real hook, as a subprocess, denies a Bash `gh pr create` and an MCP create_pull_request
        whose body lacks the repo template heading (TEMPLATE_SECTION_MISSING), and allows both once answered."""
        fixture = ast.parse((ROOT / 'tests/test_pull_request.py').read_text())
        body = next(ast.literal_eval(n.value) for n in fixture.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'GOOD_EN' for t in n.targets))
        (self.repo / 'CLAUDE.md').write_text('PR titles and commits in English.\n')
        body_file = self.repo / 'body.md'
        fakebin = Path(self.tmp.name) / 'bin'
        fakebin.mkdir()
        gh = fakebin / 'gh'
        gh.write_text('#!/bin/sh\nexit 1\n')
        gh.chmod(0o755)
        env = {k: v for k, v in os.environ.items() if not k.startswith('SQUAD_')}
        env.update(HOME=self.tmp.name, PATH=str(fakebin) + os.pathsep + env['PATH'])
        title = 'Show the guided tour notice once per browser'
        for answered in (False, True):
            current = body + ('\n## Rollback plan\nRevert the change.\n' if answered else '')
            body_file.write_text(current)
            for tool, inp in [('Bash', {'command': 'gh pr create --title ' + shlex.quote(title)
                                        + ' --body-file ' + shlex.quote(str(body_file))}),
                              ('mcp__plugin_github_github__create_pull_request', {'title': title, 'body': current})]:
                payload = {'tool_name': tool, 'cwd': str(self.repo), 'tool_input': inp}
                p = subprocess.run([sys.executable, '-I', '-B', str(HOOK)], input=json.dumps(payload),
                                   env=env, capture_output=True, text=True, timeout=30)
                self.assertEqual(p.returncode, 0, p.stderr)
                result = json.loads(p.stdout)['hookSpecificOutput']
                if answered:
                    self.assertNotEqual(result.get('permissionDecision'), 'deny', (tool, result))
                else:
                    self.assertEqual(result.get('permissionDecision'), 'deny', (tool, result))
                    self.assertIn('TEMPLATE_SECTION_MISSING', result['permissionDecisionReason'])

    def test_symlink_loop_blocks(self):
        """A template that links to itself must end in TEMPLATE_UNREADABLE, not hang or raise out of the gate."""
        self.template.unlink()
        self.template.symlink_to(self.template.name)
        self.assertEqual(self.codes('text'), {'TEMPLATE_UNREADABLE'})

    def test_oversized_or_non_regular_template_blocks(self):
        """A template over 128 KiB, or a directory where the file should be, is refused rather than read."""
        self.template.write_text('x' * 131073)
        self.assertEqual(self.codes('text'), {'TEMPLATE_UNREADABLE'})
        self.template.unlink()
        self.template.mkdir()
        self.assertEqual(self.codes('text'), {'TEMPLATE_UNREADABLE'})


if __name__ == '__main__':
    unittest.main()
