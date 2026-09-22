# NUC 构建、运行与结果目录

配置驱动分支使用 `-ConfigPath` 选择实际算例，另支持 `-PrepareOnly` 进行零步体素化检查；当前完整编译步骤、字段参考和运行命令见 [中文使用手册（P3）](user-manual-zh.md)。`CaseName` 继续只用于归档。该模式的配置/STL 快照及求解器记录位于本次 `results/` 内，外层 `inputs/` 保留兼容旧硬编码算例。本文后续“原始基线”及相关资源部署段落记录旧硬编码版本的工作流程，不作为当前 JSON 接口说明。

源码在 Mac 上阅读和修改，经 Git 推送到 fork，再由 NUC 拉取。编译、程序运行和算例计算均在 Windows NUC 上完成。项目根目录的 `AGENTS.md` 暂不纳入 Git；本说明和辅助脚本随源码仓库管理。

## 目录约定

NUC 工作根目录为 `F:\01-Project\Opensource\01-FluidX3D`：

```text
01-FluidX3D/
├── src/                              Git 仓库根目录
│   ├── src/                          上游 C++ 源文件
│   ├── scripts/
│   │   ├── build-nuc.ps1
│   │   ├── run-nuc.ps1
│   │   └── get-opencl-devices.ps1
│   ├── docs/nuc-workflow.md
│   └── temp/<build-name>/<build-id>/  构建中间文件（被 Git 忽略）
├── bin/
│   ├── <build-name>/
│   │   ├── FluidX3D.exe              正式构建产物
│   │   └── build.json                最近一次成功构建的身份记录
│   └── _runs/<case-name>/<run-id>/
│       ├── FluidX3D.exe              本次运行的二进制快照
│       └── export/                   Junction → 对应运行的 results/
└── workingdir/
    ├── _builds/<build-id>/
    │   ├── build.json                每次构建的记录，包含成功或失败状态
    │   ├── evaluation.json           MSBuild 工具链与路径求值结果
    │   └── msbuild.log
    └── <case-name>/<run-id>/
        ├── run.json                  运行身份、命令、状态、日志位置与验证结果
        ├── build.json                本次所用构建记录的快照
        ├── inputs/                   本次算例的输入资源
        ├── results/                  默认导出文件的实际存储位置
        └── logs/
            ├── stdout.log
            ├── stderr.log
            └── runner.log
```

`build-id` 和 `run-id` 使用 UTC 时间戳和 12 位 Git 提交号，例如 `20260920T013000123Z-0123456789ab`。每次运行创建独立目录，不覆盖上次结果。`BuildName`、`CaseName` 使用字母、数字、点、下划线和连字符，并以字母或数字开头；运行脚本将名称长度限制为 64 个字符，拒绝 Windows 保留名称和末尾的点。建议使用小写英文名称。

算例的名称只用于目录分类，**不会自动改变 C++ 中启用的算例**。例如 `-CaseName cavity` 不会把原始 benchmark 切换为方腔流；实际算例仍由 `src/setup.cpp` 和 `src/defines.hpp` 编译决定。

## 在 Mac 修改并同步

在 Mac 的 `FluidX3D` 仓库中确认当前分支和工作区状态，完成修改后提交并推送到用户的 fork。不要在 Mac 编译或运行 FluidX3D。

```sh
git status --short --branch
git remote -v
git add <本次修改的文件>
git commit -m "Describe the change"
git push -u origin <当前工作分支>
```

NUC 首次克隆应以完整仓库作为外层 `src`，不要只下载上游的 C++ 子目录。现有仓库无需再次执行 `git init` 或 `git clone`。NUC 上先核实分支和工作区，再拉取对应分支：

```powershell
Set-Location 'F:\01-Project\Opensource\01-FluidX3D\src'
git status --short --branch
git remote -v
git pull --ff-only
git rev-parse HEAD
```

确保 NUC 的提交号与 Mac 刚推送的提交相同；如需切换分支，先检查未提交修改，再明确执行 `git switch <工作分支>`。不要用强制重置覆盖 NUC 上已有工作。

## 在 NUC 构建

以下命令在 NUC 的 Windows PowerShell 中执行，支持 PowerShell 5.1：

```powershell
Set-Location 'F:\01-Project\Opensource\01-FluidX3D\src'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-nuc.ps1 -BuildName baseline-original
```

脚本默认工作根目录为仓库的父目录，使用工程原定的 `Release|x64` 和 `v142`，通过 `vswhere.exe` 查找 Visual Studio/MSBuild，选择实际包含该工具集配置的 VC targets。对于工程中的浮动 Windows SDK 版本 `10.0`，脚本选择完整安装的具体版本。构建前先求值并检查编译器、Windows SDK 和输出目录，再进行 `Rebuild`。无需在 SSH 会话中手动配置全局 `PATH`。

可显式传入 `-WorkspaceRoot 'F:\01-Project\Opensource\01-FluidX3D'`。`-PlatformToolset` 可用于有意进行的工具集对比，例如 `v143`，此时使用不同的 `BuildName` 保存对比产物；基线保持 `v142`。同一 `BuildName` 重建会替换该名称的正式产物，每次构建日志单独保留。构建脚本要求源码仓库干净，并记录 Git 提交、`src` tree、关键文件 blob、实际工具链、编译参数和 EXE 的 SHA256。

构建失败时不会发布成功的 `bin/<build-name>/build.json`，运行脚本因此不会误用之前的成功产物。运行快照和历史构建日志可用于回溯。

## 在 NUC 运行原始基线

```powershell
$devices = powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\get-opencl-devices.ps1 | ConvertFrom-Json
$gpu = @($devices | Where-Object {
    $_.platform -eq 'NVIDIA CUDA' -and $_.name -eq 'NVIDIA GeForce RTX 3060'
})
if ($gpu.Count -ne 1) { throw 'Expected exactly one RTX 3060; inspect the OpenCL device list.' }
$deviceId = $gpu[0].id
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-nuc.ps1 -BuildName baseline-original -CaseName benchmark -DeviceId $deviceId -ExpectBenchmark -TimeoutSeconds 900
```

`get-opencl-devices.ps1` 按原始 FluidX3D 相同的枚举顺序输出 JSON，字段为 `id`、`platform`、`name`、`vendor`、`driver`、`version`。先据此定位 RTX 3060，再显式传入本次的 OpenCL `id`；不能使用 `nvidia-smi` 编号代替，也不要把 0 写死。在 `logs/stdout.log` 核对实际使用的 `Device ID` 和 `Device Name`。其他有意运行的设备同样先查列表，再传入 `-DeviceId <编号>`；不传时使用 FluidX3D 自身的自动设备选择。

原始基线由源码启用 `BENCHMARK`、`D3Q19`、`SRT`、`FP16S`，网格为 `256 × 256 × 256`，黏度为 `1.0`，循环 1000 次、每次运行 10 步，共 10000 步。`FP16S` 用于分布函数存储压缩，算术仍使用 FP32。该 benchmark 没有外部输入，也不默认导出流场或图像，所以成功运行后的 `inputs`、`results` 目录可以为空。

运行前，脚本要求构建记录为 `schemaVersion=1`、`status=succeeded`，核对正式 EXE 的路径及 SHA256，并再次核对二进制快照的 SHA256。退出码为零且日志没有 FluidX3D `Error:` 才满足基本运行检查；传入 `-ExpectBenchmark` 还要求：

- 日志包含 `256 x 256 x 256 = 16777216` 网格信息；
- 日志包含 `D3Q19 SRT (FP32/FP16S)`；
- 日志声明 `Time Steps` 为 `10000`；
- 日志包含正数 `Peak MLUPs/s`，该行位于原始 benchmark 的完整循环之后。

`Peak MLUPs/s` 是此实现报告的峰值吞吐量，不等于整次运行的平均速度；首轮运行可能包含 OpenCL 内核即时编译等开销。该检查验证原始 benchmark 能完成，不能代替后续物理算例的守恒性、收敛性和精度验证。不使用 `-ExpectBenchmark` 时，`succeeded` 只代表进程正常结束且未检测到标准错误消息，具体算例仍需检查其输出。

标准输出、标准错误和运行记录都写入本次目录。运行超时为 1–86400 秒，默认 900 秒；超时会终止本次启动的进程树，确认进程退出并记录 `timed_out`，清理异常会记录 `cleanup_failed`。`run.json` 保存开始/结束 UTC 时间、耗时、退出码、进程 ID、设备请求参数、实际命令和所有日志路径。脚本运行时保持会话直到其返回，避免直接断开 SSH 中止记录写入。

Windows 原始 benchmark 结束时会调用 `std::cin.get()` 等待输入。脚本将标准输入连接到空文件并提供 EOF，使其自动返回；结束后删除该临时空文件。脚本仅面向无需用户交互的控制台算例，不适合需要键盘控制的交互图形模式。

## 输出与输入资源

FluidX3D 的默认导出路径是 `get_exe_path() + "export/"`，因此仅改变当前目录不能把结果写入 `workingdir`。运行脚本将正式 EXE 复制到 `bin/_runs/<case-name>/<run-id>`，在该快照目录创建本次专属 `export` junction，指向 `workingdir/<case-name>/<run-id>/results`。程序当前目录设为本次 `workingdir`。这样可保持原始 C++ 不变，默认导出结果进入每次运行独立的目录，同时所有 EXE 仍位于 `bin`。

该映射只覆盖默认的 `export` 路径，不能重定向算例中显式指定的其他绝对路径或 `get_exe_path()` 的其他子目录。后续算例应把模型、初始条件、配置等输入明确放入本次 `inputs`，并在代码或相应算例启动流程中明确指定路径；要复现的资源需记录来源和版本/哈希。

脚本不会自动部署任意 STL 模型、skybox 或其他资源。一些上游示例使用 `get_exe_path()+"../stl/..."`，这些相对位置在独立运行快照布局中不会自动成立，启用前必须明确调整资源路径或增加针对该算例的部署步骤。启用图形功能时也必须核对 skybox 路径。当前脚本自动创建新的运行目录，因此需要外部输入的算例应先扩展明确的输入部署接口，再执行；不要假定预先放在另一次运行目录里的文件会被复制。

运行快照、junction、结果和记录共同保留供回溯；它们属于外层工作目录，不纳入源码 Git。清理某次历史运行时，先确认其进程已经退出，删除 junction 本身时不要递归遍历其目标，再按需要删除该运行的 `workingdir` 和 `bin/_runs` 目录。

## SSH 会话收尾

通过 `ssh NUC` 完成操作后，检查本次开启的 SSH 会话、后台连接、隧道和转发；已完成用途的连接应关闭并确认。仅处理能确认归属本次操作的连接。若仍在执行必要任务，说明实际状态和保留原因；需用户审核的事项明确列出。每次回答结束前报告本次连接检查和清理结果。
