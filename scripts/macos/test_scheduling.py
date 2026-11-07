# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
"""Static scheduler contracts; no third-party Python dependency in CI."""
from pathlib import Path
import unittest
class SchedulingTests(unittest.TestCase):
    def test_universal_host_and_qualification_requirements(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / '.github/workflows/macos-qualification.yml').read_text()
        universal = text.split('  universal:', 1)[1].split('  smoke:', 1)[0]
        self.assertIn('runs-on: macos-15-intel', universal)
        self.assertIn('--arch x86_64', universal)
        self.assertIn('- preflight-intel', universal)
        self.assertNotIn('- preflight-arm64', universal)
        self.assertIn("needs.preflight-arm64.result == 'success'", text)
        text = " ".join(text.split())
        self.assertIn("needs.preflight-intel.result == 'success'", text)
        gate = (root / 'scripts/macos/gate.py').read_text()
        self.assertIn("('universal', 'x86_64', 'Release')", gate)
        self.assertIn('require_approved_authority', gate)
        ci = (root / 'scripts/macos/ci.py').read_text()
        self.assertIn("'x86_64;arm64' if universal", ci)
        self.assertIn("set(arches) == {'x86_64', 'arm64'}", ci)
    def test_isolated_development_workflow_cannot_claim_qualification(self):
        root = Path(__file__).resolve().parents[2]
        text = (root / '.github/workflows/macos-development-build.yml').read_text()
        self.assertIn('runs-on: macos-15-intel', text)
        self.assertEqual(text.count('--mode build --arch x86_64'), 2)
        self.assertIn('UNQUALIFIED-universal-AU-VST3', text)
        self.assertNotIn('secrets.', text)
        self.assertNotIn('contents: write', text)
        self.assertNotIn('ci.py gate', text)
        self.assertIn('retention-days: 7', text)
        self.assertIn('compiled-source-manifest.json', text)
if __name__ == '__main__': unittest.main()
