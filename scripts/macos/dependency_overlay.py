# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
"""Repair JUCE's discrete channel enum domain in an owned CI dependency clone."""
import hashlib
from pathlib import Path
import subprocess


def apply(juce, owned_root):
    juce, owned_root = Path(juce).resolve(), Path(owned_root).resolve()
    if juce != owned_root / 'JUCE':
        raise RuntimeError('Only the build-owned JUCE clone may be patched')
    if subprocess.check_output(['git', '-C', juce, 'status', '--porcelain'], text=True, timeout=60).strip():
        raise RuntimeError('A pristine dependency clone is required')
    path = juce / 'modules/juce_audio_basics/buffers/juce_AudioChannelSet.h'
    if path.is_symlink() or not path.resolve().is_relative_to(juce):
        raise RuntimeError('Dependency overlay target is outside its owned checkout')
    before = path.read_bytes()
    if hashlib.sha256(before).hexdigest() != '445a53855d3fabc8304db1fdd465b43718924644864a9f429ca4839f00eb930a':
        raise RuntimeError('Unexpected pinned JUCE channel header hash')
    anchor = b'    enum ChannelType\r\n'
    if before.count(anchor) != 1:
        anchor = b'    enum ChannelType\n'
    if before.count(anchor) != 1:
        raise RuntimeError('Supported JUCE channel enum anchor changed')
    # The existing ABI uses an unsigned int. Fixing its underlying type permits
    # all documented discrete-channel IDs (128..1023), including the AU probe's
    # 256+i values, without changing any channel number or audio computation.
    after = before.replace(anchor, anchor.replace(b'ChannelType', b'ChannelType : unsigned int'))
    if hashlib.sha256(after).hexdigest() != '5f1308b04dbaf4646ac420001068b2b90f41c0977a61fce5931ac6988ffa7675':
        raise RuntimeError('Unexpected resulting JUCE channel header hash')
    path.write_bytes(after)
    return {'file': path.relative_to(juce).as_posix(),
            'before_sha256': hashlib.sha256(before).hexdigest(),
            'after_sha256': hashlib.sha256(after).hexdigest(),
            'change': 'Fixed unsigned underlying type for the discrete channel enum domain'}
