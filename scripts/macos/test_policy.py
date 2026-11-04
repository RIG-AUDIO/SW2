# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
"""Negative admission controls; executed only by an authorized CI preflight."""
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

from policy import require, revision, owned_path, hosted_root, safe_extract_tar, safe_extract_zip
from gate import evaluate, inspect_ctest


class PublicPolicyTests(unittest.TestCase):
    def test_required_checks_are_explicit_runtime_errors(self):
        with self.assertRaises(RuntimeError): require(False, 'must fail')
        for value in ('main', 'a' * 39, 'A' * 40, None, 'a' * 40 + ';anything'):
            with self.assertRaises(RuntimeError): revision(value)
        self.assertEqual(revision('a' * 40), 'a' * 40)

    def test_hosted_private_runner_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'RIG-AUDIO/SW2',
                   'SWARAXT_REPOSITORY_PRIVATE': 'false', 'RUNNER_ENVIRONMENT': 'github-hosted',
                   'RUNNER_TEMP': str(root)}
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(hosted_root(root / 'owned'), (root / 'owned').resolve())
                with self.assertRaises(RuntimeError): hosted_root(root)
                for key, bad in [('GITHUB_REPOSITORY', 'public/repo'),
                                 ('SWARAXT_REPOSITORY_PRIVATE', 'true'),
                                 ('RUNNER_ENVIRONMENT', 'self-hosted'), ('GITHUB_ACTIONS', 'false')]:
                    with patch.dict(os.environ, {key: bad}):
                        with self.assertRaises(RuntimeError): hosted_root(root / 'owned')

    def test_symlink_or_traversal_not_owned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(RuntimeError): owned_path(root / '../escape', root)
            link = root / 'linked'
            try:
                link.symlink_to(root, target_is_directory=True)
            except OSError as error:
                self.fail('Required symlink control unavailable: ' + str(error))
            with self.assertRaises(RuntimeError): owned_path(link / 'file', root)

    def test_tar_links_escape_and_unexpected_roots_fail(self):
        for member in ('../escape', '/absolute', 'other/root', 'unsigned-universal/../../escape'):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory); archive = root / 'candidate.tar.gz'
                with tarfile.open(archive, 'w:gz') as stream:
                    info = tarfile.TarInfo(member); info.size = 1
                    stream.addfile(info, io.BytesIO(b'x'))
                with self.assertRaises(RuntimeError): safe_extract_tar(archive, root / 'output')
                self.assertFalse((root / 'output').exists())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); archive = root / 'candidate.tar.gz'
            with tarfile.open(archive, 'w:gz') as stream:
                info = tarfile.TarInfo('unsigned-universal/link'); info.type = tarfile.SYMTYPE; info.linkname = '/'
                stream.addfile(info)
            with self.assertRaises(RuntimeError): safe_extract_tar(archive, root / 'output')

    def test_tool_archive_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); archive = root / 'tool.zip'
            with zipfile.ZipFile(archive, 'w') as stream:
                info = zipfile.ZipInfo('link'); info.external_attr = 0o120777 << 16
                stream.writestr(info, '/')
            with self.assertRaises(RuntimeError): safe_extract_zip(archive, root / 'output')

    def test_full_gate_cannot_accept_empty_or_partial_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            args = SimpleNamespace(mode='full', source_sha='a' * 40, base_source_sha='b' * 40)
            with self.assertRaises(RuntimeError): evaluate(Path(directory), args)

    def test_ctest_failure_skip_and_missing_cases_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'ctest.xml'; cases = '<testcase/>' * 60
            path.write_text('<testsuite>' + cases + '</testsuite>')
            self.assertEqual(inspect_ctest(path, 60)['executed_test_count'], 60)
            for marker in ('failure', 'error', 'skipped'):
                path.write_text('<testsuite>' + cases.replace('<testcase/>', '<testcase><' + marker + '/></testcase>', 1) + '</testsuite>')
                with self.assertRaises(RuntimeError): inspect_ctest(path, 60)
            with self.assertRaises(RuntimeError): inspect_ctest(path, 61)


if __name__ == '__main__':
    unittest.main()
