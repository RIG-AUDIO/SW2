#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail-closed controls for native validation and qualification."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from ci import Campaign


class AuDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.campaign = Campaign.__new__(Campaign)
        self.campaign.root = Path(self.directory.name)
        self.campaign.report = {}
        self.campaign.save = lambda: None
        self.host = self.campaign.root / 'instrumented-host'
        self.bundle = self.campaign.root / 'Swara XT.component'
        self.calls = []
        patcher = patch('ci.time.sleep')
        self.sleep = patcher.start()
        self.addCleanup(patcher.stop)

    def responses(self, results):
        results = iter(results)

        def run(name, argv, **kwargs):
            self.assertEqual(argv, [self.host, 'AU', self.bundle, '--discover-only'])
            self.assertEqual(kwargs, {'login': True, 'expected': None, 'timeout': 120})
            self.calls.append(name)
            code, text = next(results)
            (self.campaign.root / (name + '.log')).write_text(text)
            return code

        self.campaign.run = run

    def discover(self):
        self.campaign.wait_for_ci_au(self.host, self.bundle)

    def test_pending_then_exact_discovery_uses_matching_host(self):
        self.responses([(2, 'AU_DISCOVERY_PENDING\n'), (0, 'AU_DISCOVERY_EXACT_PASS\n')])
        self.discover()
        self.assertTrue(self.campaign.report['au_discovery_exact'])
        self.assertEqual(len(self.calls), 2)
        self.sleep.assert_called_once_with(2)

    def test_scanner_abort_is_never_treated_as_success(self):
        self.responses([(-6, 'Interceptors are not working.\nAU_DISCOVERY_EXACT_PASS\n')])
        with self.assertRaises(RuntimeError):
            self.discover()
        self.assertNotIn('au_discovery_exact', self.campaign.report)
        self.assertEqual(len(self.calls), 1)

    def test_success_exit_without_exact_identity_evidence_fails(self):
        self.responses([(0, 'aumu SwXT MnTr - MontroneDSP: Swara XT\n')])
        with self.assertRaises(RuntimeError):
            self.discover()

    def test_fatal_host_failure_is_not_retried(self):
        self.responses([(1, 'FAIL: discovered AU has the expected product identity\n')])
        with self.assertRaises(RuntimeError):
            self.discover()
        self.assertEqual(len(self.calls), 1)

    def test_pending_exit_without_pending_evidence_fails(self):
        self.responses([(2, 'FAIL: unknown error\n')])
        with self.assertRaises(RuntimeError):
            self.discover()

    def test_pending_discovery_has_a_finite_deadline(self):
        self.responses([(2, 'AU_DISCOVERY_PENDING\n')] * 16)
        with self.assertRaises(RuntimeError):
            self.discover()
        self.assertEqual(len(self.calls), 16)

    def test_sanitizer_diagnostic_fails_even_with_success_marker(self):
        self.responses([(0, 'WARNING: ThreadSanitizer: data race\nAU_DISCOVERY_EXACT_PASS\n')])
        with self.assertRaises(RuntimeError):
            self.discover()
        self.assertNotIn('au_discovery_exact', self.campaign.report)


class PluginvalPolicyTests(unittest.TestCase):
    def test_full_stress_and_failure_propagation_remain_required(self):
        with tempfile.TemporaryDirectory() as directory:
            campaign = Campaign.__new__(Campaign)
            campaign.root = Path(directory)
            campaign.report = {}
            pluginval = campaign.root / 'pluginval-tool/pluginval.app/Contents/MacOS/pluginval'
            pluginval.parent.mkdir(parents=True)
            pluginval.touch()
            bundle = campaign.root / 'Swara XT.component'

            def run(name, argv, **kwargs):
                self.assertEqual(name, 'pluginval-AU')
                self.assertEqual(argv[0], pluginval)
                for option, value in (('--strictness-level', '10'), ('--repeat', '2'),
                                      ('--timeout-ms', '120000'), ('--random-seed', '0x53776172')):
                    self.assertEqual(argv[argv.index(option) + 1], value)
                self.assertIn('--randomise', argv)
                self.assertNotIn('--skip-gui-tests', argv)
                self.assertNotIn('--disabled-tests', argv)
                self.assertEqual(argv[-2:], ['--validate', bundle])
                self.assertEqual(kwargs, {'timeout': 1800, 'expected': None, 'login': True})
                return 1  # A validator failure must still fail qualification.

            campaign.run = run
            self.assertEqual(campaign.external_validation(bundle, 'AU'), 1)


class QualificationOrchestrationTests(unittest.TestCase):
    def test_release_keeps_regression_evidence_but_fails_on_validator_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            build = Path(directory)
            host = build / 'Tests/Apple/SwaraXTApplePluginHost_artefacts/Release/SwaraXTApplePluginHost'
            host.parent.mkdir(parents=True)
            host.touch()
            bundles = [build / 'Swara XT.component', build / 'Swara XT.vst3']
            campaign = Campaign.__new__(Campaign)
            campaign.args = SimpleNamespace(task='tests', profile='Release')
            campaign.root = build
            campaign.report = {}
            campaign.prepare = Mock(return_value=build / 'JUCE')
            campaign.configure = Mock(return_value=(build, 'Release'))
            campaign.bundles = Mock(return_value=bundles)
            campaign.verified_candidate = Mock(return_value=bundles)
            campaign.seal_ci_bundles = Mock()
            campaign.verify_native_host = Mock()
            campaign.register_ci_au = Mock()
            # The full host path must reach VST3 validation and both lifecycles
            # even when strict AU pluginval returns its observed abort exit.
            campaign.external_validation = Mock(side_effect=[9, 0])
            campaign.regressions = Mock()

            def run(name, argv, **kwargs):
                if name in ('actual-AU', 'actual-VST3'):
                    (build / (name + '.log')).write_text(
                        'PASS: actual plugin two-instance audio/editor/state/reopen lifecycle\n')
                return 0

            campaign.run = Mock(side_effect=run)
            campaign.finish_evidence = Mock()
            calls = Mock()
            calls.attach_mock(campaign.regressions, 'regressions')
            calls.attach_mock(campaign.finish_evidence, 'finish_evidence')
            with patch('infrastructure.cleanup_au') as cleanup, patch('ci.subprocess.check_output', return_value=''):
                with self.assertRaisesRegex(RuntimeError, 'Mandatory native validation failed'):
                    campaign.execute()
            cleanup.assert_called_once_with(build, campaign.run)
            self.assertEqual([call.args[-1] for call in campaign.external_validation.call_args_list], ['AU', 'VST3'])
            self.assertEqual(campaign.report['actual_hosts'], {'AU': 'PASS', 'VST3': 'PASS'})
            self.assertEqual([call[0] for call in calls.mock_calls], ['regressions', 'finish_evidence'])
            self.assertEqual(campaign.report['native_validation'], 'FAIL')
            self.assertEqual(campaign.report['decision'], 'QUALIFICATION_FAILED')


def load_tests(loader, tests, pattern):
    import test_compiler_cache
    tests.addTests(loader.loadTestsFromModule(test_compiler_cache))
    import test_processes
    tests.addTests(loader.loadTestsFromModule(test_processes))
    import test_intel_diagnostics
    tests.addTests(loader.loadTestsFromModule(test_intel_diagnostics))
    import test_scheduling
    tests.addTests(loader.loadTestsFromModule(test_scheduling))
    import test_tsan_shards
    tests.addTests(loader.loadTestsFromModule(test_tsan_shards))
    import test_policy
    import test_native_reference
    tests.addTests(loader.loadTestsFromModule(test_native_reference))
    tests.addTests(loader.loadTestsFromModule(test_policy))
    return tests


if __name__ == '__main__':
    unittest.main()
