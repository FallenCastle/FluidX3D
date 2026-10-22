"""Numerical and import contract tests. No Solver-IBM execution."""
import copy
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'service'))
from core import Problem, Workbench, atomic_json, read_json, WORKBENCH
from results import Field, Results
from test_service import FakePackage, FakeRunner


def vtk(name='u', dims=(4,3,2), origin=(1.25,2.25,3.25), spacing=(.5,.5,.5), invalid=False):
    components = 3 if name == 'u' else 1
    byte = name in ('flags','object','material')
    header = (f'# vtk DataFile Version 3.0\nSolver-IBM 2.0.0\nBINARY\nDATASET STRUCTURED_POINTS\n'
              f'DIMENSIONS {dims[0]} {dims[1]} {dims[2]}\nORIGIN {origin[0]} {origin[1]} {origin[2]}\n'
              f'SPACING {spacing[0]} {spacing[1]} {spacing[2]}\nPOINT_DATA {dims[0]*dims[1]*dims[2]}\n'
              f'SCALARS {name} {"unsigned_char" if byte else "float"} {components}\nLOOKUP_TABLE default\n').encode()
    values=[]
    for z in range(dims[2]):
        for y in range(dims[1]):
            for x in range(dims[0]):
                value=x+10*y+100*z
                values.extend([value,value+1,value+2] if name=='u' else [value%256])
    if invalid:
        values[0]=float('nan')
    return header+struct.pack('>'+('B' if byte else 'f')*len(values),*values)


class ResultsTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.app=Workbench(self.root/'workingdir/data',FakePackage(self.root/'package'),FakeRunner())
        self.results=Results(self.app)

    def tearDown(self):
        self.app.shutdown();self.temp.cleanup()

    def file(self, name='u', **kw):
        path=self.root/(name+'-000000010.vtk');path.write_bytes(vtk(name,**kw));return path

    def test_big_endian_vector_and_xyz_order(self):
        field=Field.read(self.file())
        z=field.slice(2,1,'x')
        self.assertEqual(z['values'],[100,101,102,103,110,111,112,113,120,121,122,123])
        self.assertEqual(z['position'],3.75)
        self.assertEqual(z['coordinates'],[[1.25,1.75,2.25,2.75],[2.25,2.75,3.25]])
        self.assertEqual(field.slice(0,2,'z')['values'],[4,14,24,104,114,124])
        self.assertEqual(field.slice(1,1,'y')['values'],[11,12,13,14,111,112,113,114])
        self.assertAlmostEqual(field.slice(2,0,'magnitude')['values'][0],5**.5)
        self.assertEqual(Field.read(self.file('flags')).slice(2,1,'scalar')['values'][0],100)

    def test_corrupt_changed_and_unsupported(self):
        path=self.file();path.write_bytes(path.read_bytes()[:-1])
        with self.assertRaises(Problem):Field.read(path)
        path=self.file();path.write_bytes(path.read_bytes().replace(b'BINARY',b'ASCII '))
        with self.assertRaises(Problem):Field.read(path)
        field=Field.read(self.file());field.path.write_bytes(field.path.read_bytes()+b'\n')
        with self.assertRaises(Problem):field.slice(2,0,'x')
        with self.assertRaises(Problem):Field.read(self.file()).slice(2,2,'x')

    def test_preview_includes_edges_and_nonfinite(self):
        field=Field.read(self.file(invalid=True));data=field.slice(2,0,'x',limit=2)
        self.assertTrue(data['sampled']);self.assertEqual(data['coordinates'][0],[1.25,2.75])
        self.assertEqual(data['invalid'],1);self.assertIsNone(data['values'][0])
        self.assertEqual(data['range'],[3,23])

    def upload(self, ident, path, data):
        return self.results.upload(ident,path,io.BytesIO(data),len(data))

    def test_standalone_and_full_directory_import(self):
        ident=self.results.create('actual fields')['id']
        self.upload(ident,'case/u-000000010.vtk',vtk())
        with self.assertRaises(Problem):self.results.directory(ident)
        self.results.finish(ident)
        m=self.results.index(ident)['metadata'];self.assertEqual(m['unit_mode'],'unknown');self.assertIsNone(m['frames'][0]['time'])
        self.assertEqual(m['bounds'],[[1,3],[2,3.5],[3,4]])
        with self.assertRaises(Problem):self.upload(ident,'new.vtk',vtk())
        ident=self.results.create('full')['id']
        self.upload(ident,'case/u-000000010.vtk',vtk())
        config={'case':{'name':'full'},'units':{'mode':'si'},'geometry':[{'id':'body','file':'inputs/assets/0.stl','transform':{'mode':'fit','size':.1,'center':[2,3,4]}}]}
        resolved={'cells':[4,3,2],'dx':.5,'origin':[1,2,3],'dt':.01}
        for name,obj in [('effective-config',config),('resolved-config',resolved)]:
            self.upload(ident,'case/'+name+'.json',json.dumps(obj).encode())
        self.upload(ident,'case/inputs/assets/0.stl',(WORKBENCH.parent/'configs/assets/unit-cube-binary.stl').read_bytes())
        self.results.finish(ident);m=self.results.index(ident)['metadata']
        self.assertEqual(m['frames'][0]['time'],.1);self.assertEqual(m['fields'][0]['unit'],'m/s')
        self.assertTrue(self.results.geometry(ident,0).is_file())
        self.assertEqual(m['geometries'][0]['transform'],config['geometry'][0]['transform'])
        self.assertEqual(len(self.results.catalog()),2)

    def test_mixed_grids_duplicates_and_metadata_rejected(self):
        ident=self.results.create('mixed')['id']
        self.upload(ident,'u-1.vtk',vtk());self.upload(ident,'p-1.vtk',vtk('p',dims=(5,3,2)))
        with self.assertRaises(Problem):self.results.finish(ident)
        self.results.cancel(ident)
        ident=self.results.create('duplicate')['id']
        self.upload(ident,'u-1.vtk',vtk());self.upload(ident,'other-1.vtk',vtk())
        with self.assertRaises(Problem):self.results.finish(ident)
        self.results.cancel(ident)
        ident=self.results.create('metadata')['id'];self.upload(ident,'u-1.vtk',vtk())
        self.upload(ident,'resolved-config.json',b'{"cells":[5,3,2],"dx":0.5,"origin":[1,2,3],"dt":0.01}')
        with self.assertRaises(Problem):self.results.finish(ident)

    def test_upload_paths_cleanup_and_windows_directory_scope(self):
        ident=self.results.create('bad')['id']
        for path in ['../u.vtk','C:/u.vtk','x\\u.vtk','source.json','runtime.exe']:
            with self.assertRaises(Problem):self.upload(ident,path,vtk())
        with self.assertRaises(Problem):self.upload(ident,'u.vtk',b'broken')
        self.assertEqual(list((self.results.import_root(ident)/'files').rglob('*')),[])
        with self.assertRaises(Problem):self.results.create('outside',str(self.root))
        folder=self.app.root.parent/'old-results';folder.mkdir();(folder/'u-12.vtk').write_bytes(vtk())
        external=self.results.create('old',str(folder))['id']
        self.assertEqual(self.results.index(external)['metadata']['frames'][0]['step'],12)
        self.assertEqual((folder/'u-12.vtk').read_bytes(),vtk())
        self.results.cancel(ident)
        self.assertFalse((self.results.root/ident).exists())

if __name__=='__main__':unittest.main()
