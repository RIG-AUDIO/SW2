#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
"""Secret-free native/universal qualification. Signing is a separate local operation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import shlex
import subprocess
import sys
import tarfile
import time
import urllib.request

from login_context import run_login
from policy import (require, hosted_root, owned_path, run_process, compare_public, files_manifest,
                    check_bundle, safe_extract_zip, safe_extract_tar, revision, SEAL, SDK_SHA,
                    HOST_ARITHMETIC, PRODUCTION_PARITY)
from infrastructure import PublicInfrastructure
from dependency_overlay import apply as apply_dependency_overlay
from native_reference import BASELINE_SHA

JUCE_SHA = 'e18f7f506c0b96f2c738a0bcd7fe6467a5005ad8'
SOURCE = Path(__file__).resolve().parents[2]


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def native_test_binaries(build,listing,architecture):
    """Verify actual compiled test executables, not just intended CMake flags."""
    build=Path(build).resolve();result={}
    for test in listing['tests']:
        require(test.get('command'),'Registered test lacks an executable command: '+test['name'])
        executable=Path(test['command'][0]).resolve()
        if not executable.is_relative_to(build):continue  # External Python/CMake tools.
        require(executable.is_file(),'Mandatory test executable missing: '+str(executable))
        relative=executable.relative_to(build).as_posix()
        if relative in result:continue
        slices=subprocess.check_output(['lipo','-archs',executable],text=True,timeout=30).split()
        require(slices==[architecture],'Test executable is not the requested native architecture: '+relative)
        result[relative]={'architectures':slices,'sha256':digest(executable)}
    require(len(result)>10,'Missing mandatory native test executable inventory')
    return result


class Campaign(PublicInfrastructure):
    def __init__(self, args):
        self.args = args
        self.root = hosted_root(args.root, SOURCE)
        self.root.mkdir(parents=True, exist_ok=False)
        self.report = {'decision': 'INCOMPLETE', 'commands': [],
                       'architecture': platform.machine(), 'profile': args.profile,
                       'source_sha': os.environ['GITHUB_SHA'], 'juce_sha': JUCE_SHA,
                       'run_id': os.environ['GITHUB_RUN_ID'], 'run_attempt': os.environ['GITHUB_RUN_ATTEMPT'],
                       'base_source_sha': revision(args.base_source_sha),
                       'stage': args.task, 'execution_mode': args.mode, 'standalone': False,
                       'repository': os.environ['GITHUB_REPOSITORY'],
                       'unsupported_diagnostics': {'RTSan': 'NOT_SUPPORTED_BY_REVIEWED_APPLE_TOOLCHAIN',
                                                   'LSan': 'NOT_SUPPORTED_BY_APPLE_RUNTIME'},
                       'signing': 'LOCAL_ONLY_NOT_RUN', 'notarization': 'LOCAL_ONLY_NOT_RUN'}
        self.env = dict(os.environ)
        self.env['SWARAXT_NATIVE_PROFILE'] = args.profile
        self.env['SWARAXT_PUBLIC_SOURCE_SHA'] = args.base_source_sha
        if hasattr(args, 'candidate_archive_sha256'):
            self.report['candidate_archive_sha256'] = args.candidate_archive_sha256
            self.report['candidate_manifest_sha256'] = digest(args.candidate / 'provenance.json')
        self.save()

    def save(self):
        (self.root / 'report.json').write_text(json.dumps(self.report, indent=2) + '\n')

    def run(self, name, argv, timeout=1800, expected=0, env=None, login=False):
        argv = list(map(str, argv))
        print('START', name, flush=True)
        start = time.monotonic()
        if login:
            code = run_login(argv, self.root / (name + '.log'), self.root, timeout,
                             self.env if env is None else env)
        else:
            with (self.root / (name + '.log')).open('x') as log:
                try:
                    code = run_process(argv, cwd=self.root, env=self.env if env is None else env,
                                       stdout=log, timeout=timeout)
                except subprocess.TimeoutExpired:
                    code = 124
        self.report['commands'].append({'name': name, 'argv': argv, 'exit_code': code,
                                       'seconds': round(time.monotonic() - start, 2)})
        cleanup = getattr(code, 'cleanup', None)
        if cleanup is not None:
            self.report['commands'][-1]['process_cleanup'] = cleanup
        self.save()
        print('END', name, code, flush=True)
        require(cleanup is None or cleanup['success'],
                name + ' process cleanup failed; original exit code ' + str(code) + ' retained')
        if expected is not None and code != expected:
            print((self.root / (name + '.log')).read_text(errors='replace')[-12000:], flush=True)
            raise RuntimeError(name + ' failed; original log retained')
        return code

    def prepare(self):
        self.verify_source()
        require(platform.system() == 'Darwin' and platform.machine() == self.args.arch, "Qualification invariant: platform.system() == 'Darwin' and platform.machine() == self.args.arch")
        self.run('ci-harness-regression', [sys.executable, SOURCE / 'scripts/macos/test_ci.py'])
        self.run('floating-call-site-audit', [sys.executable, SOURCE / 'scripts/macos/audit_from_chars.py', '--output', self.root / 'floating-call-sites.json'])
        require(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=SOURCE, text=True, timeout=120).strip() == self.report['source_sha'], "Qualification invariant: subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=SOURCE, text=True).strip() == self.report['source_sha']")
        # The pinned historical dependency contains git:// nested URLs. Use
        # HTTPS for transport without changing any recorded dependency commit.
        self.run('source-submodules', ['git', '-C', SOURCE, '-c',
                 'url.https://github.com/.insteadOf=git://github.com/',
                 'submodule', 'update', '--init', '--recursive'])
        submodules = subprocess.check_output(['git', 'submodule', 'status', '--recursive'], cwd=SOURCE, text=True, timeout=120)
        require(all(line.startswith(' ') for line in submodules.splitlines()), "Qualification invariant: all(line.startswith(' ') for line in submodules.splitlines())")
        self.report['source_submodules'] = submodules.splitlines()
        require(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=SOURCE, text=True, timeout=120).strip(), "Qualification invariant: not subprocess.check_output(['git', 'status', '--porcelain'], cwd=SOURCE, text=True).strip()")
        for name, argv in [('system', ['sw_vers']), ('architecture', ['uname', '-m']),
                           ('cpu', ['sysctl', '-n', 'machdep.cpu.brand_string']),
                           ('xcode', ['xcodebuild', '-version']), ('compiler', ['xcrun', 'clang++', '--version']),
                           ('cmake-version', ['cmake', '--version'])]:
            self.run(name, argv)
        juce = self.root / 'JUCE'
        self.run('clone-juce', ['git', 'clone', '--filter=blob:none', '--no-checkout',
                               'https://github.com/juce-framework/JUCE.git', juce])
        self.run('checkout-juce', ['git', '-C', juce, 'checkout', '--detach', JUCE_SHA])
        require(subprocess.check_output(['git', '-C', juce, 'rev-parse', 'HEAD'], text=True, timeout=120).strip() == JUCE_SHA, "Qualification invariant: subprocess.check_output(['git', '-C', juce, 'rev-parse', 'HEAD'], text=True).strip() == JUCE_SHA")
        abi = self.root / 'channel-abi.cpp'
        abi.write_text('#include <juce_audio_basics/juce_audio_basics.h>\n#include <type_traits>\n'
                       'static_assert(std::is_same_v<std::underlying_type_t<juce::AudioChannelSet::ChannelType>, unsigned int>);\n'
                       'static_assert(sizeof(juce::AudioChannelSet::ChannelType) == sizeof(unsigned int));\n')
        self.run('original-channel-abi', ['xcrun', 'clang++', '-std=c++17', '-fsyntax-only',
                 '-DJUCE_GLOBAL_MODULE_SETTINGS_INCLUDED=1', '-DJUCE_STANDALONE_APPLICATION=1',
                 '-DJUCE_USE_CURL=0', '-DJUCE_WEB_BROWSER=0', '-I' + str(juce / 'modules'), abi])
        self.report['dependency_overlay'] = apply_dependency_overlay(juce, self.root)
        self.save()
        return juce

    def configure(self, juce, universal=False):
        build = self.root / 'build'
        flags = []
        if self.args.profile == 'asan-ubsan':
            flags = ['-fsanitize=address,undefined,vptr', '-fno-sanitize-recover=all', '-fno-omit-frame-pointer']
            self.env.update(ASAN_OPTIONS='detect_leaks=0:halt_on_error=1:abort_on_error=1',
                            UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
            self.report['leak_sanitizer'] = 'NOT_SUPPORTED_BY_APPLE_RUNTIME; separate leak qualification required'
        elif self.args.profile == 'tsan':
            flags = ['-fsanitize=thread', '-fno-omit-frame-pointer']
            self.env['TSAN_OPTIONS'] = 'halt_on_error=1:abort_on_error=1'
        if flags:
            self.controls(flags)
        self.sanitizer_flags = flags
        config = 'Debug' if self.args.profile == 'Debug' else 'Release'
        self.run('configure', ['cmake', '-S', SOURCE, '-B', build, '-G', 'Ninja',
                 '-DCMAKE_BUILD_TYPE=' + config, '-DCMAKE_EXPORT_COMPILE_COMMANDS=ON',
                 '-DCMAKE_OSX_ARCHITECTURES=' + ('x86_64;arm64' if universal else self.args.arch),
                 '-DCMAKE_OSX_DEPLOYMENT_TARGET=11.0', '-DSWARAXT_JUCE_DIR=' + str(juce),
                 '-DSWARA_BUILD_STANDALONE=OFF', '-DSWARA_BUILD_SKIN_EDITOR=OFF',
                 '-DSWARA_BUILD_TESTS=' + ('OFF' if universal else 'ON'),
                 '-DSWARAXT_SHARE_TEST_JUCE=OFF', '-DSWARAXT_SHARE_TEST_PRODUCTION=OFF',
                 '-DCMAKE_C_FLAGS=' + ' '.join(flags), '-DCMAKE_CXX_FLAGS=' + ' '.join(flags),
                 '-DCMAKE_OBJCXX_FLAGS=' + ' '.join(flags)])
        cache = (build / 'CMakeCache.txt').read_text()
        for setting in ['SWARA_BUILD_STANDALONE:BOOL=OFF', 'SWARA_BUILD_SKIN_EDITOR:BOOL=OFF']:
            require(setting in cache, 'Qualification invariant: setting in cache')
        if not universal:
            shutil.copy2(build / 'compile_commands.json', self.root / 'compile-commands.json')
        return build, config

    def native_reference(self, juce, config):
        from native_reference import require_approved_authority
        return require_approved_authority(SOURCE, self.args.arch, self.args.profile)

    def controls(self, flags):
        samples = {'asan-ubsan': [
            ('asan', '#include <cstdlib>\nint main(int n,char**){auto*p=(volatile int*)malloc(sizeof(int));p[n+3]=9;free((void*)p);}', 'AddressSanitizer'),
            ('ubsan', '#include <climits>\nint main(int n,char**){volatile int a=INT_MAX;return a+n;}', 'runtime error:')],
            'tsan': [('tsan', '#include <thread>\nint x; void f(){for(int i=0;i<100000;++i)++x;} int main(){std::thread a(f),b(f);a.join();b.join();return 0;}', 'ThreadSanitizer: data race')]}
        for label, text, diagnostic in samples[self.args.profile]:
            source = self.root / (label + '-negative.cpp')
            source.write_text(text + '\n')
            binary = self.root / (label + '-negative')
            self.run(label + '-control-build', ['xcrun', 'clang++', '-std=c++17', '-O1', '-g', *flags, source, '-o', binary])
            code = self.run(label + '-negative-control', [binary], expected=None)
            require(code != 0 and diagnostic in (self.root / (label + '-negative-control.log')).read_text(), 'Sanitizer sensitivity control failed')
        self.report['sanitizer_negative_controls'] = 'PASS'
        self.save()

    def bundles(self, build, config):
        return [build / 'SwaraXT_artefacts' / config / 'AU/Swara XT.component',
                build / 'SwaraXT_artefacts' / config / 'VST3/Swara XT.vst3']

    def seal_ci_bundles(self, bundles):
        # Ad-hoc seals use no certificate, private key or Apple account. They
        # make complete bundles verifiable on both native CI architectures.
        require(os.environ.get('GITHUB_ACTIONS') == 'true', "Qualification invariant: os.environ.get('GITHUB_ACTIONS') == 'true'")
        for bundle in bundles:
            fmt = 'AU' if bundle.suffix == '.component' else 'VST3'
            self.run('seal-ci-' + fmt, ['codesign', '--force', '--sign', '-', '--timestamp=none', bundle])
            self.run('verify-ci-seal-' + fmt, ['codesign', '--verify', '--deep', '--strict', bundle])
        self.report['ci_bundle_signature'] = SEAL
        self.save()

    def register_ci_au(self, bundle, host):
        self.register_owned_au(bundle, host)

    def wait_for_ci_au(self, host, installed):
        # System auval may dlopen the AU while enumerating. A sanitized AU must
        # be discovered by the equivalently instrumented host, whose sanitizer
        # runtime is present at process startup. Never ignore a scanner crash.
        for attempt in range(16):
            if attempt:
                time.sleep(2)
            name = 'au-discovery-' + str(attempt)
            code = self.run(name, [host, 'AU', installed, '--discover-only'],
                            login=True, expected=None, timeout=120)
            text = (self.root / (name + '.log')).read_text()
            if any(marker in text for marker in ('runtime error:', 'AddressSanitizer:',
                    'ThreadSanitizer:', 'UndefinedBehaviorSanitizer:',
                    'Interceptors are not working.', 'JUCE Assertion failure')):
                raise RuntimeError('Sanitizer/assertion failure during AU discovery; original log retained')
            if code == 0 and text.splitlines().count('AU_DISCOVERY_EXACT_PASS') == 1:
                self.report['au_discovery_exact'] = True
                self.report['au_discovery_host'] = 'MATCHING_NATIVE_PROFILE_HOST'
                self.save()
                return
            if code != 2 or text.splitlines().count('AU_DISCOVERY_PENDING') != 1:
                raise RuntimeError('Actual AU discovery failed; original host log retained')
        raise RuntimeError('Actual AU registration did not expose exactly one SWARA XT type')

    def universal(self, juce):
        build, config = self.configure(juce, universal=True)
        self.run('build-universal', ['cmake', '--build', build, '--target', 'SwaraXT_AU', 'SwaraXT_VST3', '--parallel', '2'], timeout=7200)
        self.seal_ci_bundles(self.bundles(build, config))
        stage = self.root / 'unsigned-universal'
        stage.mkdir()
        binaries = {}
        for bundle in self.bundles(build, config):
            info = plistlib.loads((bundle / 'Contents/Info.plist').read_bytes())
            executable = bundle / 'Contents/MacOS' / info['CFBundleExecutable']
            arches = subprocess.check_output(['lipo', '-archs', executable], text=True, timeout=120).split()
            require(set(arches) == {'x86_64', 'arm64'}, "Qualification invariant: set(arches) == {'x86_64', 'arm64'}")
            require(info['CFBundleIdentifier'] == ('com.MontroneDSP.SwaraXT' + ('.vst3' if bundle.suffix == '.vst3' else '.component')) or info['CFBundleIdentifier'] == 'com.MontroneDSP.SwaraXT', "Qualification invariant: info['CFBundleIdentifier'] == ('com.MontroneDSP.SwaraXT' + ('.vst3' if bundle.suffix == '.vst3' else '.component')) or i")
            require(info['CFBundleShortVersionString'] == self.version, 'Product version mismatch')
            binaries[bundle.name] = check_bundle(bundle, self.version, ['arm64', 'x86_64'])
            shutil.copytree(bundle, stage / bundle.name, symlinks=True)
        commands = json.loads((build / 'compile_commands.json').read_text())
        compiled = {}
        for entry in commands:
            path = Path(entry['file'])
            if path.is_file():
                compiled[str(path)] = digest(path)
        for path in [SOURCE / 'Source/Tuning/RealFromChars.h', *(SOURCE / 'third_party/fast_float').rglob('*.h')]:
            compiled[str(path)] = digest(path)
        for relative in HOST_ARITHMETIC:
            path = SOURCE / relative
            compiled[str(path)] = digest(path)
            require(compiled[str(path)] == self.report['source_parity']['host_arithmetic_source_sha256'][relative],
                    'Host arithmetic source differs from reviewed checkout')
        compiled_manifest = {'checkout_sha': self.report['source_sha'], 'files': compiled,
                             'actual_parser_source_sha256': digest(SOURCE / 'Source/Tuning/TuningTable.cpp'),
                             'actual_cutoff_source_sha256': digest(SOURCE / 'Source/Plugin/SwaraXtParameterLayout.cpp'),
                             'parity': PRODUCTION_PARITY}
        compiled_file = self.root / 'compiled-source-manifest.json'
        compiled_file.write_text(json.dumps(compiled_manifest, indent=2) + '\n')
        shutil.copy2(compiled_file, stage / compiled_file.name)
        self.report['compiled_source_manifest_sha256'] = digest(compiled_file)
        self.report['actual_parser_source_sha256'] = compiled_manifest['actual_parser_source_sha256']
        self.report['actual_cutoff_source_sha256'] = compiled_manifest['actual_cutoff_source_sha256']
        files = files_manifest(stage)
        manifest = {'source_sha': self.report['source_sha'], 'juce_sha': JUCE_SHA,
                    'dependency_overlay': self.report['dependency_overlay'],
                    'source_submodules': self.report['source_submodules'],
                    'xcode_version': self.report['xcode_version'], 'compiler_version': self.report['compiler_version'],
                    'run_id': self.report['run_id'], 'run_attempt': self.report['run_attempt'],
                    'base_source_sha': self.args.base_source_sha, 'version': self.version,
                    'compiled_source_manifest_sha256': self.report['compiled_source_manifest_sha256'],
                    'actual_parser_source_sha256': self.report['actual_parser_source_sha256'],
                    'actual_cutoff_source_sha256': self.report['actual_cutoff_source_sha256'],
                    'qualification_status': 'BUILD_PASS_UNQUALIFIED', 'formats': ['AU', 'VST3'],
                    'standalone': False, 'ci_bundle_signature': self.report['ci_bundle_signature'],
                    'binaries': binaries, 'files': files,
                    'distribution_status': 'UNSIGNED_UNQUALIFIED_CANDIDATE'}
        (stage / 'provenance.json').write_text(json.dumps(manifest, indent=2) + '\n')
        archive = self.root / 'swaraxt-unsigned-universal.tar.gz'
        with tarfile.open(archive, 'w:gz') as stream:
            stream.add(stage, arcname='unsigned-universal')
        (self.root / 'archive-sha256.txt').write_text(digest(archive) + '  ' + archive.name + '\n')
        self.report['universal_build'] = manifest
        self.report['candidate_archive_sha256'] = digest(archive)
        self.report['candidate_manifest_sha256'] = digest(stage / 'provenance.json')

    def tests(self, juce):
        build, config = self.configure(juce)
        # Check the OS-specific memory-protection harness before compiling the
        # full application matrix. The faulting negative controls must run too.
        self.run('build-platform-preflight', ['cmake', '--build', build, '--target',
                 'AvrlibHdUpperRegisterOscillatorTests', '--parallel', '2'])
        self.run('platform-preflight', ['ctest', '--test-dir', build, '--output-on-failure',
                 '--no-tests=error', '-R', '^AvrlibHdUpperRegisterOscillatorTests$'])
        self.run('build-host-preflight', ['cmake', '--build', build, '--target',
                 'SwaraXTApplePluginHost', 'SwaraXT_AU', 'SwaraXT_VST3', '--parallel', '2'], timeout=7200)
        self.seal_ci_bundles(self.bundles(build, config))
        host = build / 'Tests/Apple/SwaraXTApplePluginHost_artefacts' / config / 'SwaraXTApplePluginHost'
        require(host.is_file(), 'Qualification invariant: host.is_file()')
        bundles = self.verified_candidate() if self.args.profile == 'Release' else self.bundles(build, config)
        if self.args.profile != 'Release':
            self.validate_native_bundles(bundles)
        validation_passed = self.actual_hosts(host, bundles, external=self.args.profile == 'Release')
        self.report['native_validation'] = 'PASS' if validation_passed else 'FAIL'
        self.save()
        self.regressions(build,juce,config)
        return validation_passed

    def regressions(self,build,juce,config):
        """Build and audit the full inventory before running CTest."""
        self.run('build-native-tests', ['cmake', '--build', build, '--target', 'SwaraXTQualificationTests',
                 '--parallel', '2', '--', '-k', '0'], timeout=10800)
        commands = json.loads((build / 'compile_commands.json').read_text())
        production = [entry for entry in commands if Path(entry['file']).is_relative_to(SOURCE / 'Source')]
        require(len(production) > 10, 'Qualification invariant: len(production) > 10')
        if self.args.profile in ('asan-ubsan', 'tsan'):
            required = set(self.sanitizer_flags)
            require(required, 'Sanitizer profile has no configured flags')
            for entry in commands:
                require(required.issubset(shlex.split(entry['command'])),
                        'Missing required sanitizer flags: ' + entry['file'])
        self.report['compile_commands_count'] = len(commands)
        self.report['production_compile_commands_count'] = len(production)
        self.report['compile_commands_audit'] = 'PASS'
        listing = json.loads(subprocess.check_output(['ctest', '--test-dir', build, '--show-only=json-v1'], text=True, timeout=60))
        require(len(listing['tests']) > 50, "Qualification invariant: len(listing['tests']) > 50")
        require(not any(p['name'] == 'DISABLED' and p['value'] for t in listing['tests'] for p in t['properties']), 'Disabled tests require explicit review')
        inventory = self.root / 'ctest-inventory.json'
        inventory.write_text(json.dumps(listing, indent=2) + '\n')
        self.report['test_count'] = len(listing['tests'])
        self.report['native_test_binaries'] = native_test_binaries(build,listing,self.args.arch)
        shard = getattr(self.args, 'tsan_shard', None)
        test_filter = []
        if shard:
            from tsan_shards import INPUT_FILES, SHARD_B, inspect_shard_junit, select_shards
            assigned = select_shards(listing, self.args.profile, self.args.arch)[shard]
            test_filter = ['-E' if shard == 'a' else '-R', '^(' + '|'.join(map(re.escape, sorted(SHARD_B))) + ')$']
            filtered = json.loads(subprocess.check_output(['ctest', '--test-dir', build,
                '--show-only=json-v1', *test_filter], text=True, timeout=60))['tests']
            require(len(filtered) == len(assigned) and {test['name'] for test in filtered} == assigned,
                    'CTest selected the wrong Intel TSan shard')
            require(json.loads((self.root / 'compile-commands.json').read_text()) == commands,
                    'Recorded compile database differs from audited commands')
            self.report['tsan_shard_inputs'] = {name: digest(self.root / name) for name in INPUT_FILES}
        # Intel TSan runs the complete board/SRC endpoint matrix much slower
        # than the other profiles. Budget 270 minutes for the unchanged suite;
        # its individual 120-second case watchdogs still reject stalled cases.
        # The Intel diagnostics workflow shards execution to fit the job cap.
        test_timeout = 16200 if self.args.arch == 'x86_64' and self.args.profile == 'tsan' else 10800
        self.report['ctest_timeout_seconds'] = test_timeout
        self.save()
        # Every registered regression must pass; this helper does not admit hosts.
        ctest = ['ctest', '--test-dir', build, '--output-on-failure', '--no-tests=error',
                 '--test-output-size-passed', '16777216', '--test-output-size-failed', '16777216',
                 '--parallel', '1', '--output-junit', self.root / 'ctest.xml', *test_filter]
        if self.args.profile == 'tsan':
            ctest.append('--verbose')  # Preserve current-case progress if interrupted.
        test_code = self.run('ctest', ctest, timeout=test_timeout, expected=None)
        require(test_code == 0, 'Native regression qualification failed')
        if shard:
            self.report.update(inspect_shard_junit(self.root / 'ctest.xml', assigned))
        else:
            from gate import inspect_ctest
            self.report.update(inspect_ctest(self.root / 'ctest.xml', len(listing['tests'])))
        self.native_reference(juce, config)

    def verified_candidate(self):
        candidate = owned_path(self.args.candidate, os.environ['RUNNER_TEMP'])
        manifest = json.loads((candidate / 'provenance.json').read_text())
        require(manifest['source_sha'] == self.report['source_sha'], 'Candidate checkout revision mismatch')
        require(manifest['base_source_sha'] == self.args.base_source_sha, 'Candidate public revision mismatch')
        require(manifest['run_id'] == self.report['run_id'] and manifest['run_attempt'] == self.report['run_attempt'], 'Candidate run/attempt mismatch')
        require(manifest['version'] == self.version and manifest['formats'] == ['AU', 'VST3'], 'Candidate product mismatch')
        require(manifest['juce_sha'] == JUCE_SHA and not manifest['standalone'], 'Candidate dependencies/formats mismatch')
        require(manifest['dependency_overlay'] == self.report['dependency_overlay'], 'Candidate dependency overlay mismatch')
        require(manifest['ci_bundle_signature'] == SEAL, 'Candidate must use CI ad-hoc sealing')
        require(files_manifest(candidate) == manifest['files'], 'Candidate file inventory/checksum mismatch')
        bundles = [candidate / 'Swara XT.component', candidate / 'Swara XT.vst3']
        for bundle in bundles:
            require(check_bundle(bundle, self.version, ['arm64', 'x86_64']) == manifest['binaries'][bundle.name], 'Candidate executable identity mismatch')
            self.run('verify-candidate-' + ('AU' if bundle.suffix == '.component' else 'VST3'), ['codesign', '--verify', '--deep', '--strict', bundle])
        self.report['actual_universal_candidate_checked'] = True
        self.report['candidate_manifest_sha256'] = digest(candidate / 'provenance.json')
        self.report['candidate_archive_sha256'] = self.args.candidate_archive_sha256
        require(self.report['candidate_archive_sha256'] and len(self.report['candidate_archive_sha256']) == 64, 'Missing verified candidate archive binding')
        return bundles

    def actual_hosts(self, host, bundles, external=False):
        from infrastructure import cleanup_au, AU_PATH
        self.verify_native_host(host)
        host_codes = []
        self.report.setdefault('actual_hosts', {})
        for bundle in bundles:
            fmt = 'AU' if bundle.suffix == '.component' else 'VST3'
            try:
                if fmt == 'AU':
                    self.register_ci_au(bundle, host)
                    bundle = AU_PATH
                    if external:
                        host_codes.append(self.run('auval', ['auval', '-v', 'aumu', 'SwXT', 'MnTr', '-strict', '-r', '2'], expected=None, timeout=900, login=True))
                if external:
                    host_codes.append(self.external_validation(bundle, fmt))
                code = self.run('actual-' + fmt, [host, fmt, bundle, self.root / (fmt + '-editor.png')], expected=None, timeout=600, login=True)
                text = (self.root / ('actual-' + fmt + '.log')).read_text(errors='replace')
                require(code == 0 and 'PASS: actual plugin two-instance audio/editor/state/reopen lifecycle' in text, 'Actual native plugin lifecycle incomplete')
                require(not any(m in text for m in ('FAIL:', 'Sanitizer:', 'runtime error:', 'JUCE Assertion failure', 'Leaked objects detected:')), 'Actual host runtime diagnostic')
                self.report['actual_hosts'][fmt] = 'PASS'
                host_codes.append(code)
            finally:
                if fmt == 'AU':
                    cleanup_au(self.root, self.run)
        return bool(host_codes) and all(code == 0 for code in host_codes)


    def smoke(self, juce):
        build, config = self.configure(juce)
        self.run('build-smoke-tools', ['cmake', '--build', build, '--target',
                 'SwaraXTApplePluginHost', 'SwaraXTChannelTypeContractTests', 'SwaraXTTuningTableTests', 'SwaraXTTuningFuzzRegressionTests', 'SwaraXTQuantizerTests', 'SwaraXTCutoffParameterTests', '--parallel', '2'])
        self.run('channel-domain-smoke', ['ctest', '--test-dir', build, '--output-on-failure',
                 '--no-tests=error', '-R', '^(SwaraXTChannelTypeContractTests|SwaraXTTuningTableTests|SwaraXTTuningFuzzRegressionTests|SwaraXTQuantizerTests|SwaraXTCutoffParameterTests)$'])
        host = build / 'Tests/Apple/SwaraXTApplePluginHost_artefacts' / config / 'SwaraXTApplePluginHost'
        require(self.actual_hosts(host, self.verified_candidate()), 'Actual native product smoke failed')
        self.report['qualification_scope'] = 'EARLY_NATIVE_HOST_SMOKE_ONLY'

    def external_validation(self, bundle, fmt):
        pluginval = self.root / 'pluginval-tool/pluginval.app/Contents/MacOS/pluginval'
        if not pluginval.exists():
            archive = self.root / 'pluginval.zip'
            with urllib.request.urlopen('https://github.com/Tracktion/pluginval/releases/download/v1.0.4/pluginval_macOS.zip', timeout=120) as response, archive.open('xb') as output:
                shutil.copyfileobj(response, output)
            require(digest(archive) == '3c4c533bda0c5059eea3ddaea752d757ee2025041f0f47e6bcb0e87f6082b29f', "Qualification invariant: digest(archive) == '3c4c533bda0c5059eea3ddaea752d757ee2025041f0f47e6bcb0e87f6082b29f'")
            safe_extract_zip(archive, self.root / 'pluginval-tool')
            require(self.args.arch in subprocess.check_output(['lipo', '-archs', pluginval], text=True, timeout=120).split(), "Qualification invariant: self.args.arch in subprocess.check_output(['lipo', '-archs', pluginval], text=True).split()")
            self.run('verify-pluginval', ['codesign', '--verify', '--deep', '--strict', self.root / 'pluginval-tool/pluginval.app'])
        # Keep the complete strictness-10 stress campaign. Its child auval can
        # be quiet longer than the default 30-second inactivity watchdog.
        self.report['pluginval_inactivity_timeout_ms'] = 120000
        self.save()
        code = self.run('pluginval-' + fmt, [pluginval, '--strictness-level', '10', '--repeat', '2',
                        '--timeout-ms', '120000', '--randomise', '--verbose', '--random-seed', '0x53776172',
                        '--output-dir', self.root / ('pluginval-' + fmt), '--validate', bundle],
                        timeout=1800, expected=None, login=True)
        self.report.setdefault('external_validators', {})[fmt] = {
            'pluginval_archive_sha256': '3c4c533bda0c5059eea3ddaea752d757ee2025041f0f47e6bcb0e87f6082b29f',
            'pluginval_binary_sha256': digest(pluginval), 'pluginval_exit_code': code,
            'pluginval_version': '1.0.4',
            'strictness': 10, 'repeat': 2, 'gui_tests': True}
        require(code != 0 or 'SUCCESS' in (self.root / ('pluginval-' + fmt + '.log')).read_text(errors='replace'), 'Incomplete pluginval results')
        if fmt == 'VST3':
            sdk = self.root / 'vst3sdk'
            sdk_sha = SDK_SHA
            self.run('clone-sdk', ['git', 'clone', '--filter=blob:none', '--no-checkout',
                                  'https://github.com/steinbergmedia/vst3sdk.git', sdk])
            self.run('checkout-sdk', ['git', '-C', sdk, 'checkout', '--detach', sdk_sha])
            require(subprocess.check_output(['git', '-C', sdk, 'rev-parse', 'HEAD'], text=True, timeout=30).strip() == SDK_SHA,
                    'VST3 SDK revision mismatch')
            self.run('sdk-submodules', ['git', '-C', sdk, 'submodule', 'update', '--init', '--recursive',
                                       'base', 'cmake', 'pluginterfaces', 'public.sdk'])
            self.report['vst3sdk_sha'] = sdk_sha
            project = self.root / 'validator-project'
            project.mkdir()
            shutil.copy2(SOURCE / 'Tests/Apple/Validator.cmake', project / 'CMakeLists.txt')
            build = self.root / 'validator-build'
            self.run('configure-validator', ['cmake', '-S', project, '-B', build, '-G', 'Ninja',
                     '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_OSX_ARCHITECTURES=' + self.args.arch,
                     '-DCMAKE_OSX_DEPLOYMENT_TARGET=11.0', '-DSWARAXT_SDK_ROOT=' + str(sdk)])
            self.run('build-validator', ['cmake', '--build', build, '--target', 'validator', '--parallel', '2'])
            validator = build / 'bin/Release/validator'
            require(subprocess.check_output(['lipo', '-archs', validator], text=True, timeout=30).split() == [self.args.arch],
                    'Steinberg validator is not the native architecture')
            self.run('validator-selftest', [validator, '-selftest'])
            sdk_code = self.run('validator-extensive', [validator, '-e', bundle], expected=None, timeout=1800)
            self.report['external_validators'][fmt].update(sdk_sha=SDK_SHA, sdk_binary_sha256=digest(validator), sdk_exit_code=sdk_code)
            if sdk_code != 0:
                code = sdk_code
        return code

    def execute(self):
        try:
            juce = self.prepare()
            validation_passed = True
            if self.args.task == 'universal':
                self.universal(juce)
            elif self.args.task == 'preflight':
                build, config = self.configure(juce)
                self.run('build-channel-contract', ['cmake', '--build', build, '--target', 'SwaraXTChannelTypeContractTests', '--parallel', '2'])
                self.run('channel-contract', ['ctest', '--test-dir', build, '--output-on-failure', '--no-tests=error', '-R', '^SwaraXTChannelTypeContractTests$'])
            elif self.args.task == 'smoke':
                self.smoke(juce)
            elif self.args.task == 'tests':
                validation_passed = self.tests(juce)
            require(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=SOURCE, text=True, timeout=120).strip(), "Qualification invariant: not subprocess.check_output(['git', 'status', '--porcelain'], cwd=SOURCE, text=True).strip()")
            self.finish_evidence()
            require(validation_passed, 'Mandatory native validation failed; validator and regression evidence retained')
            self.report['decision'] = {'preflight': 'PREFLIGHT_PASS', 'universal': 'BUILD_PASS_UNQUALIFIED',
                'smoke': 'SMOKE_PASS_NOT_FULLY_QUALIFIED', 'tests': 'NATIVE_PROFILE_PASS_NOT_FULLY_QUALIFIED'}[self.args.task]
        except BaseException as error:
            self.report['decision'] = 'QUALIFICATION_FAILED'
            self.report['failure'] = str(error)
            raise
        finally:
            self.save()


def main():
    import signal
    def cancelled(signum, frame):
        raise RuntimeError('CI process cancelled: ' + str(signum))
    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGINT, cancelled)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('task', choices=['preflight', 'universal', 'smoke', 'tests', 'cleanup', 'gate'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--source-sha', required=True)
    parser.add_argument('--base-source-sha', required=True)
    parser.add_argument('--mode', choices=['preflight', 'build', 'smoke', 'full'], required=True)
    parser.add_argument('--arch', choices=['x86_64', 'arm64'])
    parser.add_argument('--profile', choices=['Release', 'Debug', 'asan-ubsan', 'tsan'], default='Release')
    parser.add_argument('--candidate-download', type=Path)
    args = parser.parse_args()
    require(revision(args.source_sha) == os.environ['GITHUB_SHA'], 'Source revision input mismatch')
    revision(args.base_source_sha)
    require(os.environ.get('GITHUB_REPOSITORY') == 'RIG-AUDIO/SW2' and
            os.environ.get('SWARAXT_REPOSITORY_PRIVATE') == 'false', 'Public SW2 execution only')
    if args.task == 'gate':
        from gate import evaluate
        root = hosted_root(args.root, SOURCE)
        try:
            evaluate(root, args)
        except Exception as error:
            root.mkdir(parents=True, exist_ok=True)
            (root / 'qualification-gate.json').write_text(json.dumps({
                'decision': 'QUALIFICATION_FAILED', 'source_sha': args.source_sha,
                'base_source_sha': args.base_source_sha, 'mode': args.mode,
                'run_id': os.environ['GITHUB_RUN_ID'], 'run_attempt': os.environ['GITHUB_RUN_ATTEMPT'],
                'failure': str(error)}) + '\n')
            raise
        return
    if args.task == 'cleanup':
        from infrastructure import cleanup_au
        root = hosted_root(args.root)
        if root.exists():
            def cleanup_run(name, argv):
                with (root / (name + '-fallback.log')).open('x') as log:
                    result = run_process(argv, cwd=root, env=os.environ.copy(), stdout=log, timeout=120)
                    require(result == 0 and result.cleanup['success'],
                            'Fallback AU cleanup failed')
            cleanup_au(root, cleanup_run)
        return
    require(args.arch in ('arm64', 'x86_64'), 'Native architecture is required')
    require(args.task != 'universal' or args.profile == 'Release', 'Universal candidate must use Release')
    if args.task in ('smoke', 'tests'):
        require(args.candidate_download is not None, 'Candidate archive is required')
        download = owned_path(args.candidate_download, os.environ['RUNNER_TEMP'])
        archive = download / 'swaraxt-unsigned-universal.tar.gz'
        require(not archive.is_symlink() and archive.is_file(), 'Candidate archive is missing or linked')
        parts = (download / 'archive-sha256.txt').read_text().split()
        require(len(parts) == 2 and parts[1] == archive.name and parts[0] == digest(archive), 'Candidate archive checksum mismatch')
        extracted = Path(os.environ['RUNNER_TEMP']) / 'verified-candidate'
        safe_extract_tar(archive, extracted)
        args.candidate = extracted / 'unsigned-universal'
        args.candidate_archive_sha256 = parts[0]
        manifest = json.loads((args.candidate / 'provenance.json').read_text())
        require(manifest['source_sha'] == args.source_sha and manifest['base_source_sha'] == args.base_source_sha,
                'Extracted candidate source provenance mismatch')
        require(manifest['run_id'] == os.environ['GITHUB_RUN_ID'] and
                manifest['run_attempt'] == os.environ['GITHUB_RUN_ATTEMPT'], 'Extracted candidate run mismatch')
        require(files_manifest(args.candidate) == manifest['files'], 'Extracted candidate inventory mismatch')
    Campaign(args).execute()


if __name__ == '__main__':
    main()
