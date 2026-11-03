#!/usr/bin/env python3
"""Historical price arithmetic and the example's input guard, not a real AWS account test.

    python3 tests/test_cloud_resource_pricing.py
"""
from decimal import Decimal, ROUND_HALF_UP
import os
from pathlib import Path
import re
import subprocess
import unittest

import sys

if os.name == "nt":
    # its scripts and fakes run through bash and POSIX tools; the cloud-resource pricing guard is not yet verified on Windows
    print("skipped: the cloud-resource pricing guard is not yet verified on Windows")
    sys.exit(0)

ROOT = Path(__file__).resolve().parents[1]
CLOUD = ROOT / 'skills/cloud-resource/references'


class CloudResourcePricingTests(unittest.TestCase):
    def test_historical_monthly_arithmetic(self):
        text = (CLOUD / 'aws-prices.md').read_text()

        def monthly(label):
            row = next(line for line in text.splitlines() if line.startswith('| ' + label + ' |'))
            return Decimal(re.search(r'\*\*([0-9.]+)\*\*', row)[1])

        fargate = (Decimal('0.04048') + 2 * Decimal('0.004445')) * 730
        app = (Decimal('0.064') + 2 * Decimal('0.007')) * 730
        self.assertEqual(monthly('Fargate, 1 vCPU / 2 GB, always on'),
                         fargate.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))
        self.assertEqual(monthly('App Runner, 1 vCPU / 2 GB, always active'),
                         app.quantize(Decimal('.01')))
        # The sheet is dated and says it was not re-checked: the reading date stays.
        self.assertIn('without a new check', text)
        self.assertRegex(text, r'\*\*20\d\d-\d\d-\d\d\*\*')
        self.assertIn('not a query to the pricing API', (CLOUD / 'ci-and-account.md').read_text())

    def test_documented_ci_guard_rejects_missing_invalid_and_accepts_shape(self):
        doc = (CLOUD / 'ci-and-account.md').read_text()
        script = re.search(r'    run: \|\n(.*?)\n```', doc, re.S)[1]
        script = '\n'.join(line[6:] for line in script.splitlines())
        for value, success in [('', False), ('1234', False), ('x' * 12, False), ('1' * 12, True)]:
            env = dict(os.environ, TF_VAR_expected_account_id=value)
            p = subprocess.run(['bash', '-c', script], env=env, capture_output=True, text=True)
            self.assertEqual(p.returncode == 0, success, p.stderr)
            if value:
                self.assertNotIn(value, p.stdout + p.stderr)
        # This proves only the input guard; mocks do not prove AWS rejects an
        # authenticated wrong account. The procedure must state that limit.
        self.assertIn('does not prove', doc)
        self.assertIn('authorised test environment', doc)


if __name__ == '__main__':
    unittest.main()
