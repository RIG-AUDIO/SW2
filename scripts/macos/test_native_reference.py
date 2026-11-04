# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
import unittest
from native_reference import require_approved_authority
class AuthorityTests(unittest.TestCase):
    def test_unapproved_authority_fails_closed(self):
        for arch in ('arm64', 'x86_64'):
            for profile in ('Release', 'Debug', 'asan-ubsan', 'tsan'):
                with self.assertRaisesRegex(RuntimeError, 'BLOCKED'):
                    require_approved_authority('.', arch, profile)
if __name__ == '__main__': unittest.main()
