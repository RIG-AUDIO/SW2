#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 MontroneDSP
# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent raw binary32 comparison; does not issue acoustic acceptance."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct

def read(path):
    data=path.read_bytes()
    if len(data)%4:raise ValueError('Truncated binary32 capture: '+str(path))
    return data,[v[0] for v in struct.iter_unpack('<f',data)],[v[0] for v in struct.iter_unpack('<I',data)]

def ordered(bits):
    return (~bits & 0xffffffff) if bits & 0x80000000 else bits | 0x80000000

def q20(value):
    value=max(-32.,min(32.,value))*1048576.
    return int(math.copysign(math.floor(abs(value)+.5),value))

def q23(value):
    value=max(-8.,min(8.,value))*8388608.
    return int(math.copysign(math.floor(abs(value)+.5),value))

def hashes(data,values):
    h=1469598103934665603
    for b in data:h=((h^b)*1099511628211)&0xffffffffffffffff
    q=1469598103934665603
    classic=1469598103934665603
    for v in values:
        if not math.isfinite(v):return {'bit_fnv':f'{h:016x}','q20_fnv':None,'classic_q23_byte_fnv':None}
        q=((q^(q20(v)&0xffffffff))*1099511628211)&0xffffffffffffffff
        for byte in struct.pack('<i',q23(v)):
            classic=((classic^byte)*1099511628211)&0xffffffffffffffff
    return {'bit_fnv':f'{h:016x}','q20_fnv':f'{q:016x}','classic_q23_byte_fnv':f'{classic:016x}'}

def compare(left,right):
    a,x,xb=read(left);b,y,yb=read(right)
    finite=all(math.isfinite(v) for v in x+y)
    differing=[i for i,(u,v) in enumerate(zip(xb,yb)) if u!=v]
    result={'left_samples':len(x),'right_samples':len(y),'same_count':len(x)==len(y),
        'left_sha256':hashlib.sha256(a).hexdigest(),'right_sha256':hashlib.sha256(b).hexdigest(),
        'exact':a==b,'finite':finite,'first_bit_difference':differing[0] if differing else None,
        'differing_samples':len(differing),'unpaired_samples':abs(len(x)-len(y)),
        'first_divergent_sample':differing[0] if differing else (min(len(x),len(y)) if len(x)!=len(y) else None),
        'left_fingerprints':hashes(a,x),'right_fingerprints':hashes(b,y)}
    if finite and x and y:
        errors=[abs(u-v) for u,v in zip(x,y)]
        ulps=sorted(abs(ordered(u)-ordered(v)) for u,v in zip(xb,yb))
        relative=[abs(u-v)/abs(u) for u,v in zip(x,y) if abs(u)>1.e-20]
        def onset(values):
            peak=max(map(abs,values),default=0.)
            threshold=max(1.e-12,peak*1.e-4)
            return next((i for i,v in enumerate(values) if abs(v)>threshold),None)
        result.update(max_abs=max(errors),rms_error=math.sqrt(math.fsum(v*v for v in errors)/len(errors)),
            max_relative_above_1e_20=max(relative,default=0.),max_ulp=max(ulps),
            p95_ulp=ulps[int((len(ulps)-1)*.95)],p99_ulp=ulps[int((len(ulps)-1)*.99)],
            q20_differing_samples=sum(q20(u)!=q20(v) for u,v in zip(x,y)),
            classic_q23_differing_samples=sum(q23(u)!=q23(v) for u,v in zip(x,y)),
            left_onset=onset(x),right_onset=onset(y))
        if differing:
            i=differing[0];result['first_values']={'left':x[i],'right':y[i],'left_bits':f'{xb[i]:08x}','right_bits':f'{yb[i]:08x}'}
    return result

def directories(left,right):
    a={p.relative_to(left).as_posix():p for p in left.rglob('*.f32')}
    b={p.relative_to(right).as_posix():p for p in right.rglob('*.f32')}
    if not a or not b:raise ValueError('No raw float captures to compare')
    return {'reference_admission':'REVIEW_REQUIRED','missing_left':sorted(b.keys()-a.keys()),
            'missing_right':sorted(a.keys()-b.keys()),
            'files':{key:compare(a[key],b[key]) for key in sorted(a.keys()&b.keys())}}

def repeats(root):
    result={'reference_admission':'REVIEW_REQUIRED','families':{}}
    for family in sorted(root.iterdir()):
        if (family/'run1').is_dir() and list((family/'run1').glob('*.f32')):
            result['families'][family.name]=directories(family/'run1',family/'run2')
    if len(result['families'])!=4:raise ValueError('Incomplete four-family raw capture inventory')
    result['all_repeats_bitwise_equal']=all(not r['missing_left'] and not r['missing_right'] and all(v['exact'] for v in r['files'].values()) for r in result['families'].values())
    control=root/'SRC-no-contract'
    result['src_contraction_control']=directories(root/'SwaraXTHostSrcExactParityTests/run1',control)
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--left',type=Path);parser.add_argument('--right',type=Path)
    parser.add_argument('--repeat-root',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.repeat_root:result=repeats(args.repeat_root)
    else:
        if not args.left or not args.right:parser.error('left and right required')
        result=directories(args.left,args.right)
    args.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
if __name__=='__main__':main()
