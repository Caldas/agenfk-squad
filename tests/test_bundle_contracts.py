#!/usr/bin/env python3
"""Skill wiring/fixtures, not a claim about live-model behavior or accuracy."""
import ast
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ('pr-evidence', 'ci-plan-evidence', 'parallel-plan', 'engineering-evidence')
PUBLIC = (ROOT / 'agents/developer.md').exists()
AGENTS = {
    'pr-evidence': ('github', 'verifier' if PUBLIC else 'verificador'),
    'ci-plan-evidence': ('infra', 'verifier' if PUBLIC else 'verificador'),
    'parallel-plan': ('product' if PUBLIC else 'produto', 'github'),
    'engineering-evidence': ('developer' if PUBLIC else 'desenvolvimento',
                             'tester' if PUBLIC else 'testes', 'finops'),
}


class ContractTests(unittest.TestCase):
    def test_skill_metadata_and_progressive_disclosure(self):
        for name in SKILLS:
            text = (ROOT / 'skills' / name / 'SKILL.md').read_text()
            self.assertTrue(text.startswith('---\nname: ' + name + '\n'), name)
            desc = re.search(r'^description: (.+)$', text, re.M)
            self.assertIsNotNone(desc, name)
            self.assertLessEqual(len(desc[1]), 700, name)
            if ': ' in desc[1]:
                self.assertTrue(desc[1].startswith(('"', "'")), 'quote YAML colon-space: ' + name)
            self.assertLess(len(text.splitlines()), 160, name)
            for link in re.findall(r'\]\((references/[^)]+)\)', text):
                self.assertTrue((ROOT / 'skills' / name / link).is_file(), (name, link))
            for link in re.findall(r'`(references/[^`]+\.md)`', text):
                self.assertTrue((ROOT / 'skills' / name / link).is_file(), (name, link))

    def test_agents_point_to_each_procedure_on_demand(self):
        for skill, agents in AGENTS.items():
            for agent in agents:
                self.assertIn('`' + skill + '`', (ROOT / 'agents' / (agent + '.md')).read_text(), (skill, agent))
        rules = (ROOT / 'CLAUDE.md').read_text()
        for skill in SKILLS:
            self.assertIn('`' + skill + '`', rules, skill)

    def test_eval_fixtures_include_positive_negative_and_assertions(self):
        for skill in SKILLS:
            data = json.loads((ROOT / 'skills' / skill / 'evals/evals.json').read_text())
            self.assertEqual(data['skill_name'], skill)
            self.assertEqual(len(data['evals']), 3)
            self.assertEqual(len({e['id'] for e in data['evals']}), 3)
            self.assertEqual({e['should_trigger'] for e in data['evals']}, {True, False})
            for e in data['evals']:
                self.assertGreater(len(e['prompt']), 65)
                self.assertTrue(e['expected_output'] and e['assertions'])

    def test_scripts_are_offline_and_stdlib_only(self):
        allowed = {'argparse', 'collections', 'fnmatch', 'heapq', 'json', 'pathlib',
                   'posixpath', 're', 'sys', 'unicodedata'}
        for skill in SKILLS:
            for path in (ROOT / 'skills' / skill).glob('scripts/*.py'):
                tree = ast.parse(path.read_text())
                imports = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imports.update(a.name.split('.')[0] for a in node.names)
                    elif isinstance(node, ast.ImportFrom):
                        imports.add(node.module.split('.')[0])
                self.assertLessEqual(imports, allowed, path)
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                        self.assertNotIn(node.func.id, ('exec', 'eval', '__import__', 'open'), path)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                        self.assertNotIn(node.func.attr, ('write_text', 'write_bytes', 'unlink', 'mkdir'), path)

    def test_no_private_context_or_bundled_history_in_new_skills(self):
        forbidden = re.compile(r'/home/[a-z]+/|(?<!\d)\d{12}(?!\d)|-----BEGIN .*PRIVATE KEY-----', re.I)
        for skill in SKILLS:
            for path in (ROOT / 'skills' / skill).rglob('*'):
                if path.is_file():
                    self.assertNotIn(path.suffix, ('.bundle', '.zip', '.pyc'), path)
                    self.assertFalse(path.is_symlink(), path)
                    self.assertIsNone(forbidden.search(path.read_text()), path)


if __name__ == '__main__':
    unittest.main()
