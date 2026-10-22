"""Read-only V2.0.0 field post-processing. No solver or third-party Python runtime."""
from dataclasses import dataclass
import math
import mmap
from pathlib import Path
import re
import shutil
import struct
import threading
import uuid

from core import Problem, atomic_json, inside, now, read_json, stl_info, MAX_STL

FIELDS = {'u': 3, 'rho': 1, 'p': 1, 'T': 1, 'phi': 1, 'flags': 1, 'material': 1, 'object': 1}
UNITS = {'u': 'm/s', 'rho': 'kg/m³', 'p': 'Pa', 'T': 'K', 'phi': '1',
         'flags': 'bit mask', 'material': 'ID', 'object': 'ID'}
JSON_NAMES = {'effective-config.json', 'resolved-config.json', 'manifest.json'}
MAX_UPLOAD = 2 * 1024**3
MAX_IMPORT = 10 * 1024**3


@dataclass
class Field:
    path: Path
    name: str
    dimensions: list
    origin: list
    spacing: list
    components: int
    dtype: str
    offset: int
    signature: tuple

    @classmethod
    def read(cls, path):
        """Strict legacy STRUCTURED_POINTS subset emitted by Solver-IBM V2.0.0."""
        def require(ok, message):
            if not ok:
                raise Problem(path.name + '：' + message)
        with path.open('rb') as f:
            def line():
                raw = f.readline(4097)
                require(len(raw) <= 4096 and raw.endswith(b'\n'), 'VTK 头部不完整')
                return raw.decode('ascii', errors='replace').strip()
            require(line().startswith('# vtk DataFile Version'), '不是 legacy VTK 文件')
            line()  # Version title is informational; units must come from metadata.
            require(line() == 'BINARY', '首版仅支持 V2.0.0 的二进制 VTK')
            require(line() == 'DATASET STRUCTURED_POINTS', '仅支持 STRUCTURED_POINTS 均匀网格')
            def vector(keyword, cast):
                parts = line().split()
                require(len(parts) == 4 and parts[0] == keyword, '缺少 ' + keyword)
                return [cast(x) for x in parts[1:]]
            dims = vector('DIMENSIONS', int)
            origin = vector('ORIGIN', float)
            spacing = vector('SPACING', float)
            require(all(0 < n <= 2**31 for n in dims), '无效的网格数量')
            require(all(math.isfinite(v) for v in origin + spacing) and min(spacing) > 0,
                    '坐标或格距不是有限正值')
            parts = line().split()
            require(len(parts) == 2 and parts[0] == 'POINT_DATA' and int(parts[1]) == math.prod(dims),
                    'POINT_DATA 与网格数量不符')
            parts = line().split()
            require(len(parts) in (3, 4) and parts[0] == 'SCALARS', '缺少 SCALARS 字段')
            name, dtype = parts[1:3]
            components = int(parts[3]) if len(parts) == 4 else 1
            require(name in FIELDS and components == FIELDS[name], '不支持的场变量或分量数')
            require(dtype == ('unsigned_char' if name in ('flags', 'material', 'object') else 'float'),
                    '字段类型不匹配')
            require(line() == 'LOOKUP_TABLE default', '缺少 LOOKUP_TABLE')
            offset = f.tell()
            expected = offset + math.prod(dims) * components * (4 if dtype == 'float' else 1)
            stat = path.stat()
            require(stat.st_size >= expected and stat.st_size <= expected + 2, '数据未写完、被截断或包含额外字段')
            f.seek(expected)
            require(not f.read().strip(), '存在额外数据')
        return cls(path, name, dims, origin, spacing, components, dtype, offset,
                   (stat.st_size, stat.st_mtime_ns))

    def slice(self, axis, index, component, limit=257):
        if axis not in (0, 1, 2) or not 0 <= index < self.dimensions[axis]:
            raise Problem('切片索引超出网格范围')
        if component not in (['magnitude', 'x', 'y', 'z'] if self.components == 3 else ['scalar']):
            raise Problem('无效的场分量')
        stat = self.path.stat()
        if (stat.st_size, stat.st_mtime_ns) != self.signature:
            raise Problem('结果文件已经变化，请重新载入数据集', 409)
        axes = [a for a in range(3) if a != axis]
        indices = []
        for a in axes:
            n = self.dimensions[a]
            # Include both edges; never mislabel a preview as full resolution.
            count = min(n, limit)
            indices.append(sorted({round(i * (n - 1) / max(count - 1, 1)) for i in range(count)}))
        values, invalid = [], 0
        stride = self.components * (4 if self.dtype == 'float' else 1)
        with self.path.open('rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
            for j in indices[1]:
                for i in indices[0]:
                    xyz = [0, 0, 0]
                    xyz[axis], xyz[axes[0]], xyz[axes[1]] = index, i, j
                    cell = xyz[0] + self.dimensions[0] * (xyz[1] + self.dimensions[1] * xyz[2])
                    offset = self.offset + cell * stride
                    if self.dtype == 'unsigned_char':
                        value = data[offset]
                    else:
                        raw = struct.unpack_from('>' + 'f' * self.components, data, offset)
                        value = (math.hypot(*raw) if component == 'magnitude' else
                                 raw['xyz'.index(component)] if self.components == 3 else raw[0])
                    if not math.isfinite(value):
                        invalid += 1
                        value = None
                    values.append(value)
        valid = [v for v in values if v is not None]
        if not valid:
            raise Problem('此切片没有有限场值')
        return {'axis': axis, 'index': index, 'position': self.origin[axis] + index * self.spacing[axis],
                'axes': axes, 'coordinates': [[self.origin[a] + i * self.spacing[a] for i in samples]
                                             for a, samples in zip(axes, indices)],
                'values': values, 'range': [min(valid), max(valid)], 'invalid': invalid,
                'sampled': any(len(s) < self.dimensions[a] for a, s in zip(axes, indices)),
                'source_shape': [self.dimensions[a] for a in axes]}


class Results:
    def __init__(self, workbench):
        self.app = workbench
        self.root = workbench.root / 'imports'
        self.root.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.cache = {}

    def catalog(self):
        items = [{'id': 'job-' + j['id'], 'name': j['case_name'], 'status': j['status'],
                  'kind': 'job', 'created_at': j['created_at']} for j in self.app.jobs()]
        for file in self.root.glob('*/source.json'):
            try:
                item = read_json(file)
                if item.get('ready'):
                    items.append({k: item[k] for k in ('id', 'name', 'kind', 'created_at')})
            except (ValueError, KeyError, OSError):
                continue
        return sorted(items, key=lambda x: x['created_at'], reverse=True)

    def import_root(self, ident):
        if not re.fullmatch(r'import-[0-9a-f]{32}', ident):
            raise Problem('无效的导入标识')
        root = inside(self.root, ident)
        if not root.is_dir():
            raise Problem('导入记录不存在', 404)
        return root

    def create(self, name, directory=None):
        name = str(name or '手动导入')[:160]
        ident = 'import-' + uuid.uuid4().hex
        root = self.root / ident
        source = {'id': ident, 'name': name, 'kind': 'folder' if directory else 'upload',
                  'ready': False, 'created_at': now()}
        if directory is not None:
            if not isinstance(directory, str) or not directory.strip():
                raise Problem('请输入 Windows 结果目录')
            # Windows files stay in place. Restrict reads to the configured working directory.
            allowed = self.app.root.parent.resolve()
            path = Path(directory).resolve()
            if not path.is_relative_to(allowed) or path == allowed:
                raise Problem('请选择 workingdir 内的一个算例结果目录')
            path = inside(allowed, path.relative_to(allowed).as_posix())
            if not path.is_dir():
                raise Problem('结果目录不存在', 404)
            source['directory'] = str(path)
        root.mkdir()
        (root / 'files').mkdir()
        atomic_json(root / 'source.json', source)
        if directory:
            try:
                self.finish(ident)
            except Exception:
                shutil.rmtree(root)
                raise
        return {'id': ident}

    def upload(self, ident, relative, stream, size):
        with self.lock:
            root = self.import_root(ident)
            source = read_json(root / 'source.json')
            if source['ready'] or source['kind'] != 'upload':
                raise Problem('已发布的结果不能覆盖', 409)
            path = inside(root / 'files', relative)
            suffix = path.suffix.lower()
            maximum = MAX_UPLOAD if suffix == '.vtk' else MAX_STL if suffix == '.stl' else 2 * 1024**2
            if suffix not in ('.vtk', '.stl', '.json') or (suffix == '.json' and path.name not in JSON_NAMES):
                raise Problem('仅导入 VTK、二进制 STL 和 effective/resolved-config、manifest JSON')
            if not 0 < size <= maximum:
                raise Problem('文件超过导入大小限制', 413)
            files = list((root / 'files').rglob('*'))
            if len(files) >= 10000 or sum(p.stat().st_size for p in files if p.is_file()) + size > MAX_IMPORT:
                raise Problem('单次导入上限为 10 GiB / 10000 项', 413)
            if path.exists():
                raise Problem('同名文件已上传', 409)
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + '.part')
            try:
                with temporary.open('wb') as f:
                    remaining = size
                    while remaining:
                        chunk = stream.read(min(1024**2, remaining))
                        if not chunk:
                            raise Problem('文件传输不完整')
                        f.write(chunk)
                        remaining -= len(chunk)
                if suffix == '.vtk':
                    Field.read(temporary)
                elif suffix == '.stl':
                    stl_info(temporary.read_bytes())
                else:
                    if not isinstance(read_json(temporary), dict):
                        raise Problem('元数据必须为 JSON 对象')
                temporary.rename(path)
            finally:
                temporary.unlink(missing_ok=True)
            return {'path': relative, 'bytes': size}

    def finish(self, ident):
        with self.lock:
            root = self.import_root(ident)
            source = read_json(root / 'source.json')
            directory = Path(source.get('directory', root / 'files'))
            dataset = self.index(ident, directory=directory, refresh=True)
            if source['name'].lower() in ('results', 'export', 'output'):
                source['name'] = dataset['metadata']['name']
            source['ready'] = True
            atomic_json(root / 'source.json', source)
            return {'id': ident}

    def cancel(self, ident):
        with self.lock:
            root = self.import_root(ident)
            if read_json(root / 'source.json')['ready']:
                raise Problem('已完成的导入不能取消', 409)
            shutil.rmtree(root)
            self.cache.pop(ident, None)
            return {'cancelled': True}

    def directory(self, ident):
        if ident.startswith('job-'):
            record = self.app.record(ident[4:])
            if record['status'] in ('validating', 'starting', 'running', 'cancelling'):
                raise Problem('任务仍在运行，完成后自动读取结果', 409)
            return self.app.record_path(ident[4:]).parent / 'results'
        root = self.import_root(ident)
        source = read_json(root / 'source.json')
        if not source['ready']:
            raise Problem('文件尚未全部导入', 409)
        if 'directory' in source:
            path = Path(source['directory'])
            return inside(self.app.root.parent, path.relative_to(self.app.root.parent).as_posix())
        return root / 'files'

    def index(self, ident, directory=None, refresh=False):
        with self.lock:
            if not refresh and ident in self.cache:
                return self.cache[ident]
            root = directory or self.directory(ident)
            if not root.is_dir():
                raise Problem('此任务没有结果目录', 404)
            vtk_paths = []
            for path in root.rglob('*'):
                if path.suffix.lower() == '.vtk' and path.is_file():
                    vtk_paths.append(inside(root, path.relative_to(root).as_posix()))
                    if len(vtk_paths) > 10000:
                        raise Problem('单个数据集最多支持 10000 个 VTK 文件')
            if not vtk_paths:
                raise Problem('没有找到 VTK 场文件；请确认算例开启了 vtk_fields 输出')
            fields, grid, steps_known = {}, None, True
            for path in sorted(vtk_paths):
                field = Field.read(path)
                signature = (field.dimensions, field.origin, field.spacing)
                if grid is not None and signature != grid:
                    raise Problem('所选文件的网格或坐标不一致，请分别导入不同算例')
                grid = signature
                match = re.fullmatch(r'.+-(\d+)\.vtk', path.name, flags=re.I)
                step = int(match[1]) if match else 0
                steps_known &= bool(match)
                key = (step, field.name)
                if key in fields:
                    raise Problem('同一时间步存在重复变量：' + path.name)
                fields[key] = field
            # All metadata and its geometry must belong to one result root.
            parents = {p.parent for p in vtk_paths}
            if len(parents) != 1:
                raise Problem('请每次选择一个结果目录，勿合并多次计算')
            data_root = next(iter(parents))
            config_path, resolved_path = data_root / 'effective-config.json', data_root / 'resolved-config.json'
            config = read_json(inside(root, config_path.relative_to(root).as_posix())) if config_path.is_file() else {}
            resolved = read_json(inside(root, resolved_path.relative_to(root).as_posix())) if resolved_path.is_file() else {}
            dims, origin, spacing = grid
            warnings = []
            mode = config.get('units', {}).get('mode', 'unknown')
            mode = mode if mode in ('si', 'lattice') else 'unknown'
            if resolved:
                if (resolved.get('cells') != dims or any(not math.isclose(resolved.get('dx', -1), dx, rel_tol=1e-5) for dx in spacing)
                    or any(not math.isclose(resolved.get('origin', [math.inf]*3)[a] + spacing[a]/2, origin[a], abs_tol=spacing[a]*1e-4) for a in range(3))):
                    raise Problem('resolved-config 与 VTK 网格不匹配，不能组合此元数据')
            dt = resolved.get('dt') if steps_known else None
            if not isinstance(dt, (float, int)) or not math.isfinite(dt) or dt <= 0:
                dt = None
            if mode == 'unknown':
                warnings.append('缺少单位元数据：使用 VTK 原始坐标与场值，单位未知。')
            if dt is None:
                warnings.append('缺少 dt 或文件步号：不推断物理时间。')
            geometries = []
            for i, g in enumerate(config.get('geometry', [])):
                geometry = {'id': str(g.get('id', f'body-{i}')), 'transform': g.get('transform'), 'available': False}
                if g.get('motion'):
                    geometry['reason'] = '动态 STL 位姿叠加尚未支持；隐藏模型以避免与当前流场错位'
                else:
                    try:
                        path = inside(data_root, g.get('file', ''))
                        if not path.is_file():
                            raise Problem('STL 快照缺失')
                        if path.stat().st_size > MAX_STL:
                            raise Problem('STL 超过 50 MiB')
                        geometry.update(available=True, path=path.relative_to(root).as_posix())
                    except Problem as exc:
                        geometry['reason'] = str(exc)
                geometries.append(geometry)
            if not config.get('geometry'):
                for path in root.rglob('*.stl'):
                    path = inside(root, path.relative_to(root).as_posix())
                    if len(geometries) >= 254:
                        raise Problem('最多叠加 254 个 STL 对象')
                    if path.stat().st_size > MAX_STL:
                        raise Problem('STL 超过 50 MiB')
                    geometries.append({'id': path.stem, 'path': path.relative_to(root).as_posix(),
                                       'transform': None, 'available': True})
                if geometries:
                    warnings.append('STL 缺少变换元数据：按文件原始坐标叠加，请确认与流场使用相同坐标系。')
            steps = sorted({s for s, _ in fields})
            metadata = {'id': ident, 'name': config.get('case', {}).get('name', data_root.name),
                        'dimensions': dims, 'origin': origin, 'spacing': spacing, 'unit_mode': mode,
                        'coordinate_unit': 'm' if mode == 'si' else 'lu' if mode == 'lattice' else '未知单位',
                        'bounds': [[origin[a] - spacing[a]/2, origin[a] + (dims[a]-.5)*spacing[a]] for a in range(3)],
                        'frames': [{'step': s, 'time': s*dt if dt else None, 'fields': sorted(n for step, n in fields if step == s)} for s in steps],
                        'fields': [{'id': n, 'components': FIELDS[n], 'unit': UNITS[n] if mode == 'si' else
                                    ('lu' if mode == 'lattice' else '未知单位') if n not in ('flags','material','object','phi') else UNITS[n]}
                                   for n in FIELDS if any(name == n for _, name in fields)],
                        'geometries': geometries, 'warnings': warnings, 'step_known': steps_known}
            value = {'metadata': metadata, 'fields': fields, 'root': root}
            if len(self.cache) >= 8:
                self.cache.pop(next(iter(self.cache)))
            self.cache[ident] = value
            return value

    def slice(self, ident, field, step, axis, index, component):
        dataset = self.index(ident)
        data = dataset['fields'].get((step, field))
        if data is None:
            raise Problem('这个时间步没有所选场变量', 404)
        return data.slice(axis, index, component)

    def geometry(self, ident, index):
        data = self.index(ident)
        geometries = data['metadata']['geometries']
        if not 0 <= index < len(geometries) or not geometries[index]['available']:
            raise Problem('STL 快照不可用', 404)
        return inside(data['root'], geometries[index]['path'])
