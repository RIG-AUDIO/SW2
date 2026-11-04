# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
"""Independently inspect current-run evidence; partial modes cannot pass full."""
import json
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from native_reference import BASELINE_SHA, TESTS
from policy import require, digest, owned_path, JUCE_SHA, SDK_SHA, SEAL


def inspect_ctest(path, expected):
    cases = list(ET.parse(path).getroot().iter('testcase'))
    require(expected > 50 and len(cases) == expected, 'Incomplete native CTest inventory')
    failed = sum(bool(list(c.iter('failure')) or list(c.iter('error'))) for c in cases)
    skipped = sum(bool(list(c.iter('skipped'))) for c in cases)
    require(failed == 0 and skipped == 0, 'Failed or skipped native CTest cases')
    return {'executed_test_count': len(cases), 'failed_test_count': failed, 'skipped_test_count': skipped}


def evaluate(root, args):
    root = Path(root).resolve()
    require(args.mode in ('preflight', 'build', 'smoke', 'full'), 'Unknown qualification mode')
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        required_jobs = {'PREFLIGHT': 'success', 'UNIVERSAL': 'skipped', 'SMOKE': 'skipped', 'NATIVE': 'skipped'}
        if args.mode != 'preflight':
            required_jobs['UNIVERSAL'] = 'success'
        if args.mode in ('smoke', 'full'):
            required_jobs['SMOKE'] = 'success'
        if args.mode == 'full':
            required_jobs['NATIVE'] = 'success'
        for job, expected_status in required_jobs.items():
            require(os.environ.get(job + '_RESULT') == expected_status,
                    'Required job failed, missing, cancelled or skipped: ' + job)
    expected = {('preflight', a, 'Release') for a in ('arm64', 'x86_64')}
    if args.mode != 'preflight':
        expected.add(('universal', 'arm64', 'Release'))
    if args.mode in ('smoke', 'full'):
        expected |= {('smoke', a, 'Release') for a in ('arm64', 'x86_64')}
    if args.mode == 'full':
        expected |= {('tests', a, p) for a in ('arm64', 'x86_64') for p in ('Release', 'Debug', 'asan-ubsan', 'tsan')}
    found = {}
    for report_path in sorted(root.rglob('report.json')):
        require(not report_path.is_symlink(), 'Evidence report cannot be linked')
        data = json.loads(report_path.read_text())
        key = (data['stage'], data['architecture'], data['profile'])
        require(key in expected and key not in found, 'Extra or duplicated native report')
        require(data['source_sha'] == args.source_sha and data['base_source_sha'] == args.base_source_sha, 'Report source mismatch')
        require(data['run_id'] == os.environ['GITHUB_RUN_ID'] and data['run_attempt'] == os.environ['GITHUB_RUN_ATTEMPT'], 'Report run/attempt mismatch')
        require(data['repository'] == 'RIG-AUDIO/SW2' and data['execution_mode'] == args.mode, 'Report repository/mode mismatch')
        require(data['juce_sha'] == JUCE_SHA and data['standalone'] is False, 'Dependency/format mismatch')
        require(data['source_parity']['production_parity'] == 'BYTE_IDENTICAL' and
                data['source_parity']['base_source_sha'] == args.base_source_sha and
                data['source_parity']['checkout_sha'] == args.source_sha, 'Missing product source parity')
        require(data['xcode_version'].startswith('Xcode 16.4\n') and data['compiler_version'] and data['macos_version'].startswith('15.'), 'Unreviewed native toolchain')
        expected_decision = {'preflight': 'PREFLIGHT_PASS', 'universal': 'BUILD_PASS_UNQUALIFIED',
            'smoke': 'SMOKE_PASS_NOT_FULLY_QUALIFIED', 'tests': 'NATIVE_PROFILE_PASS_NOT_FULLY_QUALIFIED'}[data['stage']]
        require(data['decision'] == expected_decision, 'Native stage did not pass')
        commands = {c['name']: c['exit_code'] for c in data['commands']}
        require(commands.get('ci-harness-regression') == 0, 'Missing harness controls')
        for name, value in data['file_hashes'].items():
            require(digest(owned_path(report_path.parent / name, report_path.parent)) == value, 'Evidence log checksum mismatch')
        if data['stage'] in ('smoke', 'tests'):
            require(data['native_host']['architecture'] == data['architecture'] and
                    data['native_host']['profile'] == data['profile'], 'Incorrect native instrumented host')
            require(data['actual_hosts'] == {'AU': 'PASS', 'VST3': 'PASS'}, 'Actual product hosts incomplete')
            require(data['au_discovery_exact'] is True and data['au_discovery_host'] == 'MATCHING_NATIVE_PROFILE_HOST', 'Missing native AU discovery')
            require((report_path.parent / 'au-cleanup.json').is_file(), 'Missing owned AU cleanup evidence')
            for fmt in ('AU', 'VST3'):
                require(commands.get('actual-' + fmt) == 0, 'Actual host failed')
                text = (report_path.parent / ('actual-' + fmt + '.log')).read_text(errors='replace')
                require('PASS: actual plugin two-instance audio/editor/state/reopen lifecycle' in text and
                        not any(m in text for m in ('FAIL:', 'Sanitizer:', 'runtime error:', 'JUCE Assertion failure', 'Leaked objects detected:')), 'Actual host diagnostic/incomplete evidence')
            cleanups = list(report_path.parent.glob('owned-login-*/cleanup.json'))
            require(bool(cleanups) and all(json.loads(p.read_text())['exit_code'] == 0 for p in cleanups), 'Login worker cleanup incomplete')
        if data['stage'] == 'tests':
            require(data['compile_commands_audit'] == 'PASS' and data['production_compile_commands_count'] > 10,
                    'Missing production/instrumentation audit')
            counts = inspect_ctest(report_path.parent / 'ctest.xml', data['test_count'])
            require(all(data[k] == v for k, v in counts.items()), 'CTest report counts disagree')
            require(commands.get('ctest') == 0 and commands.get('build-native-tests') == 0, 'Missing native regression execution')
            from native_reference import require_approved_authority
            require_approved_authority(None, data['architecture'], data['profile'])
            if data['profile'] in ('asan-ubsan', 'tsan'):
                require(data['sanitizer_negative_controls'] == 'PASS', 'Sanitizer sensitivity controls missing')
            if data['profile'] == 'Release':
                require(data['actual_universal_candidate_checked'] is True, 'Release must exercise the immutable universal candidate')
                require(commands.get('auval') == 0 and 'AU VALIDATION SUCCEEDED' in (report_path.parent / 'auval.log').read_text(), 'Strict auval did not pass')
                for fmt in ('AU', 'VST3'):
                    tool = data['external_validators'][fmt]
                    require(tool['strictness'] == 10 and tool['repeat'] == 2 and tool['gui_tests'] is True and tool['pluginval_exit_code'] == 0, 'pluginval validation scope changed')
                    require(commands.get('pluginval-' + fmt) == 0 and 'SUCCESS' in (report_path.parent / ('pluginval-' + fmt + '.log')).read_text(), 'pluginval did not complete')
                sdk = data['external_validators']['VST3']
                require(sdk['sdk_sha'] == SDK_SHA and sdk['sdk_exit_code'] == 0 and commands.get('validator-selftest') == 0 and commands.get('validator-extensive') == 0, 'Steinberg validator incomplete')
                match = re.search(r'Result: (\d+) tests passed, (\d+) tests failed', (report_path.parent / 'validator-extensive.log').read_text())
                require(match and int(match[1]) >= 100 and int(match[2]) == 0, 'Extensive VST3 results incomplete')
        found[key] = data
    require(set(found) == expected, 'Failed, missing, skipped or cancelled required stage')
    universal = found.get(('universal', 'arm64', 'Release'))
    if universal:
        require(universal['universal_build']['ci_bundle_signature'] == SEAL, 'Candidate seal status mismatch')
        require(universal['universal_build']['qualification_status'] == 'BUILD_PASS_UNQUALIFIED', 'Candidate cannot claim full qualification')
        require(universal['universal_build']['base_source_sha'] == args.base_source_sha and
                universal['universal_build']['source_sha'] == args.source_sha, 'Universal source provenance mismatch')
        require(set(universal['universal_build']['binaries']) == {'Swara XT.component', 'Swara XT.vst3'}, 'AU/VST3 candidate inventory required')
        for bundle in universal['universal_build']['binaries'].values():
            require(set(bundle['architectures']) == {'arm64', 'x86_64'}, 'Universal slices missing')
        for data in found.values():
            require(data['dependency_overlay'] == universal['dependency_overlay'], 'Dependency overlay differs across jobs')
        for key, data in found.items():
            if data['stage'] in ('smoke', 'tests'):
                require(data['candidate_archive_sha256'] == universal['candidate_archive_sha256'] and
                        data['candidate_manifest_sha256'] == universal['candidate_manifest_sha256'], 'Different candidates across native jobs')
    if args.mode == 'full':
        from native_reference import require_approved_authority
        require_approved_authority(None, None, None)
    decision = {'preflight': 'PREFLIGHT_PASS', 'build': 'BUILD_PASS_UNQUALIFIED',
                'smoke': 'SMOKE_PASS_NOT_FULLY_QUALIFIED', 'full': 'FULL_NATIVE_QUALIFICATION_PASS'}[args.mode]
    output = {'decision': decision, 'source_sha': args.source_sha, 'base_source_sha': args.base_source_sha,
              'run_id': os.environ['GITHUB_RUN_ID'], 'run_attempt': os.environ['GITHUB_RUN_ATTEMPT'],
              'mode': args.mode, 'required_stages': len(expected), 'formats': ['AU', 'VST3'], 'standalone': False,
              'candidate_archive_sha256': universal['candidate_archive_sha256'] if universal else None,
              'distribution_signing': 'NOT_RUN', 'notarization': 'NOT_RUN', 'distribution_approval': False}
    (root / 'qualification-gate.json').write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps(output, indent=2))
