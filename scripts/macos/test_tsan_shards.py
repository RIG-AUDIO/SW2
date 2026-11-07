# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET

from policy import BASE_SHA, JUCE_SHA, PRODUCTION_PARITY, REPOSITORY, digest
from tsan_shards import INPUT_FILES, RUNTIME_LOGS, SHARD_B, aggregate, select_shards


def full_inventory():
    names = [f'Fixture{i}' for i in range(131)] + sorted(SHARD_B)
    return {'tests': [{'name': name, 'properties': []} for name in names]}


class TSanShardSelectionTests(unittest.TestCase):
    def test_exact_partition_and_named_board_cases(self):
        inventory = full_inventory()
        inventory['tests'].reverse()
        shards = select_shards(inventory, 'tsan', 'x86_64')
        self.assertEqual(len(shards['a']), 131)
        self.assertEqual(shards['b'], SHARD_B)
        self.assertFalse(shards['a'] & shards['b'])
        self.assertEqual(shards['a'] | shards['b'], {test['name'] for test in inventory['tests']})

    def test_rejects_duplicate_missing_or_disabled_inventory(self):
        duplicate = full_inventory()
        duplicate['tests'][1] = duplicate['tests'][0]
        missing = full_inventory()
        missing['tests'].pop()
        replaced = full_inventory()
        replaced['tests'][-1]['name'] = 'UnrelatedReplacement'
        disabled = full_inventory()
        disabled['tests'][0]['properties'] = [{'name': 'DISABLED', 'value': True}]
        for inventory, message in ((duplicate, 'Duplicate'), (missing, 'Incomplete'),
                                   (replaced, 'Incomplete'), (disabled, 'Disabled')):
            with self.subTest(message=message), self.assertRaisesRegex(RuntimeError, message):
                select_shards(inventory, 'tsan', 'x86_64')

    def test_rejects_wrong_profile_or_architecture(self):
        for profile, architecture in (('asan-ubsan', 'x86_64'), ('tsan', 'arm64')):
            with self.assertRaisesRegex(RuntimeError, 'requires Intel TSan'):
                select_shards(full_inventory(), profile, architecture)


class TSanAggregateTests(unittest.TestCase):
    source = '1' * 40
    candidate = {'source_sha': '2' * 40, 'run_id': '99', 'run_attempt': '1', 'archive_sha256': 'a' * 64}

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.write_shard('a')
        self.write_shard('b')

    def write_shard(self, shard, *, inventory=None, flags='-fsanitize=thread -fno-omit-frame-pointer',
                    case_tag=None, runtime_log='', **overrides):
        folder = self.root / shard
        folder.mkdir(exist_ok=True)
        inventory = full_inventory() if inventory is None else inventory
        names = select_shards(inventory, 'tsan', 'x86_64')[shard]
        cases = ET.Element('testsuite')
        for name in sorted(names):
            case = ET.SubElement(cases, 'testcase', name=name, status='run')
            if case_tag and len(cases) == 1:
                ET.SubElement(case, case_tag)
        ET.ElementTree(cases).write(folder / 'ctest.xml')
        (folder / 'ctest-inventory.json').write_text(json.dumps(inventory))
        (folder / 'compile-commands.json').write_text(json.dumps(
            [{'command': f'clang++ {flags} -c Source/test{i}.cpp'} for i in range(12)]))
        (folder / 'tsan-negative-control.log').write_text('WARNING: ThreadSanitizer: data race')
        for name in RUNTIME_LOGS:
            (folder / name).write_text(runtime_log)
        report = {
            'tsan_shard': shard, 'source_sha': self.source, 'run_id': '100', 'run_attempt': '1',
            'repository': REPOSITORY, 'stage': 'tests', 'base_source_sha': BASE_SHA,
            'source_parity': {'base_source_sha': BASE_SHA, 'checkout_sha': self.source,
                              'production_parity': PRODUCTION_PARITY},
            'candidate_origin': self.candidate, 'actual_universal_candidate_checked': True,
            'candidate_archive_sha256': self.candidate['archive_sha256'],
            'xcode_version': 'Xcode 16.4\nBuild version 16F6', 'compiler_version': 'Apple clang version 17',
            'macos_version': '15.7.9', 'juce_sha': JUCE_SHA, 'dependency_overlay': {},
            'decision': 'INTEL_TSAN_SHARD_PASS', 'technical_execution': 'PASS',
            'native_host': {'architecture': 'x86_64', 'profile': 'tsan'}, 'au_discovery_exact': True,
            'actual_hosts': {'AU': 'PASS', 'VST3': 'PASS'}, 'sanitizer_negative_controls': 'PASS',
            'commands': [{'name': name, 'exit_code': 0} for name in
                         ('ci-harness-regression', 'build-native-tests', 'actual-AU', 'actual-VST3', 'ctest')]
                        + [{'name': 'tsan-negative-control', 'exit_code': -6}],
            'file_hashes': {name: digest(folder / name) for name in ('ctest.xml', 'tsan-negative-control.log', *RUNTIME_LOGS)},
            'tsan_shard_inputs': {name: digest(folder / name) for name in INPUT_FILES},
            'compile_commands_audit': 'PASS', 'compile_commands_count': 12, 'production_compile_commands_count': 12,
            'profile': 'tsan', 'architecture': 'x86_64', 'test_count': 136,
            'executed_test_count': len(names), 'failed_test_count': 0, 'skipped_test_count': 0,
        }
        (folder / 'report.json').write_text(json.dumps({**report, **overrides}))

    def verdict(self, jobs='success'):
        return aggregate(self.root, self.source, '100', '1', self.candidate, jobs)

    def test_requires_both_successful_shards_with_exact_coverage(self):
        verdict = self.verdict()
        self.assertEqual(verdict['decision'], 'INTEL_TSAN_TECHNICAL_PASS')
        self.assertEqual(verdict['shards'], {'a': 131, 'b': 5})
        self.assertEqual((verdict['passed'], verdict['failed'], verdict['skipped']), (136, 0, 0))
        with self.assertRaisesRegex(RuntimeError, 'job failed'):
            self.verdict('failure')
        (self.root / 'b/report.json').unlink()
        with self.assertRaisesRegex(RuntimeError, 'exactly two'):
            self.verdict()

    def test_rejects_wrong_source_missing_flags_and_controls(self):
        for edits, message in (({'source_sha': '3' * 40}, 'source or run'),
                               ({'flags': '-fno-omit-frame-pointer'}, 'instrumentation'),
                               ({'sanitizer_negative_controls': 'FAIL'}, 'sensitivity control'),
                               ({'actual_universal_candidate_checked': False}, 'candidate provenance'),
                               ({'technical_execution': 'FAIL'}, 'execution did not pass')):
            with self.subTest(edits=edits), self.assertRaisesRegex(RuntimeError, message):
                self.write_shard('b', **edits)
                self.verdict()

    def test_rejects_failed_skipped_and_sanitizer_diagnostics(self):
        for tag in ('failure', 'skipped'):
            with self.subTest(tag=tag), self.assertRaisesRegex(RuntimeError, 'Failed, skipped'):
                self.write_shard('b', case_tag=tag)
                self.verdict()
        self.write_shard('b', runtime_log='WARNING: ThreadSanitizer: data race')
        with self.assertRaisesRegex(RuntimeError, 'TSan runtime diagnostic'):
            self.verdict()

    def test_rejects_disagreeing_inventory_and_duplicate_shard(self):
        inventory = full_inventory()
        inventory['tests'][0]['name'] = 'UnexpectedTest'
        self.write_shard('b', inventory=inventory)
        with self.assertRaisesRegex(RuntimeError, 'same complete inventory'):
            self.verdict()
        shutil.copytree(self.root / 'a', self.root / 'b', dirs_exist_ok=True)
        with self.assertRaisesRegex(RuntimeError, 'duplicate Intel TSan shard'):
            self.verdict()
