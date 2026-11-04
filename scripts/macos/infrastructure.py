# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
"""Public provenance and runner-owned installation lifecycle."""
import json
import os
from pathlib import Path
import platform
import plistlib
import subprocess

from policy import (require, hosted_root, owned_path, revision, compare_public,
                    files_manifest, digest, check_bundle, SEAL)

AU_PARENT = Path('/Library/Audio/Plug-Ins/Components')
AU_PATH = AU_PARENT / 'Swara XT.component'


def cleanup_au(root, run):
    root = hosted_root(root)
    record = root / 'owned-au.json'
    if not record.exists():
        return
    owned = json.loads(record.read_text())
    require(owned['run_id'] == os.environ['GITHUB_RUN_ID'] and
            owned['run_attempt'] == os.environ['GITHUB_RUN_ATTEMPT'], 'AU cleanup provenance mismatch')
    require(owned['path'] == str(AU_PATH), 'Unexpected AU cleanup path')
    require(not AU_PARENT.is_symlink() and not AU_PATH.is_symlink(), 'AU cleanup path changed')
    require(AU_PATH.is_dir() and AU_PATH.stat().st_ino == owned['inode'], 'Owned AU directory was replaced or removed')
    run('remove-owned-ci-au', ['sudo', '-n', '/bin/rm', '-rf', '--', AU_PATH])
    require(not AU_PATH.exists() and not AU_PATH.is_symlink(), 'Owned AU cleanup failed')
    record.unlink()
    (root / 'au-cleanup.json').write_text(json.dumps({'decision': 'OWNED_AU_REMOVED', **owned}) + '\n')


class PublicInfrastructure:
    def verify_source(self):
        source = Path(__file__).resolve().parents[2]
        hosted_root(self.root, source)
        require(platform.system() == 'Darwin' and platform.machine() == self.args.arch, 'Native macOS architecture required')
        macos = subprocess.check_output(['sw_vers', '-productVersion'], text=True, timeout=30).strip()
        require(macos.startswith('15.'), 'Reviewed macOS 15 image required')
        self.report['macos_version'] = macos
        require(revision(self.args.source_sha) == os.environ['GITHUB_SHA'], 'Source input differs from checkout revision')
        revision(self.args.base_source_sha)
        require(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True, timeout=30).strip() == self.args.source_sha, 'Checkout SHA mismatch')
        require(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=source, text=True, timeout=30).strip(),
                'Public checkout must be clean before preflight')
        xcode = subprocess.check_output(['xcodebuild', '-version'], text=True, timeout=60)
        require(xcode.startswith('Xcode 16.4\n'), 'Reviewed Xcode 16.4 is unavailable')
        self.report['xcode_version'] = xcode.strip()
        self.report['compiler_version'] = subprocess.check_output(['xcrun', 'clang++', '--version'], text=True, timeout=60).strip()
        self.report['source_parity'] = compare_public(source, source, self.args.source_sha, self.args.base_source_sha)
        self.report['runner_image'] = {k: os.environ.get(k) for k in ('ImageOS', 'ImageVersion', 'RUNNER_ARCH')}
        self.report['sdk_version'] = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-version'], text=True).strip()
        for tool, expected in [('cmake', '3.31.6'), ('ninja', '1.11.1')]:
            value = subprocess.check_output([tool, '--version'], text=True).strip()
            require(expected in value, 'Unreviewed build frontend: ' + tool)
            self.report[tool + '_version'] = value
        self.version = self.report['source_parity']['version']
        self.report['version'] = self.version
        self.save()

    def register_owned_au(self, bundle, host):
        hosted_root(self.root)
        require(platform.system() == 'Darwin', 'AU installation requires ephemeral macOS')
        bundle = Path(bundle).resolve()
        require(bundle.is_relative_to(Path(os.environ['RUNNER_TEMP']).resolve()), 'AU must be a runner-owned candidate')
        require(not AU_PATH.exists() and not AU_PATH.is_symlink(), 'Refuse to overwrite an existing AU')
        for directory in (Path.home() / 'Library/Audio/Plug-Ins/Components', AU_PARENT):
            require(not directory.is_symlink(), 'Plugin destination cannot be a symlink')
            for existing in directory.glob('*.component'):
                info = existing / 'Contents/Info.plist'
                if info.is_file():
                    units = plistlib.loads(info.read_bytes()).get('AudioComponents', [])
                    require(not any(u.get('subtype') == 'SwXT' and u.get('manufacturer') == 'MnTr' for u in units),
                            'An existing SWARA XT AU must not be replaced')
        self.run('sudo-preflight', ['sudo', '-n', '/usr/bin/true'])
        self.run('verify-ci-AU-signature', ['codesign', '--verify', '--deep', '--strict', bundle])
        self.run('stage-ci-au-directory', ['sudo', '-n', '/bin/mkdir', '-p', AU_PARENT])
        # Atomic exclusive directory reservation: never adopt a pre-existing plugin.
        self.run('reserve-owned-ci-au', ['sudo', '-n', '/bin/mkdir', AU_PATH])
        record = {'path': str(AU_PATH), 'inode': AU_PATH.stat().st_ino,
                  'run_id': self.report['run_id'], 'run_attempt': self.report['run_attempt']}
        with (self.root / 'owned-au.json').open('x') as stream:
            json.dump(record, stream)
        self.run('stage-ci-system-au', ['sudo', '-n', '/usr/bin/ditto', bundle, AU_PATH])
        require(files_manifest(AU_PATH) == files_manifest(bundle), 'Installed AU inventory/checksum mismatch')
        user = subprocess.check_output(['id', '-un'], text=True, timeout=30).strip()
        code = self.run('refresh-ci-au-registrar', ['/usr/bin/killall', '-u', user, 'AudioComponentRegistrar'], expected=None)
        require(code in (0, 1), 'CI user AudioComponentRegistrar refresh failed')
        self.wait_for_ci_au(host, AU_PATH)

    def validate_native_bundles(self, bundles):
        self.report['native_bundles'] = {}
        for bundle in bundles:
            self.report['native_bundles'][bundle.name] = check_bundle(bundle, self.version, [self.args.arch])
            self.run('verify-native-' + ('AU' if bundle.suffix == '.component' else 'VST3'),
                     ['codesign', '--verify', '--deep', '--strict', bundle])

    def verify_native_host(self, host):
        host = owned_path(host, self.root)
        arches = subprocess.check_output(['lipo', '-archs', host], text=True, timeout=30).split()
        require(arches == [self.args.arch], 'Actual discovery/lifecycle host must match the native profile architecture')
        self.report['native_host'] = {'architecture': self.args.arch, 'sha256': digest(host),
                                      'profile': self.args.profile}

    def finish_evidence(self):
        require(not (self.root / 'owned-au.json').exists(), 'AU cleanup remains incomplete')
        if self.args.task in ('smoke', 'tests'):
            require(self.report.get('au_discovery_exact') is True, 'Actual AU discovery is required')
        self.report['file_hashes'] = {p.relative_to(self.root).as_posix(): digest(p)
             for p in sorted(self.root.iterdir()) if p.is_file() and p.suffix in ('.log', '.xml')}
        if (self.root / 'native-reference/manifest.json').exists():
            self.report['native_reference_manifest_sha256'] = digest(self.root / 'native-reference/manifest.json')
