#!/usr/bin/env python3
"""Dependency and collision regression tests through the real CLI."""
import json
from pathlib import Path
import subprocess
import sys
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/parallel-plan/scripts/waves.py'


def card(cid, deps=None, touches=None, **extra):
    return dict(id=cid, depends_on=deps or [], touches=touches if touches is not None else [cid + '.py'], **extra)


class WaveTests(unittest.TestCase):
    def run_plan(self, cards, *extra):
        return subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), '-', *extra],
                              input=json.dumps(cards), text=True, capture_output=True)

    def result(self, cards, *extra):
        p = self.run_plan(cards, *extra)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        return json.loads(p.stdout)

    def test_diamond_and_determinism(self):
        data = [card('a'), card('b', ['a']), card('c', ['a']), card('d', ['b', 'c'])]
        r = self.result(data)
        self.assertEqual(r['waves'], [['a'], ['b', 'c'], ['d']])
        self.assertEqual(r, self.result(list(reversed(data))))
        self.assertEqual(r['critical_length'], 3)

    def test_long_chain_is_iterative(self):
        data = [card(str(i), [str(i-1)] if i else []) for i in range(1500)]
        r = self.result(data)
        self.assertEqual(len(r['waves']), 1500)
        self.assertEqual(r['critical_length'], 1500)

    def test_cycle_duplicate_unknown_and_ambiguous_ids(self):
        for data in ([card('a', ['b']), card('b', ['a'])], [card('a'), card('a')],
                     [card('a', ['missing'])], [card('x', ['a']), card('abc'), card('abd')],
                     [card('a', parentId='missing')], [card('a', parentId='b'), card('b', parentId='a')]):
            self.assertEqual(self.run_plan(data).returncode, 2, data)

    def test_inherits_parent_dependencies_and_expands_containers(self):
        data = [dict(id='epic', type='EPIC'), dict(id='story', type='STORY', parentId='epic',
                description='Depends on: prerequisite\n'), card('task', parentId='story'),
                card('prerequisite')]
        self.assertEqual(self.result(data)['waves'], [['prerequisite'], ['task']])
        data = [dict(id='parent', type='STORY'), card('a', parentId='parent'),
                card('b', parentId='parent'), card('c', ['parent'])]
        self.assertEqual(self.result(data)['waves'], [['a', 'b'], ['c']])

    def test_description_fields_ignore_examples_and_support_markdown(self):
        data = [dict(id='a', description='**Depends on:** none\n**Touches:** src/a.py\nSize: 2'),
                dict(id='b', description='```text\nDepends on: unknown\n```\n- Depends on: a (reason)\n- Touches: src/b.py')]
        r = self.result(data)
        self.assertEqual(r['waves'], [['a'], ['b']])
        self.assertEqual(r['critical_length'], 3)

    def test_colliding_paths_globs_and_named_resources_are_serial(self):
        for a, b in [('src/', 'src/a.py'), ('src', 'src/a.py'), ('src/billing', 'src/*.py'),
                     ('src/*.py', 'src/a.py'), ('src/*.py', 'src/?x.py'),
                     ('src/', 'src*.py'), ('./same.py', 'same.py'), ('state:db', 'state:db')]:
            r = self.result([card('a', touches=[a]), card('b', touches=[b])])
            self.assertEqual(len(r['waves']), 2, (a, b, r))
        self.assertEqual(len(self.result([card('a', touches=['state:a']),
                                        card('b', touches=['state:b'])])['waves']), 1)

    def test_annotations_cannot_hide_a_dependency_or_path_collision(self):
        data = [dict(id='a', description='Touches: src/a.py (new, generated)'),
                dict(id='b', description='Depends on: a (contract, version)\nTouches: src/b.py')]
        self.assertEqual(self.result(data)['waves'], [['a'], ['b']])
        data[1]['description'] = 'Touches: src/a.py'
        self.assertEqual(len(self.result(data)['waves']), 2)
        self.assertEqual(self.run_plan([card('a', touches=['src/a.py (unclosed'])]).returncode, 2)

    def test_unknown_touch_is_never_claimed_parallel_safe(self):
        r = self.result([card('a', touches=[]), card('b')])
        self.assertEqual(len(r['waves']), 2)
        self.assertEqual(r['unknown_touches'], ['a'])

    def test_blocked_cancelled_archived_are_not_done(self):
        for status in ('BLOCKED', 'PAUSED', 'CANCELLED', 'ARCHIVED', 'TRASHED'):
            r = self.result([card('a', status=status), card('b', ['a']), card('c')])
            self.assertEqual(r['waves'], [['c']])
            self.assertEqual(set(r['blocked']), {'a', 'b'})
        self.assertEqual(self.result([card('a', status='DONE'), card('b', ['a'])])['waves'], [['b']])

    def test_completed_parent_cannot_close_unfinished_children(self):
        data = [dict(id='parent', type='STORY', status='DONE'), card('child', parentId='parent')]
        self.assertEqual(self.run_plan(data).returncode, 2)
        data[1]['status'] = 'DONE'
        self.assertEqual(self.result(data)['waves'], [])

    def test_bad_types_paths_sizes_and_width_fail(self):
        for data in ([card('a', size=True)], [card('a', size=1.5)], [card('a', size=0)],
                     [dict(id='a', depends_on={'b': 1})], [card('a', touches=['../secret'])],
                     [card('a', touches=['/absolute'])], [card('a', touches=['x/../y'])],
                     [card('a', touches=['c:/absolute'])], [card('a', touches=['c:\\\\absolute'])]):
            self.assertEqual(self.run_plan(data).returncode, 2, data)
        self.assertEqual(self.run_plan([card('a')], '--max-width', '0').returncode, 2)
        self.assertEqual(self.run_plan([card('a')], '--max-width', '5').returncode, 2)

    def test_help_and_no_execution(self):
        p = subprocess.run([sys.executable, '-I', '-B', str(SCRIPT), '--help'], capture_output=True)
        self.assertEqual(p.returncode, 0)
        self.assertNotIn('import subprocess', SCRIPT.read_text())


if __name__ == '__main__':
    unittest.main()
