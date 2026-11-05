# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
"""Exact preprocessor-result reuse for build-owned JUCE modules, not product TUs.

No CMake target environment is merged. ccache hashes compiler content, effective
preprocessor output and code-generation options. No sloppiness or ignored flags.
"""
import collections
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tarfile
import urllib.request

VERSION='4.14.2'
UPSTREAM_COMMIT='360543256991b0df7b5ad1822bd08f8d4ae2aa90'
DARWIN_SHA256='cf240009630b605b775c7c5c7b7105a3b196c79f31af322c1557969aa28003fc'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def configure_cache(root,env,namespace):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    config=root/'ccache.conf'
    config.write_text('compiler_check = content\ndirect_mode = false\ndepend_mode = false\n'
        'hash_dir = true\nmax_size = 3G\nnamespace = '+namespace+'\n')
    result={k:v for k,v in env.items() if not k.startswith('CCACHE_')}
    result.update(CCACHE_CONFIGPATH=str(config),CCACHE_DIR=str(root/'objects'),
                  CCACHE_STATSLOG=str(root/'statistics.log'))
    return result

def install(root):
    root=Path(root);root.mkdir()
    archive=root/'ccache-darwin.tar.gz'
    with urllib.request.urlopen(f'https://github.com/ccache/ccache/releases/download/v{VERSION}/ccache-{VERSION}-darwin.tar.gz',timeout=120) as response,archive.open('xb') as stream:
        while block:=response.read(1024*1024):stream.write(block)
    if sha(archive)!=DARWIN_SHA256:raise RuntimeError('Pinned ccache archive mismatch')
    with tarfile.open(archive) as stream:
        members=stream.getmembers()
        if not 1<len(members)<100:raise RuntimeError('Unexpected tool inventory')
        for member in members:
            p=Path(member.name)
            if p.is_absolute() or '..' in p.parts or not(member.isdir() or member.isfile()):
                raise RuntimeError('Unsafe ccache archive member')
        stream.extractall(root,members=members,filter='data')
    binaries=list(root.glob('*/ccache'))
    if len(binaries)!=1:raise RuntimeError('Ambiguous compiler cache tool')
    tool=binaries[0];tool.chmod(0o755)
    if subprocess.check_output([tool,'--version'],text=True).splitlines()[0]!='ccache version '+VERSION:
        raise RuntimeError('Unexpected ccache version')
    return tool

def inventory(commands):
    files=collections.Counter(c['file'] for c in commands)
    def args(c):
        values=shlex.split(c['command']);result=[];i=0
        while i<len(values):
            if values[i] in ('-o','-c'):i+=2;continue
            result.append(values[i]);i+=1
        return values,result
    kinds=collections.defaultdict(list)
    for c in commands:
        f=c['file'];kind='JUCE' if '/JUCE/modules/' in f else 'generated' if '/generated/' in f else 'production' if '/Source/' in f else 'other'
        kinds[kind].append(c)
    groups={}
    for kind,entries in kinds.items():
        signatures=collections.Counter();definitions=set();includes=set()
        for c in entries:
            values,options=args(c)
            signatures[hashlib.sha256(json.dumps(options).encode()).hexdigest()]+=1
            definitions.add(tuple(v for v in values if v.startswith('-D')))
            includes.add(tuple(v for v in values if v.startswith(('-I','-isystem'))))
        groups[kind]={'commands':len(entries),'unique_files':len({c['file'] for c in entries}),
                      'full_environment_groups':dict(signatures),'definition_groups':len(definitions),'ordered_include_groups':len(includes)}
    return {'commands':len(commands),'unique_translation_units':len(files),'recompilations':sum(n-1 for n in files.values()),
        'groups':groups,'objective_cpp_commands':sum('objective-c++' in c['command'] or c['file'].endswith('.mm') for c in commands),
        'lto_commands':sum('-flto' in shlex.split(c['command']) for c in commands),
        'sources':dict(sorted(files.items()))}

def equivalence_controls(tool,root,compiler,env,apple=False):
    """Compare cached and original compiler objects; changed semantics must miss."""
    root=Path(root);root.mkdir()
    env=configure_cache(root/'cache',env,'independent-equivalence-controls')
    source=root/'control.cpp';source.write_text('#include "value.h"\nextern "C" int value() { return VALUE; }\n')
    inc=root/'include';inc.mkdir();header=inc/'value.h';header.write_text('#ifndef VALUE\n#define VALUE 17\n#endif\n')
    options=['-std=c++17','-O2','-g','-fPIC','-fvisibility=hidden','-fno-omit-frame-pointer','-Wall','-Wextra','-Werror','-I'+str(inc)]
    if apple:options+=['-arch','x86_64','-mmacosx-version-min=11.0']
    cases=[('original',[]),('unused-definition',['-DUNUSED_TARGET_DIAGNOSTIC=1']),
           ('effective-definition',['-DVALUE=19']),('optimization',['-O0']),
           ('asan',['-fsanitize=address,undefined,vptr','-fno-sanitize-recover=all']),
           ('tsan',['-fsanitize=thread']),('objective-cpp',['-x','objective-c++'])]
    records={}
    for name,extra in cases:
        cached=root/(name+'-cached.o');fresh=root/(name+'-fresh.o')
        command=[str(compiler),*options,*extra,'-c',str(source)]
        subprocess.run([tool,*command,'-o',cached],env=env,check=True,capture_output=True)
        subprocess.run([*command,'-o',fresh],env=env,check=True,capture_output=True)
        if sha(cached)!=sha(fresh):raise RuntimeError('Compiler-cache semantic difference: '+name)
        records[name]={'object_sha256':sha(cached),'fresh_object_sha256':sha(fresh)}
    if records['original']!=records['unused-definition']:raise RuntimeError('Unused macro changed object')
    if records['original']==records['effective-definition']:raise RuntimeError('Macro sensitivity control failed')
    header.write_text('#ifndef VALUE\n#define VALUE 23\n#endif\n')
    changed=root/'header-changed.o';fresh=root/'header-fresh.o'
    command=[str(compiler),*options,'-c',str(source)]
    subprocess.run([tool,*command,'-o',changed],env=env,check=True,capture_output=True)
    subprocess.run([*command,'-o',fresh],env=env,check=True,capture_output=True)
    if sha(changed)!=sha(fresh) or sha(changed)==records['original']['object_sha256']:
        raise RuntimeError('Header sensitivity control failed')
    stats=subprocess.check_output([tool,'--print-stats'],env=env,text=True)
    counts=dict(line.split() for line in stats.splitlines())
    if int(counts.get('preprocessed_cache_hit','0'))<1:raise RuntimeError('No proven equivalent reuse')
    return {'decision':'PASS','objects':records,'changed_header_sha256':sha(changed),'statistics':counts,
            'limitations':'Representative object controls; full configured inventory and execution are recorded separately.'}

def cmake_control(tool,root,compiler,env):
    root=Path(root);root.mkdir()
    modules=root/'JUCE/modules';modules.mkdir(parents=True)
    source=modules/'module.cpp';source.write_text('extern "C" int module() {return 31;}\n')
    product=root/'production.cpp';product.write_text('extern "C" int production() {return 47;}\n')
    (root/'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.22)\nproject(CacheGraphControl LANGUAGES CXX)\n'
        'set(CMAKE_EXPORT_COMPILE_COMMANDS ON)\nadd_library(first OBJECT JUCE/modules/module.cpp production.cpp)\n'
        'add_library(second OBJECT JUCE/modules/module.cpp production.cpp)\ntarget_compile_definitions(second PRIVATE UNUSED_TARGET_ONLY=1)\n')
    build=root/'build'
    def run(args):return subprocess.check_output(list(map(str,args)),env=env,stderr=subprocess.STDOUT,text=True)
    run(['cmake','-S',root,'-B',build,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_CXX_COMPILER='+str(compiler)])
    before=json.loads((build/'compile_commands.json').read_text())
    launcher=';'.join([sys.executable,str(Path(__file__).resolve()),'--launch',str(tool),str(root/'JUCE'),str(root/'not-generated.mm')])
    env=configure_cache(root/'cache',env,'cmake-equivalence-control')
    run(['cmake','-S',root,'-B',build,'-DCMAKE_CXX_COMPILER_LAUNCHER='+launcher])
    after=json.loads((build/'compile_commands.json').read_text())
    if before!=after:raise RuntimeError('Launcher changed CMake compile commands')
    run(['cmake','--build',build,'--parallel','2'])
    objects=[]
    for entry in after:
        args=shlex.split(entry['command']);output=args[args.index('-o')+1]
        cached=build/output;fresh=Path(str(cached)+'.independent.o')
        args[args.index('-o')+1]=str(fresh)
        subprocess.run(args,cwd=build,env=env,check=True,capture_output=True)
        if sha(cached)!=sha(fresh):raise RuntimeError('CMake object equivalence failed')
        objects.append({'source':entry['file'],'cached':sha(cached),'fresh':sha(fresh)})
    return {'decision':'PASS','evaluated_commands':'IDENTICAL','objects':objects}

def launch():
    tool,juce,generated,compiler,*args=sys.argv[2:]
    source=args[args.index('-c')+1] if '-c' in args else ''
    path=Path(source).resolve()
    eligible=path.is_relative_to(Path(juce).resolve()/'modules') or path==Path(generated).resolve()
    command=[tool,compiler,*args] if eligible else [compiler,*args]
    os.execv(command[0],command)

if __name__=='__main__':
    if sys.argv[1:2]==['--launch']:launch()
