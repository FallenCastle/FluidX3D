"""Verify the viewer API against existing Windows output bytes; never executes a local solver."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import struct
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlencode

parser=argparse.ArgumentParser();parser.add_argument('--url',default='http://127.0.0.1:8765');parser.add_argument('--run-id',required=True);parser.add_argument('--report',type=Path,required=True);args=parser.parse_args()
base=args.url;token=None

def api(path, body=None, raw=False, binary=None):
    headers={};data=None
    if body is not None:
        headers.update({'Content-Type':'application/json','X-Workbench-Token':token});data=json.dumps(body).encode()
    if binary is not None:
        headers.update({'Content-Type':'application/octet-stream','X-Workbench-Token':token});data=binary
    with urlopen(Request(base+'/api'+path,data=data,headers=headers),timeout=60) as r:
        return r.read() if raw else json.load(r)

session=api('/session');token=session['token'];job=api('/jobs/'+args.run_id);assert job['status']=='succeeded'
ident='job-'+args.run_id
m=api('/results/'+ident+'/metadata');assert m['unit_mode']=='si' and m['geometries'][0]['available']
report={'run_id':args.run_id,'solver':session['solver'],'frames':m['frames'],'checks':[]}

def download(name):return api('/jobs/'+args.run_id+'/download?'+urlencode({'path':'results/'+name}),raw=True)

step=m['frames'][1]['step'] if len(m['frames'])>1 else m['frames'][0]['step']
for name,component in [('u','magnitude'),('u','x'),('u','y'),('u','z'),('p','scalar'),('rho','scalar'),('flags','scalar')]:
    data=download(f'{name}-{step:09d}.vtk');header,payload=data.split(b'LOOKUP_TABLE default\n',1)
    dims=list(map(int,re.search(rb'DIMENSIONS (\d+) (\d+) (\d+)',header).groups()));count=math.prod(dims);components=3 if name=='u' else 1
    values=struct.unpack('>'+('B' if name=='flags' else 'f')*(count*components),payload)
    for axis in (0,1,2):
        index=dims[axis]//2;axes=[a for a in range(3) if a!=axis]
        s=api('/results/'+ident+'/slice?'+urlencode({'field':name,'component':component,'step':step,'axis':axis,'index':index}))
        expected=[]
        for j in range(dims[axes[1]]):
            for i in range(dims[axes[0]]):
                xyz=[0,0,0];xyz[axis]=index;xyz[axes[0]]=i;xyz[axes[1]]=j
                cell=xyz[0]+dims[0]*(xyz[1]+dims[1]*xyz[2]);raw=values[cell*components:(cell+1)*components]
                expected.append(math.sqrt(sum(v*v for v in raw)) if component=='magnitude' else raw['xyz'.index(component)] if components==3 else raw[0])
        error=max(abs(a-b) for a,b in zip(expected,s['values']));assert len(expected)==len(s['values']) and error<1e-12
        assert math.isclose(s['position'],m['origin'][axis]+index*m['spacing'][axis])
        report['checks'].append({'field':name,'component':component,'axis':axis,'samples':len(expected),'max_abs_error':error})

# Upload actual result bytes, metadata and STL into a separate immutable import.
u=download(f'u-{step:09d}.vtk')
raw_id=api('/results/import',{'name':'raw-vtk-acceptance'})['id']
api('/results/'+raw_id+'/upload?'+urlencode({'path':f'u-{step:09d}.vtk'}),binary=u);api('/results/'+raw_id+'/finish',{})
raw_meta=api('/results/'+raw_id+'/metadata');assert raw_meta['unit_mode']=='unknown' and raw_meta['frames'][0]['time'] is None
full_id=api('/results/import',{'name':'full-result-import-acceptance'})['id']
files=[f'u-{f["step"]:09d}.vtk' for f in m['frames']]+['effective-config.json','resolved-config.json','inputs/assets/0.stl']
for filename in files:api('/results/'+full_id+'/upload?'+urlencode({'path':'results/'+filename}),binary=download(filename))
api('/results/'+full_id+'/finish',{})
full=api('/results/'+full_id+'/metadata');assert len(full['frames'])==len(m['frames']) and full['unit_mode']=='si'
assert full['frames'][-1]['time']==m['frames'][-1]['time']
original_stl=download('inputs/assets/0.stl');imported_stl=api('/results/'+full_id+'/geometry?index=0',raw=True);assert imported_stl==original_stl
# Missing-field and invalid frame must fail, never substitute data from another frame.
try:api('/results/'+full_id+'/slice?field=p&component=scalar&step=0&axis=2&index=0')
except HTTPError as exc:assert exc.code==404
else:raise AssertionError('Missing field silently substituted')
report.update(raw_import_id=raw_id,full_import_id=full_id,stl_sha256=hashlib.sha256(imported_stl).hexdigest(),import_checks='passed')
args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'numeric_comparisons':len(report['checks']),'max_error':max(c['max_abs_error'] for c in report['checks']),'frames':len(m['frames']),'raw_import_id':raw_id,'full_import_id':full_id},ensure_ascii=False))
