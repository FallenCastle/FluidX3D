"""NUC-only matched fixed-grid P1/P2 end-to-end timing (includes startup and I/O)."""
import argparse
import copy
import csv
import datetime
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace-root',type=Path,required=True)
    parser.add_argument('--repository-root',type=Path)
    parser.add_argument('--configs-root', type=Path)
    parser.add_argument('--reference-root',type=Path,help='Historical p1-build and p2-build directories')
    parser.add_argument('--device',default='0')
    args=parser.parse_args()
    if os.name!='nt':parser.error('NUC only')
    workspace=args.workspace_root.resolve()
    repo=(args.repository_root or workspace/'src').resolve()
    configs=(args.configs_root or repo/'configs').resolve()
    root=workspace/'workingdir'/'p2-overhead'/datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    root.mkdir(parents=True)
    config=json.loads((configs/'periodic-lattice.json').read_text())
    config['domain']={'cells':[96,64,96]}
    config['run']={'steps':2000,'monitor_every':2000}
    config['output']={'vtk_fields':['flags'],'vtk_every':0,'initial':False}
    config['boundaries']=[{'id':'periodic','type':'periodic','faces':['xmin','xmax','zmin','zmax']},
                          {'id':'walls','type':'no_slip','faces':['ymin','ymax']}]
    report={'description':'Whole process elapsed time includes OpenCL compile/cache, initialization and final I/O; not isolated kernel throughput.', 'cases':[]}
    for label,build,analysis in [('p1','config-runner',False),('p2','config-runner-p2',False),('p2-sampled','config-runner-p2',True)]:
        c=copy.deepcopy(config)
        if analysis:c['analysis']={'every':100,'start_step':0,'probes':[{'id':'center','position':[48.5,32.5,48.5]}], 'forces':[{'id':'walls','target':'all_solids'}]}
        reference_name='p1-build' if label=='p1' else 'p2-build'
        exe=((args.reference_root/reference_name if args.reference_root else workspace/'bin'/build)/'FluidX3D.exe').resolve()
        build_record=json.loads((exe.parent/'build.json').read_text(encoding='utf-8-sig'))
        assert build_record['executableSha256']==hashlib.sha256(exe.read_bytes()).hexdigest()
        rec={'name':label,'executable_sha256':hashlib.sha256(exe.read_bytes()).hexdigest(),'seconds':[]}
        # First run warms the OpenCL cache; retain it separately.
        for i in range(3):
            case=root/f'{label}-{i}';case.mkdir();(case/'case.json').write_text(json.dumps(c),encoding='utf-8')
            start=time.perf_counter()
            with (case/'stdout.log').open('wb') as out,(case/'stderr.log').open('wb') as err:
                completed=subprocess.run([str(exe),'--config',str(case/'case.json'),'--output',str(case/'results'),'--device',args.device],stdout=out,stderr=err,timeout=240)
            elapsed=time.perf_counter()-start
            assert completed.returncode==0,case
            resolved=json.loads((case/'results'/'resolved-config.json').read_text())
            rec['device_field_bytes']=resolved['device_field_bytes']
            rec['host_field_and_union_bytes']=resolved['host_field_and_union_bytes']
            rec['seconds'].append(elapsed)
        rec['warm_median_seconds']=statistics.median(rec['seconds'][1:])
        report['cases'].append(rec)
    # Both new capability overhead and additional diagnostic overhead are measured.
    report['p2_over_p1']=report['cases'][1]['warm_median_seconds']/report['cases'][0]['warm_median_seconds']
    report['sampling_over_plain_p2']=report['cases'][2]['warm_median_seconds']/report['cases'][1]['warm_median_seconds']
    (root/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(root/'report.json')


if __name__=='__main__':main()
