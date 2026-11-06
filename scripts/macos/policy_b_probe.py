# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
"""Run the five original regressions against the production Policy B change."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import xml.etree.ElementTree as ET

from ci import Campaign, SOURCE
from parity_probe import once, required_commands
from policy import BASE_SHA, DUAL_INTEGRATION_TEST, DUAL_REFERENCE_TEST, digest, require

DUAL_DRIVERS = {
    'SwaraXTDualSvfSection2Tests': DUAL_REFERENCE_TEST,
    'SwaraXTDualSvfIntegrationAudit': DUAL_INTEGRATION_TEST,
}
TARGETS = ('SwaraXTAudioParityTests', *DUAL_DRIVERS, 'SwaraXTHostSrcExactParityTests',
           'SwaraXTDspFxIntegratedExactParityTests')


def current_reference_drivers(root):
    commands = []
    manifest = {}
    for target, relative in DUAL_DRIVERS.items():
        original = SOURCE / relative
        # Keep the repository selectors unchanged until every current anchor passes.
        text = once(original.read_text(), '(defined(__APPLE__) && defined(__x86_64__))',
                    'defined(__APPLE__)')
        if relative == DUAL_INTEGRATION_TEST:
            anchor = '        const auto t=renderSection2Reference(s,fx);'
            text = once(text, anchor, anchor + r'''
        std::printf("POLICY_B_DUAL native=%016llx expected=%016llx host=%016llx expected_host=%016llx\n",
            static_cast<unsigned long long>(q20Hash(t.undelayed)),
            static_cast<unsigned long long>(nativeGolden),
            static_cast<unsigned long long>(q20Hash(t.host)),
            static_cast<unsigned long long>(hostGolden));''')
        generated = root / original.name
        generated.write_text(text)
        manifest[relative] = {'original_sha256': digest(original), 'driver_sha256': digest(generated)}
        commands.append(f'''
get_target_property(sources {target} SOURCES)
list(LENGTH sources original_count)
list(FILTER sources EXCLUDE REGEX "(^|/){original.stem}[.]cpp$")
list(LENGTH sources remaining_count)
math(EXPR removed "${{original_count}}-${{remaining_count}}")
if(NOT removed EQUAL 1)
    message(FATAL_ERROR "Unexpected {target} driver inventory")
endif()
set_property(TARGET {target} PROPERTY SOURCES "${{sources}}")
target_sources({target} PRIVATE "{generated.as_posix()}")
target_include_directories({target} PRIVATE "{original.parent.as_posix()}")
''')
    install = root / 'policy-b-drivers.cmake'
    install.write_text('\n'.join(commands))
    (root / 'policy-b-entry.cmake').write_text(f'cmake_language(DEFER CALL include "{install.as_posix()}")\n')
    return manifest


class PolicyBProbe(Campaign):
    def run(self, name, argv, **kwargs):
        if name == 'configure':
            argv = [*argv, '-DCMAKE_PROJECT_SwaraXT_INCLUDE=' + str(self.root / 'policy-b-entry.cmake')]
        return super().run(name, argv, **kwargs)

    def execute(self):
        try:
            juce = self.prepare()
            self.report['current_reference_drivers'] = current_reference_drivers(self.root)
            build, _ = self.configure(juce)
            compile_db = json.loads((build / 'compile_commands.json').read_text())
            for entry in compile_db:
                require(not any(flag.startswith('-ffp-contract=') for flag in shlex.split(entry['command'])),
                        'Unexpected compiler-wide contraction flag')
            self.run('build-five-original-regressions',
                     ['cmake', '--build', build, '--parallel', '2', '--target', *TARGETS], timeout=7200)
            inventory = json.loads(subprocess.check_output(
                ['ctest', '--test-dir', build, '--show-only=json-v1'], text=True, timeout=60))
            commands = required_commands(inventory, TARGETS)
            self.report['target_executables'] = {}
            for target, command in commands.items():
                executable = Path(command[0])
                require(executable.is_file() and executable.resolve().is_relative_to(build), 'Invalid test executable: ' + target)
                slices = subprocess.check_output(['lipo', '-archs', executable], text=True, timeout=30).split()
                require(slices == [self.args.arch], 'Wrong test executable architecture: ' + target)
                self.report['target_executables'][target] = {'sha256': digest(executable), 'architecture': slices[0]}
            for target, relative in DUAL_DRIVERS.items():
                require(any(Path(entry['file']) == self.root / Path(relative).name
                            and f'CMakeFiles/{target}.dir/' in entry['command'] for entry in compile_db),
                        'Current-reference driver was not compiled: ' + target)
            self.save()
            junit = self.root / 'ctest.xml'
            code = self.run('ctest-policy-b', ['ctest', '--test-dir', build, '--verbose', '--no-tests=error',
                            '--test-output-size-passed', '16777216', '--test-output-size-failed', '16777216',
                            '-R', '^(' + '|'.join(TARGETS) + ')$', '--output-junit', junit], timeout=3600, expected=None)
            cases = {case.attrib['name']: case for case in ET.parse(junit).iter('testcase')}
            require(set(cases) == set(TARGETS), 'Incomplete targeted CTest inventory')
            self.report['tests'] = {name: 'PASS' if not any(case.find(tag) is not None for tag in ('failure', 'error', 'skipped'))
                                    else 'FAIL' for name, case in cases.items()}
            section2 = cases['SwaraXTDualSvfSection2Tests'].findtext('system-out', '')
            integration = cases['SwaraXTDualSvfIntegrationAudit'].findtext('system-out', '')
            section2_hashes = re.findall(r'(Dual(?:Relative|Independent)_\w+) hash=([a-f0-9]{16})', section2)
            anchors = re.findall(r'POLICY_B_DUAL native=([a-f0-9]{16}) expected=([a-f0-9]{16}) host=([a-f0-9]{16}) expected_host=([a-f0-9]{16})', integration)
            host = [(actual, expected) for _, _, actual, expected in anchors if int(expected, 16) != 0]
            self.report['dual_reference_inventory'] = {'section2_host_hashes': section2_hashes,
                'integration_native': [(actual, expected) for actual, expected, _, _ in anchors],
                'integration_host': host}
            require(len(dict(section2_hashes)) == 12 and len(anchors) == 48 and len(host) == 12,
                    'Incomplete current Dual reference inventory')
            require(all(actual == expected for actual, expected, _, _ in anchors)
                    and all(actual == expected for actual, expected in host), 'Current Dual integration anchor mismatch')
            require(code == 0 and set(self.report['tests'].values()) == {'PASS'}, 'Targeted Policy B regression failed')
            require(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=SOURCE, text=True).strip(),
                    'Repository source became dirty')
            self.finish_evidence()
            self.report['decision'] = 'POLICY_B_TARGETED_PASS'
        except Exception as error:
            self.report.update(decision='POLICY_B_TARGETED_FAIL', failure=str(error))
            raise
        finally:
            self.save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arch', choices=('arm64', 'x86_64'), required=True)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    args.profile, args.task, args.mode = 'Release', 'policy-b-probe', 'diagnostic'
    args.source_sha, args.base_source_sha = os.environ['GITHUB_SHA'], BASE_SHA
    PolicyBProbe(args).execute()
