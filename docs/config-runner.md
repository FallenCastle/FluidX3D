# 配置驱动的命令行算例

当前完整用法见 [中文使用手册（P3）](user-manual-zh.md)，包括编译、全部配置字段及默认值、运行和输出。下文保留原阶段功能说明；P3 模型扩展另见 [P3 模型说明](config-runner-p3.md)。

本分支提供一个固定能力的 `FluidX3D.exe`，通过 JSON 和二进制 STL 切换静态单相流算例。支持格子单位和 SI；固定 D3Q19/SRT/SUBGRID，P2 支持通过 `solver.storage` 选择 FP16S（默认）或 FP32；两者算术均为 FP32。无 GRAPHICS、PNG 或交互窗口，使用 VTK 检查几何和流场。

设计契约见 [config-runner-design.md](config-runner-design.md)，格式定义见 [case.schema.json](../schemas/case.schema.json)。C++ 执行器还会检查 schema 无法表达的周期配对、边界冲突、单位转换、几何范围和设备资源。OpenCL 内核仍在程序启动时根据网格编译，无须重新构建 C++ 可执行文件。

P2 的体积力、固定位置运动壁面、受力、探针和参数扫描见 [config-runner-p2.md](config-runner-p2.md)；P2 发布构建名为 `config-runner-p2`，下文基础命令中的 BuildName/目录可替换为该名称。

## 构建一次

所有命令在 NUC PowerShell 中执行。源码先按项目约定由 Mac 提交推送，NUC 拉取；不要在 Mac 编译运行。

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
Set-Location "$root\src"
.\scripts\build-nuc.ps1 -WorkspaceRoot $root -BuildName config-runner
```

只改变配置和 STL 时跳过构建。改动源码或依赖后才重新构建。发布构建保存在 `bin/config-runner/`，旧 `boeing-747-smoke` 和 `config-baseline-console` 独立保留。

## 先校验和检查设备

```powershell
& "$root\bin\config-runner\FluidX3D.exe" --capabilities
& "$root\bin\config-runner\FluidX3D.exe" --list-devices
& "$root\bin\config-runner\FluidX3D.exe" --config .\configs\periodic-lattice.json --validate
```

`--validate` 不初始化 GPU、不推进计算、不创建输出目录。它检查 JSON、STL 文件及变换和表面边界规则；体素化后才能确认的问题需要 prepare-only。

## 使用可追溯的运行脚本

```powershell
.\scripts\run-nuc.ps1 -WorkspaceRoot $root -BuildName config-runner `
  -CaseName periodic-lattice -ConfigPath "$root\src\configs\periodic-lattice.json" `
  -DeviceId 0 -TimeoutSeconds 300

.\scripts\run-nuc.ps1 -WorkspaceRoot $root -BuildName config-runner `
  -CaseName boeing-preview -ConfigPath "$root\src\configs\boeing-regression.json" `
  -DeviceId 0 -PrepareOnly -TimeoutSeconds 300

.\scripts\run-nuc.ps1 -WorkspaceRoot $root -BuildName config-runner `
  -CaseName boeing-config -ConfigPath "$root\src\configs\boeing-regression.json" `
  -DeviceId 0 -TimeoutSeconds 1800
```

设备编号以本机枚举为准。`CaseName` 只定义结果归档名称，`ConfigPath` 决定实际算例。

每次生成新 RunId，不覆盖已有结果。运行脚本保留 EXE 快照、build.json、run.json 和日志。配置执行器的输入快照与数值结果都位于该次运行的 `results/`：

```text
workingdir/<CaseName>/<RunId>/
  build.json
  run.json
  logs/{stdout,stderr,runner}.log
  results/
    original-config.json          原始 JSON 文件的副本
    effective-config.json         指向本次 STL 快照的 JSON
    inputs/assets/{0,1,...}.stl
    manifest.json                 输入、EXE 的 SHA256
    resolved-config.json          整数网格、格子参数、单位尺度、设备与覆盖数量
    completion.json               状态、实际步数和时长
    monitor.csv
    status.txt
    {u,rho,flags}-000000000.vtk
    ...
```

也可直接启动：

```powershell
& "$root\bin\config-runner\FluidX3D.exe" --config 'C:\cases\my case\case.json' `
  --device 0 --output 'C:\cases\my case\run-001'
```

输出目录必须不存在或为空。直接启动也生成输入快照和 EXE 哈希；需要 Git/构建身份与超时管理时使用运行脚本。

## 示例配置

| 文件 | 用途 |
| --- | --- |
| `configs/periodic-lattice.json` | 无 STL 的均匀周期流；23 步，每7步输出，最终23步另输出 |
| `configs/periodic-si.json` | 与上例相同的格子问题，验证 SI 换算；参数为数值测试设置 |
| `configs/boeing-regression.json` | 对照旧 Boeing 256 MiB、1000步设置；保留原 Re 以域宽为参考长度的定义 |
| `configs/ahmed-smoke.json` | Ahmed 静态几何37步短算，仅用于工作流检查 |

Boeing/Ahmed 模板中的 STL 相对路径适配 NUC 的 `workingdir/<case>/assets/` 布局。复制配置到别处时，修改 `geometry[].file` 指向实际 STL；相对路径始终以配置文件目录为基准。外部大型 STL 不纳入源码 Git。

## 单位、域和几何

格子模式 `units.mode="lattice"`：使用 `domain.cells`；或 `aspect_ratio + memory_budget_mb` 估算网格，最终整数网格见 resolved-config。P2 的 FP16S 为 67 Bytes/cell、FP32 为 105 Bytes/cell（P1 FP16S 为 55），这是所选精度的设备场占用，实际资源检查另外考虑 STL 临时缓冲。

SI 模式示例：

```json
"units": { "mode": "si", "reference_density": 1000, "dt": 0.003 },
"domain": { "length": [0.16, 0.16, 0.16], "dx": 0.01 },
"fluid": { "rho": 1000, "nu": 0.0006666666666666666 },
"initial": { "velocity": [0.1, 0, 0] }
```

上面的片段不是独立配置，完整可运行版本见 periodic-si.json。SI 长度为 m，时间为 s，密度为 kg/m³，速度为 m/s，运动黏度为 m²/s。也可将 `dt` 换成 `reference_velocity` 和 `lattice_velocity`：dt=u_lattice×dx/U_SI。两套时间尺度参数不能并存。

nu_lattice=nu×dt/dx²，u_lattice=u×dt/dx，rho_lattice=rho/reference_density。必须明确参考密度，它定义 rho_lattice=1 对应的物理密度。

`fluid.nu` 与 `reynolds + reference_length + reference_velocity` 二选一。后者按 nu=U×L/Re 推导，长度和速度采用所选单位。改变网格后，参考长度与几何尺寸仍需按研究问题保持一致；软件不会暗中改变 Re 或黏度。

SI 的整数网格由 length/dx 向上取整，实际域长度及实际运行时长均会保存。`run.steps` 与 SI 的 `run.duration` 二选一。近整数浮点商按数值容差归并，避免23步误变24步。

`domain.origin` 默认为 [0,0,0]，表示盒角点。格点中心位于 origin+(i+0.5)×dx，VTK 使用相同坐标。STL 体素化接口内部另有半格偏移，由执行器处理，用户不需手动减0.5。

STL 必须为二进制三角面文件，且体素化后至少存在一个固体格点。支持：

- `fit`：先旋转，然后按旋转后包围盒最长边缩放到 size，包围盒中心放到 center。适合无单位的展示模型。
- `scale`：固定比例，p=translation+R×[factor×(p_stl−pivot)]。factor 为每个 STL 坐标单位对应的配置长度，pivot 为源 STL 坐标，translation 为目标坐标。适合固定物理尺寸、改变角度及多部件装配。

轴角由 `axis`（自动归一化）和 `degrees` 定义，右手系。默认不旋转。多个 STL 按各自体素结果求固体并集，重叠不会删除已有固体。域外几何拒绝裁剪；执行器不负责自动补洞、自交修复或把封闭 STL 自动转换为内部流道。

## 边界和初场

六面命名 xmin/xmax/ymin/ymax/zmin/zmax。每个非周期表面格点必须被规则覆盖，整轴周期需同时声明相对两面。

- `no_slip`：静止壁面，TYPE_S，速度零。
- `equilibrium`：给定 rho 和三维 velocity，TYPE_E。它不是通用压力出口或零梯度出口。
- `periodic`：保留该轴周期寻址，不另外赋 flags；该轴的面不能再设置局部墙面或入口。

局部面片示例：

```json
{
  "id": "inlet-patch",
  "faces": ["xmin"],
  "type": "equilibrium",
  "priority": 1,
  "region": { "min": [4,4], "max": [12,12] },
  "rho": 1,
  "velocity": [0.03,0,0]
}
```

这个面片的两个坐标为 y,z；其它面按未固定轴的 x/y/z 顺序取坐标。使用格点中心与闭区间匹配，长度单位与配置一致。通常先用 priority=0 的墙面覆盖整个表面，再用更高优先级的局部面片覆盖。相同最高优先级且赋值不同则报错，顺序不影响结果。STL 与 equilibrium 相交报错，与 no_slip 合并。

`initial.regions` 使用 box_min/box_max/rho/velocity，可覆盖盒状初场；数组中较后的区域覆盖较早区域。固体和边界最终赋值优先于初场。区域重叠的顺序语义只适用于初场，不适用于边界优先级。

## 输出和复现

`vtk_fields` 可选 u/rho/flags；`vtk_every=0` 表示只在最终步输出（`initial=true` 时另输出初始场）。监测与输出分别按各自间隔调度，最终步不足一个间隔也会输出。prepare-only 不推进步数，并保证输出 flags。

SI VTK 的坐标、速度和密度已转换为 SI；格子模式保留格子单位。CSV 的密度、速度和总质量明确标为 lattice，time 列使用所选时间单位。总质量只统计非固体格点；开放边界不要求质量保持不变。

`completion.json` 的 succeeded 只表示达到目标步数并通过本次运行检查；不代表达到物理稳态、网格收敛或工程精度。当前没有断点续算，status.txt 仅为报告。默认 FP16S 会产生可测的分布函数量化误差，均匀周期流测试使用密度相对1e-4及速度绝对1e-5的上限，同时要求空间均匀和 SI 等价；Boeing 回归另要求场数组逐字节一致。

复现时使用 `effective-config.json` 与其 inputs/assets；它记录的是实际使用的快照路径。若原配置采用预算/时长推导，resolved-config 中可核对实际网格/步数；格式版本不变时推导算法固定，不依赖 GPU 显存大小自动改网格。EXE、输入哈希与运行脚本保存的构建提交共同标识本次计算。

## 自动验收

```powershell
python .\scripts\test-config-runner.py --workspace-root $root --device 0
```

测试要求已存在对应的 config-baseline-boeing 基线运行。结果保存到 `workingdir/config-validation/<UTC>/report.json`，另有 baseline-comparison.json。测试失败保留日志，不把错误记录删除伪装为成功。测试仅在 NUC 执行。
