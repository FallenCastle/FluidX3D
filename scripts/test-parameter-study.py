"""NUC acceptance for self-contained study assets, pointer rejection and integrity."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import datetime

sys.dont_write_bytecode=True
spec=importlib.util.spec_from_file_location('p1',Path(__file__).with_name('test-config-runner.py'))
p1=importlib.util.module_from_spec(spec);spec.loader.exec_module(p1)


def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace-root',type=Path,required=True)
    p.add_argument('--repository-root',type=Path)
    p.add_argument('--configs-root',type=Path)
    p.add_argument('--build-name',default='solver-ibm-v1.0.0')
    p.add_argument('--executable',type=Path)
    p.add_argument('--device',default='0')
    args=p.parse_args()
    if os.name!='nt':p.error('NUC only')
    workspace=args.workspace_root.resolve();repo=(args.repository_root or workspace/'src').resolve()
    configs=(args.configs_root or repo/'configs').resolve()
    exe=(args.executable or workspace/'bin'/args.build_name/'Solver-IBM.exe').resolve()
    root=workspace/'workingdir'/'study-validation'/datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    root.mkdir(parents=True)
    script=repo/'scripts'/'parameter-study.py'
    base=json.loads((configs/'periodic-lattice.json').read_text())
    p1.cube(root/'cube.stl')
    base['geometry']=[{'id':'cube','file':'cube.stl','transform':{'mode':'scale','factor':4,'translation':[6,6,6],'degrees':0}}]
    (root/'base.json').write_text(json.dumps(base),encoding='utf-8')
    study={'schema_version':1,'base_config':'base.json','parameters':[{'path':'/geometry/0/transform/degrees','values':[0,90]}]}
    p1.write_json(root/'study-spec.json',study)
    checks=[]
    def command(name,arguments,success=True):
        with (root/(name+'.log')).open('wb') as out:
            result=subprocess.run([sys.executable,str(script),*map(str,arguments)],stdout=out,stderr=subprocess.STDOUT)
        checks.append({'name':name,'exit_code':result.returncode,'expected_success':success})
        assert (result.returncode==0)==success,name
    bundle=root/'bundle'
    report={'status':'running','checks':checks}
    try:
        command('generate',['generate','--spec',root/'study-spec.json','--output',bundle])
        command('refuse-overwrite',['generate','--spec',root/'study-spec.json','--output',bundle],False)
        (root/'cube.stl').rename(root/'original-moved.stl')
        command('run-without-original-asset',['run','--study',bundle,'--workspace-root',workspace,'--build-name',args.build_name,'--executable',exe,'--device',args.device])
        summary=json.loads(next((bundle/'runs').glob('*/summary.json')).read_text())
        assert len(summary['cases'])==2 and summary['status']=='succeeded'
        for case in summary['cases']:
            resolved=json.loads((Path(case['results'])/'resolved-config.json').read_text())
            assert resolved['solid_cells']>0
            assert case['statistics'] is None
        report['batch']=summary
        config=bundle/'configs'/'00000.json';config.write_text(config.read_text()+'\n')
        command('reject-tampered-config',['run','--study',bundle,'--workspace-root',workspace,'--build-name',args.build_name,'--executable',exe,'--device',args.device],False)
        for name,axes in [
            ('missing-path',[{'path':'/unknown','values':[1]}]),
            ('duplicate-path',[{'path':'/fluid/nu','values':[1]}]*2),
            ('ancestor-path',[{'path':'/fluid','values':[{}]},{'path':'/fluid/nu','values':[1]}]),
            ('bad-escape',[{'path':'/fluid/~2','values':[1]}]),
            ('asset-path',[{'path':'/geometry/0/file','values':['cube.stl']}])]:
            invalid=dict(study,parameters=axes);p1.write_json(root/(name+'.json'),invalid)
            command(name,['generate','--spec',root/(name+'.json'),'--output',root/name],False)
        report['status']='succeeded'
    except Exception as error:
        report['status']='failed';report['error']=repr(error);raise
    finally:
        p1.write_json(root/'report.json',report);print(root/'report.json')


if __name__=='__main__':main()
