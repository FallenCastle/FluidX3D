# P2 研究功能使用说明

在 P1 的配置运行器上增加恒定体积力、固定位置的运动壁面、探针、时间统计、表压、固体受力和参数扫描。D3Q19/SRT/Smagorinsky 仍固定，分布函数存储支持 FP16S/FP32 运行时选择；一个 P2 EXE 运行以下全部算例，不因输入变化重新构建。

## NUC 入口

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
Set-Location "$root\src"
# 已有发布产物时直接运行，不需要再构建。
.\scripts\run-nuc.ps1 -WorkspaceRoot $root -BuildName config-runner-p2 `
  -CaseName poiseuille -ConfigPath "$root\src\configs\poiseuille.json" -DeviceId 0
.\scripts\run-nuc.ps1 -WorkspaceRoot $root -BuildName config-runner-p2 `
  -CaseName couette -ConfigPath "$root\src\configs\couette.json" -DeviceId 0
```

`configs/probes-periodic.json` 是探针与采样示例。更换 device 前用 `--list-devices` 核实编号。所有运行沿用 EXE/输入快照、SHA256、独立 RunId 和失败退出码。

## 运行时存储精度

在配置中指定：

```json
"solver": {"storage": "FP32"}
```

`storage` 接受 `FP16S` 或 `FP32`，省略时为 FP16S。一个 EXE 可连续运行不同精度的配置，无需重新构建；一次计算开始后精度固定。两种模式的计算算术都为 FP32，区别是分布函数在 GPU 中以 16 位压缩或 32 位浮点数存储，不影响 VTK 输出类型。

FP16S 适合优先节省显存的计算；小速度、弱强迫及壁面剪切力精度敏感的算例应检查量化误差。Poiseuille/Couette 示例显式采用 FP32。切换示例见 `configs/periodic-fp32.json`；扫描示例 `configs/study-storage.json` 用 `/solver/storage` 一次生成两种模式。

`--capabilities` 列出支持值、默认值及每格点设备字段字节数。`resolved-config.json` 记录 `storage`、`distribution_bytes_per_value`、预期和实际的分布函数缓冲区容量；`completion.json`、`status.txt` 及运行日志同时标明实际精度。非法值直接报错，不自动降级。当前仍仅支持单设备、无图形的静态单相配置能力。

## 强迫与壁面

在 `fluid` 增加 `"body_force": [0.0001,0,0]`，表示全域恒定**体积力密度**，默认零。SI 单位为 N/m³；格子换算为 `f_l=f*dt²/(reference_density*dx)`。若已知加速度 a，应先用密度计算 f=rho*a。

运动壁面示例：

```json
{"id":"top","faces":["ymax"],"type":"moving_wall","velocity":[0.05,0,0]}
```

壁面位置固定、速度恒定且只能沿切向；STL 保持静止。上游反弹修正采用格子壁面密度 1，因此含 moving_wall 时所有输入格子密度必须为 1（SI 中输入密度等于 units.reference_density）。壁面与 STL 相交拒绝。

域的角点和格点中心约定保持 P1。无滑移墙在最外层固体格点与邻接流体格点的中点：Ny 个格点、上下各一层固体时，流体高度 H=(Ny-2)*dx。解析剖面比较必须使用这一高度。

## 采样与统计

配置顶层加入：

```json
"analysis": {
  "every": 50,
  "start_step": 3900,
  "statistics": true,
  "probes": [{"id":"center","position":[4.5,8.5,4.5]}],
  "forces": [
    {"id":"lower","target":"boundary:lower"},
    {"id":"upper","target":"boundary:upper"},
    {"id":"total","target":"all_solids"}
  ]
}
```

- every 为步数间隔，缺省为 monitor_every；start_step 缺省 0，适合排除启动瞬态。
- 只在 start_step+k*every 采样，终点不整除时不额外加入统计；VTK/monitor 仍保存最终状态。prepare-only 检查探针和分组，但统计样本数为 0。
- 探针按最近格点中心采样，同距选较大索引，记录请求/实际位置。位置采用配置单位，不能在域外或固体内。
- 不指定 analysis 则不生成研究统计；statistics=false 保留采样 CSV、关闭时间累积。

结果目录新增：

| 文件 | 内容 |
|---|---|
| probes.csv | 每个探针的 rho、ux/uy/uz、speed、表压 p |
| analysis.csv | 非固体格点的质量、空间平均 rho/u/speed/p、总动能 |
| forces.csv | 各目标的流体作用于固体的 fx/fy/fz |
| statistics.json | 各量的时间均值、总体标准差、样本数和首末采样步 |

SI 下长度 m、时间 s、密度 kg/m³、速度 m/s、表压 Pa、质量 kg、动能 J、力 N。格子输入输出全部用格子单位。原 monitor.csv 中后缀 `_lattice` 的列仍是格子量。统计不是全场平均 VTK，也不自动判断稳态。

表压以 fluid.rho 为参考，不受 initial.rho 覆盖影响：`p=(rho_l-rho_fluid_l)/3*reference_density*(dx/dt)²`。可在 output.vtk_fields 加入 `"p"` 导出同定义压力场；不是绝对热力学压力。

受力 target 支持 `all_solids`、`geometry:<STL的id>`、`boundary:<固体边界id>`。指定部件与另一部件重叠或与域墙相交时，分组归属不明确，拒绝该部件统计；仍可统计 all_solids 的并集。边界分组按实际获胜规则归属，多个同赋值同优先级规则交线归先出现者。

受力来自流体—固体链接的动量交换，包含运动壁面修正，静态背景压力按 fluid.rho 扣除。开放壁面的法向力是表压力贡献；封闭物体合力不受常量背景压力影响。只在采样时读取力场，诊断值不施加到流体。暂不输出力矩、阻力系数或移动几何轨迹。

## 参数扫描

Python 3.9+，只用标准库。扫描文件示例 `configs/study-periodic.json`：

```json
{
  "schema_version":1,
  "base_config":"probes-periodic.json",
  "parameters":[
    {"path":"/fluid/nu","values":[0.02,0.04]},
    {"path":"/initial/velocity/0","values":[0.02,0.03]}
  ]
}
```

JSON Pointer 替换已存在字段，按轴的笛卡尔积生成 4 个组合。允许扫描几何变换，不允许扫描 schema_version、几何 ID 或 STL 文件路径。拒绝重复/祖先冲突参数路径；最多 10000 组合。完整参数组合由求解器严格校验，非法组合保留失败记录。

```powershell
python .\scripts\parameter-study.py generate `
  --spec .\configs\study-periodic.json --output "$root\workingdir\my-study"
python .\scripts\parameter-study.py run `
  --study "$root\workingdir\my-study" --workspace-root $root `
  --build-name config-runner-p2 --device 0 --timeout 900
```

生成目录必须为空，包含描述/基础配置快照、资产、配置和 study.json 的 SHA256 清单。生成动作不运行求解器；执行动作仅支持 Windows NUC，逐项调用 run-nuc.ps1。一个组合失败后继续执行，其余组合保留结果，批次最终返回非零。

每次执行在批次 `runs/<RunId>/` 下保存 summary.json/CSV 和日志，指向 workingdir 中每项实际结果。重复执行会生成新的运行记录。执行前检查输入哈希并固定同一 EXE 哈希；修改快照会被拒绝。没有隐式重新生成、覆盖、恢复跳过或并行 GPU 调度。

## 存储与验证

P2 设备字段在 FP16S 下为 67 B/cell、FP32 下为 105 B/cell（P1 FP16S 为 55），两种模式的主机字段均为 29 B/cell，另加并集掩码、必要的部件归属与目标索引。resolved-config 保存估算与目标索引实际分配量；这些不包含驱动全部额外峰值。网格预算按所选精度计算，同样的 memory_budget_mb 在 FP32 下得到更小的网格；预算沿用最近整数取整，属于网格估算而非严格显存上限。Boeing 回归配置已经固定原 [170,339,85] 网格。

运行 `scripts/test-config-p2.py --workspace-root ...` 验证解析流动、受力、单位、采样、分组和批量流程；P1 回归继续用 test-config-runner.py。默认采用 FP32、固定 tau 的扩散尺度细化（H=8/16/32，Re=4）。Smagorinsky 与存储精度对解析剖面有可测影响，验收报告记录三档网格的实际误差，不把复杂外形短算等同于物理精度验证。

## 精度验收与历史限制

当前运行时 FP32 的三档 Poiseuille/Couette 速度及受力验收通过，默认 P2 验收脚本返回零。详见 [运行时精度验收记录](validation/runtime-storage-2026-09-22.md)。

此前 FP16S 在声学尺度细化的 Couette H=32 中出现约 8.15% 受力误差，同参数 FP32 约为 0.014%。该量化限制仍存在，不因增加 FP32 选项而消失。另有声学尺度的 FP32 Poiseuille 速度误差未过阈值，说明单纯提高存储精度不能替代合理的离散参数选择。历史失败及独立诊断结果保留在 [原 P2 验收记录](validation/config-runner-p2-2026-09-22.md)，本次没有放宽验收容差。
