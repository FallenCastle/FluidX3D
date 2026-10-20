# Solver-IBM 软件使用手册

**适用版本：V2.1.0 development；同时说明 V2.0.0 正式包的独立使用方法。**

更新日期：2026-10-20。数值源码基线：`2235d31eccdd6c41efdcaace4c96bdd2cc09216f`，`src/` Git tree：`76465e1458fcd3f287b7fa4169733a34e48e22ff`。

本手册从连接服务器开始，依次说明程序选择、编译、配置、各功能算例计算、结果查看和验证。初次使用先完成第 2、3 章；需要修改或重新生成 EXE 时再执行第 4 章。所有求解器调用，包括 `--version`、`--validate` 和预处理，均在 Windows 服务器 **desktop-msi** 上执行。Mac 用于文件编辑、Git 和下载结果。

当前 V2.1.0 仍是开发版。断点续算的数值等价及主要协议测试已通过，但试用发现“缩短目标步数被拒绝时改写原结果元数据”的问题，M6 尚未关闭。第 10 章给出实际使用边界。V2.0.0 正式包、标签和历史验收记录保持原样。

## 阅读导航

| 现在要做什么 | 直接阅读 |
|---|---|
| 已有 EXE，想先跑通一次 | [第 3 章](#first-run) |
| 想从源码编译 | [第 4 章](#build) |
| 想建立自己的 JSON/STL 算例 | [第 5 章](#case-setup)、[字段参考](#fields) |
| 想算基础流动、受力或 SI 问题 | [第 6 章](#basic) |
| 想算传热、自由液面或运动物体 | [第 7 章](#thermal)、[第 8 章](#free-surface)、[第 9 章](#motion) |
| 想从检查点恢复或延长计算 | [第 10 章](#restart) |
| 想批量改变参数 | [第 11 章](#study) |
| 想看流场、温度、液面和曲线 | [第 12 章](#postprocessing) |
| 想核验安装和物理精度 | [第 13 章](#verification) |
| 遇到报错，或查找某个示例 | [第 14 章](#troubleshooting)、[全部算例索引](#case-index) |

<a id="versions"></a>
## 1. 软件版本与能力

### 1.1 选择哪一套程序

| 入口 | 位置（相对服务器工作根目录） | 用途 |
|---|---|---|
| V2.0.0 正式程序 | `package/V2.0.0/bin/Solver-IBM.exe` | 已验收的流动、热、自由液面和规定运动；不支持断点续算 |
| V2.1.0 原开发构建 | `bin/checkpoint-v2.1.0-dev/Solver-IBM.exe` | 含断点续算；2026-10-15 的开发试用构建 |
| 本手册核验构建 | `bin/manual-v2.1.0-20261020/Solver-IBM.exe` | 同一数值源码的独立重建，核验记录见第 13.5 节 |
| 自己的新构建 | `bin/<你指定的BuildName>/Solver-IBM.exe` | 按第 4 章生成，使用自己的构建记录 |

`BuildName` 是文件夹名称，产品版本来自 `src/version.hpp`。把 2.1.0 源码构建到一个名字含 `2.0.0` 的目录，不会变成 V2.0.0。实际身份由 `--version`、`--capabilities`、旁边的 `build.json` 和 EXE SHA256 共同确认。

### 1.2 当前能力与组合要求

- 三维、单 OpenCL 设备上的低马赫 LBM；D3Q19/D3Q27、SRT/TRT、Smagorinsky 开/关。
- 纯流动支持 FP16S/FP32 分布函数存储，运算均为 FP32；共有 16 种模型组合。
- 热输运/流固共轭传热、单液相自由液面、规定运动 STL 可独立、两两或同时启用，均要求 `solver.storage="FP32"`；每种功能组合支持 8 种流动模型。
- JSON 与二进制 STL 输入；格子单位或 SI；探针、受力、时间统计、VTK/CSV/JSON 输出及参数扫描。
- V2.1.0 开发版增加检查点保存、恢复及延长计算。

物体运动由配置预先给定，诊断受力不会改变轨迹。气体使用固定环境压强，未求解气相动力学。热模型使用常物性、理想热接触和显热收支。当前接口未开放六自由度响应、碰撞、变形、相变、动态接触角、多 GPU 或自动收敛停止。`run.steps`/`duration` 仍是终止条件。产品名 Solver-IBM 不代表本版本另行实现了新的浸入边界算法。

### 1.3 四个名称的含义

| 名称 | 作用 | 例子 |
|---|---|---|
| `BuildName` | 选择哪套 EXE：`bin/<BuildName>/` | `checkpoint-v2.1.0-dev` |
| `ConfigPath` | 决定真正计算的 JSON 文件 | `src/configs/poiseuille.json` |
| `CaseName` | 给计算结果分类：`workingdir/<CaseName>/` | `manual-poiseuille` |
| `RunId` | 一次实际启动的唯一编号 | 脚本自动生成的 UTC 时间与提交前缀 |

`case.name` 是配置中的描述名称。`-CaseName poiseuille` 本身不会创建 Poiseuille 流，仍须提供相应 `-ConfigPath`。

<a id="environment"></a>
## 2. 工作环境、连接与文件位置

### 2.1 从 Mac 进入 Windows PowerShell

在 **Mac 终端**执行：

```sh
ssh desktop-msi
```

登录后，如果提示符是 `C:\Users\...>`，输入下行进入 PowerShell；如果已是 `PS C:\...>`，直接执行后面的初始化。

```powershell
powershell.exe -NoProfile
```

在 **desktop-msi PowerShell** 中执行：

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
Set-Location "$root\src"
Get-Location
$PSVersionTable.PSVersion
[Environment]::Is64BitProcess
```

应进入 `F:\01-Project\Opensource\01-FluidX3D\src`，使用 PowerShell 5.1 或以上、64 位进程。Windows 的 `src` 是整个 Git 仓库，C++ 源码另在 `src/src` 下。脚本名称中的 `nuc` 是历史名称，连接目标始终为 `desktop-msi`。

每个下文独立操作块都会初始化所需变量。PowerShell 用 `& $exe` 调用变量中的程序路径；反引号 `` ` `` 表示续行，其后不能有空格。命令完成后紧接着检查 `$LASTEXITCODE`，它属于刚才启动的外部进程。

### 2.2 工作目录地图

```text
F:\01-Project\Opensource\01-FluidX3D\
├── AGENTS.md
├── src\                         Git 仓库：编辑后经 Git 同步
│   ├── src\                     C++、OpenCL 内核和 version.hpp
│   ├── configs\                 36 个算例 JSON、3 个扫描规格
│   │   ├── assets\              内置小型 STL
│   │   └── reference\           MARIN 参考数据与来源
│   ├── scripts\                 构建、运行、扫描、验证脚本
│   ├── schemas\                 JSON 辅助 schema
│   └── docs\                    本手册
├── bin\<BuildName>\             Solver-IBM.exe 与 build.json
├── bin\_runs\<CaseName>\<RunId>\ 每次启动的 EXE 快照
├── workingdir\_builds\<BuildId>\ 构建记录与日志
├── workingdir\<CaseName>\<RunId>\
│   ├── run.json
│   ├── build.json
│   ├── logs\                    stdout、stderr、runner 日志
│   └── results\                 输入快照、CSV、VTK、完成记录
└── package\V2.0.0\              已固定的正式归档
```

自己的配置和模型放到 `workingdir/my-inputs/<项目名>/` 等仓库外目录。结果写到 `workingdir/`。正式包内文件作为只读输入，算例需要修改时先复制到包外。

Mac 源码仓库为 `/Users/czy/Data/01-work/02-project/02-opensource/05-FluidX3D/FluidX3D`。Mac 的 `cases/` 与 Windows 的 `workingdir/` 是不同位置；配置里不能引用 Mac 路径供 Windows 求解器读取。

### 2.3 运行与编译分别需要什么

| 组件 | 使用已有 EXE | 重新编译 | 用途 |
|---|---|---|---|
| GPU 驱动及 OpenCL 运行时 | 需要 | 运行时需要 | 设备计算和运行时 OpenCL 内核编译 |
| Microsoft Visual C++ v14 x64 运行库 | 需要 | 编译环境通常已具备 | 当前 EXE 使用 MSVCP140/VCRUNTIME140 系列动态库 |
| Windows PowerShell | 脚本入口需要 | 需要 | 运行、构建、日志归档 |
| Git | 不强制 | 需要 | 构建脚本读取提交和干净工作树 |
| Visual Studio/Build Tools、MSVC、Windows SDK | 无需 | 需要 | Windows C++/资源编译与链接 |
| Python 3.9+ | 扫描、验证需要 | 编译本身无需 | 扫描和自动验证；实测 Python 3.12.10 |
| ParaView | 后处理可选 | 无需 | 查看 VTK；可以装在 Windows 或 Mac |

当前 EXE 的依赖检查确认使用 MSVCP140.dll、VCRUNTIME140.dll/VCRUNTIME140_1.dll；新 Windows 机器需安装与构建工具同版或更新的 x64 v14 运行库，入口见 [Microsoft 官方运行库说明与下载](https://learn.microsoft.com/zh-CN/cpp/windows/latest-supported-vc-redist)。已安装完整构建环境的当前服务器可直接运行。

仓库随附编译使用的 OpenCL 头文件和库，实际设备运行仍需要显卡驱动提供 OpenCL。当前配置接口不需要为了切换格子、碰撞模型、精度或物理模块手改 `defines.hpp`。

<a id="first-run"></a>
## 3. 使用现有程序完成第一次计算

### 3.1 找到程序并确认身份

以下整章在 **desktop-msi PowerShell** 执行。先使用现有开发构建，不需要先编译。

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$buildName = 'checkpoint-v2.1.0-dev'
$exe = "$root\bin\$buildName\Solver-IBM.exe"
if (-not (Test-Path $exe)) { throw 'Build not found; follow chapter 4 or use the release package.' }
$build = Get-Content "$root\bin\$buildName\build.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$build | Select-Object status, productVersion, gitCommit, sourceTree, executableSha256
$actualHash = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLowerInvariant()
if ($build.status -ne 'succeeded' -or $actualHash -ne $build.executableSha256) { throw 'Invalid build identity.' }
& $exe --version
if ($LASTEXITCODE -ne 0) { throw 'Version query failed.' }
& $exe --capabilities
if ($LASTEXITCODE -ne 0) { throw 'Capabilities query failed.' }
```

应显示 `Solver-IBM 2.1.0`。开发状态可从 `--capabilities` 中的 `release_status` 确认。EXE 查询成功表示程序能启动，实际 GPU 可用性还需下面的预处理。

### 3.2 查询并选择 GPU

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$devices = powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File "$root\src\scripts\get-opencl-devices.ps1" | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'OpenCL enumeration failed.' }
$devices | Format-Table id, platform, name, driver
$gpu = @($devices | Where-Object { $_.platform -eq 'NVIDIA CUDA' -and $_.name -eq 'NVIDIA GeForce RTX 4070 Ti SUPER' })
if ($gpu.Count -ne 1) { throw 'Inspect the device list and select one actual device.' }
$deviceId = [int]$gpu[0].id
$deviceId
```

2026-10-20 实测 NVIDIA 为 OpenCL device `0`，AMD 核显为 `1`。`nvidia-smi` 的编号不等于 OpenCL 编号；更换硬件或驱动后重新执行此步骤。以下示例中的 `-DeviceId 0` 均指本次实测 NVIDIA 设备，使用前据实际列表调整。

### 3.3 校验、预处理、计算和检查结果

使用 `periodic-fp32.json`：16×16×16 周期域，23 步，无外部模型，适合第一次检查。下面的块可在新 PowerShell 中独立执行；先按 3.2 节核实编号。

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$buildName = 'checkpoint-v2.1.0-dev'
$deviceId = 0
$exe = "$root\bin\$buildName\Solver-IBM.exe"
$config = "$root\src\configs\periodic-fp32.json"

# 解析配置、单位、边界和 STL 格式，不初始化 GPU。
& $exe --config $config --validate
if ($LASTEXITCODE -ne 0) { throw 'Configuration validation failed.' }

# 初始化 GPU 并输出第 0 步，结果归到单独的预处理算例名下。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\src\scripts\run-nuc.ps1" `
  -WorkspaceRoot $root -BuildName $buildName -DeviceId $deviceId `
  -CaseName manual-periodic-prepare -ConfigPath $config -PrepareOnly -TimeoutSeconds 900
if ($LASTEXITCODE -ne 0) { throw 'Prepare failed; inspect the printed logs directory.' }

# 正式推进 23 步。每次重复启动都会分配新的 RunId。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\src\scripts\run-nuc.ps1" `
  -WorkspaceRoot $root -BuildName $buildName -DeviceId $deviceId `
  -CaseName manual-periodic-fp32 -ConfigPath $config -TimeoutSeconds 900
if ($LASTEXITCODE -ne 0) { throw 'Run failed; inspect run.json and logs.' }

$runDir = Get-ChildItem "$root\workingdir\manual-periodic-fp32" -Directory |
  Sort-Object Name | Select-Object -Last 1 -ExpandProperty FullName
$record = Get-Content "$runDir\run.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$results = [string]$record.paths.results
$done = Get-Content "$results\completion.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$record | Select-Object status, exitCode, elapsedSeconds, failureReason
$done | Select-Object status, steps, requested_steps
Import-Csv "$results\monitor.csv" | Select-Object -Last 5
Get-ChildItem $results -Name
```

通过条件：外层记录 `status=succeeded`，内层 `status=succeeded`，`steps=requested_steps=23`；存在 `u-000000023.vtk`、`rho-000000023.vtk`、`flags-000000023.vtk`。预处理的内层状态则是 `prepared`、步数 0。日志位于各自的 `<RunId>/logs/`。`--validate` 通过不能替代 GPU 预处理。

均匀周期流应基本保持均匀，监控值应有限。这是安装与输入链路检查；Poiseuille/Couette 和物理精度套件用于进一步验证数值结果。

<a id="25-使用正式发布包"></a>
### 3.4 独立使用 V2.0.0 正式包

此块使用包内 EXE、配置和脚本，完全独立于开发版构建。V2.0.0 没有断点续算功能。

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$package = "$root\package\V2.0.0"
$deviceId = 0
$exe = "$package\bin\Solver-IBM.exe"
& $exe --version
if ($LASTEXITCODE -ne 0) { throw 'Release executable failed.' }
& $exe --config "$package\cases\configs\periodic-lattice.json" --validate
if ($LASTEXITCODE -ne 0) { throw 'Release configuration failed.' }
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File "$package\source\scripts\run-package.ps1" `
  -PackageRoot $package -WorkspaceRoot $root -DeviceId $deviceId `
  -CaseName manual-release-periodic `
  -ConfigPath "$package\cases\configs\periodic-lattice.json" -TimeoutSeconds 900
if ($LASTEXITCODE -ne 0) { throw 'Release run failed.' }
$runDir = Get-ChildItem "$root\workingdir\manual-release-periodic" -Directory |
  Sort-Object Name | Select-Object -Last 1 -ExpandProperty FullName
Get-Content "$runDir\run.json" -Raw -Encoding UTF8
```

应显示 `Solver-IBM 2.0.0`。正式包输出仍在包外 `workingdir/`。改变算例时更换 `-ConfigPath`；包中 `cases/configs/` 的 STL 路径已做包内适配。

### 3.5 三种运行入口如何选择

| 入口 | 用途与区别 |
|---|---|
| `Solver-IBM.exe --config ...` | 直接校验或诊断；新计算的 `--output` 必须不存在或为空；不会生成外层 `run.json`、运行 EXE 快照或超时管理 |
| `scripts/run-nuc.ps1` | 日常开发构建计算；自动分配 RunId、复制 EXE、留存日志与输入、检查完成状态 |
| `package/V2.0.0/source/scripts/run-package.ps1` | 正式包计算；核对包和构建身份，正确定位迁移后的 EXE 和包内资源 |

日常运行脚本超时缺省为 900 s，本手册显式填写；长算例按预计耗时增大，范围是 1–86400 s。超时会终止进程。新的直接调用使用新结果目录；恢复原目录必须遵守第 10 章的续算契约。

<a id="build"></a>
## 4. 从源码编译

### 4.1 检查工具链

在 desktop-msi PowerShell 执行：

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
git --version
python --version
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) { throw 'Install Visual Studio Installer and C++ build components.' }
& $vswhere -latest -products '*' -requires Microsoft.Component.MSBuild -property installationPath
Get-ChildItem 'C:\Program Files (x86)\Windows Kits\10\Include' -Directory
Get-Content "$root\src\src\version.hpp" | Select-String 'VERSION_|RELEASE_STATUS'
```

新机器需要准备工具链时，打开 Visual Studio Installer，选择已安装版本的“修改”，勾选“使用 C++ 的桌面开发”；在“单个组件”中确认 MSVC v142（VS 2019 C++ x64/x86 工具集）与完整 Windows SDK。按下修改/安装后等待完成，再执行本节检查。当前 desktop-msi 已具备这些组件，日常使用无需重复安装。Visual Studio 的主版本与 C++ 平台工具集是两件事：当前服务器使用 VS 18/MSBuild 18.9，仍以 `v142` 编译。构建脚本通过 `vswhere` 自动选择 MSBuild、C++ 工具和 SDK，并保存到构建记录。

2026-10-20 实测工具链为 MSVC `14.29.30133`、Windows SDK `10.0.26100.0`、Release x64；以后以新构建 `build.json` 为准。完整验证涉及深层目录，当前服务器已开启 Windows 长路径支持；可只读检查：

```powershell
(Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem').LongPathsEnabled
```

### 4.2 核对并同步源码

**Mac 终端**：

```sh
cd /Users/czy/Data/01-work/02-project/02-opensource/05-FluidX3D/FluidX3D
git status --short --branch
git remote -v
git branch --show-current
git rev-parse HEAD
```

当前开发分支为 `feature/checkpoint-restart`，fork 为 `git@github.com:FallenCastle/FluidX3D.git`。自己修改源码后，在 Mac 明确暂存本次文件、提交、推送；不要把算例结果或大型 STL 加入源码仓库。

**desktop-msi PowerShell**：

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
git -C "$root\src" status --short --branch
git -C "$root\src" remote -v
git -C "$root\src" branch --show-current
# 先确认工作树干净；目标分支应与 Mac 当前工作分支一致。
git -C "$root\src" switch feature/checkpoint-restart
if ($LASTEXITCODE -ne 0) { throw 'Branch switch failed; inspect local changes.' }
git -C "$root\src" pull --ff-only origin feature/checkpoint-restart
if ($LASTEXITCODE -ne 0) { throw 'Pull failed; do not build an unconfirmed revision.' }
git -C "$root\src" rev-parse HEAD
```

比较两端提交。构建脚本要求包括未跟踪文件在内的工作树干净。自己的配置保存在仓库外；发现未知修改先辨认来源，不能直接重置覆盖。

服务器至 GitHub 若不可达，可在 Mac 为已推送的分支生成 bundle，再传到服务器。以下是本地 Git 同步备用入口，不修改正式包。

**Mac 终端**：

```sh
cd /Users/czy/Data/01-work/02-project/02-opensource/05-FluidX3D/FluidX3D
git bundle create /tmp/solver-ibm-sync.bundle feature/checkpoint-restart
scp /tmp/solver-ibm-sync.bundle desktop-msi:F:/01-Project/Opensource/01-FluidX3D/solver-ibm-sync.bundle
```

**desktop-msi PowerShell**：

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
git -C "$root\src" pull --ff-only "$root\solver-ibm-sync.bundle" feature/checkpoint-restart
if ($LASTEXITCODE -ne 0) { throw 'Bundle synchronization failed.' }
git -C "$root\src" rev-parse HEAD
```

同步完成且两端提交一致后删除本次中转 bundle。Mac 至 GitHub 的 22 端口若被阻断，可单次使用 `git -c core.sshCommand='ssh -p 443 -o Hostname=ssh.github.com' push origin feature/checkpoint-restart`；这不改变仓库远端地址。

### 4.3 生成新的开发构建

使用自己的独立名称，例如 `my-v2.1.0-dev`。后面章节引用现有构建时，将块内 `$buildName` 替换成这个名称即可。

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$buildName = 'my-v2.1.0-dev'
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File "$root\src\scripts\build-nuc.ps1" `
  -WorkspaceRoot $root -BuildName $buildName -PlatformToolset v142
if ($LASTEXITCODE -ne 0) { throw 'Build failed; inspect workingdir/_builds.' }

$exe = "$root\bin\$buildName\Solver-IBM.exe"
$build = Get-Content "$root\bin\$buildName\build.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$build | Select-Object status, productVersion, gitCommit, sourceTree, executableSha256, buildLog
$actualHash = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLowerInvariant()
if ($build.status -ne 'succeeded' -or $actualHash -ne $build.executableSha256) { throw 'Build verification failed.' }
& $exe --version
if ($LASTEXITCODE -ne 0) { throw 'Executable cannot start.' }
```

成功产物在 `bin/my-v2.1.0-dev/`，详细日志在 `workingdir/_builds/<BuildId>/msbuild.log`，中间文件在 `src/temp/<BuildName>/<BuildId>/`。EXE 存在本身不表示本次编译成功。

**当前 `build-nuc.ps1`、`run-nuc.ps1` 和扫描器的默认构建名称仍为 `solver-ibm-v1.0.0`。始终显式填写 `BuildName`。** 重建同一个名字会替换该目录的 EXE/build.json；对比不同构建时使用不同名称。

### 4.4 什么修改需要重新编译

| 改动 | 操作 |
|---|---|
| JSON 中的模型、物性、网格、边界、STL 变换、运动、步数和输出 | 无需 C++ 重编译，重新校验并启动新算例 |
| 更换或修改 STL/轨迹输入 | 无需 C++ 重编译，重新预处理；已有检查点不能随意换资产 |
| `.cpp`、`.hpp`、OpenCL 内核源码、工程或编译选项 | 按既有 Mac→Git→服务器流程重建、验证 |
| 只改文档 | 不改变数值源码树；保留构建身份，不声称重新构建了程序 |

OpenCL 内核在启动相应模型时由驱动编译/加载缓存，因此首次 GPU 初始化可能比后续启动慢。

### 4.5 从正式包重建 V2.0.0

需要固定正式源码时，从包内 Git bundle 克隆到新的包外工作区。`source/` 是没有 `.git` 的源码快照，不能直接作为现有构建脚本的工作仓库。

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$package = "$root\package\V2.0.0"
$rebuild = "$root\workingdir\rebuild-v2.0.0-" + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
git clone "$package\source.git.bundle" "$rebuild\src"
if ($LASTEXITCODE -ne 0) { throw 'Bundle clone failed.' }
git -C "$rebuild\src" checkout --detach v2.0.0
if ($LASTEXITCODE -ne 0) { throw 'Release checkout failed.' }
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File "$rebuild\src\scripts\build-nuc.ps1" `
  -WorkspaceRoot $rebuild -BuildName rebuilt-v2.0.0 -PlatformToolset v142
if ($LASTEXITCODE -ne 0) { throw 'Release rebuild failed.' }
```

重建后的 EXE 和证据属于这次重建。不同工具链/驱动可能产生不同二进制或浮点结果，不替换正式归档的 EXE 和原始哈希。

<a id="case-setup"></a>
## 5. 创建和修改自己的算例

### 5.1 一个完整的自建算例

下面创建包外输入目录，复制一个内置立方体，写出带探针和受力统计的完整配置。此例为周期流中的静态物体，用于学习输入与输出链路。

**desktop-msi PowerShell**：

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$inputDir = "$root\workingdir\my-inputs\cube-demo"
if (Test-Path $inputDir) { throw 'Use a new input directory or inspect the existing files first.' }
New-Item -ItemType Directory -Path "$inputDir\assets" | Out-Null
Copy-Item "$root\src\configs\assets\unit-cube-binary.stl" "$inputDir\assets\unit-cube-binary.stl"
@'
{
  "schema_version": 1,
  "case": {"name": "my-static-cube"},
  "solver": {"lattice":"D3Q19", "collision":"SRT", "storage":"FP32", "turbulence":"none"},
  "units": {"mode":"lattice"},
  "domain": {"cells":[32,16,16]},
  "fluid": {"rho":1.0, "nu":0.05},
  "initial": {"velocity":[0.03,0,0]},
  "geometry": [
    {"id":"body", "file":"assets/unit-cube-binary.stl",
     "transform":{"mode":"fit", "size":4.0, "center":[16,8,8]}}
  ],
  "boundaries": [
    {"id":"periodic", "faces":["xmin","xmax","ymin","ymax","zmin","zmax"], "type":"periodic"}
  ],
  "run": {"steps":200, "monitor_every":20},
  "output": {"vtk_fields":["u","rho","p","flags"], "vtk_every":100, "initial":true},
  "analysis": {
    "every":20, "start_step":0, "statistics":true,
    "probes":[{"id":"upstream", "position":[4.5,8.5,8.5]}],
    "forces":[{"id":"body-force", "target":"geometry:body"}]
  }
}
'@ | Set-Content "$inputDir\case.json" -Encoding UTF8
$exe = "$root\bin\checkpoint-v2.1.0-dev\Solver-IBM.exe"
& $exe --config "$inputDir\case.json" --validate
if ($LASTEXITCODE -ne 0) { throw 'Custom config invalid.' }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\src\scripts\run-nuc.ps1" `
  -WorkspaceRoot $root -BuildName checkpoint-v2.1.0-dev -DeviceId 0 `
  -CaseName my-static-cube-prepare -ConfigPath "$inputDir\case.json" -PrepareOnly -TimeoutSeconds 900
if ($LASTEXITCODE -ne 0) { throw 'Custom geometry preparation failed.' }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\src\scripts\run-nuc.ps1" `
  -WorkspaceRoot $root -BuildName checkpoint-v2.1.0-dev -DeviceId 0 `
  -CaseName my-static-cube -ConfigPath "$inputDir\case.json" -TimeoutSeconds 900
if ($LASTEXITCODE -ne 0) { throw 'Custom case failed.' }
```

预期有 0、100、200 步的 VTK，0、20、…、200 步的探针与受力，共 11 次采样；`forces.csv` 中 ID 为 `body-force`。几何准备时查看 `flags` 和 `resolved-config.json`，确认物体位于域内、探针未落入固体、受力目标非空。周期域没有持续外部驱动，物体阻力可使初始流动逐渐衰减。

### 5.2 修改配置的顺序

1. 选单位与参考尺度，再定域尺寸、网格和时间步。
2. 选择模型与精度，设置密度、运动黏度或 Re。
3. 设置初始场、重力/体积力、全部六面边界和几何位置。
4. 按需加入热、自由液面、运动、探针、输出与检查点字段。
5. 先 `--validate`，再 `--prepare-only`；检查体素后进行短算，最后延长到所需时间。

配置省略 `solver` 时会选择 D3Q19/SRT/**Smagorinsky/FP16S**。为让自己的意图明确，建议像上例那样显式填写四个模型字段。更改 JSON/STL 后复用 EXE；恢复既有检查点则受第 10 章的严格白名单约束。

### 5.3 格子单位和 SI 的完整对应例

`periodic-fp32.json` 是格子示例，`periodic-si.json` 是已有 SI 示例。下面给出可独立保存为 JSON 的 SI 配置，16³ 网格、`dx=0.01 m`、`dt=0.003 s`、0.069 s 共 23 步。

```json
{
  "schema_version": 1,
  "case": {"name":"periodic-si-with-probe"},
  "solver": {"lattice":"D3Q19", "collision":"SRT", "storage":"FP32", "turbulence":"none"},
  "units": {"mode":"si", "reference_density":1000, "dt":0.003},
  "domain": {"length":[0.16,0.16,0.16], "dx":0.01, "origin":[0,0,0]},
  "fluid": {"rho":1000, "nu":0.0006666666666666668},
  "initial": {"velocity":[0.1,0,0]},
  "geometry": [],
  "boundaries": [
    {"id":"periodic", "faces":["xmin","xmax","ymin","ymax","zmin","zmax"], "type":"periodic"}
  ],
  "run": {"duration":0.069, "monitor_every":7},
  "output": {"vtk_fields":["u","rho","flags","p"], "vtk_every":7, "initial":true},
  "analysis": {"every":7, "start_step":0, "statistics":true,
    "probes":[{"id":"center", "position":[0.085,0.085,0.085]}], "forces":[]}
}
```

计算出的格子速度为 0.03、黏度为 0.02。`duration` 与 `steps` 二选一，实际推进 `ceil(duration/dt)` 步。SI 中把热温度写成 K、重力写成 m/s²、`body_force` 写成 N/m³。参考速度只用于尺度推导，不会自动赋给流场。完整换算和约束见附录 A.3。

### 5.4 网格、Re、时间与资源

| 想改变什么 | 修改方法 | 需要一起检查 |
|---|---|---|
| 格子域尺寸 | `domain.cells` | STL/探针/边界区域仍在域内，长度与 Re 的定义 |
| SI 网格精度 | `domain.dx`，长度保持 `domain.length` | 生成的实际 cells、格子速度/黏度、dt、显存和步数 |
| 通过预算估算格点 | 用 `aspect_ratio`+`memory_budget_mb` 替换 cells，仅格子模式 | 预算是字段估算，另有驱动、几何和临时状态开销 |
| 指定 Re | 用 `reynolds`+`reference_length`+`reference_velocity` 替换 `nu` | 三项必须都给；不会自动设置速度 |
| 延长新计算 | 增大 `steps` 或 SI `duration` | 输出频率、脚本超时、磁盘；已有结果续算看第 10 章 |
| 减少 VTK 文件 | 增大 `vtk_every`，或设为 0 | 0 仍写最终帧，`initial=true` 还写初始帧 |
| 增加采样 | 减小 `analysis.every`，设置 `start_step` | 分析与 monitor、VTK 各自独立调度 |

保持物理问题不变的网格加密，需要同步考虑单位换算和时间尺度，不能只改格点数后直接比较。稳态问题应检查速度/力/热量随时间是否稳定；瞬态问题应覆盖所需物理时间。目前没有自动收敛停止开关。

### 5.5 JSON 与路径规则

配置采用 UTF-8 JSON：双引号，无注释、无尾逗号，字段与枚举区分大小写；未知键、重复键和重复 ID 会拒绝。`null` 不等于省略，整数写 `1000`，不写 `1000.0`。当前解析器不接受额外的顶层 `$schema` 字段，schema 文件仅供编辑器辅助检查。

STL 相对路径以**配置文件所在目录**解析；命令行 `--config`/`--output` 的相对路径以当前终端目录解析。复制一个含 STL 的 JSON 时，应保留相对资产结构或改写成正确路径。JSON 推荐使用 `F:/cases/body.stl`；使用反斜杠时写成 `F:\\cases\\body.stl`。

`resolved-config.json` 是派生记录，不能直接当输入。复用某次运行可用其 `effective-config.json` 和完整的 `inputs/assets/`；搬迁时保留目录结构，并指定新的输出目录。

<a id="basic"></a>
## 6. 基础流动、STL、边界与分析

### 6.1 模型和精度如何开启

下表表示替换完整配置中的 `solver` 对象，不是独立算例：

| 目的 | 配置 |
|---|---|
| D3Q19、SRT、FP32、无亚格子模型 | `{"lattice":"D3Q19","collision":"SRT","storage":"FP32","turbulence":"none"}` |
| D3Q27、TRT、Smagorinsky | `{"lattice":"D3Q27","collision":"TRT","storage":"FP32","turbulence":"smagorinsky"}` |
| 自定义 Cs | 在 Smagorinsky 对象内加 `"smagorinsky_constant":0.17` |
| 自定义 TRT Λ | 在 TRT 对象内加 `"trt_magic_parameter":0.1875` |
| 纯流动改用 FP16S | 只改 `"storage":"FP16S"`；热/自由液面/运动物体不允许 |

关闭亚格子模型使用 `turbulence="none"`，并删除 Cs 字段；SRT 模式删除 Λ。`models-periodic.json` 演示全部模型参数。16 组合扫描见第 11 章，精度验证见第 13 章 P3；FP16S 在弱强迫通道上已有量化误差记录，不能用程序启动成功推断其精度与 FP32 相同。

### 6.2 基础算例的完整运行入口

下面一次运行表中的七个小算例。只想运行一个时，在 `$files` 中保留该文件名。代码块可独立执行，结果分别存到 `workingdir/manual-<文件名去扩展名>/<RunId>/`。

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$buildName = 'checkpoint-v2.1.0-dev'
$deviceId = 0
$files = @('periodic-lattice.json', 'periodic-fp32.json', 'periodic-si.json',
           'models-periodic.json', 'probes-periodic.json', 'poiseuille.json', 'couette.json')
foreach ($file in $files) {
  $config = "$root\src\configs\$file"
  & "$root\bin\$buildName\Solver-IBM.exe" --config $config --validate
  if ($LASTEXITCODE -ne 0) { throw "Invalid config: $file" }
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\src\scripts\run-nuc.ps1" `
    -WorkspaceRoot $root -BuildName $buildName -DeviceId $deviceId `
    -CaseName ('manual-' + [IO.Path]::GetFileNameWithoutExtension($file)) `
    -ConfigPath $config -TimeoutSeconds 900
  if ($LASTEXITCODE -ne 0) { throw "Run failed: $file" }
}
```

| 文件 | 功能与应该看到的结果 | 进一步验证 |
|---|---|---|
| `periodic-lattice.json` | 纯周期流，使用模型默认值；监控/VTK 按指定步输出 | P1 的周期流与调度检查 |
| `periodic-fp32.json` | 同类 FP32 存储入口 | 存储套件的两种存储路径 |
| `periodic-si.json` | SI 单位流动，结果坐标和速度换成 SI | P1/P2/P3 的单位等价检查 |
| `models-periodic.json` | D3Q27、TRT、自定义 Cs/Λ | P3 的 16 模型、剪切波和通道剖面 |
| `probes-periodic.json` | 全域分析、点探针、均值/标准差 | `probes.csv`、`analysis.csv`、`statistics.json`，P2 采样断言 |
| `poiseuille.json` | 常体积力驱动、两壁无滑移，4000 步；出现抛物线速度剖面 | P2/P3 比较解析速度、壁面受力和网格细化 |
| `couette.json` | 固定位置的切向运动壁面，4000 步；出现近线性速度剖面 | P2/P3 比较解析 Couette 剖面 |

上述标准配置未必含所有精度测试使用的网格和强迫参数。P2 的 6 个剖面、P3 的 96 个剖面是脚本生成的独立输入，完整重现使用第 13 章命令。

### 6.3 六面、局部边界与驱动力

| 功能 | 开启方法 | 核对要点 |
|---|---|---|
| 周期 | 相对两面均为 `periodic` | 整方向配对，不支持局部周期 |
| 固壁 | `type="no_slip"` | 最外一层格点作为壁面，影响有效通道宽度 |
| 指定入口/出口 | `type="equilibrium"`，同时给 `rho`、`velocity` | 固定两者；当前没有独立的通用压力出口或零梯度出口 |
| 运动壁面 | `type="moving_wall"`，给切向 `velocity` | 壁面位置固定、法向速度为零，格子参考/初始密度须为 1 |
| 局部入口 | 整面低优先级规则上叠加高 `priority` 的 `region` | x 面区域坐标为 y/z，y 面为 x/z，z 面为 x/y；角点也参与优先级判断 |
| 体积驱动力 | `fluid.body_force=[fx,fy,fz]` | 输入是力密度，SI 为 N/m³；Poiseuille 示例 |
| 重力 | `physics.gravity=[gx,gy,gz]` | 输入是加速度，SI 为 m/s²；与额外体积力相加 |

所有六面都要声明。给局部入口前先声明完整底层覆盖，否则区域外会报未覆盖；同优先级不同赋值的交叠会报冲突。完整字段见附录 A.8，程序校验会报告覆盖范围。

### 6.4 静态 STL 的准备和外部模型

开启静态 STL：在 `geometry` 中添加含 `id`、`file`、`transform` 的对象；无运动时省略 `motion`。第 5.1 节已给出可直接运行的小型模型完整配置。

- `fit`：把旋转后的最长包围盒边缩放到 `size`，放到 `center`，保持形状比例。
- `scale`：给 `factor`、源坐标 `pivot` 和目标 `translation`，适合已经明确模型单位的工程资产。源坐标为 mm、目标 SI 为 m 时可用 `factor=0.001`。
- 支持多个静态 STL 并集。单独统计某个对象受力时，还要求对象间归属不含糊，不能与其他固体重叠或贴合域固壁。
- 输入必须是非空二进制 STL；ASCII 需要在几何工具中导出为 binary STL。输入检查包括大小、顶点、包围盒和域内范围；预处理检查体素数、边界交叠和探针。

`boeing-regression.json` 与 `ahmed-smoke.json` 使用仓库外的大型模型。先核对配置解析到的实际路径，再运行：

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$buildName = 'checkpoint-v2.1.0-dev'
$deviceId = 0
foreach ($file in @('boeing-regression.json', 'ahmed-smoke.json')) {
  $config = "$root\src\configs\$file"
  $case = Get-Content $config -Raw -Encoding UTF8 | ConvertFrom-Json
  foreach ($geometry in $case.geometry) {
    $asset = [IO.Path]::GetFullPath((Join-Path (Split-Path $config -Parent) $geometry.file))
    if (-not (Test-Path $asset)) { throw "Prepare the external STL first: $asset" }
  }
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\src\scripts\run-nuc.ps1" `
    -WorkspaceRoot $root -BuildName $buildName -DeviceId $deviceId `
    -CaseName ('manual-' + [IO.Path]::GetFileNameWithoutExtension($file)) `
    -ConfigPath $config -PrepareOnly -TimeoutSeconds 1800
  if ($LASTEXITCODE -ne 0) { throw "Geometry preparation failed: $file" }
}
```

去掉 `-PrepareOnly` 即按原配置推进：Boeing 1000 步、Ahmed 37 步；仍为每次独立 RunId。2026-10-20 两份配置及其外部资产均在当前服务器完整运行通过。复制到其他机器时可用 V2.0.0 正式包内已适配资源的相应配置，通过 3.4 节入口运行。

这些运行提供预处理、回归和短算证据；工程阻力精度还需要针对具体来流、网格、边界和统计时段验证。包里其他模型有些仅为资产归档，不能仅凭存在 STL 认定已制成可计算算例。

### 6.5 探针、全域统计、分组受力

在完整配置顶层加入 `analysis` 即开启分析。示例片段：

```json
{
  "analysis": {
    "every": 20,
    "start_step": 100,
    "statistics": true,
    "probes": [{"id":"center", "position":[8.5,8.5,8.5]}],
    "forces": [{"id":"body", "target":"geometry:body"}]
  }
}
```

它是顶层对象的补充片段，需要配置中存在 `geometry` ID `body`、探针处于非固体格点、目标步数不小于 100。没有 STL 时先用 `probes-periodic.json`；带受力的完整例子用第 5.1 节，通道壁面受力验证用 P2。

`analysis:{}` 会开启全域分析；省略 `analysis` 则关闭。受力目标可选 `all_solids`、`geometry:<id>`、`boundary:<id>`。`forces.csv` 输出流体作用于固体的 `fx/fy/fz`，当前没有自动输出升阻力系数；动态对象的力矩另在 `object-motion.csv` 中。

采样严格按 `start_step+k*every`，不额外补最终样本。监控、分析和 VTK 三套间隔独立。样本均值和总体标准差在 `statistics.json` 中；一个样本的标准差为 0、零样本为 null。探针取最近格点中心，不进行空间插值；实际坐标保存在派生记录。

<a id="thermal"></a>
## 7. 热输运与流固共轭传热

### 7.1 启用热模型的最小改动

在完整配置里提供 `physics.thermal` 对象，并选择 FP32；不需要额外的 `enabled` 开关。以下是需要合入配置的字段片段：

```json
{
  "solver": {"storage":"FP32", "turbulence":"none"},
  "physics": {
    "thermal": {
      "reference_temperature":300.0, "initial_temperature":300.0,
      "specific_heat":1000.0, "conductivity":0.6
    }
  },
  "output": {"vtk_fields":["T","u","rho","flags"], "vtk_every":100, "initial":true}
}
```

`reference_temperature` 同时用于温度尺度和自然对流参考，`initial_temperature` 是初温。SI 温度使用 K，导热率 W/(m·K)，比热 J/(kg·K)，密度取 `fluid.rho`。此处仅演示字段，数值需要配合实际单位、尺度与热扩散率。

设置固体导热时，在 `physics.thermal.materials` 定义各材料，再由每个 `geometry[].material` 引用材料 ID。材料可以有自己的密度、比热、导热率、初温和 `heat_source`。流固界面为理想热接触；热源是固体体积发热率，SI 为 W/m³。

### 7.2 直接运行六个热示例

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$buildName = 'checkpoint-v2.1.0-dev'
$deviceId = 0
$files = @('thermal-diffusion-lattice.json', 'thermal-multilayer-conduction-lattice.json',
           'thermal-boundaries-lattice.json', 'conjugate-heated-cube-lattice.json',
           'thermal-natural-convection-cavity-lattice.json',
           'thermal-natural-convection-conductive-wall-lattice.json')
foreach ($file in $files) {
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\src\scripts\run-nuc.ps1" `
    -WorkspaceRoot $root -BuildName $buildName -DeviceId $deviceId `
    -CaseName ('manual-' + [IO.Path]::GetFileNameWithoutExtension($file)) `
    -ConfigPath "$root\src\configs\$file" -TimeoutSeconds 1800
  if ($LASTEXITCODE -ne 0) { throw "Thermal example failed: $file" }
}
```

| 配置 | 功能与启用位置 | 观察与检查 |
|---|---|---|
| `thermal-diffusion-lattice.json` | `physics.thermal`、局部初温覆盖 | 温度从局部热区扩散；原示例只有 20 步 |
| `thermal-multilayer-conduction-lattice.json` | 多材料及热边界，40000 步 | 分段温度梯度、材料界面热流连续性 |
| `thermal-boundaries-lattice.json` | `boundaries[].thermal` | 恒温侧、对流侧和绝热侧；原示例 40 步 |
| `conjugate-heated-cube-lattice.json` | 固体材料、体积热源、流动 | `T`、`material`、固体加热及向流体传热；原示例 40 步 |
| `thermal-natural-convection-cavity-lattice.json` | 重力+正 `thermal_expansion`+冷热壁 | 温差驱动环流和温度场；原示例 30000 步 |
| `thermal-natural-convection-conductive-wall-lattice.json` | 自然对流+导热固壁 | 固壁内部与流体中的连续温度变化 |

运行后除常规完成记录外，查看 `T-*.vtk`、`material-*.vtk`（配置选中时）和 `conservation-budget.csv`。成功推进到目标步数只是运行检查，定量误差按 7.5 节测试。

### 7.3 强制对流、自然对流与湍流热输运

- **强制对流**：热模型已开启，设置初始/边界速度或体积驱动力，使流体携带温度。正式平滑强制对流例由 `test-v2-physics.py` 生成。
- **自然对流**：在热模型里给正 `thermal_expansion`，顶层 `physics.gravity` 给加速度向量，边界/初场提供温差。浮力使用 Boussinesq 近似；`thermal_expansion=0` 没有温差浮力。
- **Smagorinsky 热输运**：选择 `solver.turbulence="smagorinsky"`；热对象的 `turbulent_prandtl` 缺省为 0.9。关闭亚格子模型时该数值不会自动创造湍流。

`resolved-config.json` 的 `thermal` 记录实际格子扩散率、材料换算和热子步。热更新采用显式守恒输运并自动选取偶数热子步；很大的材料扩散率对比可能使子步超限。常物性与 Boussinesq 的适用条件需由具体算例判断。

### 7.4 四种热边界、热源和随体初温

以下对象放在某个非周期流动边界的 `thermal` 字段里：

| 热条件 | 完整 `thermal` 对象 | 单位与方向 |
|---|---|---|
| 绝热 | `{"type":"adiabatic"}` | 零法向热流；缺省行为 |
| 恒温 | `{"type":"fixed_temperature","temperature":310}` | SI 为 K |
| 指定热流 | `{"type":"heat_flux","heat_flux":100}` | SI 为 W/m²，正值表示进入计算域；仅固壁 |
| 外界对流 | `{"type":"convection","ambient_temperature":300,"heat_transfer_coefficient":10}` | SI 为 K、W/(m²·K)；仅固壁 |

`periodic` 不能同时设置热边界。设置热条件不会代替流动边界的 `type`、面、密度/速度等字段。

固体源示例可查看 `conjugate-heated-cube-lattice.json` 的 `materials[].heat_source`。固体局部初温用 `geometry[].thermal_regions`，坐标为相对初始运动枢轴的物体局部坐标。它定义初始分布；持续加热使用材料热源。

指定热流和独立固体热源的定量验证配置由 `test-v2-scenarios.py` 生成，分别位于报告目录的 `thermal-known-heat-flux/case.json`、`thermal-known-solid-source/case.json`。执行 7.5 节后可直接复用这些完整输入，无需从片段拼装。

### 7.5 如何执行热模型的精度验证

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$buildName = 'checkpoint-v2.1.0-dev'
$env:PYTHONIOENCODING = 'utf-8'
python "$root\src\scripts\test-v2-physics.py" --workspace-root $root `
  --build-name $buildName --device 0
if ($LASTEXITCODE -ne 0) { throw 'Physical accuracy suite failed.' }
python "$root\src\scripts\test-v2-scenarios.py" --workspace-root $root `
  --build-name $buildName --device 0
if ($LASTEXITCODE -ne 0) { throw 'Scenario suite failed.' }
```

两套同时含自由液面和运动场景，当前没有 `--case` 或 `--thermal-only` 过滤参数。报告分别在 `workingdir/v2-physics/<时间戳>/report.json`、`workingdir/v2-scenarios/<时间戳>/report.json`，各子目录留存实际 `case.json`、stdout/stderr 和 results。

| 验证对象 | 固定判据（当前测试源码） |
|---|---|
| 平滑周期热扩散 | 相对 L2 ≤ 2%，范数以温度扰动为参考 |
| 平滑强制对流 | 相对 L2 ≤ 3%，同时比较扩散衰减与相位移动 |
| 多层导热 | 界面热流相对误差 ≤ 3% |
| 自然对流 Ra=1000 | 平均 Nu 相对参考 1.118 的误差 ≤ 5%；测试生成 34×34×4、50000 步输入 |
| 随体温度闭环 | 相对静止参考的温度扰动 L2 ≤ 2% |
| 显热收支 | 按脚本定义的初始能量/累计输入归一化，残差比例 ≤ 0.5% |
| 已知热流、固体热源 | 场景套件中的相对累计输入误差 ≤ `1e-5` |

这些阈值绑定测试里的网格、参数、时间和范数。直接运行仓库短示例不会自动执行同一对照。要复跑某个生成输入，例如指定热流：

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$latest = Get-ChildItem "$root\workingdir\v2-scenarios" -Directory |
  Sort-Object Name | Select-Object -Last 1 -ExpandProperty FullName
$config = "$latest\thermal-known-heat-flux\case.json"
if (-not (Test-Path $config)) { throw 'Run the scenario suite first.' }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\src\scripts\run-nuc.ps1" `
  -WorkspaceRoot $root -BuildName checkpoint-v2.1.0-dev -DeviceId 0 `
  -CaseName manual-known-heat-flux -ConfigPath $config -TimeoutSeconds 1800
if ($LASTEXITCODE -ne 0) { throw 'Heat-flux rerun failed.' }
```

该重跑生成新的结果；对照量的自动计算仍由原验证套件完成。

<a id="free-surface"></a>
## 8. 单液相自由液面

### 8.1 如何开启并定义初始液体

提供 `physics.free_surface`，显式选择 FP32，再给初始液体区域或液体入口。下面是合入完整配置的字段片段：

```json
{
  "solver": {"storage":"FP32", "turbulence":"none"},
  "physics": {
    "gravity":[0,0,-0.0001],
    "free_surface":{"surface_tension":0.0001, "environment_pressure":0}
  },
  "initial": {
    "velocity":[0,0,0],
    "liquid_regions":[{"shape":"box", "box_min":[1,1,1], "box_max":[30.999,10.999,10.999]}]
  },
  "output": {"vtk_fields":["phi","u","rho","flags"], "vtk_every":100, "initial":true}
}
```

该片段使用格子量，域需容纳所列液体盒。`phi` 是液体填充率；空区、界面和液体由初始化构造。初始液体区域还可用球（`shape="sphere"`、`center`、`radius`）或封闭二进制 STL（`shape="stl"`、`file`、`transform`），可选 `fill` 为 `(0,1]`；多个区域取最大填充率。

提供 `physics.free_surface` 即启用；只在输出里加 `phi` 不会启用物理模块。该模型求液体，气体为指定环境压强，不适用于需要气相惯性或密闭气体压缩的解释。

### 8.2 静水、液滴与接触角算例

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$buildName = 'checkpoint-v2.1.0-dev'
$deviceId = 0
$files = @('free-surface-hydrostatic-lattice.json', 'free-surface-static-droplet-lattice.json',
           'free-surface-contact-angle-60-lattice.json', 'free-surface-contact-angle-90-lattice.json',
           'free-surface-contact-angle-120-lattice.json')
foreach ($file in $files) {
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\src\scripts\run-nuc.ps1" `
    -WorkspaceRoot $root -BuildName $buildName -DeviceId $deviceId `
    -CaseName ('manual-' + [IO.Path]::GetFileNameWithoutExtension($file)) `
    -ConfigPath "$root\src\configs\$file" -TimeoutSeconds 1800
  if ($LASTEXITCODE -ne 0) { throw "Free-surface example failed: $file" }
}
```

| 算例 | 修改与观察 |
|---|---|
| 静水 `hydrostatic` | 重力与液柱高度决定静水压差；查看 rho/p、液体质量和界面 |
| 静滴 `static-droplet` | 表面张力和球形初始液体；查看界面形状及 Laplace 压差 |
| 60°/90°/120° | 在域固壁的 `contact_angle` 或对应 STL 的 `contact_angle` 中设固定角；比较最终润湿形态 |

接触角单位是度，严格在 `(0,180)`，缺省 90；它是固定静态角，不含动态角和前进/后退角滞后。表面张力 SI 为 N/m；格子值上限为 0.1。定量拟合由物理套件执行，目测液滴外形不能代替角度误差判据。

### 8.3 晃荡、溃坝、充排液和 STL 液体区域

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$buildName = 'checkpoint-v2.1.0-dev'
$deviceId = 0
$files = @('free-surface-sloshing-lattice.json', 'free-surface-dam-break-lattice.json',
           'free-surface-fill-drain-lattice.json', 'free-surface-stl-mask-lattice.json',
           'free-surface-marin-dam-break-si.json')
foreach ($file in $files) {
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\src\scripts\run-nuc.ps1" `
    -WorkspaceRoot $root -BuildName $buildName -DeviceId $deviceId `
    -CaseName ('manual-' + [IO.Path]::GetFileNameWithoutExtension($file)) `
    -ConfigPath "$root\src\configs\$file" -TimeoutSeconds 1800
  if ($LASTEXITCODE -ne 0) { throw "Free-surface scenario failed: $file" }
}
```

| 配置 | 功能、资源和检查 |
|---|---|
| `free-surface-sloshing-lattice.json` | 初始扰动液面后晃荡；液位探针曲线，主频与衰减；3000 步 |
| `free-surface-dam-break-lattice.json` | 初始液柱向空区流动；原始示例只有 20 步，用于功能短算 |
| `free-surface-fill-drain-lattice.json` | `liquid_inlet` 与 `open_outlet`；检查边界通量和域内质量变化 |
| `free-surface-stl-mask-lattice.json` | 初始液体由内置 `assets/` STL 划定，且启用热；保留相对资产目录 |
| `free-surface-marin-dam-break-si.json` | SI 的 MARIN/SPHERIC 溃坝障碍物，使用内置障碍 STL、参考液位表；计算 3 s，检查固定测点 |

充排液边界必须给 `type`、`faces`、`rho`、`velocity`，需要时再给热条件。例如格子模式液体入口的字段片段：

```json
{"id":"inlet", "faces":["xmin"], "type":"liquid_inlet", "rho":1.0, "velocity":[0.01,0,0]}
```

液体入口保持入口格点充满。`open_outlet` 也需要显式密度与速度；它是当前自由液面实现的开口条件，不等于对任意单相流通用的压力出口。热充排液时补充入口/出口温度，计算离散显热焓流。

液位探针通过 `analysis.surface_levels=[{"id":"H1","position":[x,y]}]` 开启。沿 z 柱输出积分液高 `liquid_height` 与最上方液体高程 `top_elevation`；具体坐标换成域内位置。探针处液面破碎时，两种高度的物理意义不同。

### 8.4 应该查看哪些文件

- `phi-*.vtk`：在 ParaView 用 `phi=0.5` 等值面查看自由液面；这是填充率可视化，精确质量从 CSV 判断。
- `free-surface.csv`：液体质量、体积、质心、液面范围等；带 `_lattice` 的列维持格子单位。
- `surface-levels.csv`：有液位探针时创建，按探针 ID 分组看随时间曲线。
- `boundary-flux.csv`：存在自由液面开口时的质量/显热焓流；**向外为正，入口通常为负**。
- `conservation-budget.csv`：`mass_current - mass_initial + cumulative_mass_outward` 为质量残差。开放问题应与累计通量比较，不能要求域内质量恒定。

### 8.5 如何验证结果

按 7.5 节执行 `test-v2-physics.py` 和 `test-v2-scenarios.py`；以下是当前源码中的量化检查：

| 检查 | 当前判据 |
|---|---|
| 静水压差、静滴压差 | 当前物理脚本共用 `laplace_pressure_relative=0.05` 的相对误差门槛 |
| 固定接触角 | 拟合角度绝对误差 ≤ 5° |
| 小振幅晃荡 | 主频相对误差 ≤ 3% |
| 闭合液体质量 | 相对初始质量的残差 ≤ 0.1% |
| MARIN 液位 | 固定测点/时间窗的 RMSE 除以初始液深 ≤ 0.20 |
| MARIN 到达时间 | 固定定义下误差 ≤ 0.15 s |
| 已知充排液流量 | 场景脚本累计通量相对误差 ≤ `1e-5` |

历史 V2.0.0 验收表中静水单项记录的门槛为 2%；本手册列的是当前 `test-v2-physics.py` 实际使用的共用 5% 判据，未改测试阈值。测试报告记录本次实测误差，历史报告不覆盖新运行。

MARIN 的参考来源、测点、归一化与原始数据哈希见 [configs/reference/README.md](../configs/reference/README.md)。测试脚本会固定相应窗口；不把这一专项结论扩展为任意尺度或任意测点的精度保证。

<a id="motion"></a>
## 9. 动态 STL 与多物理组合

### 9.1 如何开启规定运动

在某个 `geometry` 对象内提供 `motion`，选择 FP32；`transform` 定义初始模型，`motion` 定义随时间的位姿。以下片段加入该对象内：

```json
{"motion":{"translation":{"type":"constant_velocity", "velocity":[0.03,0,0], "start_time":0, "stop_time":40}}}
```

这是格子速度和步数，表示前 40 步平移、之后保持位置。给平移定律 `sinusoidal` 时提供三元 `amplitude`、正 `period`；给旋转定律时提供非零 `axis`，匀速为 `angular_velocity_degrees`，正弦为 `amplitude_degrees`+`period`。角度单位为度，SI 时间为 s、速度为 m/s，格子时间为 step。

平移与旋转定律可同时存在；`trajectory` 时间表与二者互斥。`motion.pivot` 是目标世界坐标的枢轴，`transform.pivot` 则是源 STL 坐标的变换参考点，两者不同。

### 9.2 平移、旋转、多体和轨迹算例

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$buildName = 'checkpoint-v2.1.0-dev'
$deviceId = 0
$files = @('dynamic-translation-stop-lattice.json', 'dynamic-rotation-lattice.json',
           'dynamic-sinusoidal-multi-lattice.json', 'dynamic-trajectory-lattice.json',
           'dynamic-thermal-cycle-lattice.json', 'dynamic-water-entry-lattice.json')
foreach ($file in $files) {
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\src\scripts\run-nuc.ps1" `
    -WorkspaceRoot $root -BuildName $buildName -DeviceId $deviceId `
    -CaseName ('manual-' + [IO.Path]::GetFileNameWithoutExtension($file)) `
    -ConfigPath "$root\src\configs\$file" -TimeoutSeconds 1800
  if ($LASTEXITCODE -ne 0) { throw "Dynamic example failed: $file" }
}
```

| 配置 | 应该观察与验证的内容 |
|---|---|
| `dynamic-translation-stop-lattice.json` | 单物体以 0.03 cell/step 平移，40 步停止；60 步终态位移 x=1.2 cells |
| `dynamic-rotation-lattice.json` | 定轴转动；检查角度、枢轴与角速度，而不是仅看包围盒 |
| `dynamic-sinusoidal-multi-lattice.json` | 多对象、正弦平移、组合旋转；对象 ID 分别保持，位姿遵循各自定律 |
| `dynamic-trajectory-lattice.json` | 关键帧时间严格递增，首帧为 0；区间线性插值、末帧后保持 |
| `dynamic-thermal-cycle-lattice.json` | 运动固体保留非均匀温度历史，600 步闭环；与静止参考温度比较 |
| `dynamic-water-entry-lattice.json` | 规定运动入水；液面扰动、非零动态受力、质量收支 |

`object-*.vtk` 用对象编号查看运动几何，`object-motion.csv` 给位移、枢轴、轴角、线/角速度、力/力矩，热模型还含温度范围和显热。该 CSV 的位移、速度、力、力矩列名带 `_lattice`，即使 SI 输入也仍为格子值；温度按当前温度单位。

规定运动的最大表面速度限制为 0.05 cell/step，转动还要考虑距枢轴最远处的速度。程序保持对象目标体素数；对象必须始终位于域内，不能相互穿透、碰撞或与其他固体接触。运动越界或体素约束失败会中止。

### 9.3 两两和三项组合怎样开启

热、自由液面与运动均按前述字段启用；组合时同时提供这些对象，并满足全部依赖：

| 组合 | 入口配置 | 依赖与输出 |
|---|---|---|
| 热+自由液面 | `thermal-free-surface-smoke.json` | FP32、thermal、free_surface、初始液体；T、phi、显热和质量 |
| 热+运动 | `dynamic-thermal-cycle-lattice.json` | FP32、thermal、每个 STL 的 material、motion；材料坐标热历史 |
| 自由液面+运动 | `dynamic-water-entry-lattice.json` | FP32、free_surface、液体区域、motion；phi、object、诊断受力 |
| 热+自由液面+运动 | `thermal-free-surface-dynamic-cycle-lattice.json` | 全部字段；闭合容器质量与显热收支 |
| 三项组合+充排液 | `thermal-free-surface-dynamic-fill-drain-lattice.json` | 再加液体入口/出口与热边界；离散质量流、焓流和热源累计 |

运行尚未在 9.2 节执行的三个组合配置：

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$buildName = 'checkpoint-v2.1.0-dev'
$files = @('thermal-free-surface-smoke.json', 'thermal-free-surface-dynamic-cycle-lattice.json',
           'thermal-free-surface-dynamic-fill-drain-lattice.json')
foreach ($file in $files) {
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\src\scripts\run-nuc.ps1" `
    -WorkspaceRoot $root -BuildName $buildName -DeviceId 0 `
    -CaseName ('manual-' + [IO.Path]::GetFileNameWithoutExtension($file)) `
    -ConfigPath "$root\src\configs\$file" -TimeoutSeconds 1800
  if ($LASTEXITCODE -ne 0) { throw "Combined example failed: $file" }
}
```

### 9.4 动态及组合功能的验证

`test-v2-scenarios.py` 对平移启停、旋转、时间表、多体运动按配置计算预期位姿，绝对误差门槛 `1e-9`；检查入水有非零动态受力，并核对综合容器的质量、显热、热源和边界通量。`test-v2-physics.py` 比较运动热历史闭环的温度误差。两者的命令见 7.5 节。

全部非空功能组合共有 7 类，与 8 种 FP32 流动模型组成 **56 项短算矩阵**。独立执行：

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$env:PYTHONIOENCODING = 'utf-8'
python "$root\src\scripts\test-v2.py" --workspace-root $root `
  --build-name checkpoint-v2.1.0-dev --device 0 --steps 8
if ($LASTEXITCODE -ne 0) { throw 'Feature/model matrix failed.' }
```

查看 `workingdir/v2-validation/<时间戳>/report.json` 的 56 行 `matrix`。此矩阵验证组合能运行、输出有限及完成记录；物理误差仍以物理/场景套件为准。显热收支不包含机械功和黏性耗散，不能当作完整机械—热总能量。

<a id="restart"></a>
## 10. 断点续算（V2.1.0 开发版）

### 10.1 当前状态与使用边界

V2.0.0 正式 EXE 没有 `--restart`。使用 V2.1.0 开发版时，在 `run` 中加入 `checkpoint_every`（0/省略为禁用）和 `checkpoint_keep`（缺省 2，范围 1–1000）。正常计算完成时还保存终态检查点。

**已知缺陷 `TRIAL-20261015-01` 尚未修复**：将新目标缩短到检查点步数或此前接受的目标以下时，程序虽返回 5，仍可能改写原 `completion.json`、`effective-config.json`、`run.lock` 并新增重启配置。2026-10-15 试用的 CSV 与检查点本身未变。现有 45 项套件未覆盖全部元数据副作用，因此其通过不能证明这个契约已满足。不要在唯一的有效结果目录上尝试拒绝路径；测试使用完整副本。当前阶段仍未正式封版。

### 10.2 完整示例：先计算 2000 步，再延长到 4000 步

以下从无外部资产的 `checkpoint-resume-lattice.json` 开始。它每 500 步保存一次、保留 2 份；先正常结束再续算，比人工强杀更适合首次学习。

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$buildName = 'checkpoint-v2.1.0-dev'
$deviceId = 0
$caseName = 'manual-checkpoint'
$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$inputDir = "$root\workingdir\my-inputs\checkpoint-$stamp"
New-Item -ItemType Directory -Path $inputDir | Out-Null
Copy-Item "$root\src\configs\checkpoint-resume-lattice.json" "$inputDir\case-2000.json"

# 第一次正常计算。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\src\scripts\run-nuc.ps1" `
  -WorkspaceRoot $root -BuildName $buildName -CaseName $caseName `
  -ConfigPath "$inputDir\case-2000.json" -DeviceId $deviceId -TimeoutSeconds 900
if ($LASTEXITCODE -ne 0) { throw 'Initial checkpoint run failed.' }
$sourceRun = Get-ChildItem "$root\workingdir\$caseName" -Directory | Sort-Object Name | Select-Object -Last 1
$sourceRecord = Get-Content "$($sourceRun.FullName)\run.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$results = [string]$sourceRecord.paths.results
Get-ChildItem "$results\checkpoint" -Directory | Select-Object Name

# 仅修改白名单中的目标步数，保持 case.name、模型、资产、输出及采样不变。
$extended = Get-Content "$inputDir\case-2000.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$extended.run.steps = 4000
$extended | ConvertTo-Json -Depth 100 | Set-Content "$inputDir\case-4000.json" -Encoding UTF8

# 重启入口按原 RunId 定位；结果续写原 results。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\src\scripts\run-nuc.ps1" `
  -WorkspaceRoot $root -BuildName $buildName -CaseName $caseName `
  -ConfigPath "$inputDir\case-4000.json" -DeviceId $deviceId `
  -RestartFromRunId $sourceRun.Name -TimeoutSeconds 900
if ($LASTEXITCODE -ne 0) { throw 'Restart failed; inspect the new run record.' }

$restartRun = Get-ChildItem "$root\workingdir\$caseName" -Directory | Sort-Object Name | Select-Object -Last 1
$restartRecord = Get-Content "$($restartRun.FullName)\run.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$restartResults = [string]$restartRecord.paths.results
$done = Get-Content "$restartResults\completion.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$restartRecord | Select-Object status, restart, paths
$done | Select-Object status, steps, requested_steps, restarted_from_step, restarts
Import-Csv "$restartResults\monitor.csv" | Select-Object -Last 5
```

通过条件：新外层记录成功，内层 `steps=requested_steps=4000`，来源步为 2000，重启链新增一项。两次 `paths.results` 指向同一原目录，最新外层 RunId 只有自己的日志和 EXE 快照，**不能假定最新外层目录下一定有 results 子目录**。

### 10.3 从意外中断恢复

保存的检查点是保存时刻状态，不是任意强杀时刻。恢复后从最新有效保存步重新推进，CSV 会回到对应字节位置再续写，超出检查点的 VTK 会按记录清理。

1. 确认原求解进程已经结束，原 results 内有 `original-config.json`、`inputs/`、`checkpoint/`。
2. 使用原配置或仅单调增大目标的配置，保持资产不变。
3. 使用相同 CaseName 和原 RunId，执行与 10.2 节相同的 `-RestartFromRunId` 命令。
4. 检查来源检查点、警告、完成步数及重启链；不要只检查新外层日志文件是否存在。

如需主动中断自己的测试，第二个 PowerShell 终端中先查看**该次** `run.json.processId`，用 `Get-CimInstance Win32_Process -Filter "ProcessId=<具体编号>"` 核对 `ExecutablePath` 与 `run.json.command.executable` 一致，再对这个 PID 执行 `Stop-Process -Id <具体编号>`。不要按所有 `Solver-IBM` 进程名批量结束。检查点保存后再中断，才能实际验证恢复。

完整的真实强杀与字节等价测试已包含在 `test-checkpoint.py` 中；第 13 章给出标准入口。关闭 SSH 终端不等同于一个经过核验的中断/恢复流程，长任务应保留运行入口和日志。

### 10.4 直接 EXE 与脚本恢复的区别

直接调用示例，须把原 results 路径与配置替换为自己的实际位置：

```text
Solver-IBM.exe --config <原配置或合法延长配置> --device 0 --output <原results目录> --restart
```

它直接续写 results，没有新的外层运行归档。标准脚本入口是 10.2 节的 `run-nuc.ps1 -RestartFromRunId`，推荐日常使用。包运行包装器源码已加入参数透传，但现有 V2.0.0 固定包并不包含该功能；当前没有可用的正式 V2.1.0 包，不能对 V2.0.0 包照搬此参数。

### 10.5 可以改变什么，不能改变什么

| 情况 | 当前契约 |
|---|---|
| 增大 `run.steps` 或 `run.duration` | 允许；解析后的目标步数不能小于检查点步数和已接受目标 |
| `steps` 改成 `duration`，或反向 | 不允许，即使换算出的目标相同 |
| 改 `checkpoint_every`、`checkpoint_keep` | 允许，其他字段仍按原配置 |
| 改模型、精度、网格、物性、边界、输出、分析调度或运动 | 不允许；作为新算例计算 |
| 改 STL 内容 | 哈希变化拒绝；仅把原文件移走时可按封存资产快照回退 |
| 换产品版本、发布状态或数值内核身份 | 拒绝，不支持跨产品版本检查点迁移 |
| 同源码重建、EXE 哈希改变 | 身份检查允许并警告；同设备逐位一致的保证仍绑定相同运行环境/构建 |
| 原目标已完成，恢复到同一目标 | finish-only 收尾，不再推进时间步 |
| 换设备 | 可尝试兼容加载，不承诺跨设备逐位一致；保留设备与驱动记录 |

`case.name`、采样起点/间隔和 VTK 设置也属于受保护配置。为了“多存一些输出”而修改这些字段，不能直接沿用原检查点。

### 10.6 保留、损坏回退、锁和磁盘

```text
results/
├── checkpoint/
│   ├── latest.json               提示指针，加载时仍校验候选
│   └── step-<补齐的步号>/         已提交检查点
│       ├── checkpoint.json       格式、身份、场清单、SHA256
│       ├── host-state.json       统计、输出位置、预算和运动热历史记录
│       └── *.bin                 分布函数及各物理模块状态
├── quarantine/                   结构损坏候选的隔离目录（出现损坏时）
├── run.lock                      单写者保护文件
└── inputs/restart-configs/       实际使用过的恢复配置
```

磁盘上可能有临时目录；未完成提交的临时目录不当作有效检查点。加载按新到旧验证完整候选，结构损坏隔离后尝试次新；版本/身份/配置不兼容则直接拒绝，不靠旧候选规避契约。活动进程持有锁时禁止并发写；进程已死的残留锁由恢复入口处理，不要手动删掉活动锁。

单份检查点包含分布函数、宏观场、力场及各启用模块状态，通常接近一份完整数值状态的大小；运动热历史另计。保留策略提交时峰值约为 `(keep+1)×单份大小`，隔离目录和 VTK/CSV 另外占空间；程序预检不是整个运行期磁盘容量保证。可以实测每份大小：

```powershell
# 将 $results 设为自己的实际结果目录后执行。
Get-ChildItem "$results\checkpoint" -Directory | Where-Object Name -Like 'step-*' | ForEach-Object {
  $size = (Get-ChildItem $_.FullName -Recurse -File | Measure-Object Length -Sum).Sum
  [pscustomobject]@{Checkpoint=$_.Name; MiB=[math]::Round($size/1MB, 2)}
}
```

同机、同 GPU、驱动与构建下，当前等价性测试逐字节比较数值状态和输出；更换环境的保证范围见 [冻结判据](validation/checkpoint-tolerance-thresholds.md)。阶段故障注入覆盖进程崩溃窗口，未做真实硬件断电试验。

### 10.7 退出码与恢复验证

| EXE 退出码 | 含义与处理 |
|---|---|
| 0 | 完成；也可能包含损坏回退的警告，仍需读 stderr/来源记录 |
| 1 | 一般配置、运行或锁错误 |
| 3 | 无可用检查点，检查损坏/隔离记录 |
| 4 | 保存失败，运行中止；旧有效检查点保留 |
| 5 | 身份或配置契约拒绝；当前缩短目标路径存在 10.1 节副作用 |

运行包装器自己的进程退出码不保证等于内部 EXE 的专用码；包装器会把失败写入 `run.json.failureReason`，内部码见 `run.json.exitCode` 与日志。

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$env:PYTHONIOENCODING = 'utf-8'
python "$root\src\scripts\test-checkpoint.py" --workspace-root $root `
  --build-name checkpoint-v2.1.0-dev --device 0 `
  --baseline-executable "$root\package\V2.0.0\bin\Solver-IBM.exe"
if ($LASTEXITCODE -ne 0) { throw 'Checkpoint suite failed.' }
```

带基线参数时当前为 45 项，含全模块恢复、强杀、保留、锁、故障注入、损坏回退与禁用路径基线对照。报告在 `workingdir/checkpoint-validation/<时间戳>/report.json`。套件通过后仍须保留当前已知问题记录，不据此宣布正式验收完成。

<a id="study"></a>
## 11. 参数扫描与批量计算

### 11.1 三个现成扫描入口

| 扫描规格 | 基础算例 | 组合数量与参数 |
|---|---|---|
| `study-periodic.json` | `probes-periodic.json` | 2 个黏度 × 2 个初始 x 速度 = 4 |
| `study-storage.json` | `probes-periodic.json` | FP16S/FP32 = 2 |
| `study-models.json` | `models-study-base.json` | Q × collision × turbulence × storage = 16 |

扫描规格与求解器算例是两种 JSON。将规格交给 `parameter-study.py generate`；生成的单个 `configs/00000.json` 才是可以传给 EXE 的算例。

### 11.2 生成并执行一次完整扫描

以下可独立执行。把 `$specName` 改为表中另一个文件即可运行其他扫描；每次生成用新目录。

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$buildName = 'checkpoint-v2.1.0-dev'
$deviceId = 0
$specName = 'study-models.json'
$env:PYTHONIOENCODING = 'utf-8'
$stamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$study = "$root\workingdir\manual-study-$stamp"
python "$root\src\scripts\parameter-study.py" generate `
  --spec "$root\src\configs\$specName" --output $study
if ($LASTEXITCODE -ne 0) { throw 'Study generation failed.' }
python "$root\src\scripts\parameter-study.py" run --study $study `
  --workspace-root $root --build-name $buildName --device $deviceId --timeout 900
if ($LASTEXITCODE -ne 0) { throw 'Inspect failed rows in the study summary.' }
$summaryDir = Get-ChildItem "$study\runs" -Directory | Sort-Object Name |
  Select-Object -Last 1 -ExpandProperty FullName
Import-Csv "$summaryDir\summary.csv" | Format-Table id, status, steps, elapsed_seconds, results
```

每个组合串行通过 `run-nuc.ps1` 启动，结果在 `workingdir/study-.../<RunId>/`；扫描目录的 `summary.json`/`summary.csv` 给出真实运行路径。某项失败后继续其余组合，最后有失败则整体非零退出。重复 `run` 会全部重新执行，当前没有自动跳过已成功项的选项。

### 11.3 编写自己的扫描规格

下面的完整规格与 `models-study-base.json` 位于同一目录时可生成 4 个组合：

```json
{
  "schema_version":1,
  "base_config":"models-study-base.json",
  "parameters":[
    {"path":"/fluid/nu", "values":[0.02,0.04]},
    {"path":"/initial/velocity/0", "values":[0.02,0.03]}
  ]
}
```

`base_config` 相对规格所在目录解析；`parameters[].path` 使用 JSON Pointer，必须指向基础 JSON **已经存在的字段**，不能凭求解器有默认值就省略。`/geometry/0/transform/degrees` 可扫描首个物体初始角；数组索引从 0 开始，`~1` 表示 `/`、`~0` 表示 `~`。

组合总数最多 10000。路径不能重复/父子重叠，不能扫描 schema_version、整个几何对象或几何 file/id。生成器复制 `geometry` STL 并封存哈希，生成后不要手改快照；调整输入后重新 generate 到新目录。当前生成器只显式搬运 `geometry[].file`，使用 `initial.liquid_regions[].shape="stl"` 的自定义扫描需额外保留该资产的可解析位置，不能假定它也已自包含。

同时扫描 SRT/TRT 与 Λ 时，SRT+Λ 组合会非法；默认 16 模型基础配置省略 Cs/Λ，因此各组合都可解析。生成步骤不会替代求解器的合法性判断。

### 11.4 验证扫描工具与用正式包扫描

`test-parameter-study.py` 验证快照、资产缺失后的独立运行、路径错误和篡改拒绝；标准命令见第 13 章。16 模型扫描通过表示生成和执行链路正常，物理精度仍看相应数值基准。

使用 V2.0.0 包内规格时，generate 的 `--spec` 指向 `$package\cases\configs\study-models.json`，run 加 `--executable "$package\bin\Solver-IBM.exe"`，仍显式给 `--build-name solver-ibm-v2.0.0`。生成与结果目录均在包外。

<a id="postprocessing"></a>
## 12. 结果查看与后处理

### 12.1 先找到本次真正的结果目录

下面以 `manual-poiseuille` 为例，换成实际 CaseName 即可。恢复计算也始终从记录中的 `paths.results` 找结果。

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$caseName = 'manual-poiseuille'
$runDir = Get-ChildItem "$root\workingdir\$caseName" -Directory | Sort-Object Name |
  Select-Object -Last 1 -ExpandProperty FullName
$record = Get-Content "$runDir\run.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$results = [string]$record.paths.results
$record | Select-Object runId, status, exitCode, failureReason, paths
Get-Content "$results\completion.json" -Raw -Encoding UTF8
Get-Content "$runDir\logs\stderr.log"
Import-Csv "$results\monitor.csv" | Select-Object -Last 5
```

| 文件 | 应如何使用 |
|---|---|
| 外层 `run.json` | 本次命令、EXE 身份、设备请求、PID、实际结果路径、超时和退出信息 |
| 外层 `build.json` | 本次所用构建身份快照 |
| `original-config.json` | 原始输入字节，追溯输入 |
| `effective-config.json` | STL 指向封存资产的有效输入；可配合 inputs/assets 复用 |
| `resolved-config.json` | 实际模型、网格、单位换算、内存、设备、覆盖和采样落点；用于检查而非直接输入 |
| `manifest.json` | 配置、STL、EXE 的来源 SHA256；不同于正式包根目录同名清单 |
| `completion.json` | 求解器完成/失败状态、请求及实际步数、重启链 |
| `status.txt` | 简短运行摘要 |
| `logs/stdout.log`、`stderr.log`、`runner.log` | 输出、诊断和包装器记录；读相应外层 RunId 下的日志 |

运行脚本会保留 `bin/_runs/<CaseName>/<RunId>/` 的 EXE 副本，其 export junction 映射到结果目录。归档时保存 EXE/build.json、完整输入快照及需要的 CSV/VTK；仅复制一张结果图片不足以复现。

### 12.2 各输出字段、调度和单位

| VTK 字段 | 含义 | 单位与模块条件 |
|---|---|---|
| `u` | 三分量速度 | 当前单位，SI 为 m/s |
| `rho` | 密度 | 当前单位，SI 为 kg/m³ |
| `p` | 相对 `fluid.rho` 的表压 | SI 为 Pa；需在 vtk_fields 中选择 |
| `flags` | 单元位标记 | 无量纲，TYPE_S 位表示固体；其他非零位不全是固体 |
| `T` | 温度 | 热模型，SI 为 K |
| `material` | 热材料编号 | 热模型，0 为流体材料 |
| `object` | 运动对象编号 | 动态几何，按记录映射对象 |
| `phi` | 液体填充率 | 自由液面，无量纲 |

VTK 为 legacy binary `STRUCTURED_POINTS`、`POINT_DATA`；坐标对应求解格点中心，网格间距已按单位换算。每个字段独立成一组文件，例如 `u-000000100.vtk`。`vtk_every=0` 保留最终帧，加上可选初始帧；正常完成总写最终帧。预处理总写第 0 步 flags。

| CSV | 内容及单位 |
|---|---|
| `monitor.csv` | step、time、非固体格点数、质量/密度/最大速度；`_lattice` 列维持格子值，time 为当前时间单位 |
| `probes.csv` | id、实际坐标、rho、ux/uy/uz、speed、p；SI 为 m、kg/m³、m/s、Pa |
| `analysis.csv` | 非固体全域质量、平均速度/密度/压力、动能；SI 为 kg、m/s、kg/m³、Pa、J |
| `forces.csv` | 受力组 fx/fy/fz，流体作用于固体；SI 为 N |
| `free-surface.csv` | 质量、体积、质心、液面范围、干湿面积；列名为格子量 |
| `surface-levels.csv` | id、x/y、liquid_height、top_elevation；当前长度单位 |
| `boundary-flux.csv` | 向外质量流、热模型下的显热焓流；`_lattice` 列为格子量 |
| `conservation-budget.csv` | 初始/当前质量和显热、累计流出/热输入、残差；列名为格子量 |
| `object-motion.csv` | 每个对象姿态、线/角速度、力/力矩、固体温度与显热；按列名解释单位 |

`statistics.json` 给全域、探针和受力的样本数、平均、总体标准差。它是选定量的时间统计，当前不自动生成每格点时均 VTK 场。

### 12.3 在 ParaView 打开速度和温度

ParaView 可在 Windows 直接打开结果，也可将所需结果复制到 Mac 后打开。下载和安装从 [ParaView 官方网站](https://www.paraview.org/download/) 进行，选择本机系统对应版本。本手册不依赖专用 Solver-IBM 插件。

1. `File → Open`，进入实际 results，选择按编号成组的 `u-*.vtk`，然后 `Apply`。若只需终态，展开分组选择最终步文件。
2. 在着色数组中选择 `u`，分量选 `Magnitude`；查看分量时改选 X/Y/Z。使用色标重置功能适配当前数据范围。
3. 用 `Slice` 查看通道截面，按流向与剖面方向调整切面；几何范围在数据的信息面板中核对。
4. 温度同理，打开 `T-*.vtk`，按 `T` 着色；压力打开 `p-*.vtk`。各字段是独立 reader，需要分别加载。
5. 文件序列用时间播放控件逐帧查看。只有初始/最终两帧时只能播放这两帧，不能还原未保存的中间过程。

文件分组、reader 和 Apply 操作参考 [ParaView 数据加载指南](https://docs.paraview.org/en/latest/UsersGuide/dataIngestion.html)；着色和视图操作参考 [显示指南](https://docs.paraview.org/en/latest/UsersGuide/displayingData.html)。

### 12.4 自由液面、物体与实际时间

- 打开 `phi-*.vtk`，使用 `Contour`，选择 phi、等值 0.5，Apply；隐藏原体数据后观察液面。
- 打开 `object-*.vtk`，按对象编号着色，可用 Threshold 选择某个正编号对象。运动信息以 `resolved-config.json` 和 `object-motion.csv` 的编号/geometry_id 对应。
- 查看固体时不能把 flags 的“非零”全部选作固体。TYPE_S 是最低位；可以在 Calculator 中生成 `floor(flags)-2*floor(flags/2)`，再 Threshold 选值 1。
- 分别加载的多个字段若要组合运算，应确保同网格、同保存步，再用适合的合并数组操作；初学者先分别查看，避免把不同时间步叠加解释。

过滤器用途参考 [ParaView 过滤指南](https://docs.paraview.org/en/latest/UsersGuide/filteringData.html)。

编号表示**求解步号**。普通 VTK 序列在 ParaView 中可能按帧序号播放，显示时间不能直接当作秒；真实时间 `t=step*dt`，查 `resolved-config.json`。需要精确时间轴时可在结果副本中生成官方支持的 `.vtk.series` 文件，列出每个帧文件和物理时间。例如在已有 `$results` 下：

```powershell
# 在 12.1 节取得 $results 后执行；仅新增后处理元文件。
$resolved = Get-Content "$results\resolved-config.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$frames = @(Get-ChildItem "$results\phi-*.vtk" -File | Sort-Object Name | ForEach-Object {
  if ($_.BaseName -match '^phi-([0-9]+)$') {
    @{name=$_.Name; time=([double]$Matches[1] * [double]$resolved.dt)}
  }
})
if ($frames.Count -eq 0) { throw 'No phi frames; choose the output field you saved.' }
@{'file-series-version'='1.0'; files=$frames} | ConvertTo-Json -Depth 10 |
  Set-Content "$results\phi.vtk.series" -Encoding ASCII
```

先核对当前派生记录的单位字段；`.series` 属后处理文件，不参与求解器续算清单。恢复期间不要同时修改正在写入的结果。

### 12.5 查看探针、受力、液位和守恒曲线

快速检查不需要额外 Python 库：

```powershell
# $results 由 12.1 节取得；把 ID 改成实际配置里的值。
Import-Csv "$results\probes.csv" | Where-Object id -EQ 'center' | Select-Object time, ux, p
Import-Csv "$results\forces.csv" | Select-Object -Last 10
if (Test-Path "$results\surface-levels.csv") {
  Import-Csv "$results\surface-levels.csv" | Select-Object -Last 10
}
if (Test-Path "$results\conservation-budget.csv") {
  Import-Csv "$results\conservation-budget.csv" | Select-Object -Last 1
}
```

CSV 可用 ParaView 打开为表格，切到 Line Chart View，将 X 轴指定为 `time`，选择需显示的数值列。多探针/多对象 CSV 先按 id/geometry_id 筛选，防止把不同对象的行连成一条曲线；也可用表格软件完成相同操作。ParaView 视图行为见 [显示指南中的表格与图表说明](https://docs.paraview.org/en/latest/UsersGuide/displayingData.html)。

看质量残差时，对闭合液体以初始液体质量归一化；开口系统还要计累计向外通量。显热残差为“当前−初始+流出焓−热源输入−边界热输入”，归一化尺度按对应验证脚本，不能只看带单位残差数值大小。

### 12.6 导出和保存后处理工作

在 ParaView 保存 State 记录加载与过滤设置，保存 Screenshot/Animation 导出图片或动画；输入路径搬迁后按提示重新指定文件位置。动画的帧率是展示设置，实际物理时间仍由步号与 dt 决定。

复制结果到 Mac 时，可在 Windows 打包所需子集后，用已有文件传输方式下载到项目根之外/专门后处理目录；只查看 CSV/终态时无需搬走所有历史 VTK。保留配置、EXE 身份和必要参考输出，才能再次复现。

<a id="verification"></a>
## 13. 验证安装、功能和数值结果

### 13.1 分层检查，按需要执行

| 层次 | 命令/对象 | 能确认什么 |
|---|---|---|
| 配置检查 | `--validate` | 类型、必填、换算、边界覆盖、STL 文件/变换；不使用 GPU |
| 几何预处理 | `--prepare-only` | GPU 可初始化、体素、探针/受力归属和第 0 步输出 |
| 示例计算 | 运行某个 configs JSON | 对应输入完整推进、基本输出/记录存在 |
| 物理精度 | P2/P3、V2 physics/scenarios | 按固定网格、窗口、参考和范数计算误差 |
| 功能组合 | `test-v2.py` | 7 类功能 × 8 种 FP32 模型的短算兼容性 |
| 检查点协议 | `test-checkpoint.py` | 恢复等价、强杀、故障、锁、保留及基线；仍有 10.1 节覆盖缺口 |
| 正式包完整性 | 包内 `test-package.py` | 清单、身份、包装器、对应版本套件和包内容不变性 |

日常改 JSON 先做前三级；需要确认数值精度时做对应专项。完整九套适用于对当前开发构建进行系统回归，程序没改时不必每次重复全部测试。

### 13.2 九套验证入口与报告目录

以下路径均相对 `src/scripts/`；每次在外层 `workingdir/<报告目录>/<时间戳>/` 保存报告，不覆盖旧记录。

| 套件 | 脚本 | 报告目录 | 当前覆盖 |
|---|---|---|---|
| P1 | `test-config-runner.py` | `config-validation` | CLI、配置、单位、静态 STL/边界、Boeing/Ahmed，29 次调用 |
| P2 | `test-config-p2.py` | `p2-validation` | 采样、压力/受力、解析通道、SI、扫描，25 次调用/6 个剖面 |
| 存储 | `test-runtime-storage.py` | `storage-validation` | 两种存储、内存、历史 FP16/FP32 对照，14 次调用/5 组比较 |
| P3 | `test-config-p3.py` | `p3-validation` | 16 模型、96 剖面、剪切波、Cs/Λ、SI、回归和扫描 |
| 参数扫描 | `test-parameter-study.py` | `study-validation` | 9 项快照、资产、路径与篡改检查 |
| V2 物理 | `test-v2-physics.py` | `v2-physics` | 14 项热、自由液面及运动热历史基准 |
| V2 场景 | `test-v2-scenarios.py` | `v2-scenarios` | 13 项 MARIN、充排液、热源、规定运动和综合场景 |
| V2 矩阵 | `test-v2.py` | `v2-validation` | 56 项 FP32 功能/模型组合 |
| 检查点 | `test-checkpoint.py` | `checkpoint-validation` | 带冻结基线时 45 项 |

P1、存储和 P3 需要历史对照数据/EXE。本服务器可使用 `package/V2.0.0/tests/reference/`，含 boeing-baseline、fp16-reference、fp32-diagnostic-build、p2-build 等；保持历史名字和哈希。缺少参考文件应准备正确资源，不能删掉对照断言后宣称通过。

### 13.3 在当前开发构建上完整运行九套

**desktop-msi PowerShell**。这段代码是完整入口；已有对应专项报告时，可只保留需要的条目。

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$repo = "$root\src"
$buildName = 'checkpoint-v2.1.0-dev'
$deviceId = 0
$reference = "$root\package\V2.0.0\tests\reference"
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
$suites = @(
  @{File='test-config-runner.py'; Extra=@('--reference-root', $reference)},
  @{File='test-config-p2.py'; Extra=@()},
  @{File='test-runtime-storage.py'; Extra=@('--reference-root', $reference)},
  @{File='test-config-p3.py'; Extra=@('--reference-root', $reference)},
  @{File='test-parameter-study.py'; Extra=@()},
  @{File='test-v2-physics.py'; Extra=@()},
  @{File='test-v2-scenarios.py'; Extra=@()},
  @{File='test-v2.py'; Extra=@()},
  @{File='test-checkpoint.py'; Extra=@('--baseline-executable', "$root\package\V2.0.0\bin\Solver-IBM.exe")}
)
foreach ($suite in $suites) {
  $suiteArgs = @("$repo\scripts\$($suite.File)", '--workspace-root', $root,
    '--build-name', $buildName, '--repository-root', $repo,
    '--configs-root', "$repo\configs", '--device', [string]$deviceId) + $suite.Extra
  Write-Host "Running $($suite.File)"
  python @suiteArgs
  if ($LASTEXITCODE -ne 0) { throw "Suite failed: $($suite.File). Inspect its report and logs." }
}
```

脚本打印的报告目录优先于手动猜测。报告 `status` 应为 `succeeded`；负向用例的 EXE 非零退出是预期行为，由测试脚本断言，不要求每次内部调用都返回 0。

P3 的 FP32 通道应满足速度 L2/L∞ < 3%、受力误差 < 4%；FP16S 的 48 个通道剖面中存在 32 个不满足同一精度阈值，这是记录的精度边界，套件没有把它们当作 FP32 通过项。看 `profiles[].within_fp32_thresholds` 时先看 storage；不能把总体 suite succeeded 理解为所有存储下剖面都达到同一个阈值。

### 13.4 正式包验证与开发版验证分别执行

V2.0.0 正式包使用它自己保存的入口，跑对应的八套；不能把开发仓库的九套发布器当作该正式包的历史验收入口。

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$package = "$root\package\V2.0.0"
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
python "$package\test-package.py" --package-root $package --workspace-root $root --device 0
if ($LASTEXITCODE -ne 0) { throw 'Release package validation failed.' }
```

完整报告在 `workingdir/package-validation/<时间戳>/report.json`。仅做清单/身份/包装器检查时，包内入口支持 `--skip-suites`；该结果必须注明跳过数值套件，不能当作完成八套。输出、工作区均须在包外，包内程序和参考数据不被改写。

### 13.5 本手册本次核验记录

2026-10-20 在 desktop-msi（SEVERUS），OpenCL device 0 NVIDIA RTX 4070 Ti SUPER、驱动 610.88，Python 3.12.10，MSVC v142/14.29.30133、SDK 10.0.26100.0：

- 从干净提交 `2235d31` 独立构建 `manual-v2.1.0-20261020`，构建状态成功，EXE SHA256 为 `a695808aa7e6413c051c9820d3b1b7415a22f39971cf00171716f02c0ff8c94e`。
- 36/36 仓库算例配置校验通过，36/36 按原配置通过标准 `run-nuc.ps1` 完整运行。附录 C 的耗时是本次实测，包括包装器启动，且受驱动缓存与系统负载影响。
- 九套开发构建验证通过；检查点为 45/45，V2 矩阵为 56/56。仍保留 10.1 节的试用缺陷。
- V2.0.0 正式包周期算例运行入口单独通过；本次这一步不等于重新做了包内全部八套完整性/数值验收。

原始记录在服务器 `workingdir/user-manual-verification-20261020/`，Mac 对应 `reports/user-manual-verification-2026-10-20/`。适用范围与命令块检查结果见 [本次手册核验说明](validation/user-manual-2026-10-20.md)。编写提交晚于数值构建，文档更新不改变上述数值源码树。ParaView 操作按官方指南核对，本次未做交互界面实测。

<a id="troubleshooting"></a>
## 14. 故障排查与日常速查

### 14.1 按失败位置排查

| 现象/信息 | 先检查什么 | 下一步 |
|---|---|---|
| 找不到 EXE/BuildName | 第 1 章目录，`Get-ChildItem "$root\bin" -Directory` | 显式用实际 BuildName；需要时按第 4 章构建 |
| `The source repository must be clean` | `git status --porcelain`，含未跟踪文件 | 在 Mac 管理源码改动，自己的输入/结果放仓库外 |
| 无 vswhere/MSVC/SDK | 第 4.1 节依赖、构建日志 | 补齐 C++ 桌面组件、v142 和完整 SDK |
| `git pull` 网络失败 | 分支、提交、GitHub 通路 | 第 4.2 节 bundle 备用同步，两端核对 SHA |
| 缺 MSVCP140/VCRUNTIME140 DLL | 第 2.3 节运行库 | 从 Microsoft 官方入口安装 x64 v14 Redistributable，版本不早于构建工具 |
| EXE 仅显示帮助 | 是否传 `--config` | 用当前配置入口，旧位置参数 `Solver-IBM.exe 0` 不适用 |
| `Unknown field`/`Missing required field` | 大小写、完整 JSON、必填/互斥字段 | 对照附录 A，检查 JSON 是否误加 `$schema`、null 或说明文字 |
| `Requested OpenCL device not found` | 当前 OpenCL 设备枚举 | 按 3.2 节选设备，不用 nvidia-smi 编号代替 |
| GPU 初始化慢 | 首次模型/驱动内核编译，stdout/stderr | 首次编译与加载有耗时；按日志定位，不先认定死锁 |
| 显存/单缓冲上限 | cells、Q、storage、物理模块 | 减小格点；预算不是总显存上限保证 |
| `Output directory must be empty` | 直接调用复用了非空目录 | 新计算给新目录，续算走第 10 章 |
| `STL not found` | 相对配置文件目录的资产路径 | 保留 assets 结构或改正确路径，检查 Mac/Windows 路径区别 |
| `Only valid binary STL` | 二进制格式、长度、三角形和顶点 | 从几何工具正确导出 binary STL |
| STL 越界/零体素 | 单位、size/center、域范围和网格 | 先预处理，查看 flags；细小物体需足够格点 |
| 边界未覆盖/冲突 | 六面、region、priority、棱角 | 整面底层覆盖，再以较高优先级设置局部区域 |
| `moving_wall requires lattice density 1` | 参考、初始、局部和边界密度 | 格子模式均 1；SI 中等于 reference_density |
| 探针在固体/受力目标为空 | 实际体素、ID、采样点 | 修改落点或目标，重做预处理 |
| 受力目标重叠或贴壁 | geometry 交叠、与域固壁接触 | 明确对象归属；整体目标与分组不可简单相加 |
| 无 `statistics.json` | analysis 是否开启、statistics 是否 true、是否完成 | 查 completion 与分析设置 |
| 最终步无探针行 | start_step 与 every 调度 | 仅命中调度的步采样，不自动补最终样本 |
| `features require solver.storage=FP32` | 热/自由液面/motion 开关 | 显式使用 FP32 |
| 动态表面速度超限 | 平移速度、转速×半径、振幅/周期 | 将最远表面速度控制在 0.05 cell/step 限制内 |
| 运动交叠/越界 | 枢轴、轨迹、范围、物体间距 | 调整输入，本版无碰撞和自动裁剪 |
| 温度子步超限 | 材料扩散率、单位、网格/时间尺度 | 核对物性换算，检查 resolved thermal.substeps |
| 质量或显热残差大 | 初始量、开口通量、热源、热边界、单位 | 按具体基准定义归一化；查 conservation-budget 和 boundary-flux |
| 速度/温度出现异常或非有限值 | 尺度、格子速度/黏度、网格、边界、时间曲线 | 回到已验证小算例逐项改动，进行对应物理对照 |
| 包装器 `timed_out` | timeoutSeconds、stdout、运行规模 | 调整时限或计算规模，不把超时结果当完整终态 |
| 续算找不到原 results | 外层新 RunId 不等于数据目录 | 读取该次 run.json.paths.results |
| 续算退出码 3/4/5 | 第 10.7 节和 stderr | 保留原目录，区分结构损坏、保存失败和契约拒绝 |
| 扫描字段不存在 | 基础 JSON 内是否真有该键 | 显式补字段，检查 Pointer/数组索引 |
| 扫描快照哈希变化 | 是否修改生成文件 | 从新基础输入 generate 到新目录 |
| Python 重定向输出编码错误 | 中文用例名、cp1252 环境 | 设置 `PYTHONIOENCODING=utf-8`，保留原日志 |

`max_prescribed_mach` 是根据输入速度计算的诊断量，不预测强迫后的实际最大速度。解析器接受的参数范围也不等于所有流动都能达到同样精度的范围。

### 14.2 提交问题时保留哪些证据

提供产品版本/构建记录/EXE 哈希、命令与 run.json、完整配置与所需 STL、resolved/completion、stdout/stderr、异常前后相关 CSV 或必要 VTK。恢复问题另保留检查点和重启链。小型可复现输入比只描述“算不对”更容易定位。

### 14.3 常用命令速查

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$buildName = 'checkpoint-v2.1.0-dev'
$exe = "$root\bin\$buildName\Solver-IBM.exe"
& $exe --version
& $exe --help
& $exe --capabilities
& $exe --list-devices
# 替换为实际输入。校验不创建计算结果。
& $exe --config "$root\src\configs\periodic-fp32.json" --validate
```

| 操作 | 正文入口 |
|---|---|
| 已有开发 EXE 计算 | 3.3；换 ConfigPath/CaseName |
| 正式包计算 | 3.4；使用包内脚本与资产 |
| 编译 | 4.3；显式 BuildName |
| 预处理 | 3.3 或 6.4 的 `-PrepareOnly` |
| 延长续算 | 10.2；使用原 RunId 和白名单配置 |
| 批量扫描 | 11.2 |
| 找日志和结果 | 12.1 |
| 完整九套 | 13.3 |

工作结束关闭本次使用完毕的 SSH 会话；只处理能确认归属的连接和进程。若仍在运行必要任务，先核对真实状态、日志与所需连接，不盲目结束。

<a id="fields"></a>
## 附录 A. 完整配置字段参考

“缺省”表示字段省略时的行为，null 不等于省略。`Imax=9007199254740991`（`2^53−1`）；正整数为 1..Imax，非负整数为 0..Imax，另有较小字段上限时按该上限。有限数不含 NaN/Infinity、布尔值和数值字符串；三元向量严格为三个有限数，布尔量使用 true/false。正密度、黏度等换算后还必须能表示为正的有限 FP32，松弛率另有约束。

### A.1 顶层结构与算例名称

| 字段 | 类型 / 内容 | 缺省值 |
|---|---|---|
| `schema_version` | 整数，目前只能为 `1` | 必填，无默认值 |
| `case` | 对象，只含下面的 `name` | 必填，无默认值 |
| `case.name` | 非空字符串；描述算例，不决定目录或物理模型 | 必填，无默认值 |
| `solver` | 模型选择对象，见 A.2 | 省略等同 `{}`，启用全部模型默认值 |
| `units` | 单位对象，见 A.3 | 必填，无默认值 |
| `domain` | 计算域对象，见 A.4 | 必填，无默认值 |
| `fluid` | 流体密度、黏度和旧式常量体积力对象，见 A.5 | 必填，无默认值 |
| `physics` | 重力、共轭传热和自由液面对象，见 A.12 | 无新增物理时可省略 |
| `initial` | 初始条件对象，见 A.6 | 必填，无默认值 |
| `geometry` | STL 对象数组，见 A.7 | 必填；无 STL 时写 `[]` |
| `boundaries` | 边界对象数组，见 A.8 | 必填，必须声明全部六面 |
| `run` | 步数和监控对象，见 A.9 | 必填，无默认值 |
| `output` | VTK 输出对象，见 A.10 | 省略等同 `{}`，使用默认输出 |
| `analysis` | 探针和统计对象，见 A.11 | 省略表示关闭分析；`{}` 表示开启默认全域分析 |

### A.2 `solver`：模型和精度

| 字段 | 可用值 / 范围 | 缺省值与条件 |
|---|---|---|
| `solver.lattice` | `"D3Q19"`、`"D3Q27"` | `"D3Q19"` |
| `solver.collision` | `"SRT"`、`"TRT"` | `"SRT"` |
| `solver.storage` | `"FP16S"`、`"FP32"` | `"FP16S"`；控制分布函数存储，算术均为 FP32 |
| `solver.turbulence` | `"none"`、`"smagorinsky"` | `"smagorinsky"` |
| `solver.smagorinsky_constant` | 数值，`0 < Cs <= 1` | `0.17326595533835415`；仅 Smagorinsky 模式允许提供 |
| `solver.trt_magic_parameter` | 数值，`0 < Λ <= 1` | `0.1875`，即 `3/16`；仅 TRT 模式允许提供 |

Cs、Λ 无量纲，不随 SI 换算。关闭 Smagorinsky 时写 `"turbulence":"none"` 并省略 `smagorinsky_constant`，不能用 `Cs=0` 关闭。SRT 时省略 `trt_magic_parameter`。默认 Cs 保留原内核系数 `0.76421222f`；自定义值使用 `18*sqrt(2)*Cs²`，该系数必须能表示为正的有限 FP32。TRT 基础偶、奇松弛率还必须满足有限且严格处于 `(0,2)`，因此仅满足 Λ 范围并不保证任意黏度组合都被接受。

**省略 `solver` 会开启 Smagorinsky，并使用 FP16S。** 如需关闭亚格子模型，应明确写 `none`。启用 `physics.thermal`、`physics.free_surface` 或任意 `geometry[].motion` 时必须显式写 `"storage":"FP32"`；这三类功能不接受 FP16S。P3 验收已发现 FP16S 在弱体积力、较细通道网格上的量化误差；需做精度比较时可显式选 FP32，具体结果见 [P3 验收记录](validation/config-runner-p3-2026-09-22.md)。

### A.3 `units`：格子单位与 SI

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

SI 模式下，长度/位置为 m、时间为 s、速度为 m/s、密度为 kg/m³、运动黏度为 m²/s、体积力密度为 N/m³。STL 源坐标及 `transform.pivot` 的例外见 A.7。不存在独立的每字段单位标签；不能在同一个 SI 配置中把某个速度当作格子值输入。

### A.4 `domain`：网格、范围和原点

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

启用自由液面额外增加设备 20、主机 12 bytes/cell；动态几何额外增加设备/主机各 1 bytes/cell；热模型额外增加设备 34、主机 30 bytes/cell。三者可以相加。额外还有 STL、驱动和分配开销；主机基本字段 29 bytes/cell，另计并集掩码、几何归属、受力分组和运动热历史。程序在实际运行时核查所选设备的容量与分布函数单缓冲上限。查看 `resolved-config.json` 中的网格及内存估算，不能只依据输入预算判断。

### A.5 `fluid`：密度、黏度与体积力

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

重力应写在 `physics.gravity`，其输入是加速度，程序会按流体密度转换为基础体积力，并在热模型中同时用作 Boussinesq 浮力方向。`fluid.body_force` 适合额外的压降驱动力；两者存在时相加。

### A.6 `initial`：初始场与局部覆盖

| 字段 | 可用值 / 范围 | 缺省值 |
|---|---|---|
| `initial.velocity` | 三元向量，格子速度或 m/s | 必填；静止也须写 `[0,0,0]` |
| `initial.rho` | 正数，格子密度或 kg/m³ | `fluid.rho` |
| `initial.regions` | 局部盒子数组 | `[]` |
| `initial.regions[].box_min` | 三元向量，盒子最小坐标 | 每个区域必填 |
| `initial.regions[].box_max` | 三元向量，每方向不得小于对应 `box_min` | 每个区域必填 |
| `initial.regions[].rho` | 正数，格子密度或 kg/m³ | 每个区域必填，不继承全域值 |
| `initial.regions[].velocity` | 三元向量，格子速度或 m/s | 每个区域必填，不继承全域值 |
| `initial.temperature` | 正数，格子温标或 K | 启用热模型时可覆盖 `physics.thermal.initial_temperature` |
| `initial.regions[].temperature` | 正数，格子温标或 K | 可选；仅热模型允许 |
| `initial.liquid_regions` | 初始液体区域数组 | 自由液面必需，除非存在 `liquid_inlet` |
| `initial.liquid_regions[].shape` | `"box"`、`"sphere"`、`"stl"` | 省略为 `box` |
| `initial.liquid_regions[].fill` | `0 < fill <= 1` | `1`；与几何子格填充率相乘 |

盒子坐标使用当前单位，按格点中心落入**闭区间**判断。多个区域重叠时，数组中后面的区域覆盖前面的区域。它们只定义初始场，边界和固体赋值随后生效。输入区域可以不命中格点，解析器不保证每个区域实际覆盖非零格点。`liquid_regions` 的盒子使用 `box_min/box_max`，球使用 `center/radius`，封闭体使用二进制 STL 的 `file/transform`；多个液体区域取最大填充率。STL 液体掩膜的变换语义与 A.7 相同。

### A.7 `geometry`：静态与规定运动二进制 STL

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
| `geometry[].material` | `physics.thermal.materials[].id` | 热模型下每个 STL 必填；否则禁止 |
| `geometry[].thermal_regions` | 物体局部坐标中的 `box_min/box_max/temperature` 数组 | `[]`；随物体一起运动 |
| `geometry[].contact_angle` | `0 < θ < 180`，度 | `90`；仅自由液面允许 |
| `geometry[].motion` | 规定运动对象，见 A.14 | 省略表示静止 |

STL 本身不携带长度单位。`fit` 先旋转，再把旋转后包围盒的最长边等比例缩放到 `size`，最后把包围盒中心放到 `center`。这不是分别拉伸 x/y/z 三个方向。

`scale` 的目标坐标为：

```text
p_target = translation + R(axis,degrees) * (factor * (p_STL - pivot))
```

`pivot` 是变换前要减去的参考点，变换后该点位于 `translation`；公式没有额外的 `+pivot`。例如源 STL 使用 mm、目标为 SI m，保持原点时可用 `factor=0.001`、`pivot=[0,0,0]`、`translation=[0,0,0]`。

格式必须是非空二进制 STL，长度严格等于 `84 + 50*三角形数` bytes，顶点有限，包围盒不能完全退化。ASCII STL 不支持。变换后须位于计算域内，程序不自动裁剪。正式运行/预处理还会检查每个 STL 至少体素化出一个固体格点。静态 STL 继续按固体并集处理。带 `motion` 的 STL 保留独立对象 ID，并在每一步重新体素化；多个动态对象不得互相重叠、碰撞、穿越域边界或接触另一个固体。固体温度按材料坐标随物体移动，不在旧位置遗留热量。

STL 不能与最终生效的 `equilibrium` 或 `moving_wall` 边界相交；静态 `no_slip` 可以合并，但单物体受力统计另有归属约束，见 A.11。

### A.8 `boundaries`：六面、局部区域和优先级

| 字段 | 可用值 / 范围 | 缺省值与条件 |
|---|---|---|
| `boundaries[].id` | 非空字符串，在 `boundaries` 内唯一 | 必填 |
| `boundaries[].faces` | 非空、无重复字符串数组；元素为 `xmin`、`xmax`、`ymin`、`ymax`、`zmin`、`zmax` | 必填 |
| `boundaries[].type` | `"periodic"`、`"no_slip"`、`"equilibrium"`、`"moving_wall"`、`"liquid_inlet"`、`"open_outlet"` | 必填 |
| `boundaries[].priority` | 整数 `-1000000..1000000`，越大越优先 | `0` |
| `boundaries[].region` | 含 `min`、`max` 的对象，限定面内范围 | 省略表示整面；`periodic` 禁止 |
| `boundaries[].region.min` | 两个有限数，面内最小坐标 | 提供 `region` 时必填 |
| `boundaries[].region.max` | 两个有限数，每项不小于对应 `min` | 提供 `region` 时必填 |
| `boundaries[].rho` | 正数，格子密度或 kg/m³ | `equilibrium`、`liquid_inlet`、`open_outlet` 必填；其他类型禁止 |
| `boundaries[].velocity` | 三元向量，格子速度或 m/s | `equilibrium`、`liquid_inlet`、`open_outlet`、`moving_wall` 必填 |
| `boundaries[].contact_angle` | `0 < θ < 180`，度 | 固壁默认为 `90`；仅自由液面固壁允许 |
| `boundaries[].thermal` | 热边界对象，见 A.12 | 未给出时绝热 |

各边界类型的行为：

| 类型 | 含义 | 必要约束 |
|---|---|---|
| `periodic` | 整个坐标方向周期相连 | 相对两面必须均为周期；同一面不能混入其他类型；不能局部周期 |
| `no_slip` | 固定零速度固壁 | 不填写 `rho` 或 `velocity` |
| `equilibrium` | 固定密度和速度的平衡分布边界（`TYPE_E`） | 同时指定 `rho`、`velocity`；不能只给压力或只给速度 |
| `moving_wall` | 位置固定、速度恒定的切向运动壁面 | 每个指定面法向速度分量严格为零；不接受 `rho` |
| `liquid_inlet` | 自由液面液体储库入口 | 指定 `rho`、`velocity`；入口单元保持充满液体 |
| `open_outlet` | 自由液面开口出口 | 指定 `rho`、`velocity`；离散质量及焓流写入收支 |

`equilibrium` 可用于当前接口的指定入口/出口条件，但不等同于通用压力出口、零梯度出口或其他未实现的边界算法。`moving_wall` 改变壁面速度，不改变壁面位置，也不驱动 STL 移动。

存在任意运动壁面时，`fluid.rho`、`initial.rho`、所有局部初始密度和 `equilibrium.rho` 换算后的格子密度都必须**恰好为 1**。SI 中通常对应所有这些密度均等于 `units.reference_density`。

`region` 使用当前长度单位，按格点中心在闭区间内判定。两坐标的顺序固定如下：

| 所在面 | `region.min/max` 的分量顺序 |
|---|---|
| `xmin`、`xmax` | `[y,z]` |
| `ymin`、`ymax` | `[x,z]` |
| `zmin`、`zmax` | `[x,y]` |

每个面都必须声明，每个非周期面的边界格点都必须被该面的规则覆盖。棱边、角点以及同面局部区域的重叠，统一按最高 `priority` 选择。最高优先级相同且类型/赋值不同会报错；相同赋值允许重叠，其归属使用数组中先出现的规则。受力分组和 `boundary_coverage.winning_cells` 使用最终胜出的规则，低优先级规则可被完全覆盖。常见写法是先放低优先级整面规则，再用较高优先级局部入口覆盖。

### A.9 `run`：终止条件与监控

| 字段 | 可用值 / 范围 | 缺省值与条件 |
|---|---|---|
| `run.steps` | 正整数 `1..Imax` | 与 `duration` 恰好提供一个；没有默认步数 |
| `run.duration` | 正数，s | 仅 SI 可用；与 `steps` 互斥 |
| `run.monitor_every` | 正整数 `1..Imax`，步数间隔 | `100` |
| `run.checkpoint_every` | 非负整数 `0..Imax`，检查点步数间隔；`0` 或缺省 = 禁用 | 禁用 |
| `run.checkpoint_keep` | 整数 `1..1000`，保留最近检查点个数 | `2` |

`duration` 转换为 `ceil(duration/dt)` 步，接近整数时使用与网格同类的 `1e-10` 相对容差；结果必须为 `1..Imax`，实际终止时间是 `steps*dt`。`monitor.csv` 包含初始第 0 步、监控间隔和最终步。监控间隔、VTK 间隔、分析间隔是三个独立设置。

启用 `checkpoint_every` 后，求解器在间隔整数倍步及正常完成时保存检查点到 `checkpoint/` 子目录，`--restart` 可从最新有效检查点续算；详见第 10 章。检查点占用与保留策略见 10.6 节。

零步检查使用 `--prepare-only`，配置里的目标步数仍必须为正，不能填 `steps:0`。

### A.10 `output`：VTK 输出

| 字段 | 可用值 / 范围 | 缺省值 |
|---|---|---|
| `output.vtk_fields` | 非空、无重复数组：`"u"`、`"rho"`、`"flags"`、`"p"`、`"T"`、`"material"`、`"object"`、`"phi"` | `["u","rho","flags"]`；后四项要求对应物理功能 |
| `output.vtk_every` | 非负整数 `0..Imax`，步数间隔 | `0`，不输出中间周期帧 |
| `output.initial` | 布尔值 | `true`，输出第 0 步 |

正常计算**总会输出最终步**，与 `vtk_every` 是否整除终止步无关。`vtk_every=0` 表示“最终帧，加上可选初始帧”，不表示关闭所有 VTK。`vtk_fields=[]` 不允许。`--prepare-only` 总会输出第 0 步所选字段，并保证输出 `flags`，即使 `initial=false` 或字段列表不含 `flags`。

`u` 为速度三分量，`rho` 为密度，`flags` 为格点位标记，`p` 为相对 `fluid.rho` 的表压；`T` 为温度，`material` 为热材料 ID，`object` 为动态对象 ID，`phi` 为液体填充率。SI 配置的 VTK 坐标、间距、速度、密度、压强均转换为 SI；文件名按步数至少补齐九位，例如 `u-000000023.vtk`。

### A.11 `analysis`：采样、探针与固体受力

| 字段 | 可用值 / 范围 | 缺省值与条件 |
|---|---|---|
| `analysis.every` | 正整数 `1..Imax`，采样步数间隔 | `run.monitor_every` 的实际值 |
| `analysis.start_step` | 非负整数，不超过计算后的 `run.steps` | `0` |
| `analysis.statistics` | 布尔值，是否额外生成时均及标准差 | `true` |
| `analysis.probes` | 探针对象数组 | `[]` |
| `analysis.probes[].id` | 非空字符串，在探针列表内唯一 | 每个探针必填 |
| `analysis.probes[].position` | 三元向量，当前长度单位；每方向在 `[origin,origin+cells*dx)` 内 | 每个探针必填 |
| `analysis.surface_levels` | 液位探针数组 | `[]`；仅自由液面允许 |
| `analysis.surface_levels[].id` | 非空唯一字符串 | 每个液位探针必填 |
| `analysis.surface_levels[].position` | `[x,y]` 两个坐标 | 每个液位探针必填；沿 z 柱积分液体高度 |
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

### A.12 `physics.thermal`：流固共轭传热

热模型采用显式守恒有限体积温度输运。流体中包含对流和导热，固体中只求解导热；流固面使用调和平均导热系数表达理想热接触。不同材料均采用常数密度、比热和导热系数。自然对流使用 Boussinesq 近似，浮力项由 `physics.gravity`、`reference_temperature` 和 `thermal_expansion` 共同确定。

| 字段 | 类型 / 单位 | 缺省值与条件 |
|---|---|---|
| `physics.gravity` | 三元加速度；格子模式为 cell/step²，SI 为 m/s² | `[0,0,0]`；同时作用于基础流动和 Boussinesq 浮力 |
| `physics.thermal.reference_temperature` | 正数，SI 为 K | 必填；温度无量纲化尺度和 Boussinesq 参考温度 |
| `physics.thermal.initial_temperature` | 正数，SI 为 K | 必填；全域初温 |
| `physics.thermal.specific_heat` | 正数，SI 为 J/(kg·K) | 必填；流体定压比热 |
| `physics.thermal.conductivity` | 正数，SI 为 W/(m·K) | 必填；流体导热系数 |
| `physics.thermal.thermal_expansion` | 非负数，SI 为 1/K | `0`；为零时没有温差浮力 |
| `physics.thermal.turbulent_prandtl` | 正数 | `0.9`；Smagorinsky 模式下控制涡热扩散率 |
| `physics.thermal.materials` | 固体材料数组，ID 唯一，最多 254 个 | `[]`；存在热 STL 时须定义并引用 |
| `materials[].density` | 正数，SI 为 kg/m³ | 必填 |
| `materials[].specific_heat` | 正数，SI 为 J/(kg·K) | 必填 |
| `materials[].conductivity` | 正数，SI 为 W/(m·K) | 必填 |
| `materials[].heat_source` | 有限数，SI 为 W/m³ | `0`；正值加热，负值冷却 |
| `materials[].initial_temperature` | 正数，SI 为 K | 流体全域初温 |

格子模式也按 `alpha = conductivity/(density*specific_heat)` 解释输入；热扩散率必须落在稳定范围内。程序根据流体和所有固体的最大扩散率自动选择偶数个热子步，超过 1024 个子步的材料对比会被拒绝。热源、边界热量和开口焓流计入 `conservation-budget.csv`；这是显热收支，不包含黏性耗散、运动物体做功或完整机械能。

每个非周期边界可设置 `thermal`：

| `thermal.type` | 必要字段 | 行为 |
|---|---|---|
| `adiabatic` | 无 | 零法向热流；省略 `thermal` 时也是绝热 |
| `fixed_temperature` | `temperature` | 固定壁面或开口温度 |
| `heat_flux` | `heat_flux` | 仅固壁；指定进入计算域的面热流密度 |
| `convection` | `ambient_temperature`、`heat_transfer_coefficient` | 仅固壁；环境对流换热 |

热模型下每个 STL 必须用 `geometry[].material` 引用一种材料。`geometry[].thermal_regions` 的盒子坐标以物体初始枢轴为原点；它只覆盖初始固体温度并随物体移动。浸没固体持续发热应使用材料 `heat_source`，不要依赖反复重置初温。

### A.13 `physics.free_surface`：单液相自由液面

本版只推进液体；气体不占用另一套流场，按固定环境压强处理。没有蒸发、沸腾、凝固、气相惯性或密闭气体压缩模型。

| 字段 | 类型 / 单位 | 缺省值与条件 |
|---|---|---|
| `physics.free_surface.surface_tension` | 非负数；SI 为 N/m | 必填；格子值不得超过 0.1 |
| `physics.free_surface.environment_pressure` | 非负表压；SI 为 Pa | `0` |
| `initial.liquid_regions` | 盒、球或封闭二进制 STL 区域 | 无 `liquid_inlet` 时至少一个 |
| `geometry[].contact_angle` | `(0,180)` 度 | `90`，每个固体独立设置 |
| `boundaries[].contact_angle` | `(0,180)` 度 | `90`，仅 `no_slip`/`moving_wall` |

接触角是固定静态角，不含前进/后退角滞后或动态接触角。开口边界记录每个监控时刻的离散质量流和显热焓流；程序按逐步累计目标修正界面质量，并在热自由液面中按热源、边界热量和焓流闭合显热收支。`equilibrium` 保留旧单相语义，不能替代 `liquid_inlet` 或 `open_outlet`。

`analysis.surface_levels` 为每个 `[x,y]` 位置生成 `surface-levels.csv`，列出沿 z 柱积分得到的 `liquid_height` 及最高充液格点顶面 `top_elevation`。强破碎液面可能同一柱存在多个液段，此时积分液高比“最上方界面”更稳定。

### A.14 `geometry[].motion`：规定刚体运动

多个 STL 可使用不同的平移、旋转或轨迹。平移与旋转规律可以组合；时间表轨迹与这两类规律互斥。SI 配置中的位移、速度、时间使用 m、m/s、s，角度使用度，角速度使用度/s；格子配置使用 cell、cell/step、step、度、度/step。

| 字段 | 内容 |
|---|---|
| `motion.pivot` | 世界坐标中的旋转枢轴；省略时使用初始 STL 几何中心 |
| `motion.translation.type` | `constant_velocity` 或 `sinusoidal` |
| 匀速平移 | `velocity`，可选 `start_time`、`stop_time`；停后保持最终位移 |
| 正弦平移 | `amplitude`、`period`，可选 `phase_degrees`、`start_time`、`stop_time` |
| `motion.rotation.type` | `constant_angular_velocity` 或 `sinusoidal`，均须提供非零 `axis` |
| 匀速旋转 | `angular_velocity_degrees`，可选 `start_time`、`stop_time` |
| 正弦旋转 | `amplitude_degrees`、`period`，可选 `phase_degrees`、`start_time`、`stop_time` |
| `motion.trajectory_axis` | 时间表角度使用的旋转轴，默认 `[1,0,0]` |
| `motion.trajectory` | 至少两个 `{time,translation,degrees}` 关键帧；首帧时间为 0，时间严格递增，区间内线性插值，末帧后保持 |

程序限制规定运动物体表面最大格子速度不超过 0.05 cell/step，并要求体素单元数在运动中保持不变。当前不计算碰撞、接触、变形或六自由度响应；`object-motion.csv` 中的力和力矩是诊断量，不反过来改变规定轨迹。

### A.15 新增输出与守恒文件

启用相应模型后，结果目录增加：

| 文件 | 主要内容 |
|---|---|
| `free-surface.csv` | 液体质量、体积、质心、液面范围、固体干湿面积 |
| `surface-levels.csv` | 用户指定位置的积分液高和顶部高程 |
| `boundary-flux.csv` | `liquid_inlet`/`open_outlet` 的向外质量流；热模型还含显热焓流 |
| `conservation-budget.csv` | 初始/当前液体质量、累计开口流、质量残差；初始/当前显热、累计焓流、热源、边界热量及显热残差 |
| `object-motion.csv` | 每个动态 STL 的单元数、平移、中心、轴角、线/角速度、力、力矩和固体温度范围/显热 |

质量正方向按流出域定义，因此入口通常为负值。显热残差按“当前 − 初始 + 流出焓 − 热源输入 − 边界热输入”定义。`resolved-config.json` 记录实际格子物性、热子步、材料换算、自由液面环境密度、对象及守恒投影是否启用；验收或问题复现应与 `completion.json`、EXE SHA256 一起保留。


### A.16 液体区域和运动定律的嵌套字段补充

以下路径在 A.6/A.14 的对应对象内使用，禁止混入其他模式专属字段。

| 字段 | 类型、范围与默认 |
|---|---|
| `initial.liquid_regions[].shape` | box/sphere/stl，缺省 box |
| 盒区域 `box_min`、`box_max` | 各为三元坐标，逐方向 min≤max，当前长度单位 |
| 球区域 `center`、`radius` | 三元中心、正半径，当前长度单位 |
| STL 区域 `file`、`transform` | 二进制封闭 STL 和与 geometry 相同的变换；相对配置目录 |
| 区域 `fill` | `(0,1]`，缺省 1；与几何子格填充率相乘 |
| `motion.translation.velocity` | 三元速度，仅 constant_velocity，必填 |
| `motion.translation.amplitude` | 三元位移振幅，仅 sinusoidal，必填 |
| `motion.rotation.axis` | 非零三元向量，两种旋转定律均必填，内部归一化 |
| `motion.rotation.angular_velocity_degrees` | 有限数，度/当前时间单位，仅 constant_angular_velocity，必填 |
| `motion.rotation.amplitude_degrees` | 有限数，度，仅 sinusoidal，必填 |
| 平移/旋转 `period` | 正时间，仅 sinusoidal，必填 |
| 平移/旋转 `phase_degrees` | 有限角度，度，仅 sinusoidal，缺省 0 |
| 平移/旋转 `start_time` | 非负时间，缺省 0 |
| 平移/旋转 `stop_time` | 非负时间，提供时必须大于 start_time；省略表示不停止 |
| `motion.trajectory[].time` | 非负时间，首项严格为 0，后续严格递增 |
| `motion.trajectory[].translation` | 三元位移，当前长度单位，每个关键帧必填 |
| `motion.trajectory[].degrees` | 有限角度，度，每个关键帧必填 |
| `motion.trajectory_axis` | 非零向量，缺省 `[1,0,0]`；只允许与 trajectory 同时出现 |
| `motion.pivot` | 三元世界坐标枢轴，省略按初始 STL 几何中心 |
| `geometry[].thermal_regions[].box_min/box_max` | 相对物体初始枢轴的局部三元坐标，当前长度单位 |
| `geometry[].thermal_regions[].temperature` | 正温度，仅热模型，SI 为 K |

`motion` 必须包含 translation、rotation 或 trajectory 之一，空对象和仅 pivot 不构成运动。translation 与 rotation 可组合，trajectory 与二者互斥。对象最多 254 个，各自 ID 唯一；旋转角按右手方向。单个配置不接受外部轨迹 CSV 路径，轨迹表是 JSON 内关键帧数组。

<a id="cli"></a>
## 附录 B. 命令行和脚本参数

以下默认值按当前脚本源码记录；示例一律显式指定实际构建名称。

### B.1 直接调用 EXE

```text
Solver-IBM.exe --config FILE [--device ID] [--output DIR] [--restart] [--validate | --prepare-only]
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
| `--restart` | 从 `--output` 指向的原运行目录中最新有效检查点续算；原目录必须含 `original-config.json`、`inputs/`、`checkpoint/` | 不启用；与 `--validate`/`--prepare-only` 互斥 |
| `--version` | 输出产品名称和版本，单独使用 | 不启用 |
| `--help` | 显示用法，单独使用 | 无参数启动也显示帮助 |
| `--capabilities` | 输出当前 EXE 支持能力的 JSON，单独使用 | 不启用 |
| `--list-devices` | 枚举 OpenCL 设备，单独使用 | 不启用 |

参数不可重复，未知参数报错。`--validate` 与 `--prepare-only` 互斥；`--help` 等查询选项不可与 `--config` 混用。`--validate` 不检查设备是否可用、显存是否足够、STL 是否体素化为零，也不检查探针是否落入体素固体；需要 `--prepare-only` 完成这些检查。其标准输出是 JSON 加一行通过提示，不是纯 JSON 文件。

正常完成返回退出码 0，配置入口捕获错误返回 1；断点续算另有专用退出码：3 = 无可用检查点（全部候选校验失败，已隔离），4 = 检查点保存失败（运行终止，旧检查点保持可用），5 = 兼容性/配置契约拒绝（当前开发版的拒绝副作用见第 10 章）。外部运行脚本还会检查完成记录及日志，不只依赖退出码。完整调用和独立变量初始化见第 3、10 章。直接调用不提供外层运行记录、EXE 快照和超时管理；日常计算使用 `run-nuc.ps1`。

### B.2 `run-nuc.ps1` 参数

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
| `-RestartFromRunId` | 同 `CaseName` 下先前运行的 RunId；从其 `results/` 目录的检查点续算，结果继续写入原 results 目录，本次运行仍有独立 RunId 的日志、EXE 快照与 `run.json`（含 `restart` 溯源块） | 不提供；要求 `ConfigPath`，与 `PrepareOnly`/`ExpectBenchmark` 互斥 |
| `-ExpectBenchmark` | 上游硬编码 benchmark 专用验收开关 | 默认关闭；与 `ConfigPath` 互斥，当前配置运行不使用 |

`BuildName`、`CaseName` 均为 1–64 字符，首字符字母或数字，余下允许字母、数字、点、下划线和连字符；不能以点结尾，不能使用 Windows 保留名。脚本要求对应 `build.json` 成功且 EXE SHA256 一致；普通构建还要求记录中的绝对路径匹配。`-ExecutablePath` 允许迁移定位，但保留原始构建路径作为来源记录，不省略哈希校验。手动替换 EXE 会被拒绝。

完整预处理命令见第 6.4 节。预处理完成后，去掉 `-PrepareOnly` 会重新初始化并计算，不会从第 0 步结果续算。脚本没有 `-Validate` 参数，静态校验直接使用 EXE 的 `--validate`。

超时时脚本终止自己启动的进程树并写入 `timed_out`；计算及脚本返回前保持 SSH 会话。正常结束后可执行 `exit` 退出 PowerShell，再按登录环境退出 SSH；不要通过断开会话代替正常结束计算。

### B.3 `run-package.ps1` 参数与包验证

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
| `-RestartFromRunId` | 透传给 `run-nuc.ps1`，从先前 RunId 的检查点续算 | 不提供 |

当前源码包装器包含恢复透传参数，但已固定的 V2.0.0 包中没有断点续算能力。现有正式包应使用它自带的 `source/scripts/run-package.ps1`。正式包完整验证的独立命令见 13.4 节：V2.0.0 包执行对应八套，开发分支的发布器包含九套门槛；两者不可混称。`--skip-suites` 的结果明确记录跳过数值套件。

### B.4 `build-nuc.ps1` 参数

| 参数 | 类型、约束 | 当前脚本默认 |
|---|---|---|
| `-WorkspaceRoot` | 工作根目录，仓库为该目录下 src | 脚本所在仓库的父目录 |
| `-BuildName` | 首字符字母/数字，后续字母/数字/点/下划线/连字符；为兼容运行入口，用 1–64 字符、非保留名、不以点结尾 | `solver-ibm-v1.0.0`，实际使用显式指定 |
| `-PlatformToolset` | 已安装的 `v`+数字工具集 | `v142` |

构建入口执行 Release x64 Rebuild，自动记录编译器/SDK/工程身份。入口检查源码工作树干净并验证 EXE 产物；同名构建目录受构建锁保护。

### B.5 `parameter-study.py` 参数与规格字段

| 子命令参数 | 含义 | 默认 |
|---|---|---|
| `generate --spec` | 只含 schema_version/base_config/parameters 的扫描规格 JSON | 必填 |
| `generate --output` | 新目录或已有空目录 | 必填 |
| `run --study` | 含生成 study.json 的目录 | 必填 |
| `run --workspace-root` | Windows 工作根目录 | 必填 |
| `run --build-name` | 构建选择名称 | `solver-ibm-v1.0.0`，显式填写 |
| `run --executable` | 迁移后的 EXE，旁边保留 build.json | 省略则按 BuildName 定位 |
| `run --device` | 实际 OpenCL 设备 ID | 0，先枚举核实 |
| `run --timeout` | 每个组合秒数，下游允许 1–86400 | 900 |

| 规格字段 | 要求 |
|---|---|
| `schema_version` | 整数 1 |
| `base_config` | 基础 JSON，相对规格目录或绝对路径 |
| `parameters` | 非空参数轴数组，各轴长度乘积不超过 10000 |
| `parameters[].path` | 指向基础 JSON 已有位置的 JSON Pointer |
| `parameters[].values` | 非空 JSON 值数组；具体合法性由生成后的求解器校验 |


<a id="case-index"></a>
## 附录 C. 全部算例与扫描索引

### C.1 36 个可执行算例配置

文件均位于仓库 `configs/`，点击文件名可打开完整输入。规模与步数为原文件，精度套件可能生成不同输入；“检查”列指出应使用的定量验证入口。耗时为 2026-10-20 的独立构建在 RTX 4070 Ti SUPER 上通过标准包装器实测的秒数，包含启动/记录开销，不是纯内核计时，不保证其他设备相同。

| 配置与启用功能 | 原始网格；步数/时间 | STL 依赖 | 章节；检查 | 本次耗时 s |
|---|---|---|---|---:|
| [ahmed-smoke.json](../configs/ahmed-smoke.json)<br>外部 Ahmed 静态 STL；默认模型 | 96×48×48；37 步 | 仓库外模型；先看 6.4 | 6.4；P1 | 0.81 |
| [boeing-regression.json](../configs/boeing-regression.json)<br>外部 Boeing、Re 指定黏度、平衡远场 | 170×339×85；1000 步 | 仓库外模型；先看 6.4 | 6.4；P1 历史回归 | 5.55 |
| [checkpoint-resume-lattice.json](../configs/checkpoint-resume-lattice.json)<br>FP32；checkpoint_every=500、keep=2 | 32×32×32；2000 步 | 无 | 10；检查点套件 | 1.00 |
| [conjugate-heated-cube-lattice.json](../configs/conjugate-heated-cube-lattice.json)<br>thermal、多材料、固体热源、流动 | 24×16×16；40 步 | assets/：unit-cube-binary.stl | 7；场景热源/收支 | 0.58 |
| [couette.json](../configs/couette.json)<br>FP32；固定位置切向 moving_wall | 8×18×8；4000 步 | 无 | 6；P2/P3 解析剖面 | 0.59 |
| [dynamic-rotation-lattice.json](../configs/dynamic-rotation-lattice.json)<br>FP32；motion 匀速定轴转动 | 40×28×24；400 步 | assets/：rectangular-box-2x1x1-binary.stl | 9；场景位姿 | 1.27 |
| [dynamic-sinusoidal-multi-lattice.json](../configs/dynamic-sinusoidal-multi-lattice.json)<br>FP32；多体、正弦、平移/转动组合 | 48×32×24；480 步 | assets/：rectangular-box-2x1x1-binary.stl, unit-cube-binary.stl | 9；场景位姿 | 1.70 |
| [dynamic-thermal-cycle-lattice.json](../configs/dynamic-thermal-cycle-lattice.json)<br>FP32；thermal+motion，局部温度闭环 | 40×28×24；600 步 | assets/：rectangular-box-2x1x1-binary.stl | 9；物理温度 L2 | 2.30 |
| [dynamic-trajectory-lattice.json](../configs/dynamic-trajectory-lattice.json)<br>FP32；motion.trajectory 时间表 | 40×30×24；400 步 | assets/：rectangular-box-2x1x1-binary.stl | 9；场景关键帧 | 1.28 |
| [dynamic-translation-stop-lattice.json](../configs/dynamic-translation-stop-lattice.json)<br>FP32；匀速平移和 stop_time | 32×20×20；60 步 | assets/：unit-cube-binary.stl | 9；场景停止位姿 | 0.62 |
| [dynamic-water-entry-lattice.json](../configs/dynamic-water-entry-lattice.json)<br>FP32；free_surface+motion，规定入水 | 40×24×32；350 步 | assets/：unit-cube-binary.stl | 9；场景质量/受力 | 1.51 |
| [free-surface-contact-angle-120-lattice.json](../configs/free-surface-contact-angle-120-lattice.json)<br>FP32；free_surface，120° 固定角 | 40×40×24；400 步 | 无 | 8；物理角度拟合 | 0.64 |
| [free-surface-contact-angle-60-lattice.json](../configs/free-surface-contact-angle-60-lattice.json)<br>FP32；free_surface，60° 固定角 | 40×40×24；400 步 | 无 | 8；物理角度拟合 | 0.64 |
| [free-surface-contact-angle-90-lattice.json](../configs/free-surface-contact-angle-90-lattice.json)<br>FP32；free_surface，90° 固定角 | 40×40×24；400 步 | 无 | 8；物理角度拟合 | 0.64 |
| [free-surface-dam-break-lattice.json](../configs/free-surface-dam-break-lattice.json)<br>FP32；free_surface，简化溃坝短算 | 32×12×20；20 步 | 无 | 8；功能/组合检查 | 0.55 |
| [free-surface-fill-drain-lattice.json](../configs/free-surface-fill-drain-lattice.json)<br>FP32；液体入口/开口出口 | 48×24×24；200 步 | 无 | 8；场景已知流量 | 0.70 |
| [free-surface-hydrostatic-lattice.json](../configs/free-surface-hydrostatic-lattice.json)<br>FP32；free_surface+gravity，静水 | 20×8×28；1500 步 | 无 | 8；物理压差 | 0.62 |
| [free-surface-marin-dam-break-si.json](../configs/free-surface-marin-dam-break-si.json)<br>FP32；SI 溃坝与障碍、液位测点 | 161×50×50；3.0 s | assets/：marin-obstacle-161x403x161-binary.stl | 8；场景 MARIN 参考 | 9.80 |
| [free-surface-sloshing-lattice.json](../configs/free-surface-sloshing-lattice.json)<br>FP32；初始液面扰动、晃荡 | 64×8×32；3000 步 | 无 | 8；物理频率/场景幅度 | 0.94 |
| [free-surface-static-droplet-lattice.json](../configs/free-surface-static-droplet-lattice.json)<br>FP32；表面张力、球形液滴 | 48×48×48；1000 步 | 无 | 8；物理 Laplace 压差 | 0.72 |
| [free-surface-stl-mask-lattice.json](../configs/free-surface-stl-mask-lattice.json)<br>FP32；STL 液体区域+热+自由液面 | 24×24×24；8 步 | assets/：unit-cube-binary.stl | 8；初始化/矩阵 | 1.99 |
| [models-periodic.json](../configs/models-periodic.json)<br>FP32 D3Q27/TRT/Smagorinsky、自定义 Cs/Λ | 16×16×16；23 步 | 无 | 6；P3 参数 | 1.31 |
| [models-study-base.json](../configs/models-study-base.json)<br>16 模型扫描基础输入，也可单独运行 | 16×16×16；23 步 | 无 | 11；P3/扫描 | 0.56 |
| [periodic-fp32.json](../configs/periodic-fp32.json)<br>均匀周期流、显式 FP32 | 16×16×16；23 步 | 无 | 3/6；P1/存储 | 0.58 |
| [periodic-lattice.json](../configs/periodic-lattice.json)<br>均匀周期流、格子单位、默认模型 | 16×16×16；23 步 | 无 | 6；P1 | 0.56 |
| [periodic-si.json](../configs/periodic-si.json)<br>SI 单位、长度/dx/dt 换算 | 16×16×16；23 步 | 无 | 5/6；单位等价 | 0.55 |
| [poiseuille.json](../configs/poiseuille.json)<br>FP32；体积力和无滑移通道 | 8×18×8；4000 步 | 无 | 6；P2/P3 解析剖面 | 0.58 |
| [probes-periodic.json](../configs/probes-periodic.json)<br>FP16S；探针、全域时间统计 | 16×16×16；23 步 | 无 | 6；P2/扫描 | 0.56 |
| [thermal-boundaries-lattice.json](../configs/thermal-boundaries-lattice.json)<br>FP32；恒温、对流、绝热边界 | 20×8×8；40 步 | 无 | 7；物理热边界收支 | 0.55 |
| [thermal-diffusion-lattice.json](../configs/thermal-diffusion-lattice.json)<br>FP32；thermal 和局部初温 | 24×12×12；20 步 | 无 | 7；脚本生成平滑热扩散/强制对流 | 0.55 |
| [thermal-free-surface-dynamic-cycle-lattice.json](../configs/thermal-free-surface-dynamic-cycle-lattice.json)<br>FP32；三项组合闭合周期 | 36×24×28；800 步 | assets/：unit-cube-binary.stl | 9；场景质量/显热 | 2.62 |
| [thermal-free-surface-dynamic-fill-drain-lattice.json](../configs/thermal-free-surface-dynamic-fill-drain-lattice.json)<br>FP32；三项组合+温差入口/出口 | 48×24×28；200 步 | assets/：unit-cube-binary.stl | 9；场景通量/温度/热源 | 1.53 |
| [thermal-free-surface-smoke.json](../configs/thermal-free-surface-smoke.json)<br>FP32；thermal+free_surface 短算 | 20×12×16；12 步 | 无 | 9；功能/组合矩阵 | 0.56 |
| [thermal-multilayer-conduction-lattice.json](../configs/thermal-multilayer-conduction-lattice.json)<br>FP32；材料界面和导热 | 42×10×10；40000 步 | assets/：thermal-slab-1x4x4-binary.stl | 7；物理热流 | 8.86 |
| [thermal-natural-convection-cavity-lattice.json](../configs/thermal-natural-convection-cavity-lattice.json)<br>FP32；gravity+thermal_expansion、冷热壁 | 32×32×4；30000 步 | 无 | 7；脚本生成 Ra=1000 | 7.28 |
| [thermal-natural-convection-conductive-wall-lattice.json](../configs/thermal-natural-convection-conductive-wall-lattice.json)<br>FP32；自然对流和导热固壁 | 40×36×4；1000 步 | assets/：thin-plate-1x16x2-binary.stl | 7；物理连续温度 | 0.83 |

任取索引中的一个文件，按下面的通用入口独立运行。修改 `$file` 即选择功能，修改 `$buildName` 即选择程序；输出配置中的字段必须与启用模块一致。

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
$buildName = 'checkpoint-v2.1.0-dev'
$file = 'dynamic-rotation-lattice.json'
$config = "$root\src\configs\$file"
& "$root\bin\$buildName\Solver-IBM.exe" --config $config --validate
if ($LASTEXITCODE -ne 0) { throw 'Config invalid.' }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$root\src\scripts\run-nuc.ps1" `
  -WorkspaceRoot $root -BuildName $buildName -DeviceId 0 `
  -CaseName ('manual-' + [IO.Path]::GetFileNameWithoutExtension($file)) `
  -ConfigPath $config -TimeoutSeconds 1800
if ($LASTEXITCODE -ne 0) { throw 'Example failed; inspect the printed run directory.' }
```

### C.2 三个扫描规格

| 文件 | 组合 | 用法 |
|---|---|---|
| [study-periodic.json](../configs/study-periodic.json) | 4：黏度×初始速度 | 第 11.2 节替换 specName |
| [study-storage.json](../configs/study-storage.json) | 2：FP16S/FP32 | 同上 |
| [study-models.json](../configs/study-models.json) | 16：四类模型选择 | 同上，基础输入为 models-study-base.json |

### C.3 内置资源与参考

`configs/assets/` 保存 unit-cube、rectangular-box、thermal-slab、thin-plate 和 MARIN 障碍物等小型二进制 STL；按原配置目录相对解析。`configs/reference/spheric-test2-levels.csv` 与 README 保存外部参考表和来源，不能改作本项目计算结果。Boeing/Ahmed 外部资产路径见第 6.4 节和原 JSON；其他模型素材的完备状态以各自 README 和正式包索引为准。

## 依据与维护

当前行为依据 [config.cpp](../src/config.cpp)、[config_runner.cpp](../src/config_runner.cpp)、[config_analysis.hpp](../src/config_analysis.hpp)、[config_checkpoint.hpp](../src/config_checkpoint.hpp)、[脚本目录](../scripts/) 和对应配置，而非上游 README 的全部功能列表。JSON schema 用于辅助，最终以 EXE 校验和 GPU 预处理为准。

[服务器工作流](nuc-workflow.md)、[V2.0.0 发布说明](releases/V2.0.0.md)、[V2.0.0 验收](validation/solver-ibm-v2.0.0-2026-09-27.md)、[V2.1.0 开发版说明](releases/V2.1.0.md)、[本次手册核验](validation/user-manual-2026-10-20.md) 分别记录约定、正式能力、历史结论与本次操作证据。新字段或默认值变化时，同步更新源码解析、schema、配置、手册和对应验证记录。当前已知缺陷的状态以最新修复/试用记录为准，未修复前保留开发版标记。
