# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from compiler_cache import configure_cache,inventory,launch

class CacheControls(unittest.TestCase):
    def test_untrusted_cache_environment_is_not_inherited(self):
        with tempfile.TemporaryDirectory() as d:
            env=configure_cache(d,{'PATH':'/bin','CCACHE_IGNOREOPTIONS':'-fsanitize=*','CCACHE_SLOPPINESS':'time_macros','CCACHE_REMOTE_STORAGE':'https://untrusted'},'x86_64-Release')
            self.assertNotIn('CCACHE_IGNOREOPTIONS',env);self.assertNotIn('CCACHE_SLOPPINESS',env);self.assertNotIn('CCACHE_REMOTE_STORAGE',env)
            self.assertIn('compiler_check = content',Path(env['CCACHE_CONFIGPATH']).read_text())
            self.assertIn('direct_mode = false',Path(env['CCACHE_CONFIGPATH']).read_text())
    def test_launcher_preserves_all_arguments_and_never_caches_product(self):
        for source,cache in [('/owned/JUCE/modules/juce_core/core.mm',True),('/owned/Source/Plugin/PluginProcessor.cpp',False),('/owned/build/juce_audio_utils.mm',True),('/another/JUCE/modules/core.mm',False)]:
            args=['/compiler','-x','objective-c++','-fsanitize=thread','-arch','arm64','-isysroot','/sdk','-Werror','-c',source,'-o','object.o']
            with patch.object(sys,'argv',['launcher','--launch','/cache','/owned/JUCE','/owned/build/juce_audio_utils.mm',*args]),patch('compiler_cache.os.execv') as execute:
                launch();self.assertEqual(execute.call_args.args,('/cache' if cache else '/compiler',['/cache',*args] if cache else args))
    def test_inventory_never_collapses_different_include_order_or_definitions(self):
        commands=[{'file':'a.cpp','command':'clang++ -DFIRST=1 -Ione -Itwo -o a.o -c a.cpp'}, {'file':'a.cpp','command':'clang++ -DFIRST=2 -Itwo -Ione -o b.o -c a.cpp'}]
        data=inventory(commands);group=data['groups']['other']
        self.assertEqual(data['unique_translation_units'],1);self.assertEqual(group['definition_groups'],2);self.assertEqual(group['ordered_include_groups'],2);self.assertEqual(len(group['full_environment_groups']),2)

if __name__=='__main__':unittest.main()
