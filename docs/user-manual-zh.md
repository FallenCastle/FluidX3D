# Solver-IBM V1.0.0 使用手册

本手册面向基于 FluidX3D 开发的 **Solver-IBM V1.0.0**，覆盖编译、JSON 配置、STL、命令行运行和结果检查。修改配置中的模型、参数、网格、边界或 STL 后，可直接复用同一个 EXE；OpenCL 内核仍会在运行时由设备驱动编译或从驱动缓存加载。

正式版本由 Git 标签 `v1.0.0` 固定；产品版本的唯一代码来源为 `src/version.hpp`。发布包的 `manifest.json` 和构建记录 `build.json` 保存具体提交、源码树和可执行文件 SHA256。`Solver-IBM.exe --version` 查询程序版本；`schema_version: 1` 仍表示 JSON 配置格式版本，与产品版本号分开管理。项目仓库和 NUC 工作目录仍沿用现有 `FluidX3D` 路径。

当前支持：单 GPU、三维单相流、静态 STL 并集、常量体积力、固定位置的运动壁面、探针及受力统计；模型组合为 D3Q19/D3Q27 × SRT/TRT × Smagorinsky 开/关 × FP16S/FP32，共 16 种。图形模式、运动 STL、自由液面、热模型、多 GPU、断点续算未作为本配置接口开放。

## 目录

- [1. 环境与目录](#1-环境与目录)
- [2. 编译与快速运行](#2-编译与快速运行)
- [3. JSON 通用规则](#3-json-通用规则)
- [4. 完整配置字段参考](#4-完整配置字段参考)
- [5. 完整示例与常见修改](#5-完整示例与常见修改)
- [6. 命令行及运行脚本参考](#6-命令行及运行脚本参考)
- [7. 参数扫描](#7-参数扫描)
- [8. 输出文件与结果检查](#8-输出文件与结果检查)
- [9. 常见错误](#9-常见错误)
- [10. 依据与维护](#10-依据与维护)

## 1. 环境与目录

### 1.1 工作分工

Mac 用于编辑代码、配置和文档，并通过 Git 提交、推送。**Solver-IBM 的编译、可执行程序调用和计算均在 Windows NUC 上完成**，包括 `--validate`。Mac 不编译或运行求解器。

| 用途 | 位置 |
|---|---|
| Mac 源码仓库 | `/Users/czy/Data/01-work/02-project/02-opensource/05-FluidX3D/FluidX3D` |
| 连接 NUC | 在 Mac 终端执行 `ssh NUC` |
| NUC 工作根目录 | `F:\01-Project\Opensource\01-FluidX3D` |
| NUC 源码仓库 | `F:\01-Project\Opensource\01-FluidX3D\src` |
| 正式 EXE 和构建记录 | `bin/<BuildName>/Solver-IBM.exe`、`build.json` |
| 算例运行记录 | `workingdir/<CaseName>/<RunId>/` |
| 每次运行的 EXE 快照 | `bin/_runs/<CaseName>/<RunId>/` |
| V1.0.0 正式发布归档 | `package/V1.0.0/`，发布后不在其中写入新结果 |

后文 PowerShell 示例均在 **NUC 的 64 位 Windows PowerShell** 中执行。若 SSH 登录后进入 `cmd.exe`，先输入 `powershell.exe -NoProfile`。PowerShell 中行尾反引号 `` ` `` 表示续行，其后不能再有空格。

### 1.2 编译和运行依赖

| 依赖 | 要求及用途 |
|---|---|
| Git | 拉取源码，记录分支、提交和源码树 |
| Windows PowerShell | 5.1 或以上；脚本通过 `powershell.exe` 调用 |
| Visual Studio / Build Tools | 安装 MSBuild 和 C++ 桌面开发组件；构建脚本通过 `vswhere.exe` 自动发现 |
| MSVC 工具集 | 默认 `v142`，即 VS 2019 C++ 工具集，可装在 VS 2022 中 |
| Windows SDK | 完整安装 Windows 10 SDK；脚本为项目中的 `10.0` 自动选择具体已安装版本 |
| OpenCL | 安装目标 GPU 的驱动及 OpenCL 运行时；仓库随附编译使用的 OpenCL 头文件和库 |
| Python | 仅参数扫描及 Python 验收脚本需要；本手册使用 Python 3.9+，扫描器仅用标准库 |

已验收 NUC 构建使用 MSVC `14.29.30133`、Windows SDK `10.0.22621.0`、`Release|x64`。不需要为了切换 D3Q19/D3Q27、SRT/TRT 或 FP16S/FP32 手动编辑 `defines.hpp`；当前编译配置是运行时选择功能的宿主配置。

## 2. 编译与快速运行

### 2.1 同步当前代码

Mac 上在源码仓库内检查并提交自己的修改：

```sh
cd /Users/czy/Data/01-work/02-project/02-opensource/05-FluidX3D/FluidX3D
git status --short --branch
git remote -v
git branch --show-current
# 有修改时，git add 明确的文件，随后 git commit，再 git push。
git rev-parse HEAD
```

NUC 上检查并拉取同一分支：

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
Set-Location "$root\src"
git status --short --branch
git remote -v
git branch --show-current
# 开发仓库拉取当前工作分支；精确复现正式发布请使用 v1.0.0 标签或第 2.5 节的 bundle。
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw 'Git pull failed.' }
git rev-parse HEAD
```

核对 Mac/NUC 提交一致。不要通过强制重置覆盖本地修改。配置和 STL 可放在仓库外的算例目录；构建前源码仓库必须干净，包含未跟踪文件也会被检查。

### 2.2 编译一次

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
Set-Location "$root\src"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-nuc.ps1 `
  -WorkspaceRoot $root -BuildName solver-ibm-v1.0.0 -PlatformToolset v142
if ($LASTEXITCODE -ne 0) { throw 'Build failed; inspect the build log.' }

$build = Get-Content "$root\bin\solver-ibm-v1.0.0\build.json" -Raw | ConvertFrom-Json
$build | Select-Object status, gitCommit, sourceTree, executablePath, executableSha256
```

构建脚本执行 `Release|x64` 的 `Rebuild`，检查工具链和输出路径，将 EXE 发布到 `bin/solver-ibm-v1.0.0/`。详细日志位于 `workingdir/_builds/<BuildId>/msbuild.log`。成功应同时满足脚本正常退出、`build.json.status = succeeded`、EXE 哈希与记录一致，不能仅凭 EXE 存在判断。

| `build-nuc.ps1` 参数 | 可用值 / 约束 | 缺省值 |
|---|---|---|
| `-WorkspaceRoot` | Windows 工作根目录，输出写入其 `bin`、`workingdir` | 脚本所在源码仓库的父目录 |
| `-BuildName` | 以字母或数字开头，后续为字母、数字、`.`、`_`、`-`；为兼容运行脚本，使用不超过 64 字符的非 Windows 保留名且不以点结尾 | `solver-ibm-v1.0.0`；建议仍显式填写 |
| `-PlatformToolset` | `v` 加数字，且必须实际安装，如 `v142`、`v143` | `v142` |

同一 `BuildName` 重建会替换该名称的正式产物，历史构建日志和历史运行快照保留。比较工具集或代码版本时使用不同 `BuildName`。仅改变 JSON/STL 无需重建；改变 C++ 或构建选项后需要重建。

### 2.3 查询能力与设备

```powershell
$exe = "$root\bin\solver-ibm-v1.0.0\Solver-IBM.exe"
& $exe --version
& $exe --help
& $exe --capabilities
& $exe --list-devices

$devices = powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\get-opencl-devices.ps1 | ConvertFrom-Json
$devices | Format-Table id, platform, name, driver
$gpu = @($devices | Where-Object { $_.name -eq 'NVIDIA GeForce RTX 3060' })
if ($gpu.Count -ne 1) { throw 'Inspect the device list and select the intended OpenCL device.' }
$deviceId = [int]$gpu[0].id
```

`--device` 使用 **OpenCL 设备编号**，不能用 `nvidia-smi` 编号代替。上例按本 NUC 的 RTX 3060 名称选择；更换硬件时按实际列表修改筛选条件。`--version` 输出 `Solver-IBM 1.0.0`。`--capabilities` 返回 JSON，其中 `product`、`version` 标识产品，`upstream` 保留来源，`defaults` 是模型默认值，`parameters` 是条件参数范围，`model_device_bytes_per_cell` 是各模型的字段内存估算。

### 2.4 校验并运行第一个算例

沿用上面的 `$root`、`$exe`、`$deviceId`：

```powershell
& $exe --config "$root\src\configs\periodic-lattice.json" --validate
if ($LASTEXITCODE -ne 0) { throw 'Configuration validation failed.' }

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-nuc.ps1 `
  -WorkspaceRoot $root -BuildName solver-ibm-v1.0.0 -CaseName periodic-demo `
  -ConfigPath "$root\src\configs\periodic-lattice.json" -DeviceId $deviceId `
  -TimeoutSeconds 900
if ($LASTEXITCODE -ne 0) { throw 'Run failed; inspect run.json and logs.' }
```

运行脚本会打印本次目录。`CaseName` 只是归档名称，**实际算例由 `ConfigPath` 指定**。重复运行会创建新 `RunId`，无需手动更改输出路径。检查该目录下 `run.json` 和 `results/completion.json`，再查看 VTK、CSV；[第 8 节](#8-输出文件与结果检查)说明各文件用途。

### 2.5 使用正式发布包

V1.0.0 完整归档位于 `F:\01-Project\Opensource\01-FluidX3D\package\V1.0.0`。已有可执行文件，无需重新编译。包内 `cases/configs/` 保存可移植配置，`cases/models/` 保存全部已有模型输入；模型目录还包含未完成几何准备的素材，不表示每个模型都已通过计算验收。完整内容及限制见 [V1.0.0 发布说明](releases/V1.0.0.md)。

在 NUC 上运行包内配置：

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$package = "$root\package\V1.0.0"
$exe = "$package\bin\Solver-IBM.exe"
& $exe --version
& $exe --list-devices
# 按刚才的 OpenCL 列表选择设备，当前 NUC 的 RTX 3060 为设备 0。
$deviceId = 0
& $exe --config "$package\cases\configs\periodic-lattice.json" --validate
if ($LASTEXITCODE -ne 0) { throw 'Packaged configuration validation failed.' }

powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File "$package\source\scripts\run-package.ps1" `
  -PackageRoot $package -WorkspaceRoot $root -CaseName release-periodic `
  -ConfigPath "$package\cases\configs\periodic-lattice.json" -DeviceId $deviceId
if ($LASTEXITCODE -ne 0) { throw 'Packaged run failed; inspect the run record.' }
```

将 `ConfigPath` 改为包内 `poiseuille.json`、`couette.json`、`boeing-regression.json` 或 `ahmed-smoke.json`，即可使用同一 EXE 运行对应算例。计算结果和运行记录保存到包外 `workingdir/`。需要修改算例时，将配置复制到新的工作目录，同时调整 `geometry[].file` 指向的 STL；不要修改正式包中的文件。不要直接把正式包当作 `run-nuc.ps1` 的普通构建目录，因为原始 `build.json` 保留了构建时的绝对路径；包运行入口负责这一层适配并保留来源记录。

`source/` 是发布提交的源码快照，不含 `.git`。需要从包中重建时，使用 `source.git.bundle` 克隆到一个新的、空的工作目录；不要在正式包内编译：

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$package = "$root\package\V1.0.0"
$rebuild = "$root\workingdir\rebuild-v1.0.0-" + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
New-Item -ItemType Directory -Path $rebuild | Out-Null
git clone "$package\source.git.bundle" "$rebuild\src"
if ($LASTEXITCODE -ne 0) { throw 'Bundle clone failed.' }
git -C "$rebuild\src" checkout --detach v1.0.0
if ($LASTEXITCODE -ne 0) { throw 'Release tag checkout failed.' }
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File "$rebuild\src\scripts\build-nuc.ps1" `
  -WorkspaceRoot $rebuild -BuildName solver-ibm-v1.0.0 -PlatformToolset v142
if ($LASTEXITCODE -ne 0) { throw 'Release rebuild failed.' }
```

源码可复现不意味着不同工具链、驱动或 OpenCL 设备一定产生相同的 EXE 或逐字节相同的流场。每次重建保留自己的 `build.json` 和验收记录，不替换发布包中的构建证据。

## 3. JSON 通用规则

配置是 UTF-8 JSON 文件，顶层为对象。字段名、枚举值均区分大小写；使用双引号，不写注释或尾逗号。未知字段、重复键、重复 ID、错误类型会被拒绝。不要把本手册的说明列写入 JSON，也不要自行加入 `$schema` 字段，当前解析器不接受该顶层键。

本手册的“缺省值”表示**字段省略时的行为**。表中“必填，无默认值”必须显式提供；C++ 结构体的初始值不代表允许省略配置字段。`null` 不等于省略。

统一约定：

| 记号 / 类型 | 含义 |
|---|---|
| `Imax` | `9007199254740991`，即 `2^53 - 1` |
| 正整数 | JSON 整数，`1..Imax`，若某字段有更小上限则以字段表为准 |
| 非负整数 | JSON 整数，`0..Imax` |
| 有限数 | JSON 数值且可表示为有限 double；不接受 NaN、Infinity、布尔值或数值字符串 |
| 正数 | 有限数且严格大于 0 |
| 三元向量 | 恰好 3 个有限数的数组，顺序 `[x,y,z]` |
| 布尔值 | `true` 或 `false`，不接受 `0`、`1` |

整数位置写 `1000`，不要写 `1000.0` 或 `1e3`。所有进入求解器的换算结果还必须满足 FP32 表示范围；正密度、黏度、单位比例等不能下溢成零，松弛时间和模型系数有额外检查。[case.schema.json](../schemas/case.schema.json) 可用于编辑器辅助检查，**最终以 EXE 的校验为准**，因为文件、单位换算、边界覆盖及 GPU 体素检查无法仅由 schema 完成。

配置文件中的 STL 相对路径以**该配置文件所在目录**为基准。命令行的相对 `--config`、`--output` 路径以启动进程的当前目录为基准。JSON 中推荐路径写为 `models/body.stl` 或 `F:/cases/body.stl`；使用反斜杠时需要转义为 `F:\\cases\\body.stl`。

## 4. 完整配置字段参考

### 4.1 顶层结构与算例名称

| 字段 | 类型 / 内容 | 缺省值 |
|---|---|---|
| `schema_version` | 整数，目前只能为 `1` | 必填，无默认值 |
| `case` | 对象，只含下面的 `name` | 必填，无默认值 |
| `case.name` | 非空字符串；描述算例，不决定目录或物理模型 | 必填，无默认值 |
| `solver` | 模型选择对象，见 4.2 | 省略等同 `{}`，启用全部模型默认值 |
| `units` | 单位对象，见 4.3 | 必填，无默认值 |
| `domain` | 计算域对象，见 4.4 | 必填，无默认值 |
| `fluid` | 流体和体积力对象，见 4.5 | 必填，无默认值 |
| `initial` | 初始条件对象，见 4.6 | 必填，无默认值 |
| `geometry` | STL 对象数组，见 4.7 | 必填；无 STL 时写 `[]` |
| `boundaries` | 边界对象数组，见 4.8 | 必填，必须声明全部六面 |
| `run` | 步数和监控对象，见 4.9 | 必填，无默认值 |
| `output` | VTK 输出对象，见 4.10 | 省略等同 `{}`，使用默认输出 |
| `analysis` | 探针和统计对象，见 4.11 | 省略表示关闭分析；`{}` 表示开启默认全域分析 |

### 4.2 `solver`：模型和精度

| 字段 | 可用值 / 范围 | 缺省值与条件 |
|---|---|---|
| `solver.lattice` | `"D3Q19"`、`"D3Q27"` | `"D3Q19"` |
| `solver.collision` | `"SRT"`、`"TRT"` | `"SRT"` |
| `solver.storage` | `"FP16S"`、`"FP32"` | `"FP16S"`；控制分布函数存储，算术均为 FP32 |
| `solver.turbulence` | `"none"`、`"smagorinsky"` | `"smagorinsky"` |
| `solver.smagorinsky_constant` | 数值，`0 < Cs <= 1` | `0.17326595533835415`；仅 Smagorinsky 模式允许提供 |
| `solver.trt_magic_parameter` | 数值，`0 < Λ <= 1` | `0.1875`，即 `3/16`；仅 TRT 模式允许提供 |

Cs、Λ 无量纲，不随 SI 换算。关闭 Smagorinsky 时写 `"turbulence":"none"` 并省略 `smagorinsky_constant`，不能用 `Cs=0` 关闭。SRT 时省略 `trt_magic_parameter`。默认 Cs 保留原内核系数 `0.76421222f`；自定义值使用 `18*sqrt(2)*Cs²`，该系数必须能表示为正的有限 FP32。TRT 基础偶、奇松弛率还必须满足有限且严格处于 `(0,2)`，因此仅满足 Λ 范围并不保证任意黏度组合都被接受。

**省略 `solver` 会开启 Smagorinsky，并使用 FP16S。** 如需关闭亚格子模型，应明确写 `none`。P3 验收已发现 FP16S 在弱体积力、较细通道网格上的量化误差；需做精度比较时可显式选 FP32，具体结果见 [P3 验收记录](validation/config-runner-p3-2026-09-22.md)。

### 4.3 `units`：格子单位与 SI

| 字段 | 可用值 / 范围 | 缺省值与条件 |
|---|---|---|
| `units.mode` | `"lattice"`、`"si"` | 必填，无默认值 |
| `units.reference_density` | 正数，kg/m³；一单位格子密度对应的物理密度 | SI 必填；格子模式禁止提供 |
| `units.dt` | 正数，s；每步物理时间 | SI 时间换算方案一；与下述两个速度字段互斥，无固定默认值 |
| `units.reference_velocity` | 正数，m/s；用于确定时间尺度的参考速度大小 | SI 方案二，与 `lattice_velocity` 一起必填；不得同时提供 `dt` |
| `units.lattice_velocity` | 正数，无量纲；与上项对应的格子速度大小 | SI 方案二，与 `reference_velocity` 一起必填；无固定默认值 |

格子模式只能写 `{"mode":"lattice"}`，内部采用 `dx=1`、`dt=1`、参考密度 `1`。SI 模式二选一：

```json
{"mode":"si","reference_density":1000,"dt":0.003}
```

```json
{"mode":"si","reference_density":1000,"reference_velocity":0.1,"lattice_velocity":0.03}
```

当 `domain.dx=0.01` m 时，两者均给出 `dt=0.003` s。速度方案使用 `dt = lattice_velocity * dx / reference_velocity`。这些参考速度**不会自动设置初始速度或边界速度**，仍需填写相应 `velocity` 字段。

以 `rho_ref = units.reference_density` 表示密度尺度，下标 L 表示求解器格子值：

| 量 | SI 输入到格子值的换算 |
|---|---|
| 密度 | `rho_L = rho / rho_ref` |
| 速度 | `u_L = u * dt / dx` |
| 运动黏度 | `nu_L = nu * dt / dx²` |
| 体积力密度 | `f_L = f * dt² / (rho_ref * dx)` |
| 基础松弛时间 | `tau = 0.5 + 3 * nu_L`，转为 FP32 后仍须严格大于 `0.5` |

SI 模式下，长度/位置为 m、时间为 s、速度为 m/s、密度为 kg/m³、运动黏度为 m²/s、体积力密度为 N/m³。STL 源坐标及 `transform.pivot` 的例外见 4.7。不存在独立的每字段单位标签；不能在同一个 SI 配置中把某个速度当作格子值输入。

### 4.4 `domain`：网格、范围和原点

| 字段 | 可用值 / 范围 | 缺省值与条件 |
|---|---|---|
| `domain.cells` | 三个整数，每项 `3..1000000`，包含边界层 | 格子模式方案一必填；与预算方案互斥；SI 禁止 |
| `domain.aspect_ratio` | 三元向量，每项 `0 < a < 1000000` | 格子模式方案二必填，配合 `memory_budget_mb` |
| `domain.memory_budget_mb` | 整数 `1..1048576`，这里 1 MB 按 `1024²` bytes 计算 | 格子模式方案二必填，配合 `aspect_ratio` |
| `domain.length` | 三个正数，物理目标长度，m | SI 必填；格子模式禁止 |
| `domain.dx` | 正数，m，各方向相同的网格间距 | SI 必填；格子模式禁止，不可写 `dx:1` |
| `domain.origin` | 三元向量，计算域外框最小角点；单位为格子长度或 m | `[0,0,0]` |

三种合法组合：格子模式 `cells`；格子模式 `aspect_ratio + memory_budget_mb`；SI 模式 `length + dx`。不能混合三种方案。SI 不额外填写 `cells`：程序按 `ceil(length[a]/dx)` 生成，每方向须为 `3..1000000`；非常接近整数时先按相对容差 `1e-10` 处理浮点舍入。实际长度为 `cells[a]*dx`，可能略大于输入 `length`。

网格总数不得超过 `10000000000`，并受主机分配范围、GPU 显存和单缓冲分配上限限制。索引 `(i,j,k)` 的格点中心坐标为：

```text
origin + ([i,j,k] + [0.5,0.5,0.5]) * dx
```

所以 `origin` 是外框角点，不是第一个格点中心；网格外框为 `origin .. origin + cells*dx`。较大的原点也必须仍能分辨相邻格点。壁面占最外侧一层格点；例如 `cells=[8,18,8]`、y 两端固壁时，y 方向有 16 层流体格点。

显存预算方案按长宽高比例估算维数，再各自取最近整数，**预算不是严格的最大显存保证**。当前设备字段开销如下，已包含本版本启用的体积力/受力字段：

| 速度集 | FP16S | FP32 |
|---|---:|---:|
| D3Q19 | 67 bytes/cell | 105 bytes/cell |
| D3Q27 | 83 bytes/cell | 137 bytes/cell |

额外还有 STL、驱动和分配开销；主机基本字段 29 bytes/cell，另计并集掩码、几何归属和受力分组。程序在实际运行时核查所选设备的容量与分布函数单缓冲上限。查看 `resolved-config.json` 中的网格及内存估算，不能只依据输入预算判断。

### 4.5 `fluid`：密度、黏度与体积力

| 字段 | 可用值 / 范围 | 缺省值与条件 |
|---|---|---|
| `fluid.rho` | 正数，格子密度或 kg/m³ | 必填；也是压强零点的参考密度 |
| `fluid.nu` | 正数，运动黏度，格子值或 m²/s | 黏度方案一必填；与下面三个 Re 字段互斥 |
| `fluid.reynolds` | 正数，无量纲 Re | 方案二必填 |
| `fluid.reference_length` | 正数，格子长度或 m | 方案二必填 |
| `fluid.reference_velocity` | 正数，格子速度或 m/s | 方案二必填 |
| `fluid.body_force` | 三元向量，可正、负、零；格子力密度或 N/m³ | `[0,0,0]`，常量、全域施加 |

方案二用 `nu = reference_velocity * reference_length / reynolds` 计算运动黏度，SI 模式再转换为格子黏度。这三个量没有默认值，也不自动读取 `units.reference_velocity`；两处参考速度分别服务于 Re 和时间尺度。`fluid.reference_velocity` 同样不会自动设置流场速度。

`body_force` 是**单位体积上的力**，不是加速度；已知加速度 `a` 时，按目标物理定义填写 `f = rho*a`。当前字段是固定三元常量，不能提供随时间、坐标变化的表达式或数组场。

### 4.6 `initial`：初始场与局部覆盖

| 字段 | 可用值 / 范围 | 缺省值 |
|---|---|---|
| `initial.velocity` | 三元向量，格子速度或 m/s | 必填；静止也须写 `[0,0,0]` |
| `initial.rho` | 正数，格子密度或 kg/m³ | `fluid.rho` |
| `initial.regions` | 局部盒子数组 | `[]` |
| `initial.regions[].box_min` | 三元向量，盒子最小坐标 | 每个区域必填 |
| `initial.regions[].box_max` | 三元向量，每方向不得小于对应 `box_min` | 每个区域必填 |
| `initial.regions[].rho` | 正数，格子密度或 kg/m³ | 每个区域必填，不继承全域值 |
| `initial.regions[].velocity` | 三元向量，格子速度或 m/s | 每个区域必填，不继承全域值 |

盒子坐标使用当前单位，按格点中心落入**闭区间**判断。多个区域重叠时，数组中后面的区域覆盖前面的区域。它们只定义初始场，边界和固体赋值随后生效。输入区域可以不命中格点，解析器不保证每个区域实际覆盖非零格点。

### 4.7 `geometry`：静态二进制 STL

| 字段 | 可用值 / 范围 | 缺省值与条件 |
|---|---|---|
| `geometry[].id` | 非空字符串，在 `geometry` 内唯一 | 每个对象必填 |
| `geometry[].file` | 已存在的二进制 STL 文件路径，相对配置文件目录或绝对路径 | 每个对象必填 |
| `geometry[].transform` | 变换对象 | 每个对象必填，不能省略整个变换 |
| `geometry[].transform.mode` | `"fit"`、`"scale"` | 必填 |
| `geometry[].transform.size` | 正数，目标最长包围盒边长，格子长度或 m | `fit` 必填；`scale` 禁止 |
| `geometry[].transform.center` | 三元向量，目标包围盒中心，格子坐标或 m | `fit` 必填；`scale` 禁止 |
| `geometry[].transform.factor` | 正数，每个 STL 源长度单位对应的目标长度 | `scale` 必填；`fit` 禁止 |
| `geometry[].transform.pivot` | 三元向量，**STL 源坐标**中的参考点 | `scale` 默认为 `[0,0,0]`；`fit` 禁止 |
| `geometry[].transform.translation` | 三元向量，目标坐标中的平移量 | `scale` 必填，即使为 `[0,0,0]`；`fit` 禁止 |
| `geometry[].transform.axis` | 非零三元向量，有限非零模长；程序归一化 | `[1,0,0]` |
| `geometry[].transform.degrees` | 任意有限数，旋转角度，度；按右手方向 | `0` |

STL 本身不携带长度单位。`fit` 先旋转，再把旋转后包围盒的最长边等比例缩放到 `size`，最后把包围盒中心放到 `center`。这不是分别拉伸 x/y/z 三个方向。

`scale` 的目标坐标为：

```text
p_target = translation + R(axis,degrees) * (factor * (p_STL - pivot))
```

`pivot` 是变换前要减去的参考点，变换后该点位于 `translation`；公式没有额外的 `+pivot`。例如源 STL 使用 mm、目标为 SI m，保持原点时可用 `factor=0.001`、`pivot=[0,0,0]`、`translation=[0,0,0]`。

格式必须是非空二进制 STL，长度严格等于 `84 + 50*三角形数` bytes，顶点有限，包围盒不能完全退化。ASCII STL 不支持。变换后须位于计算域内，程序不自动裁剪。正式运行/预处理还会检查每个 STL 至少体素化出一个固体格点。多个 STL 取固体并集；几何不会随时间平移或旋转。

STL 不能与最终生效的 `equilibrium` 或 `moving_wall` 边界相交；静态 `no_slip` 可以合并，但单物体受力统计另有归属约束，见 4.11。

### 4.8 `boundaries`：六面、局部区域和优先级

| 字段 | 可用值 / 范围 | 缺省值与条件 |
|---|---|---|
| `boundaries[].id` | 非空字符串，在 `boundaries` 内唯一 | 必填 |
| `boundaries[].faces` | 非空、无重复字符串数组；元素为 `xmin`、`xmax`、`ymin`、`ymax`、`zmin`、`zmax` | 必填 |
| `boundaries[].type` | `"periodic"`、`"no_slip"`、`"equilibrium"`、`"moving_wall"` | 必填 |
| `boundaries[].priority` | 整数 `-1000000..1000000`，越大越优先 | `0` |
| `boundaries[].region` | 含 `min`、`max` 的对象，限定面内范围 | 省略表示整面；`periodic` 禁止 |
| `boundaries[].region.min` | 两个有限数，面内最小坐标 | 提供 `region` 时必填 |
| `boundaries[].region.max` | 两个有限数，每项不小于对应 `min` | 提供 `region` 时必填 |
| `boundaries[].rho` | 正数，格子密度或 kg/m³ | 仅 `equilibrium` 必填；其他类型禁止 |
| `boundaries[].velocity` | 三元向量，格子速度或 m/s | `equilibrium`、`moving_wall` 必填；其他类型禁止 |

各边界类型的行为：

| 类型 | 含义 | 必要约束 |
|---|---|---|
| `periodic` | 整个坐标方向周期相连 | 相对两面必须均为周期；同一面不能混入其他类型；不能局部周期 |
| `no_slip` | 固定零速度固壁 | 不填写 `rho` 或 `velocity` |
| `equilibrium` | 固定密度和速度的平衡分布边界（`TYPE_E`） | 同时指定 `rho`、`velocity`；不能只给压力或只给速度 |
| `moving_wall` | 位置固定、速度恒定的切向运动壁面 | 每个指定面法向速度分量严格为零；不接受 `rho` |

`equilibrium` 可用于当前接口的指定入口/出口条件，但不等同于通用压力出口、零梯度出口或其他未实现的边界算法。`moving_wall` 改变壁面速度，不改变壁面位置，也不驱动 STL 移动。

存在任意运动壁面时，`fluid.rho`、`initial.rho`、所有局部初始密度和 `equilibrium.rho` 换算后的格子密度都必须**恰好为 1**。SI 中通常对应所有这些密度均等于 `units.reference_density`。

`region` 使用当前长度单位，按格点中心在闭区间内判定。两坐标的顺序固定如下：

| 所在面 | `region.min/max` 的分量顺序 |
|---|---|
| `xmin`、`xmax` | `[y,z]` |
| `ymin`、`ymax` | `[x,z]` |
| `zmin`、`zmax` | `[x,y]` |

每个面都必须声明，每个非周期面的边界格点都必须被该面的规则覆盖。棱边、角点以及同面局部区域的重叠，统一按最高 `priority` 选择。最高优先级相同且类型/赋值不同会报错；相同赋值允许重叠，其归属使用数组中先出现的规则。受力分组和 `boundary_coverage.winning_cells` 使用最终胜出的规则，低优先级规则可被完全覆盖。常见写法是先放低优先级整面规则，再用较高优先级局部入口覆盖。

### 4.9 `run`：终止条件与监控

| 字段 | 可用值 / 范围 | 缺省值与条件 |
|---|---|---|
| `run.steps` | 正整数 `1..Imax` | 与 `duration` 恰好提供一个；没有默认步数 |
| `run.duration` | 正数，s | 仅 SI 可用；与 `steps` 互斥 |
| `run.monitor_every` | 正整数 `1..Imax`，步数间隔 | `100` |

`duration` 转换为 `ceil(duration/dt)` 步，接近整数时使用与网格同类的 `1e-10` 相对容差；结果必须为 `1..Imax`，实际终止时间是 `steps*dt`。`monitor.csv` 包含初始第 0 步、监控间隔和最终步。监控间隔、VTK 间隔、分析间隔是三个独立设置。

零步检查使用 `--prepare-only`，配置里的目标步数仍必须为正，不能填 `steps:0`。

### 4.10 `output`：VTK 输出

| 字段 | 可用值 / 范围 | 缺省值 |
|---|---|---|
| `output.vtk_fields` | 非空、无重复数组，元素仅 `"u"`、`"rho"`、`"flags"`、`"p"` | `["u","rho","flags"]` |
| `output.vtk_every` | 非负整数 `0..Imax`，步数间隔 | `0`，不输出中间周期帧 |
| `output.initial` | 布尔值 | `true`，输出第 0 步 |

正常计算**总会输出最终步**，与 `vtk_every` 是否整除终止步无关。`vtk_every=0` 表示“最终帧，加上可选初始帧”，不表示关闭所有 VTK。`vtk_fields=[]` 不允许。`--prepare-only` 总会输出第 0 步所选字段，并保证输出 `flags`，即使 `initial=false` 或字段列表不含 `flags`。

`u` 为速度三分量，`rho` 为密度，`flags` 为格点位标记，`p` 为相对 `fluid.rho` 的表压。SI 配置的 VTK 坐标、间距、速度、密度、压强均转换为 SI；文件名按步数至少补齐九位，例如 `u-000000023.vtk`。

### 4.11 `analysis`：采样、探针与固体受力

| 字段 | 可用值 / 范围 | 缺省值与条件 |
|---|---|---|
| `analysis.every` | 正整数 `1..Imax`，采样步数间隔 | `run.monitor_every` 的实际值 |
| `analysis.start_step` | 非负整数，不超过计算后的 `run.steps` | `0` |
| `analysis.statistics` | 布尔值，是否额外生成时均及标准差 | `true` |
| `analysis.probes` | 探针对象数组 | `[]` |
| `analysis.probes[].id` | 非空字符串，在探针列表内唯一 | 每个探针必填 |
| `analysis.probes[].position` | 三元向量，当前长度单位；每方向在 `[origin,origin+cells*dx)` 内 | 每个探针必填 |
| `analysis.forces` | 固体受力组数组 | `[]` |
| `analysis.forces[].id` | 非空字符串，在受力组列表内唯一 | 每个受力组必填 |
| `analysis.forces[].target` | `"all_solids"`、`"geometry:<id>"`、`"boundary:<id>"` | 每个受力组必填；ID 必须存在，boundary 只能是固壁类型 |

提供 `analysis:{}` 会开启全域分析，并创建三个 CSV；没有探针/受力组的 CSV 只有表头。省略整个 `analysis` 则不创建分析 CSV 和 `statistics.json`，但仍有 `monitor.csv`。

采样步数严格为 `start_step + k*every`，`k=0,1,...`，不超过终止步。**不会为了最终步额外补采样**。例如终止 23 步、从 5 开始每 7 步采样，采样为 5、12、19。正常运行样本数为 `floor((steps-start_step)/every)+1`；预处理不采样，样本数为 0。`statistics=false` 保留瞬时 CSV，关闭 `statistics.json`。

探针取最近的格点中心，不做插值：索引为 `floor((position-origin)/dx)`，恰处于相邻中心中点时取较大索引。请求坐标和实际中心均记录在 `resolved-config.json` 中，CSV 的 x/y/z 是实际中心。正式运行或预处理发现探针落入固体会报错。

受力是**流体作用于固体的力**，使用动量交换并扣除参考密度背景，含运动壁面修正；SI 输出单位为 N。目标规则：

- `all_solids` 包含全部最终固体格点，不包括平衡边界。
- `geometry:<id>` 选取指定 STL 的固体格点。被单独统计的物体不能与其他 STL 重叠，也不能与域固壁相接而产生归属歧义；程序会报错。
- `boundary:<id>` 选取该规则最终胜出的固壁格点，类型必须为 `no_slip` 或 `moving_wall`。
- 每个受力组必须命中至少一个固体格点。多个统计组可以包含同一格点，如“全部固体”和“下壁面”，它们不能直接相加当作总力。

当前输出 `fx/fy/fz`，不直接输出力矩、阻力系数或升力系数。压强和力的换算为：

```text
p = (rho_L - fluid.rho / rho_ref) / 3 * rho_ref * (dx/dt)^2
F = F_L * rho_ref * dx^4 / dt^2
```

即使 `initial.rho` 覆盖了初始密度，压强零点仍来自 `fluid.rho`。全域统计排除固体，包含非固体的平衡边界格点；平均速度等为格点算术平均，质量和动能按格点体积积分。时间统计用 double 精度在线累积，`std_population` 是除以样本数 N 的总体标准差；一个样本时为 0，零样本时均值/标准差为 `null`。这不是逐格点的时均 VTK 场。

## 5. 完整示例与常见修改

### 5.1 最小完整格子配置

下面是完整配置，可保存为 `case.json`。这是均匀周期流，无 STL；省略 `solver`、`output`、`analysis` 时按前文默认值运行。

```json
{
  "schema_version": 1,
  "case": {"name": "periodic-minimal"},
  "units": {"mode": "lattice"},
  "domain": {"cells": [16,16,16]},
  "fluid": {"rho": 1, "nu": 0.02},
  "initial": {"velocity": [0.03,0,0]},
  "geometry": [],
  "boundaries": [
    {"id":"periodic", "faces":["xmin","xmax","ymin","ymax","zmin","zmax"], "type":"periodic"}
  ],
  "run": {"steps": 23}
}
```

### 5.2 完整 SI 配置

下面的 SI 周期流与上一例具有相同的格子尺寸、格子速度和格子黏度。加上了输出和探针；最终时间 `0.069` s，对应 23 步。

```json
{
  "schema_version": 1,
  "case": {"name": "periodic-si-with-probe"},
  "solver": {"storage": "FP32"},
  "units": {"mode": "si", "reference_density": 1000, "dt": 0.003},
  "domain": {"length": [0.16,0.16,0.16], "dx": 0.01, "origin": [0,0,0]},
  "fluid": {"rho": 1000, "nu": 0.0006666666666666668},
  "initial": {"velocity": [0.1,0,0]},
  "geometry": [],
  "boundaries": [
    {"id":"periodic", "faces":["xmin","xmax","ymin","ymax","zmin","zmax"], "type":"periodic"}
  ],
  "run": {"duration": 0.069, "monitor_every": 7},
  "output": {"vtk_fields":["u","rho","flags","p"], "vtk_every":7, "initial":true},
  "analysis": {
    "every": 7,
    "start_step": 0,
    "statistics": true,
    "probes": [{"id":"center", "position":[0.085,0.085,0.085]}],
    "forces": []
  }
}
```

监控与 VTK 在 0、7、14、21、23 步输出，分析在 0、7、14、21 步采样。若把时间方案改为参考速度方案，可替换 `units` 为 4.3 的第二个对象，其他字段无需改变。

### 5.3 选择模型、使用 Re 或显存预算

以下均为**替换完整配置中的对应对象**，不是单独可运行的算例文件。

使用 D3Q27、TRT、FP32，关闭亚格子模型：

```json
{"solver":{"lattice":"D3Q27","collision":"TRT","storage":"FP32","turbulence":"none","trt_magic_parameter":0.1875}}
```

格子单位中以 Re 指定黏度，得到 `nu=0.03*16/24=0.02`：

```json
{"fluid":{"rho":1,"reynolds":24,"reference_length":16,"reference_velocity":0.03}}
```

格子模式按 `2:1:1` 和 256 MiB 字段预算估算尺寸：

```json
{"domain":{"aspect_ratio":[2,1,1],"memory_budget_mb":256,"origin":[0,0,0]}}
```

预算示例应先用 `--validate` 查看生成的尺寸，再决定是否运行；改变模型/存储后预算生成的格点数也会变化。

### 5.4 添加 STL

示例目录：

```text
my-case/
  case.json
  models/
    body.stl
```

格子单位下，在足够大的域内把物体最长边设置为 8、中心放到 `[16,16,16]`，绕 z 旋转 90 度：

```json
{
  "geometry": [
    {"id":"body", "file":"models/body.stl",
     "transform":{"mode":"fit","size":8,"center":[16,16,16],"axis":[0,0,1],"degrees":90}}
  ]
}
```

这是字段片段，不应直接粘到前面 `16³` 小域而不检查包围盒。应根据模型和计算域调整中心、尺寸，并用 `--prepare-only` 检查 `flags`。

如果 STL 源坐标单位是 mm、目标为 SI，使用显式比例：

```json
{
  "geometry": [
    {"id":"body", "file":"models/body.stl",
     "transform":{"mode":"scale","factor":0.001,"pivot":[0,0,0],"translation":[0.1,0.05,0.05]}}
  ]
}
```

两种方案不要同时写入同一个 `transform`。更换 `case.json` 所在目录时，记得同步调整或复制相对路径指向的 STL。

### 5.5 局部入口与边界优先级

以下是格子域 `[32,16,16]` 的完整 `boundaries` 对象片段：x 两端默认固壁，xmin 中部开一个平衡入口，xmax 中部开一个平衡出口，y/z 周期。这里的“出口”仍固定 `rho` 和 `velocity`，没有额外开放边界算法。

```json
{
  "boundaries": [
    {"id":"x-walls", "faces":["xmin","xmax"], "type":"no_slip", "priority":0},
    {"id":"inlet", "faces":["xmin"], "type":"equilibrium", "priority":10,
     "region":{"min":[4,4],"max":[12,12]}, "rho":1, "velocity":[0.03,0,0]},
    {"id":"outlet", "faces":["xmax"], "type":"equilibrium", "priority":10,
     "region":{"min":[4,4],"max":[12,12]}, "rho":1, "velocity":[0.03,0,0]},
    {"id":"periodic-yz", "faces":["ymin","ymax","zmin","zmax"], "type":"periodic"}
  ]
}
```

### 5.6 Poiseuille / Couette 与已有配置

仓库已有完整通道配置，无需从零组合字段。沿用 2.3 的设备选择，在 NUC 执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-nuc.ps1 `
  -WorkspaceRoot $root -BuildName solver-ibm-v1.0.0 -CaseName poiseuille `
  -ConfigPath "$root\src\configs\poiseuille.json" -DeviceId $deviceId -TimeoutSeconds 900

powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-nuc.ps1 `
  -WorkspaceRoot $root -BuildName solver-ibm-v1.0.0 -CaseName couette `
  -ConfigPath "$root\src\configs\couette.json" -DeviceId $deviceId -TimeoutSeconds 900
```

两者均为 `[8,18,8]` 网格、4000 步、FP32，x/z 周期，y 两端固壁；分析在 3900、3950、4000 步取样。Poiseuille 使用 x 方向体积力；Couette 使用上壁面 `[0.05,0,0]` 的固定切向速度。现有文件没有关闭 Smagorinsky，因而采用其默认值。要做关闭亚格子模型的比较，在副本中补充 `solver.turbulence="none"`。

| 文件（均在 `configs/`） | 用途 |
|---|---|
| [periodic-lattice.json](../configs/periodic-lattice.json) | 格子单位周期流基本示例 |
| [periodic-si.json](../configs/periodic-si.json) | SI 周期流与单位换算 |
| [periodic-fp32.json](../configs/periodic-fp32.json) | FP32 存储示例 |
| [probes-periodic.json](../configs/probes-periodic.json) | 探针和分析示例 |
| [poiseuille.json](../configs/poiseuille.json) | 体积力、静态壁面、探针和受力 |
| [couette.json](../configs/couette.json) | 固定位置运动壁面、受力 |
| [models-periodic.json](../configs/models-periodic.json) | D3Q27/TRT/FP32 与显式 Cs、Λ |
| [boeing-regression.json](../configs/boeing-regression.json) | Boeing STL 回归配置 |
| [ahmed-smoke.json](../configs/ahmed-smoke.json) | Ahmed STL 短算配置 |
| [study-periodic.json](../configs/study-periodic.json) | 基础参数扫描规格，不能直接传给 EXE |
| [study-storage.json](../configs/study-storage.json) | 两种存储模式扫描规格 |
| [study-models.json](../configs/study-models.json) | 16 种模型组合扫描规格 |
| [models-study-base.json](../configs/models-study-base.json) | 模型扫描使用的完整基础算例 |

STL 算例仍以配置中 `geometry[].file` 指向的实际文件为准。`--validate` 可以提前发现资源缺失；不要只复制 JSON 而遗漏 STL。

## 6. 命令行及运行脚本参考

### 6.1 直接调用 EXE

```text
Solver-IBM.exe --config FILE [--device ID] [--output DIR] [--validate | --prepare-only]
Solver-IBM.exe --version
Solver-IBM.exe --help
Solver-IBM.exe --capabilities
Solver-IBM.exe --list-devices
```

| 参数 | 可用值 / 含义 | 缺省行为 |
|---|---|---|
| `--config FILE` | 算例 JSON 路径 | 计算/校验/预处理时必填 |
| `--device ID` | 十进制数字串，整数 `0..2147483647`；运行时必须对应实际 OpenCL 设备 | 自动选择估算 FLOPs 最高的设备 |
| `--output DIR` | 不存在的目录或已有空目录；不能复用非空结果目录 | 配置所在目录下的 `results` |
| `--validate` | 解析、换算、边界覆盖和 STL 格式/变换检查，不初始化 GPU，不创建结果目录 | 不启用 |
| `--prepare-only` | 初始化 GPU、体素化、完成几何/探针/受力归属检查，输出第 0 步，不迭代 | 不启用 |
| `--version` | 输出产品名称和版本，单独使用 | 不启用 |
| `--help` | 显示用法，单独使用 | 无参数启动也显示帮助 |
| `--capabilities` | 输出当前 EXE 支持能力的 JSON，单独使用 | 不启用 |
| `--list-devices` | 枚举 OpenCL 设备，单独使用 | 不启用 |

参数不可重复，未知参数报错。`--validate` 与 `--prepare-only` 互斥；`--help` 等查询选项不可与 `--config` 混用。`--validate` 不检查设备是否可用、显存是否足够、STL 是否体素化为零，也不检查探针是否落入体素固体；需要 `--prepare-only` 完成这些检查。其标准输出是 JSON 加一行通过提示，不是纯 JSON 文件。

正常完成返回退出码 0，配置入口捕获错误返回 1；外部运行脚本还会检查完成记录及日志，不只依赖退出码。调用示例：

```powershell
$exe = "$root\bin\solver-ibm-v1.0.0\Solver-IBM.exe"
& $exe --config 'F:\cases\my-case\case.json' --validate

$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
& $exe --config 'F:\cases\my-case\case.json' --device $deviceId `
  --output "$root\workingdir\manual-prepare-$stamp" --prepare-only
```

将示例中的 `F:\cases\my-case\case.json` 替换成实际文件。直接调用会保存求解器的输入快照和结果，但没有运行脚本提供的 EXE 副本、外层 `run.json`、超时管理及日志归档；正式计算宜使用下面的脚本。

### 6.2 `run-nuc.ps1` 参数

| 参数 | 可用值 / 范围 | 缺省值与条件 |
|---|---|---|
| `-WorkspaceRoot` | Windows 工作根目录 | 脚本所在源码仓库的父目录；建议显式填写 |
| `-BuildName` | 选择 `bin/<BuildName>` 下已成功构建的 EXE | `solver-ibm-v1.0.0` |
| `-ExecutablePath` | 显式指定迁移后的 `Solver-IBM.exe`，同目录必须有对应 `build.json`；用于发布包和测试入口 | 无；省略时按 BuildName 定位 |
| `-CaseName` | 结果归档目录名，不改变物理算例 | `benchmark`；建议填写本次算例名 |
| `-DeviceId` | 整数 `0..2147483647`，实际 OpenCL ID | 不提供时由求解器自动选择 |
| `-TimeoutSeconds` | 整数 `1..86400`，整次进程最长时间，秒 | `900` |
| `-ConfigPath` | 算例 JSON 路径，相对当前目录或绝对路径 | 无；当前配置驱动 EXE 运行时应提供 |
| `-PrepareOnly` | 开关，不跟 `true`；只进行零步预处理 | 默认关闭，必须同时提供 `ConfigPath` |
| `-ExpectBenchmark` | 上游硬编码 benchmark 专用验收开关 | 默认关闭；与 `ConfigPath` 互斥，当前配置运行不使用 |

`BuildName`、`CaseName` 均为 1–64 字符，首字符字母或数字，余下允许字母、数字、点、下划线和连字符；不能以点结尾，不能使用 Windows 保留名。脚本要求对应 `build.json` 成功且 EXE SHA256 一致；普通构建还要求记录中的绝对路径匹配。`-ExecutablePath` 允许迁移定位，但保留原始构建路径作为来源记录，不省略哈希校验。手动替换 EXE 会被拒绝。

对一个 STL 算例先预处理：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-nuc.ps1 `
  -WorkspaceRoot $root -BuildName solver-ibm-v1.0.0 -CaseName ahmed-prepare `
  -ConfigPath "$root\src\configs\ahmed-smoke.json" -DeviceId $deviceId `
  -PrepareOnly -TimeoutSeconds 900
```

检查 `flags-000000000.vtk` 和 `resolved-config.json` 后，以同一配置去掉 `-PrepareOnly` 正式运行。正式运行会重新初始化，不会从预处理结果续算。脚本没有 `-Validate` 参数，静态校验直接调用 EXE 的 `--validate`。

超时时脚本终止自己启动的进程树并写入 `timed_out`；计算及脚本返回前保持 SSH 会话。正常结束后可执行 `exit` 退出 PowerShell，再按登录环境退出 SSH；不要通过断开会话代替正常结束计算。

### 6.3 `run-package.ps1` 参数与包验证

正式发布包推荐使用此入口；它核对产品身份、版本和 EXE 哈希，再委托 `run-nuc.ps1` 建立包外运行目录。

| 参数 | 可用值 / 含义 | 缺省值 |
|---|---|---|
| `-PackageRoot` | 含 `manifest.json` 的发布包目录 | 必填 |
| `-WorkspaceRoot` | 包外 Windows 工作根目录，不能指向包内部；输出路径不能经 junction/symlink 回到包内 | 必填 |
| `-ConfigPath` | 完整算例 JSON，STL 相对路径仍以该 JSON 所在目录解释 | 包内 `cases/configs/periodic-lattice.json` |
| `-CaseName` | 包外结果目录名，名称规则与 `run-nuc.ps1` 一致 | `solver-ibm-demo` |
| `-DeviceId` | 实际 OpenCL ID，整数 `0..2147483647` | 不提供时由求解器自动选择 |
| `-TimeoutSeconds` | 整次进程秒数，整数 `1..86400` | `900` |
| `-PrepareOnly` | 只做零步预处理 | 默认关闭 |

全包文件校验及发布验收使用 `test-package.py`，结果写在包外：

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$package = "$root\package\V1.0.0"
python "$package\source\scripts\test-package.py" `
  --package-root $package --workspace-root $root --device $deviceId
if ($LASTEXITCODE -ne 0) { throw 'Package acceptance failed; inspect the printed report.' }
```

默认执行文件清单校验、版本/能力核对、包运行入口检查以及 P1/P2/存储/P3/扫描套件。`--skip-suites` 可跳过这五套完整回归，仅执行文件、身份和包运行检查；报告明确记录跳过内容，不能将这种检查当作完整发布验收。程序启动前后均检查包内容没有改变。所有程序调用仍须在 NUC 执行。

## 7. 参数扫描

扫描器把一份基础算例和若干参数轴展开成笛卡尔积，每个组合生成独立 JSON，随后串行通过 `run-nuc.ps1` 执行。下面所有示例在 NUC 运行。

### 7.1 扫描规格格式

扫描规格与算例配置是**两种不同 JSON**。扫描规格只能包含下列字段，不能直接传给 `Solver-IBM.exe --config`：

| 字段 | 可用值 / 范围 | 缺省值 |
|---|---|---|
| `schema_version` | 整数 `1` | 必填 |
| `base_config` | 完整基础算例路径，相对于扫描规格所在目录，或绝对路径 | 必填 |
| `parameters` | 非空参数轴数组，所有轴长度之积最多 `10000` | 必填 |
| `parameters[].path` | 以 `/` 开头的 JSON Pointer，必须指向基础配置内已有字段/数组元素 | 每个轴必填 |
| `parameters[].values` | 非空数组，元素是每个组合替换进去的 JSON 值 | 每个轴必填，无自动范围过滤 |

例如下列规格与 `models-study-base.json` 放在同一目录，生成 16 个组合：

```json
{
  "schema_version": 1,
  "base_config": "models-study-base.json",
  "parameters": [
    {"path":"/solver/lattice", "values":["D3Q19","D3Q27"]},
    {"path":"/solver/collision", "values":["SRT","TRT"]},
    {"path":"/solver/turbulence", "values":["none","smagorinsky"]},
    {"path":"/solver/storage", "values":["FP16S","FP32"]}
  ]
}
```

使用 `/fluid/nu` 修改黏度、`/initial/velocity/0` 修改 x 速度、`/geometry/0/transform/size` 修改首个 STL 的尺寸。Pointer 中 `~1` 表示 `/`，`~0` 表示 `~`。数组索引从 0 开始，不能使用 `-` 追加元素。字段必须已经存在，即使它在求解器中有默认值，也不能扫描基础 JSON 中省略的字段。

参数路径不得重复或存在父子重叠；不能扫描 `schema_version`、整个 `geometry`、整个几何对象或 `geometry[].file/id`，可以扫描几何变换。生成器复制 STL 并改写路径，记录配置和资产 SHA256。`generate` 不替代求解器校验：例如同时扫描 `SRT/TRT` 和 Λ 会产生 SRT+Λ 无效组合，应分开扫描。默认 16 模型基础配置省略 Cs/Λ，避免该问题。

### 7.2 生成和执行命令

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
Set-Location "$root\src"
$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$study = "$root\workingdir\model-study-$stamp"

python .\scripts\parameter-study.py generate `
  --spec .\configs\study-models.json --output $study
if ($LASTEXITCODE -ne 0) { throw 'Study generation failed.' }

# $deviceId 由第 2.3 节的设备探针选定。
python .\scripts\parameter-study.py run --study $study `
  --workspace-root $root --build-name solver-ibm-v1.0.0 --device $deviceId --timeout 900
if ($LASTEXITCODE -ne 0) { throw 'Some study cases failed; inspect summary.json.' }
```

| 子命令参数 | 含义 / 范围 | 缺省值 |
|---|---|---|
| `generate --spec` | 扫描规格 JSON | 必填 |
| `generate --output` | 新目录或已有空目录，存放整个扫描快照 | 必填 |
| `run --study` | 包含生成的 `study.json` 的**目录**，不是文件路径 | 必填 |
| `run --workspace-root` | NUC 工作根目录 | 必填 |
| `run --build-name` | 成功构建名称；遵循运行脚本名称规则 | `solver-ibm-v1.0.0` |
| `run --executable` | 显式指定已迁移的 `Solver-IBM.exe`，旁边保留其 `build.json`；用于包内 EXE | 无；默认按 workspace 和 build-name 定位 |
| `run --device` | 整数；下游运行脚本要求 `0..2147483647` 且设备存在 | `0`，建议查询后显式传入 |
| `run --timeout` | 每个算例的秒数；下游脚本要求 `1..86400` | `900` |

若要扫描正式包中的模型，`generate --spec` 指向包内 `cases/configs/study-models.json`，生成目录仍放在包外；`run` 增加 `--executable "$package\bin\Solver-IBM.exe"`。不要把新 study 生成到正式发布包内。

目录中包含 `study-original.json`、`base-original.json`、`configs/00000.json` 等、`assets/` 和 `study.json`。运行前校验快照及 EXE 哈希，运行过程中也检查 EXE 是否被替换。单个算例失败后继续其他组合，最终有失败则返回非零；各次执行的汇总写到 `<study>/runs/<RunId>/summary.json` 和 `summary.csv`。重复 `run` 会全部重新执行并创建新记录，不会跳过上次成功项。

## 8. 输出文件与结果检查

### 8.1 目录与来源记录

脚本运行创建如下目录：

```text
workingdir/<CaseName>/<RunId>/
  run.json
  build.json
  inputs/                         兼容旧流程；配置运行的有效快照在 results 内
  logs/
    stdout.log
    stderr.log
    runner.log
  results/
    original-config.json
    effective-config.json
    resolved-config.json
    manifest.json
    completion.json
    status.txt
    inputs/assets/0.stl          有几何时创建，按 0、1、2... 编号
    monitor.csv
    u-000000000.vtk              具体字段和帧由配置决定
    ...
    probes.csv                  提供 analysis 时创建
    analysis.csv
    forces.csv
    statistics.json             analysis.statistics=true 时创建
```

| 文件 | 用途 |
|---|---|
| 外层 `build.json` | 本次构建身份快照：Git 提交、源码树、工具集、EXE 哈希和构建日志 |
| 外层 `run.json` | 启动命令、设备请求、进程、时间、退出状态、失败原因、结果路径与完成验证 |
| `original-config.json` | 原始 JSON 字节副本 |
| `effective-config.json` | STL 路径已改为本次快照路径的可复用算例；省略字段仍按默认值解释 |
| `resolved-config.json` | 实际模型、格子参数、尺寸、单位换算、内存估算、设备、几何覆盖、探针落点等派生结果；它不是可直接传入 EXE 的算例配置 |
| `manifest.json` | 原始配置、STL、实际 EXE 的 SHA256 来源记录 |
| `completion.json` | 求解器状态：`starting`、`succeeded`、`prepared`、`failed`；成功时含实际和请求步数、模型信息 |
| `status.txt` | 简洁运行摘要 |

`bin/_runs/<CaseName>/<RunId>/` 保留 EXE 快照，其 `export` junction 指向本次 `results`。复现时使用同一 EXE 和该次 `effective-config.json`，指定一个新的输出目录；不要把 `resolved-config.json` 当作输入。

### 8.2 VTK 与 CSV

VTK 是 legacy binary `STRUCTURED_POINTS` 格式，各字段分别保存，中心坐标/网格间距已按单位设置。`flags` 是无量纲位标记，固体含 `TYPE_S`，平衡边界含 `TYPE_E`；程序初始化可能添加其他内部位，不应把所有非零格点都当作固体。可用支持该格式的后处理工具检查几何体素与流场。

| 文件 | 列名 | 单位与范围 |
|---|---|---|
| `monitor.csv` | `step,time,fluid_cells,mass_lattice,rho_min_lattice,rho_max_lattice,speed_max_lattice` | `time=step*dt`；带 `_lattice` 的量即使 SI 配置也保持格子值；排除固体 |
| `probes.csv` | `step,time,id,x,y,z,rho,ux,uy,uz,speed,p` | 当前单位；坐标是实际格点中心 |
| `analysis.csv` | `step,time,fluid_cells,mass,rho_mean,ux_mean,uy_mean,uz_mean,speed_mean,p_mean,kinetic_energy` | 全域非固体统计；SI 中分别用 kg、kg/m³、m/s、Pa、J |
| `forces.csv` | `step,time,id,fx,fy,fz` | 流体对所选固体的力；SI 为 N |

`statistics.json` 按 `global`、`probes.<id>`、`forces.<id>` 保存样本数、首末采样步，以及各字段的 `mean`、`std_population`。CSV 的 ID 会按 CSV 规则加引号、转义；解析时使用 CSV 读取器，不要直接按逗号切字符串。

### 8.3 检查一次运行

将 `$runDir` 设置为脚本打印的实际运行目录：

```powershell
$runDir = 'F:\01-Project\Opensource\01-FluidX3D\workingdir\periodic-demo\<实际RunId>'
$record = Get-Content "$runDir\run.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$done = Get-Content "$runDir\results\completion.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$resolved = Get-Content "$runDir\results\resolved-config.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$record | Select-Object status, exitCode, elapsedSeconds, failureReason
$done | Select-Object status, steps, requested_steps, solver
$resolved | Select-Object cells, lattice_nu, tau, max_prescribed_mach, device_id, device_name
Get-Content "$runDir\logs\stderr.log"
Import-Csv "$runDir\results\monitor.csv" | Select-Object -Last 5
```

正常计算应为外层 `run.json.status=succeeded`，内层 `completion.json.status=succeeded`，且 `steps=requested_steps`。预处理则外层 `succeeded`、内层 `prepared`、实际步数 0。脚本同时检查记录和输出存在性；数值是否达到所需精度，还应看守恒量、探针、受力和具体算例的收敛结果。

`max_prescribed_mach` 只根据已给定初始/边界速度计算，并不预测体积力作用后的最大速度，也不是自动稳定性判据。相应输入范围是软件可接受范围，不是所有流动都可靠的物理参数范围。

## 9. 常见错误

| 现象 / 报错 | 处理方式 |
|---|---|
| `The source repository must be clean` | Mac 上提交应跟踪的改动并推送，NUC 拉取；自己的算例/结果放在仓库外，检查未跟踪文件，不直接丢弃未知修改 |
| 找不到 `vswhere`、工具集或 Windows SDK | 安装/补齐 1.2 所列依赖，检查构建日志；使用实际安装的工具集，默认 v142 |
| EXE 只显示帮助 | 提供 `--config`；不要沿用硬编码版本的位置参数 `Solver-IBM.exe 0` |
| `Unknown field` / `Missing required field` | 对照第 4 节检查拼写、大小写、必填字段和互斥项；不要用 `null` 代替省略 |
| `Output directory must be empty` | 给直接调用指定新的 `--output`，或用运行脚本自动分配目录；不要覆盖已有结果 |
| `Requested OpenCL device not found` | 重新枚举 OpenCL ID，确认驱动及所选设备；校验模式不会检测该错误 |
| `Estimated device memory...` / `Distribution buffer...` | 减少格点或预算，核对当前 Q 和存储；检查设备显存与单缓冲限制 |
| `STL not found` / `Only valid binary STL` | 检查相对配置目录的路径和二进制格式；先转换 ASCII STL，确认文件完整 |
| `STL outside domain` / `voxelized to zero solid cells` | 检查单位、尺寸、中心和计算域；通过预处理检查体素结果，必要时增大网格分辨率 |
| `Uncovered boundary face` | 对该面提供完整底层规则，再用局部高优先级规则覆盖；六面声明完整仍可能有未覆盖格点 |
| `Conflicting boundaries` | 处理角点/棱边/局部重叠，明确优先级；同最高优先级必须同类型同赋值 |
| `moving_wall requires lattice density 1` | SI 下检查所有密度与 `reference_density` 一致；格子模式均为 1 |
| `Probe is inside solid` / `Empty force target` | 检查实际落点、体素、最高优先级归属与目标 ID，查看预处理结果 |
| `Overlapping geometry force target` / `touches domain wall` | 分离被单独统计的对象或改为有明确含义的整体固体统计 |
| 无 `statistics.json` | 检查是否提供 `analysis` 且 `statistics=true`；失败退出也可能来不及生成 |
| 最终步没有探针样本 | 检查 `start_step + k*every` 是否恰好命中最终步；分析不会自动补最后一帧 |
| 扫描路径不存在 | 在基础配置中显式补出该字段，检查数组索引与 JSON Pointer |
| 扫描快照哈希不一致 | 保留原快照；更改基础算例或规格后生成到新的目录，再重新执行 |
| `timed_out` | 查看日志判断耗时位置，调整网格/步数或 `TimeoutSeconds`；不要把超时输出当完整计算结果 |
| FP16S 弱强迫通道误差明显 | 与同模型 FP32 对比，并参考已记录的存储量化误差；切换存储无需重新编译 |

## 10. 依据与维护

字段名、默认值和校验规则以 [config.cpp](../src/config.cpp)、[config.hpp](../src/config.hpp)、[solver_options.hpp](../src/solver_options.hpp) 为依据；运行和几何行为来自 [config_runner.cpp](../src/config_runner.cpp)，分析来自 [config_analysis.hpp](../src/config_analysis.hpp)。脚本参数以 [build-nuc.ps1](../scripts/build-nuc.ps1)、[run-nuc.ps1](../scripts/run-nuc.ps1)、[parameter-study.py](../scripts/parameter-study.py) 为准。

本手册是当前配置驱动接口的统一使用入口。阶段设计和验收记录保留历史信息：

- [NUC 构建、运行目录约定](nuc-workflow.md)
- [V1.0.0 发布说明](releases/V1.0.0.md)、[版本交接文档](handoff-v1.0.0.md)
- [P0/P1 说明](config-runner.md)、[P2 说明](config-runner-p2.md)、[P3 模型说明](config-runner-p3.md)
- [P3 验收记录及精度边界](validation/config-runner-p3-2026-09-22.md)

以后新增字段或改变默认值时，应同步更新 schema、此手册、示例和适用的验收记录；运行已有 EXE 时优先查询该 EXE 的 `--capabilities` 并检查其构建身份。
