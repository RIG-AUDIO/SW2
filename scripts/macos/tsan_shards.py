# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
"""Select and independently verify the two Intel TSan regression shards."""
import argparse
import json
import os
from pathlib import Path
import shlex
import xml.etree.ElementTree as ET

from policy import BASE_SHA, JUCE_SHA, PRODUCTION_PARITY, REPOSITORY, digest, require, revision

SHARD_B = frozenset({
    'SwaraBoardSafetyTests', 'SwaraBoardIntegrationTests', 'SwaraBoardGuiTests',
    'SwaraXTChannelTypeContractTests', 'SwaraXTCutoffParameterTests',
})
TOTAL = 136
TSAN_FLAGS = {'-fsanitize=thread', '-fno-omit-frame-pointer'}
INPUT_FILES = ('ctest-inventory.json', 'compile-commands.json')
RUNTIME_LOGS = ('ctest.log', 'actual-AU.log', 'actual-VST3.log')


def select_shards(inventory, profile, architecture):
    require(profile == 'tsan' and architecture == 'x86_64', 'Sharding requires Intel TSan')
    tests = inventory['tests']
    names = {test['name'] for test in tests}
    require(len(tests) == len(names), 'Duplicate CTest names')
    require(len(names) == TOTAL and SHARD_B <= names, 'Incomplete mandatory CTest inventory')
    require(not any(prop['name'] == 'DISABLED' and prop['value']
                    for test in tests for prop in test['properties']), 'Disabled CTest case')
    return {'a': names - SHARD_B, 'b': SHARD_B}


def inspect_shard_junit(path, expected):
    cases = list(ET.parse(path).getroot().iter('testcase'))
    require(len(cases) == len(expected) and {case.attrib['name'] for case in cases} == expected,
            'Wrong or duplicate JUnit test names')
    require(all(case.get('status') == 'run' and
                not any(case.find(tag) is not None for tag in ('failure', 'error', 'skipped'))
                for case in cases), 'Failed, skipped or unexecuted shard test')
    return {'executed_test_count': len(cases), 'failed_test_count': 0, 'skipped_test_count': 0}


def aggregate(root, source, run, attempt, candidate, job_result):
    require(job_result == 'success', 'A required Intel TSan shard job failed or did not finish')
    reports = list(root.glob('*/report.json'))
    require(len(reports) == 2, 'Expected exactly two Intel TSan shard artifacts')
    coverage = {}
    inventories = []
    toolchains = []
    for report in reports:
        folder = report.parent
        data = json.loads(report.read_text())
        shard = data['tsan_shard']
        require(shard in ('a', 'b') and shard not in coverage, 'Wrong or duplicate Intel TSan shard')
        require((data['source_sha'], data['run_id'], data['run_attempt']) == (source, run, attempt),
                'Shard source or run identity mismatch')
        parity = data['source_parity']
        require(data['repository'] == REPOSITORY and data['stage'] == 'tests' and
                data['base_source_sha'] == parity['base_source_sha'] == BASE_SHA and
                parity['checkout_sha'] == source and parity['production_parity'] == PRODUCTION_PARITY,
                'Shard source integrity evidence missing')
        require(data['candidate_origin'] == candidate and data['actual_universal_candidate_checked'] is True
                and data['candidate_archive_sha256'] == candidate['archive_sha256'], 'Shard candidate provenance mismatch')
        require(data['xcode_version'].startswith('Xcode 16.4\n') and data['compiler_version'] and data['juce_sha'] == JUCE_SHA and
                data['macos_version'].startswith('15.'), 'Shard toolchain mismatch')
        toolchains.append((data['xcode_version'], data['compiler_version'], data['dependency_overlay']))
        require(data['decision'] == 'INTEL_TSAN_SHARD_PASS' and data['technical_execution'] == 'PASS',
                'Shard execution did not pass')
        require(data['native_host']['architecture'] == 'x86_64' and data['native_host']['profile'] == 'tsan' and
                data['actual_hosts'] == {'AU': 'PASS', 'VST3': 'PASS'} and data['au_discovery_exact'] is True,
                'Instrumented host evidence missing')
        commands = {entry['name']: entry['exit_code'] for entry in data['commands']}
        require(all(commands.get(name) == 0 for name in
                    ('ci-harness-regression', 'build-native-tests', 'actual-AU', 'actual-VST3', 'ctest')),
                'Mandatory shard command did not pass')
        require(data['sanitizer_negative_controls'] == 'PASS' and commands.get('tsan-negative-control') not in (None, 0),
                'TSan sensitivity control did not pass')
        for name in ('ctest.xml', 'tsan-negative-control.log', *RUNTIME_LOGS):
            require(digest(folder / name) == data['file_hashes'][name], 'Shard log checksum mismatch: ' + name)
        require('ThreadSanitizer: data race' in (folder / 'tsan-negative-control.log').read_text(),
                'TSan negative control did not detect a race')
        for name in RUNTIME_LOGS:
            require('ThreadSanitizer:' not in (folder / name).read_text(errors='replace'),
                    'TSan runtime diagnostic: ' + name)
        for name in INPUT_FILES:
            require(digest(folder / name) == data['tsan_shard_inputs'][name], 'Shard input checksum mismatch: ' + name)
        compiled = json.loads((folder / 'compile-commands.json').read_text())
        require(data['compile_commands_audit'] == 'PASS' and data['production_compile_commands_count'] > 10 and
                len(compiled) == data['compile_commands_count'] >= data['production_compile_commands_count'] and
                all(TSAN_FLAGS.issubset(shlex.split(entry['command'])) for entry in compiled),
                'Missing TSan compile instrumentation')
        inventory = json.loads((folder / 'ctest-inventory.json').read_text())
        assigned = select_shards(inventory, data['profile'], data['architecture'])
        counts = inspect_shard_junit(folder / 'ctest.xml', assigned[shard])
        require(data['test_count'] == TOTAL and all(data[key] == value for key, value in counts.items()),
                'Shard CTest report counts disagree')
        coverage[shard] = assigned[shard]
        inventories.append(assigned['a'] | assigned['b'])
    require(toolchains[0] == toolchains[1], 'Shard compiler or JUCE overlay differs')
    require(set(coverage) == {'a', 'b'} and not coverage['a'] & coverage['b'] and
            coverage['a'] | coverage['b'] == inventories[0] == inventories[1],
            'Intel TSan shards do not cover the same complete inventory')
    return {'decision': 'INTEL_TSAN_TECHNICAL_PASS', 'source_sha': source, 'run_id': run, 'run_attempt': attempt,
            'candidate_origin': candidate, 'shards': {shard: len(names) for shard, names in coverage.items()},
            'passed': TOTAL, 'failed': 0, 'skipped': 0}


def main():
    from intel_diagnostics import ARCHIVE_SHA256, CANDIDATE_ATTEMPT, CANDIDATE_RUN, CANDIDATE_SHA

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifacts', type=Path)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    source = revision(os.environ['GITHUB_SHA'])
    run, attempt = os.environ['GITHUB_RUN_ID'], os.environ['GITHUB_RUN_ATTEMPT']
    candidate = {'source_sha': CANDIDATE_SHA, 'run_id': CANDIDATE_RUN, 'run_attempt': CANDIDATE_ATTEMPT,
                 'archive_sha256': ARCHIVE_SHA256}
    try:
        verdict = aggregate(args.artifacts, source, run, attempt, candidate, os.environ['SHARD_JOBS_RESULT'])
    except Exception as error:
        verdict = {'decision': 'INTEL_TSAN_QUALIFICATION_FAILED', 'source_sha': source, 'run_id': run,
                   'run_attempt': attempt, 'failure': str(error)}
        raise
    finally:
        args.report.write_text(json.dumps(verdict, indent=2) + '\n')
        print(json.dumps(verdict, indent=2))


if __name__ == '__main__':
    main()
