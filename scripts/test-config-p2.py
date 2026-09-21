"""P2 NUC acceptance: analytic channels, sampling, units, forces and batch studies."""
import argparse
import copy
import csv
import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location('p1', Path(__file__).with_name('test-config-runner.py'))
p1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p1)


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')


def rows(path):
    with path.open(encoding='utf-8', newline='') as file:
        return list(csv.DictReader(file))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace-root', type=Path, required=True)
    parser.add_argument('--build-name', default='config-runner-p2')
    parser.add_argument('--device', default='0')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Run on Windows NUC only')
    workspace = args.workspace_root
    repo = workspace / 'src'
    exe = workspace / 'bin' / args.build_name / 'FluidX3D.exe'
    root = workspace / 'workingdir' / 'p2-validation' / datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    root.mkdir(parents=True)
    report = {'status': 'running', 'build': read(exe.parent/'build.json'),
              'executable_sha256': hashlib.sha256(exe.read_bytes()).hexdigest(), 'tests': [], 'profiles': []}
    print(root, flush=True)

    def invoke(name, config, options=(), error=None):
        directory = root / name
        directory.mkdir()
        write(directory/'case.json', config)
        start = time.perf_counter()
        with (directory/'stdout.log').open('wb') as stdout, (directory/'stderr.log').open('wb') as stderr:
            result = subprocess.run([str(exe), '--config', str(directory/'case.json'), '--device', args.device,
                                     '--output', str(directory/'results'), *options], stdout=stdout, stderr=stderr,
                                    cwd=workspace, timeout=240)
        report['tests'].append({'name': name, 'exit_code': result.returncode, 'expected_error': error,
                                'elapsed_seconds': time.perf_counter()-start})
        write(root/'report.json', report)
        if error:
            assert result.returncode != 0 and error.lower() in (directory/'stderr.log').read_text(encoding='utf-8').lower(), name
        else:
            assert result.returncode == 0, name
            if '--validate' not in options:
                completion = read(directory/'results'/'completion.json')
                assert completion['status'] == ('prepared' if '--prepare-only' in options else 'succeeded')
                assert completion['steps'] == (0 if '--prepare-only' in options else config['run']['steps'])
        print(name, result.returncode, flush=True)
        return directory/'results'

    try:
        base = read(repo/'configs'/'probes-periodic.json')
        base['analysis']['probes'][0]['id'] = '中心,"probe"'
        base['analysis']['probes'][0]['position'] = [8, 8.5, 8.5]
        r = invoke('periodic-probes', base)
        samples = rows(r/'probes.csv')
        assert [int(x['step']) for x in samples] == [3, 10, 17]
        assert samples[0]['x'] == '8.5'
        stat = read(r/'statistics.json')['probes']['中心,"probe"']
        for field in ['rho', 'ux', 'uy', 'uz', 'speed', 'p']:
            numbers = [float(x[field]) for x in samples]
            assert math.isclose(stat['fields'][field]['mean'], statistics.mean(numbers), rel_tol=1e-12, abs_tol=1e-14)
            assert math.isclose(stat['fields'][field]['std_population'], statistics.pstdev(numbers), rel_tol=1e-10, abs_tol=1e-14)
        prepared = invoke('prepare-probes', base, ('--prepare-only',))
        assert read(prepared/'statistics.json')['global']['count'] == 0
        bad = copy.deepcopy(base); bad['analysis']['probes'][0]['position'][0] = 16
        invoke('outside-probe', bad, error='outside domain')
        bad = copy.deepcopy(base); bad['analysis']['probes'] *= 2
        invoke('duplicate-probe', bad, error='duplicate probe')
        bad = copy.deepcopy(base); bad['analysis']['start_step'] = 24
        invoke('late-sample', bad, error='exceeds run.steps')
        bad = copy.deepcopy(base); bad['analysis']['every'] = 0
        invoke('zero-interval', bad, error='outside supported range')
        bad = copy.deepcopy(base); bad['analysis']['forces'] = [{'id':'bad','target':'boundary:periodic'}]
        invoke('non-solid-target', bad, error='non-solid force target')
        variable = copy.deepcopy(base)
        variable['run']['steps'] = 31
        variable['analysis'].update(start_step=0, every=3)
        variable['initial']['regions'] = [{'box_min':[0,0,0],'box_max':[8,16,16],'rho':1.001,'velocity':[0.01,0,0]}]
        vr = invoke('varying-statistics', variable)
        vs = rows(vr/'probes.csv'); vm = read(vr/'statistics.json')['probes']['中心,"probe"']
        assert vm['fields']['ux']['std_population'] > 1e-6
        for field in ['rho','ux','p']:
            values = [float(x[field]) for x in vs]
            assert math.isclose(vm['fields'][field]['mean'],statistics.mean(values),rel_tol=1e-10,abs_tol=1e-12)
            assert math.isclose(vm['fields'][field]['std_population'],statistics.pstdev(values),rel_tol=1e-9,abs_tol=1e-12)
        plain = copy.deepcopy(variable); del plain['analysis']
        nr = invoke('sampling-independent', plain)
        for field in ['u','rho','flags','p']:
            assert p1.vtk(nr/f'{field}-000000031.vtk')['payload'] == p1.vtk(vr/f'{field}-000000031.vtk')['payload']
        # Nonzero pressure reference and SI factors, including initial rho distinct from fluid.rho.
        lb = copy.deepcopy(base); lb['initial']['rho'] = 1.001
        lb['analysis'].update(start_step=0,every=7)
        lr = invoke('lattice-pressure', lb)
        si = copy.deepcopy(lb); si['units']={'mode':'si','reference_density':1000,'dt':.003}
        si['domain']={'length':[.16,.16,.16],'dx':.01}; si['fluid']={'rho':1000,'nu':.02*.01**2/.003}
        si['initial']={'rho':1001,'velocity':[.03*.01/.003,0,0]}
        si['analysis']['probes'][0]['position']=[.08,.085,.085]
        sr = invoke('SI 中文 probes',si)
        for a,b in zip(rows(lr/'probes.csv'),rows(sr/'probes.csv')):
            for field,scale in [('rho',1000),('ux',.01/.003),('p',1000*(.01/.003)**2)]:
                assert math.isclose(float(b[field]),float(a[field])*scale,rel_tol=2e-6,abs_tol=1e-8),(field,a,b)
        for case in ['poiseuille','couette']:
            for height in [8,16,32]:
                c = read(repo/'configs'/f'{case}.json')
                c['domain']['cells']=[8,height+2,8]
                nu = .1*height/8  # acoustic scaling: fixed U=0.05 and Re=4
                c['fluid']['nu'] = nu
                steps = math.ceil(1.6*height**2/nu)
                c['run'].update(steps=steps,monitor_every=steps)
                c['analysis'].update(start_step=steps-98,every=49)
                c['analysis']['probes'][0]['position']=[4.5,height/2+.5,4.5]
                if case=='poiseuille': c['fluid']['body_force']=[8*nu*.05/height**2,0,0]
                out=invoke(f'{case}-{height}',c)
                u=p1.vtk(out/f'u-{steps:09d}.vtk')['values']
                actual=[sum(u[3*(x+8*(y+(height+2)*z))] for x in range(8) for z in range(8))/64 for y in range(1,height+1)]
                theory=[.05*(y-.5)/height if case=='couette' else 4*.05*(y-.5)*(height-y+.5)/height**2 for y in range(1,height+1)]
                l2=math.sqrt(sum((a-b)**2 for a,b in zip(actual,theory))/sum(b*b for b in theory))
                linf=max(abs(a-b) for a,b in zip(actual,theory))/.05
                force=read(out/'statistics.json')['forces']
                shear=nu*.05*64/height
                expected=([4*nu*.05*64/height]*2 if case=='poiseuille' else [shear,-shear])
                measured=[force[n]['fields']['fx']['mean'] for n in ['lower','upper']]
                force_error=max(abs(a-b)/abs(b) for a,b in zip(measured,expected))
                profile={'case':case,'H':height,'nu':nu,'Re':.05*height/nu,'steps':steps,'l2_relative':l2,'linf_over_U':linf,
                         'force_measured':measured,'force_expected':expected,'force_relative_error':force_error,
                         'u':actual,'analytical_u':theory,'results':str(out)}
                report['profiles'].append(profile);write(root/'report.json',report)
                assert l2<.03 and linf<.03,(case,height,l2,linf)
                assert force_error<.04,(case,height,measured,expected)
                assert int(rows(out/'analysis.csv')[-1]['fluid_cells'])==64*height
        for case in ['poiseuille','couette']:
            lattice = copy.deepcopy(read(root/f'{case}-16'/'case.json'))
            config = copy.deepcopy(lattice)
            dx,dt,rho=.01,.003,1000
            config['units']={'mode':'si','reference_density':rho,'dt':dt}
            config['domain']={'length':[n*dx for n in lattice['domain']['cells']],'dx':dx}
            config['fluid']['rho']=rho
            config['fluid']['nu']*=dx*dx/dt
            if 'body_force' in config['fluid']:
                config['fluid']['body_force']=[x*rho*dx/dt**2 for x in config['fluid']['body_force']]
            for b in config['boundaries']:
                if 'velocity' in b: b['velocity']=[x*dx/dt for x in b['velocity']]
            for p in config['analysis']['probes']:p['position']=[x*dx for x in p['position']]
            out=invoke(case+'-SI',config)
            before=read(root/f'{case}-16'/'results'/'statistics.json')
            after=read(out/'statistics.json')
            for side in ['lower','upper','total']:
                for field in ['fx','fy','fz']:
                    a=before['forces'][side]['fields'][field]['mean']
                    b=after['forces'][side]['fields'][field]['mean']
                    assert math.isclose(b,a*rho*dx**4/dt**2,rel_tol=1e-5,abs_tol=1e-7),(case,side,field,a,b)
            fields=p1.vtk(out/f"u-{config['run']['steps']:09d}.vtk")
            assert fields['spacing']==(.01,.01,.01)
        wall=read(repo/'configs'/'couette.json');wall['boundaries'][2]['velocity'][1]=.01
        invoke('normal-wall-speed',wall,error='tangential')
        wall['boundaries'][2]['velocity'][1]=0;wall['fluid']['rho']=2
        invoke('wall-density',wall,error='density 1')
        wall=read(repo/'configs'/'couette.json');wall['analysis']['probes'][0]['position']=[4.5,.5,4.5]
        invoke('solid-probe',wall,error='inside solid')
        # Snapshot geometry targets, rejected overlapping target, force sampling must not perturb fields.
        mesh=root/'cube.stl';p1.cube(mesh)
        geo=copy.deepcopy(base);geo['analysis']={'every':7,'probes':[], 'forces':[{'id':'cube','target':'geometry:cube'}]}
        geo['geometry']=[{'id':'cube','file':str(mesh),'transform':{'mode':'scale','factor':4,'translation':[6,6,6]}}]
        gr=invoke('geometry-force',geo)
        assert read(gr/'statistics.json')['forces']['cube']['count']==4
        gp=copy.deepcopy(geo);del gp['analysis']; gpr=invoke('geometry-no-force-sampling',gp)
        for f in ['rho','u','flags']:
            assert p1.vtk(gr/f'{f}-000000023.vtk')['payload']==p1.vtk(gpr/f'{f}-000000023.vtk')['payload']
        geo['geometry'].append(dict(geo['geometry'][0],id='overlap'))
        invoke('overlap-force',geo,error='overlapping geometry force target')
        # Batch generation and execution, all through the production NUC wrapper.
        study=root/'study 中文'
        script=repo/'scripts'/'parameter-study.py'
        subprocess.run([sys.executable,str(script),'generate','--spec',str(repo/'configs'/'study-periodic.json'),'--output',str(study)],check=True)
        subprocess.run([sys.executable,str(script),'run','--study',str(study),'--workspace-root',str(workspace),'--build-name',args.build_name,'--device',args.device],check=True)
        summary=read(next((study/'runs').glob('*/summary.json')))
        assert summary['status']=='succeeded' and len(summary['cases'])==4
        assert all(x['steps']==23 for x in summary['cases'])
        # Failed combination is retained and does not stop the remaining case.
        badspec=root/'study-fail.json'
        write(badspec,{'schema_version':1,'base_config':str(repo/'configs'/'probes-periodic.json'),'parameters':[{'path':'/fluid/nu','values':[-.01,.02]}]})
        badstudy=root/'failed-study'
        subprocess.run([sys.executable,str(script),'generate','--spec',str(badspec),'--output',str(badstudy)],check=True)
        result=subprocess.run([sys.executable,str(script),'run','--study',str(badstudy),'--workspace-root',str(workspace),'--build-name',args.build_name,'--device',args.device])
        assert result.returncode!=0
        summary=read(next((badstudy/'runs').glob('*/summary.json')))
        assert [x['status'] for x in summary['cases']]==['failed','succeeded']
        report['status']='succeeded'
    except Exception as error:
        report['status']='failed';report['error']=repr(error)
        raise
    finally:
        write(root/'report.json',report)
        print(root/'report.json',flush=True)


if __name__=='__main__':
    main()
