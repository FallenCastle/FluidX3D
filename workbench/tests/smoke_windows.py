"""End-to-end acceptance through the real service. Run on Windows only."""
import argparse
import copy
import json
import os
from pathlib import Path
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError


def main():
    if os.name != 'nt':
        raise SystemExit('Run real Solver-IBM acceptance on Windows only.')
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    token = None
    def request(path, payload=None, method=None, binary=None):
        headers = {}
        if payload is not None:
            binary = json.dumps(payload).encode()
            headers['Content-Type'] = 'application/json'
        if binary is not None:
            headers['X-Workbench-Token'] = token
        req = Request(args.url+'/api'+path, data=binary, method=method, headers=headers)
        with urlopen(req, timeout=70) as response:
            return json.load(response)
    session = request('/session')
    token = session['token']
    assert session['solver']['version'] == '2.0.0'
    device = next((d['id'] for d in session['devices'] if 'NVIDIA' in d['name']), session['devices'][0]['id'])
    report = {'solver':session['solver'], 'devices':session['devices'], 'checks':[]}
    config = json.loads((root / 'default-case.json').read_text(encoding='utf-8'))
    config['run'].update(steps=23, monitor_every=7)
    config['output'].update(vtk_every=0, initial=False)
    config['analysis']['every'] = 7
    config['case']['name'] = 'web-smoke-si-cube'
    data = (root.parent / 'configs/assets/unit-cube-binary.stl').read_bytes()
    asset = request('/assets?name=smoke-cube.stl', binary=data)
    config['geometry'][0]['file'] = asset['path']
    assert asset['triangles'] == 12
    report['checks'].append({'name':'STL upload','passed':True,'sha256':asset['sha256']})
    checked = request('/validate', {'config':config})
    assert checked['valid']
    report['checks'].append({'name':'V2.0.0 validate','passed':True})
    for kind in ['escape', 'refinement', 'checkpoint']:
        bad = copy.deepcopy(config)
        if kind == 'escape':
            bad['geometry'][0]['file'] = '../private.stl'
        elif kind == 'refinement':
            bad['refinement'] = {}
        else:
            bad['run']['checkpoint_every'] = 10
        try:
            request('/validate', {'config':bad})
            raise AssertionError('Unsupported input was accepted: '+kind)
        except HTTPError as exc:
            assert exc.code == 400
        report['checks'].append({'name':'reject '+kind,'passed':True})
    def submit(c, timeout=90):
        return request('/jobs', {'config':c,'device_id':device,'timeout_seconds':timeout,
                                  'refinement':{'schema':'solver-ibm.refinement-draft','regions':[{'level':1}]}})
    def wait(job, state=None):
        deadline = time.monotonic()+120
        while time.monotonic()<deadline:
            record=request('/jobs/'+job['id'])
            if state and record['status']==state:
                return record
            if record['status'] not in ['validating','starting','running','cancelling']:
                return record
            time.sleep(.2)
        raise AssertionError('Task did not reach expected state')
    long = copy.deepcopy(config)
    long['case']['name']='web-stop-acceptance'
    long['run'].update(steps=100000000, monitor_every=10000)
    long['analysis']['every']=10000
    job=submit(long)
    assert wait(job,'running')['status']=='running'
    request('/jobs/'+job['id']+'/stop',{})
    stopped=wait(job)
    assert stopped['status']=='cancelled',stopped
    report['checks'].append({'name':'terminate owned process','passed':True,'job':job['id']})
    long['case']['name']='web-timeout-acceptance'
    job=submit(long,1)
    timed=wait(job)
    assert timed['status']=='timed_out',timed
    report['checks'].append({'name':'timeout cleanup','passed':True,'job':job['id']})
    bad=copy.deepcopy(config)
    bad['case']['name']='web-validation-failure'
    bad['domain']['dx']=-.01
    job=submit(bad)
    failed=wait(job)
    assert failed['status']=='failed',failed
    report['checks'].append({'name':'solver validation failure','passed':True,'job':job['id']})
    job=submit(config)
    completed=wait(job)
    assert completed['status']=='succeeded',completed
    assert completed['completion']['steps']==23 and completed['exit_code']==0
    series=request('/jobs/'+job['id']+'/series?file=probes.csv')
    assert series['rows'] and series['rows'][-1]['step']==23
    monitor=request('/jobs/'+job['id']+'/series?file=monitor.csv')
    assert monitor['rows'][-1]['step']==23
    files=request('/jobs/'+job['id']+'/files')['files']
    assert any(f['path'].startswith('results/u-') and f['path'].endswith('.vtk') for f in files)
    snapshot=request('/jobs/'+job['id']+'/download?path=inputs/case.json')
    assert snapshot==config and 'refinement' not in snapshot
    ignored=request('/jobs/'+job['id']+'/download?path=refinement-draft.json')
    assert not ignored['applied']
    report['checks'].append({'name':'23-step real run, CSV, VTK, immutable snapshot','passed':True,'job':job['id']})
    report['passed']=True
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True,indent=2))


if __name__=='__main__':
    main()
