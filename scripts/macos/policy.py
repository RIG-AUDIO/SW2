# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
"""Fail-closed public CI ownership, archive and public-source boundaries."""
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import signal
import subprocess
import tarfile
import zipfile

REPOSITORY = 'RIG-AUDIO/SW2'
JUCE_SHA = 'e18f7f506c0b96f2c738a0bcd7fe6467a5005ad8'
SDK_SHA = '9fad9770f2ae8542ab1a548a68c1ad1ac690abe0'
SEAL = 'CI_AD_HOC_SEALED_NOT_DEVELOPER_ID_SIGNED'
BASE_SHA = '5e7b967db0b52f773f382217a72c6c0c3ff6b8f7'


def require(condition, message='Qualification invariant failed'):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def revision(value):
    require(isinstance(value, str) and re.fullmatch('[0-9a-f]{40}', value), 'An exact commit SHA is required')
    return value


def owned_path(path, root):
    raw_root, raw_path = Path(root).absolute(), Path(path).absolute()
    root = raw_root.resolve()
    if raw_path.is_relative_to(raw_root):
        relative = raw_path.relative_to(raw_root)
    elif raw_path.is_relative_to(root):
        relative = raw_path.relative_to(root)
    else:
        raise RuntimeError('Path is outside its owned root')
    require(relative.parts and '..' not in relative.parts, 'Owned path must be strictly below its root')
    current = root
    for part in relative.parts:
        current = current / part
        require(not current.is_symlink(), 'Symlink in owned path')
    resolved = current.resolve()
    require(resolved != root and resolved.is_relative_to(root), 'Path is outside its owned root')
    return resolved


def hosted_root(root, source=None):
    require(os.environ.get('GITHUB_ACTIONS') == 'true', 'GitHub Actions is required')
    require(os.environ.get('GITHUB_REPOSITORY') == REPOSITORY, 'Public SW2 only')
    require(os.environ.get('SWARAXT_REPOSITORY_PRIVATE') == 'false', 'Public repository event required')
    require(os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted', 'Ephemeral GitHub-hosted runner required')
    root = owned_path(root, os.environ['RUNNER_TEMP'])
    if source is not None:
        source = Path(source).resolve()
        require(not root.is_relative_to(source) and not source.is_relative_to(root), 'Source and generated files must be separate')
    return root


def run_process(argv, *, cwd, env, stdout, timeout):
    """Bound process groups, including descendants, on timeout and cancellation."""
    process = subprocess.Popen(list(map(str, argv)), cwd=cwd, env=env, stdout=stdout,
                               stderr=subprocess.STDOUT, start_new_session=True)
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124
    finally:
        # Validators may leave a child even after their parent exits.
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=5)


def files_manifest(root):
    root = Path(root).resolve()
    result = {}
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), 'Candidate symlinks are not accepted')
        if path.is_file() and path.relative_to(root).as_posix() != 'provenance.json':
            result[path.relative_to(root).as_posix()] = digest(path)
    return result


def safe_extract_tar(archive, destination):
    destination = Path(destination)
    require(not destination.exists() and not destination.is_symlink(), 'Extraction destination must be new')
    with tarfile.open(archive, 'r:gz') as stream:
        members = stream.getmembers()
        require(bool(members) and len(members) < 10000, 'Invalid candidate archive inventory')
        total = 0
        names = set()
        for member in members:
            require(str(PurePosixPath(member.name)) == member.name.rstrip('/'), 'Noncanonical archive member')
            require(member.name not in names, 'Duplicate archive member')
            names.add(member.name)
            require(member.name == 'unsigned-universal' or member.name.startswith('unsigned-universal/'), 'Unexpected candidate archive root')
            require('\\' not in member.name and member.name.split('/').count('..') == 0, 'Unsafe archive path')
            require(member.isdir() or member.isfile(), 'Archive links and special files are forbidden')
            require((destination / member.name).resolve().is_relative_to(destination.resolve()), 'Archive path escapes extraction root')
            total += member.size
        require(total < 2 * 1024**3, 'Candidate archive exceeds size budget')
        destination.mkdir(mode=0o700)
        stream.extractall(destination, members=members, filter='data')


def safe_extract_zip(archive, destination):
    destination = Path(destination)
    require(not destination.exists(), 'Tool extraction destination must be new')
    with zipfile.ZipFile(archive) as stream:
        names = set()
        total = 0
        for item in stream.infolist():
            require(str(PurePosixPath(item.filename)) == item.filename.rstrip('/'), 'Noncanonical tool archive member')
            require(item.filename not in names, 'Duplicate tool archive member')
            names.add(item.filename)
            require('\\' not in item.filename and (destination / item.filename).resolve().is_relative_to(destination.resolve()), 'Unsafe tool archive path')
            kind = (item.external_attr >> 16) & 0o170000
            require(kind in (0, 0o040000, 0o100000), 'Tool archive links and special files forbidden')
            total += item.file_size
        require(total < 2 * 1024**3, 'Tool archive exceeds size budget')
        destination.mkdir(mode=0o700)
        stream.extractall(destination)
        for item in stream.infolist():
            path = destination / item.filename
            if path.is_file():
                path.chmod(0o755 if (item.external_attr >> 16) & 0o111 else 0o644)


def git_tree(source, ref):
    output = subprocess.check_output(['git', 'ls-tree', '-rz', '--full-tree', revision(ref)], cwd=source, timeout=60)
    return {entry.split(b'\t', 1)[1].decode(): entry.split(b'\t', 1)[0].decode()
            for entry in output.split(b'\0') if entry}


PARSER_HASHES = {'Source/Tuning/RealFromChars.h': 'fb47ca3421c701681d53025fe11e883ae9e4fcf376d904a7c34d2a9a772b7d96', 'third_party/fast_float/UPSTREAM.json': '43d3685de2707cb0830ca59b561dd33d214e0eefe31112b94bb7558a67bfc391', 'REUSE.toml': '53860a3e09d87db5dc318ef5e2ca51a93c035248aa4f595caf4fbef9674f5c14', 'LICENSES/MIT.txt': 'e562f3f974ced7e69dd1db77b820b36bcf8f30377f1aa105723fba449c53c4e6'}

def compare_public(source, baseline, checkout_sha, base_sha):
    require(base_sha == BASE_SHA, 'Approved SW2 base required')
    before, after = git_tree(source, BASE_SHA), git_tree(source, checkout_sha)
    differences = [p for p in sorted(set(before) | set(after)) if before.get(p) != after.get(p)]
    parser_paths = {'Source/Plugin/SwaraXtParameterLayout.cpp', 'Source/Tuning/TuningTable.cpp', 'Source/Tuning/RealFromChars.h', 'REUSE.toml', 'LICENSES/MIT.txt'}
    allowed_shared = {'CMakeLists.txt', 'Tests/CMakeLists.txt', 'Tests/Qualification.cmake', 'cmake/StandaloneMidiCapacity.cmake'}
    for path in differences:
        require(path in parser_paths or path.startswith('third_party/fast_float/') or path in allowed_shared or path.startswith(('scripts/macos/', 'Tests/Apple/', 'docs/macos/'))
                or path in ('.github/workflows/macos-qualification.yml', '.github/workflows/macos-development-build.yml'), 'Product source changed: ' + path)
    # Exact, reviewed parser-only exception; arbitrary production changes still fail.
    original = subprocess.check_output(['git', 'show', BASE_SHA + ':Source/Tuning/TuningTable.cpp'], cwd=source).decode()
    expected = original.replace('#include "Tuning/TuningTable.h"', '#include "Tuning/TuningTable.h"\n#include "Tuning/RealFromChars.h"')
    expected = expected.replace('std::from_chars(first, last, value, std::chars_format::general)', 'detail::realFromChars(first, last, value)')
    expected = expected.replace('std::from_chars(line.data(), line.data() + line.size(), value)', 'detail::realFromChars(line.data(), line.data() + line.size(), value)')
    require((Path(source) / 'Source/Tuning/TuningTable.cpp').read_text() == expected, 'Unreviewed tuning parser change')
    cutoff_original = subprocess.check_output(['git', 'show', BASE_SHA + ':Source/Plugin/SwaraXtParameterLayout.cpp'], cwd=source).decode()
    cutoff_expected = cutoff_original.replace('#include "Plugin/SwaraXtParameterLayout.h"', '#include "Plugin/SwaraXtParameterLayout.h"\n#include "Tuning/RealFromChars.h"')
    cutoff_expected = cutoff_expected.replace('std::from_chars(first, last, number, std::chars_format::general)', 'tuning::detail::realFromChars(first, last, number)')
    require((Path(source) / 'Source/Plugin/SwaraXtParameterLayout.cpp').read_text() == cutoff_expected, 'Unreviewed Filter Cutoff parser change')
    parser_hashes = PARSER_HASHES
    for path, expected_hash in parser_hashes.items():
        require(digest(Path(source) / path) == expected_hash, 'Unreviewed parser dependency: ' + path)
    vendor = Path(source) / 'third_party/fast_float'
    upstream = json.loads((vendor / 'UPSTREAM.json').read_text())
    require(upstream['commit'] == '05087a303dad9c98768b33c829d398223a649bc6', 'fast_float pin changed')
    require({p.relative_to(vendor).as_posix(): digest(p) for p in vendor.rglob('*') if p.is_file() and p.name != 'UPSTREAM.json'} == upstream['files'], 'fast_float source inventory changed')
    for path in differences:
        if path.startswith('third_party/'):
            require(path.startswith('third_party/fast_float/'), 'Existing dependency changed')
    trees = {}
    for path in ('Source', 'resources', 'third_party', 'Tests'):
        old = subprocess.run(['git', 'rev-parse', BASE_SHA + ':' + path], cwd=source,
                             text=True, capture_output=True, check=True).stdout.strip()
        new = subprocess.run(['git', 'rev-parse', checkout_sha + ':' + path], cwd=source,
                             text=True, capture_output=True, check=True).stdout.strip()
        if path == 'resources':
            require(old == new, 'Protected product tree changed: ' + path)
        trees[path] = {'base': old, 'checkout': new}
    version = re.search(r'project\(SwaraXT VERSION ([0-9.]+)', (Path(source) / 'CMakeLists.txt').read_text())
    require(version and version[1] == '1.3.0', 'Product version changed')
    return {'base_source_sha': BASE_SHA, 'checkout_sha': checkout_sha,
            'production_parity': 'EXACT_PARSER_PORTABILITY_EXCEPTION', 'actual_parser_source_sha256': digest(Path(source) / 'Source/Tuning/TuningTable.cpp'), 'actual_cutoff_source_sha256': digest(Path(source) / 'Source/Plugin/SwaraXtParameterLayout.cpp'), 'parser_dependency_hashes': parser_hashes, 'version': '1.3.0',
            'product_trees': trees,
            'integration_paths': differences}


def check_bundle(bundle, version, architectures):
    import plistlib
    bundle = Path(bundle)
    require(not bundle.is_symlink(), 'Plugin bundle cannot be linked')
    files_manifest(bundle)
    info = plistlib.loads((bundle / 'Contents/Info.plist').read_bytes())
    identifier = info['CFBundleIdentifier']
    suffix = '.component' if bundle.suffix == '.component' else '.vst3'
    require(identifier in ('com.MontroneDSP.SwaraXT', 'com.MontroneDSP.SwaraXT' + suffix), 'Unexpected plugin identifier')
    require(info['CFBundleShortVersionString'] == version and info['CFBundleVersion'] == version, 'Inconsistent bundle/product version')
    name = info['CFBundleExecutable']
    require(Path(name).name == name and name not in ('', '.', '..'), 'Invalid bundle executable name')
    executable = owned_path(bundle / 'Contents/MacOS' / name, bundle)
    arches = subprocess.check_output(['lipo', '-archs', executable], text=True, timeout=30).split()
    require(set(arches) == set(architectures), 'Incorrect executable architecture slices')
    if suffix == '.component':
        units = info.get('AudioComponents', [])
        require(len(units) == 1 and all(units[0].get(k) == v for k, v in
                [('type', 'aumu'), ('subtype', 'SwXT'), ('manufacturer', 'MnTr')]), 'Unexpected AU identity')
    return {'architectures': sorted(arches), 'executable_sha256': digest(executable),
            'bundle_identifier': identifier, 'version': version}
