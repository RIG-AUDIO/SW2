# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
"""Current Mac authority admission. Candidate records never approve themselves."""
BASELINE_SHA = '5e7b967db0b52f773f382217a72c6c0c3ff6b8f7'
TESTS = {}

def require_approved_authority(source, architecture, profile):
    raise RuntimeError('BLOCKED: current 1.3.0 macOS audio authority requires independent owner review; historical references cannot qualify this candidate')
