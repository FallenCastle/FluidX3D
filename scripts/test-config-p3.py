"""NUC-only model matrix, numerical accuracy, parameter and compatibility acceptance."""
import argparse
import copy
import datetime
import hashlib
import importlib.util
import itertools
import json
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location('p2', Path(__file__).with_name('test-config-p2.py'))
p2 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p2)
read, write, vtk = p2.read, p2.write, p2.p1.vtk


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace-root', required=True, type=Path)
    parser.add_argument('--build-name', default='config-runner-p3')
    parser.add_argument('--device', default='0')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Run on Windows NUC only')
    w = args.workspace_root
    repo = w/'src'
    exe = w/'bin'/args.build_name/'FluidX3D.exe'
    baseline = w/'bin'/'config-runner-p2'/'FluidX3D.exe'
    root = w/'workingdir'/'p3-validation'/datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    root.mkdir(parents=True)
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    report = {'status':'running', 'build':read(exe.parent/'build.json'), 'executable_sha256':sha(exe),
              'tests':[], 'profiles':[], 'matrix':[], 'comparisons':[], 'performance':[]}
    print(root, flush=True)

    def invoke(name, config, *, binary=exe, invalid=False, prepare=False, source=None):
        folder=root/name; folder.mkdir()
        write(folder/'case.json', config)
        start=time.perf_counter()
        options=['--validate'] if invalid else (['--prepare-only'] if prepare else [])
        with (folder/'stdout.log').open('wb') as out, (folder/'stderr.log').open('wb') as err:
            result=subprocess.run([str(binary),'--config',str(source or folder/'case.json'),
                                   '--device',args.device,'--output',str(folder/'results'),*options],
                                  cwd=folder, stdout=out,stderr=err,timeout=300)
        elapsed=time.perf_counter()-start
        report['tests'].append({'name':name,'exit_code':result.returncode,'expected_failure':invalid,'elapsed_seconds':elapsed})
        if invalid:
            assert result.returncode!=0 and 'solver' in (folder/'stderr.log').read_text(encoding='utf-8').lower(),name
        else:
            assert result.returncode==0,name
            output=folder/'results'
            resolved=read(output/'resolved-config.json')
            completion=read(output/'completion.json')
            assert completion['status']==('prepared' if prepare else 'succeeded'),name
            assert completion['steps']==(0 if prepare else config['run']['steps']),name
            if binary==exe:
                solver=dict(lattice='D3Q19',collision='SRT',storage='FP16S',turbulence='smagorinsky')
                solver.update(config.get('solver',{}))
                for key in solver:
                    assert resolved['solver'][key]==solver[key],(name,key)
                assert completion['solver']==resolved['solver']
                q=27 if solver['lattice']=='D3Q27' else 19
                width=4 if solver['storage']=='FP32' else 2
                n=math.prod(resolved['cells'])
                assert resolved['actual_distribution_buffer_bytes']==resolved['distribution_buffer_bytes']==n*q*width
                assert resolved['device_field_bytes']==n*(q*width+29)
                assert resolved['host_field_and_union_bytes']==n*30
                log=(folder/'stdout.log').read_text(encoding='utf-8',errors='replace')
                assert f"{solver['lattice']} {solver['collision']} (FP32/{solver['storage']})" in log
                assert 'Turbulence = '+solver['turbulence'] in log
        write(root/'report.json',report)
        print(name, result.returncode, flush=True)
        return folder/'results',elapsed

    def identical(name,a,b,statistics_too=True):
        files=sorted(p.name for p in a.glob('*.vtk'))
        assert files and files==sorted(p.name for p in b.glob('*.vtk')),name
        for filename in files:
            x,y=vtk(a/filename),vtk(b/filename)
            assert all(x[k]==y[k] for k in ['payload','origin','spacing','dimensions']),(name,filename)
        if statistics_too:
            assert read(a/'statistics.json')==read(b/'statistics.json'),name
        report['comparisons'].append({'name':name,'exact_vtk_arrays':len(files),'statistics_equal':statistics_too})

    try:
        assert sha(exe)==report['build']['executableSha256']
        cap=json.loads(subprocess.check_output([str(exe),'--capabilities']))
        assert cap['lattice']==['D3Q19','D3Q27'] and cap['collision']==['SRT','TRT']
        assert cap['turbulence']==['none','smagorinsky'] and cap['storage']==['FP16S','FP32']
        report['capabilities']=cap
        periodic=read(repo/'configs'/'probes-periodic.json')
        mesh=root/'cube.stl'; p2.p1.cube(mesh)
        combined=read(repo/'configs'/'couette.json')
        combined['domain']['cells']=[16,18,16]
        combined['fluid']['body_force']=[.0001,0,0]
        combined['boundaries'][2]['velocity']=[.08,0,0]
        combined['geometry']=[{'id':'cube','file':str(mesh),'transform':{'mode':'scale','factor':3,'translation':[6,6,6]}}]
        combined['run']={'steps':37,'monitor_every':7}
        combined['output']['vtk_every']=7
        combined['analysis'].update(start_step=0,every=7)
        combined['analysis']['forces'].append({'id':'cube','target':'geometry:cube'})
        combinations=list(itertools.product(['D3Q19','D3Q27'],['SRT','TRT'],['none','smagorinsky'],['FP16S','FP32']))
        for lattice,collision,turbulence,storage in combinations:
            model=dict(lattice=lattice,collision=collision,turbulence=turbulence,storage=storage)
            tag='-'.join([lattice,collision,turbulence,storage])
            c=copy.deepcopy(periodic); c['solver']=model
            r,_=invoke('uniform-'+tag,c)
            rho=vtk(r/'rho-000000023.vtk')['values']; u=vtk(r/'u-000000023.vtk')['values']
            assert max(rho)==min(rho) and max(abs(v-1) for v in rho)<1e-4
            assert max(abs(a-b) for a,b in zip(u,[.03,0,0]*4096))<1e-5
            c=copy.deepcopy(combined); c['solver']=model
            r,_=invoke('combined-'+tag,c)
            plain=copy.deepcopy(c);del plain['analysis']
            pr,_=invoke('plain-'+tag,plain)
            identical('sampling invariant '+tag,r,pr,False)
            perf=copy.deepcopy(periodic);perf['solver']=model;perf.pop('analysis')
            perf['domain']['cells']=[64,32,64];perf['run']={'steps':500,'monitor_every':500}
            perf['output']={'vtk_fields':['rho'],'vtk_every':0,'initial':False}
            durations=[]
            for repetition in range(2):
                _,elapsed=invoke('performance-'+tag+'-'+str(repetition),perf)
                durations.append(elapsed)
            report['performance'].append({'solver':model,'cells':[64,32,64],'steps':500,
                'process_seconds':durations,'warm_seconds':durations[1],
                'device_field_bytes':math.prod(perf['domain']['cells'])*(int(lattice[3:])*(4 if storage=='FP32' else 2)+29)})
            report['matrix'].append({'solver':model,'status':'succeeded'})
            for case,height in itertools.product(['poiseuille','couette'],[8,16,32]):
                c=read(repo/'configs'/(case+'.json'));c['solver']=model
                speed=.05*8/height;nu=.1;steps=math.ceil(1.6*height*height/nu)
                c['domain']['cells']=[8,height+2,8];c['fluid']['nu']=nu
                c['run']={'steps':steps,'monitor_every':steps}
                c['analysis'].update(start_step=steps-98,every=49)
                c['analysis']['probes'][0]['position']=[4.5,height/2+.5,4.5]
                if case=='poiseuille':c['fluid']['body_force']=[8*nu*speed/height**2,0,0]
                else:c['boundaries'][2]['velocity']=[speed,0,0]
                r,_=invoke(f'{case}-{height}-'+tag,c)
                u=vtk(r/f'u-{steps:09d}.vtk')['values']
                actual=[sum(u[3*(x+8*(y+(height+2)*z))] for x in range(8) for z in range(8))/64 for y in range(1,height+1)]
                theory=[speed*(y-.5)/height if case=='couette' else 4*speed*(y-.5)*(height-y+.5)/height**2 for y in range(1,height+1)]
                l2=math.sqrt(sum((a-b)**2 for a,b in zip(actual,theory))/sum(b*b for b in theory))
                linf=max(abs(a-b) for a,b in zip(actual,theory))/speed
                stats=read(r/'statistics.json')['forces']
                measured=[stats[n]['fields']['fx']['mean'] for n in ['lower','upper']]
                shear=nu*speed*64/height
                expected=[4*shear,4*shear] if case=='poiseuille' else [shear,-shear]
                force_error=max(abs(a-b)/abs(b) for a,b in zip(measured,expected))
                profile={'solver':model,'case':case,'H':height,'nu':nu,'U':speed,'steps':steps,
                         'l2_relative':l2,'linf_over_U':linf,'force_relative_error':force_error,
                         'force_measured':measured,'force_expected':expected,'u':actual,'analytical_u':theory,
                         'within_fp32_thresholds':l2<.03 and linf<.03 and force_error<.04,'results':str(r)}
                report['profiles'].append(profile)
        # Every exposed parameter rejects invalid values and irrelevant settings.
        for key in ['smagorinsky_constant','trt_magic_parameter']:
            for index,value in enumerate([0,-.1,1.01,1e-200,'0.17',None,True]):
                c=copy.deepcopy(periodic);c['solver']={'collision':'TRT','turbulence':'smagorinsky',key:value}
                invoke(f'invalid-{key}-{index}',c,invalid=True)
        for model in [{'collision':'SRT','trt_magic_parameter':.1875},
                      {'turbulence':'none','smagorinsky_constant':.17},{'collision':'MRT'},
                      {'lattice':'D3Q15'},{'lattice':'d3q27'},{'turbulence':'off'}]:
            c=copy.deepcopy(periodic);c['solver']=model
            invoke('invalid-model-'+str(len(report['tests'])),c,invalid=True)
        # Preserve defaults against the retained P2 production executable, both precisions.
        assert sha(baseline)==read(baseline.parent/'build.json')['executableSha256']
        report['p2_reference_build']=read(baseline.parent/'build.json')
        for storage in ['FP16S','FP32']:
            c=copy.deepcopy(combined);c['solver']={'storage':storage}
            old,_=invoke('p2-default-'+storage,c,binary=baseline)
            new,_=invoke('p3-default-'+storage,c)
            identical('P2 compatibility '+storage,old,new)
            c['solver'].update(lattice='D3Q19',collision='SRT',turbulence='smagorinsky',smagorinsky_constant=cap['defaults']['smagorinsky_constant'])
            explicit,_=invoke('explicit-default-'+storage,c)
            identical('explicit default Cs '+storage,new,explicit)
        # Cs and Lambda are active, not metadata-only knobs.
        for key,values in [('smagorinsky_constant',[.1,.3]),('trt_magic_parameter',[.1,.25])]:
            outputs=[]
            for index,value in enumerate(values):
                c=copy.deepcopy(combined);c['solver']={'lattice':'D3Q27','collision':'TRT','storage':'FP32',
                    'turbulence':'smagorinsky' if key=='smagorinsky_constant' else 'none',key:value}
                r,_=invoke('parameter-'+key+'-'+str(index),c);outputs.append(vtk(r/'u-000000037.vtk')['values'])
            difference=max(abs(a-b) for a,b in zip(*outputs))
            assert difference>1e-7,(key,difference)
            report['comparisons'].append({'name':key+' changes field','max_velocity_difference':difference})
        c=copy.deepcopy(combined);c['solver']={'lattice':'D3Q27','collision':'SRT','turbulence':'none','storage':'FP32'}
        srt,_=invoke('degenerate-srt',c)
        c['solver'].update(collision='TRT',trt_magic_parameter=(3*c['fluid']['nu'])**2)
        trt,_=invoke('degenerate-trt',c)
        for field in ['rho','u']:
            difference=max(abs(a-b) for a,b in zip(vtk(srt/f'{field}-000000037.vtk')['values'],vtk(trt/f'{field}-000000037.vtk')['values']))
            assert difference<3e-6,(field,difference)
            report['comparisons'].append({'name':'SRT/TRT degeneration '+field,'max_difference':difference})
        # A shear wave with wave vector (1,1,1), transverse velocity (1,-1,0).
        c=copy.deepcopy(periodic);c.pop('analysis');n=24;steps=32;amplitude=.001
        c['domain']['cells']=[n]*3;c['fluid']['nu']=.1
        c['solver']={'lattice':'D3Q27','collision':'TRT','turbulence':'none','storage':'FP32'}
        c['run']={'steps':steps,'monitor_every':steps};c['output']['vtk_every']=0
        regions=[];initial=[]
        for z,y,x in itertools.product(range(n),repeat=3):
            v=amplitude*math.sin(2*math.pi*(x+y+z+1.5)/n);initial.extend([v,-v,0])
            regions.append({'box_min':[x,y,z],'box_max':[x+1,y+1,z+1],'velocity':[v,-v,0]})
        c['initial']={'velocity':[0,0,0],'regions':regions}
        r,_=invoke('three-dimensional-shear-wave',c)
        decay=math.exp(-.1*3*(2*math.pi/n)**2*steps)
        actual=vtk(r/f'u-{steps:09d}.vtk')['values'];theory=[v*decay for v in initial]
        error=math.sqrt(sum((a-b)**2 for a,b in zip(actual,theory))/sum(v*v for v in theory))
        assert error<.03,error
        report['shear_wave']={'N':n,'steps':steps,'l2_relative':error,'threshold':.03}
        # SI equivalence includes voxelization, moving wall, body force and group forces.
        c=copy.deepcopy(combined);c['solver']={'lattice':'D3Q27','collision':'TRT','turbulence':'none','storage':'FP32'}
        lattice,_=invoke('si-reference',c)
        si=copy.deepcopy(c);dx,dt,rho=.01,.003,1000
        si['units']={'mode':'si','reference_density':rho,'dt':dt}
        si['domain']={'length':[n*dx for n in c['domain']['cells']],'dx':dx}
        si['fluid']={'rho':rho,'nu':c['fluid']['nu']*dx*dx/dt,'body_force':[v*rho*dx/dt**2 for v in c['fluid']['body_force']]}
        for b in si['boundaries']:
            if 'velocity' in b:b['velocity']=[v*dx/dt for v in b['velocity']]
        for g in si['geometry']:
            g['transform']['factor']*=dx;g['transform']['translation']=[v*dx for v in g['transform']['translation']]
        for p in si['analysis']['probes']:p['position']=[v*dx for v in p['position']]
        sr,_=invoke('SI 中文 model',si)
        for field,scale in [('u',dx/dt),('rho',rho),('p',rho*(dx/dt)**2),('flags',1)]:
            a=vtk(lattice/f'{field}-000000037.vtk')['values'];b=vtk(sr/f'{field}-000000037.vtk')['values']
            assert all(math.isclose(y,x*scale,rel_tol=2e-5,abs_tol=1e-6) for x,y in zip(a,b)),field
        before,after=read(lattice/'statistics.json'),read(sr/'statistics.json')
        for target in before['forces']:
            for field in ['fx','fy','fz']:
                a=before['forces'][target]['fields'][field]['mean'];b=after['forces'][target]['fields'][field]['mean']
                assert math.isclose(b,a*rho*dx**4/dt**2,rel_tol=2e-5,abs_tol=1e-7),(target,field)
        repeated,_=invoke('snapshot-model',read(sr/'effective-config.json'),source=sr/'effective-config.json')
        identical('model SI snapshot',sr,repeated)
        # Production batch wrapper must retain exactly the same EXE for all 16 models.
        study=root/'study-models';script=repo/'scripts'/'parameter-study.py'
        subprocess.run([sys.executable,str(script),'generate','--spec',str(repo/'configs'/'study-models.json'),'--output',str(study)],check=True)
        subprocess.run([sys.executable,str(script),'run','--study',str(study),'--workspace-root',str(w),'--build-name',args.build_name,'--device',args.device],check=True)
        summary=read(next((study/'runs').glob('*/summary.json')))
        assert summary['status']=='succeeded' and len(summary['cases'])==16
        for row in summary['cases']:
            record=read(Path(row['run_directory'])/'run.json')
            assert record['build']['executableSha256']==report['executable_sha256']
            actual=read(Path(row['results'])/'resolved-config.json')['solver']
            for pointer,value in row['parameters'].items():assert actual[pointer.split('/')[-1]]==value
        report['batch']=summary
        failures=[p for p in report['profiles'] if p['solver']['storage']=='FP32' and not p['within_fp32_thresholds']]
        report['analytic_fp32_failures']=failures
        assert not failures,[(p['solver'],p['case'],p['H']) for p in failures]
        assert sha(exe)==report['executable_sha256']
        report['status']='succeeded'
    except Exception as error:
        report['status']='failed';report['error']=repr(error)
        raise
    finally:
        write(root/'report.json',report)
        print(root/'report.json',flush=True)


if __name__=='__main__':
    main()
