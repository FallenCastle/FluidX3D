# Solver-IBM：NUC 构建、运行与版本归档

当前正式版本为 **V1.0.0**，可执行文件为 `Solver-IBM.exe`。完整配置字段和操作说明见 [用户手册](user-manual-zh.md)，发布内容见 [V1.0.0 发布说明](releases/V1.0.0.md)。以下当前流程适用于配置驱动命令行版本；保留的上游/阶段历史文档可能仍写有 `FluidX3D.exe` 或旧 BuildName。

## 工作环境与目录

Mac 用于阅读、编辑、Git 提交和推送；所有求解器编译、程序调用和算例计算在 Windows NUC 完成，包括 `--version`、`--validate` 和测试脚本中启动的程序。连接方式为 `ssh NUC`。项目根目录的 `AGENTS.md` 在 Mac、NUC 各保留一份，暂不纳入 Git；源码、脚本和本说明纳入源码仓库管理。

NUC 工作根目录为 `F:\01-Project\Opensource\01-FluidX3D`：

```text
01-FluidX3D/
├── AGENTS.md                         NUC 本地长期规则
├── src/                              Git 仓库，不是仅 C++ src 子目录
│   ├── src/version.hpp               产品版本的统一来源
│   ├── scripts/
│   ├── configs/
│   ├── docs/
│   └── temp/<build-name>/<build-id>/  被 Git 忽略的构建中间文件
├── bin/
│   ├── solver-ibm-v1.0.0/
│   │   ├── Solver-IBM.exe
│   │   └── build.json                构建身份与校验值
│   └── _runs/<case-name>/<run-id>/    每次运行的 EXE 快照
├── workingdir/
│   ├── _builds/<build-id>/            build.json、evaluation.json、msbuild.log
│   └── <case-name>/<run-id>/
│       ├── run.json                  命令、构建、设备、状态、退出码、验证
│       ├── build.json                本次使用的构建记录
│       ├── inputs/
│       ├── results/                  求解器快照、记录、VTK、CSV 等
│       └── logs/                     stdout.log、stderr.log、runner.log
└── package/
    └── V1.0.0/                       固定的正式发布归档
```

`BuildId` 和 `RunId` 使用 UTC 时间戳及 Git 提交前缀。每次运行创建独立目录，不覆盖上次结果。`BuildName`、`CaseName` 只用于选择构建或结果分类；**算例由 `ConfigPath` 指定**，`-CaseName cavity` 不会自动创建方腔流。名称限制详见用户手册第 6 节。

## Mac 修改，经 Git 同步到 NUC

在 Mac 的 `FluidX3D/` 源码仓库内检查实际远端、分支和修改，明确暂存本次文件并提交推送：

```sh
git status --short --branch
git remote -v
git branch --show-current
git add <本次修改的文件>
git commit -m "Describe the change"
git push -u origin <当前工作分支>
git rev-parse HEAD
```

NUC 上核对当前分支和工作区，再拉取同一分支：

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
Set-Location "$root\src"
git status --short --branch
git remote -v
git branch --show-current
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw 'Git pull failed.' }
git rev-parse HEAD
```

确保两端提交一致，不强制重置未知修改。算例输入、结果和临时测试文件放在仓库外；构建脚本检查未提交和未跟踪文件。正式 V1.0.0 的精确源码基线是 `v1.0.0` 标签；发布包还保存源码快照和可克隆的 Git bundle。

## 在 NUC 编译

在 NUC 的 64 位 Windows PowerShell 中执行：

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
Set-Location "$root\src"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\build-nuc.ps1 `
  -WorkspaceRoot $root -BuildName solver-ibm-v1.0.0 -PlatformToolset v142
if ($LASTEXITCODE -ne 0) { throw 'Build failed; inspect workingdir/_builds.' }
Get-Content "$root\bin\solver-ibm-v1.0.0\build.json" -Raw | ConvertFrom-Json
& "$root\bin\solver-ibm-v1.0.0\Solver-IBM.exe" --version
```

脚本使用 `Release|x64` 和默认 `v142`，通过 `vswhere.exe` 查找实际安装的 Visual Studio/MSBuild、VC targets 和 Windows SDK；先核对工具链与输出目录，再执行 `Rebuild`。现有验收环境使用 MSVC `14.29.30133`、Windows SDK `10.0.22621.0`。源码随附 OpenCL 头文件/链接库，运行时仍需 GPU 驱动提供 OpenCL。

`build.json` 保存 Git 提交、源码树、实际工具链、编译参数和 EXE SHA256。成功必须同时满足脚本退出成功、记录 `status=succeeded` 和 EXE 哈希匹配。不能只看是否存在 EXE。同一 BuildName 重建会替换开发区该名称的产物；每次构建日志和运行快照独立保留。**已经发布的 `package/V1.0.0` 不通过重建覆盖。**

模型、参数、STL 或边界只改 JSON 时无须重建 C++；改变 C++ 或编译选项后重新构建并完成对应验收。尝试其他工具集时使用新的 BuildName。

## 选择设备并运行配置

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
Set-Location "$root\src"
$devices = powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\get-opencl-devices.ps1 | ConvertFrom-Json
$devices | Format-Table id, platform, name, driver
$gpu = @($devices | Where-Object { $_.name -eq 'NVIDIA GeForce RTX 3060' })
if ($gpu.Count -ne 1) { throw 'Inspect the OpenCL list and choose the intended device.' }
$deviceId = [int]$gpu[0].id

& "$root\bin\solver-ibm-v1.0.0\Solver-IBM.exe" `
  --config "$root\src\configs\periodic-lattice.json" --validate
if ($LASTEXITCODE -ne 0) { throw 'Configuration validation failed.' }
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-nuc.ps1 `
  -WorkspaceRoot $root -BuildName solver-ibm-v1.0.0 -CaseName periodic-demo `
  -ConfigPath "$root\src\configs\periodic-lattice.json" -DeviceId $deviceId `
  -TimeoutSeconds 900
if ($LASTEXITCODE -ne 0) { throw 'Run failed; inspect run.json and logs.' }
```

OpenCL 设备编号与 `nvidia-smi` 编号不等价，每次按实际列表选择。`--validate` 不初始化 GPU；STL 体素化、探针落入固体或受力归属等检查需要 `-PrepareOnly`。预处理输出第 0 步，正式运行会重新初始化，不从预处理结果续算。

运行脚本核对构建记录和 EXE 哈希，保存本次二进制快照。旧默认 `export/` 路径通过该快照目录的 junction 映射到本次 `results/`；配置模式同时显式指定求解器输出目录。配置和 STL 的有效快照在 `results/effective-config.json`、`results/inputs/assets/`，不要把 `resolved-config.json` 当作可运行输入。

标准输出、标准错误和运行记录均保留。正常计算要求外层 `run.json.status=succeeded`、内层 `completion.json.status=succeeded` 且实际步数等于请求步数；预处理的内层状态为 `prepared`、实际 0 步。进程成功不等于物理精度达标，还需查看守恒、受力、剖面和收敛依据。

超时范围为 1–86400 秒，默认 900 秒。脚本只终止自己启动的进程树，记录 `timed_out`；无法确认清理完成时记录 `cleanup_failed`。运行及记录写入结束前保持 SSH 会话。

## 正式发布包

每个正式版本必须在 `package/V<major>.<minor>.<patch>/` 单独归档。V1.0.0 的固定位置为 `F:\01-Project\Opensource\01-FluidX3D\package\V1.0.0`。至少包含：

- 原样源码快照、Git bundle、原有许可证与第三方许可证。
- `bin/Solver-IBM.exe` 和原始构建记录。
- 用户手册、发布说明、交接文档。
- 全部算例配置、STL 及其他输入，完整测试脚本和必要基准资料。
- 历史与本版本验收报告、文件清单和 SHA256。

包内 `manifest.json` 校验文件清单中的全部文件，清单自身除外。保留必要对照 VTK；不归档全部历史运行流场。历史输入和报告保留原文、失败记录及来源路径，不把旧数据改成当次发布的验证结果。P1/P2 等历史对照程序保留原始程序名和 build.json。

运行正式包使用 `source/scripts/run-package.ps1`，详见[用户手册第 2.5 节](user-manual-zh.md#25-使用正式发布包)。输出写在包外 `workingdir/`，不修改包内文件。包中 `source/` 不含 `.git`，重建时先从 `source.git.bundle` 克隆到新的工作区。

发布先在独立暂存目录整理并校验，完成包内运行验证后再固定为对应版本目录。若发现已发布版本需要修复，发布新补丁版本，不覆盖已有包或移动标签。Git 标签、代码版本、EXE 版本、文档和 manifest 必须对应同一正式版本。

## 开发阶段与版本号

V2.0 是下一阶段名称：开发期间仍使用 `V1.x.x`，功能开发完成且测试通过后才正式发布 `V2.0.0`。之后 V3.0 开发期间使用 `V2.x.x`，通过发布验收后才使用 `V3.0.0`，依次类推。开发版本的小版本/补丁号随实际变更递增，每次更新统一修改 `src/version.hpp` 并同步文档和记录。

新阶段先确认需求、边界和验收标准，不因阶段名称自动启用此前讨论的功能建议。长期规则以两端项目根目录 `AGENTS.md` 为准，交接入口见 [V1.0.0 交接文档](handoff-v1.0.0.md)。

## 历史产物与 SSH 收尾

过去 `FluidX3D.exe`、`config-runner*` 和 `baseline-original` 对应的构建及验收证据不改名、不伪造版本身份。旧硬编码 benchmark 的 `-ExpectBenchmark`、位置式设备参数及 `setup.cpp` 选算例方式不适用于当前配置驱动 EXE；历史重放使用明确保留的旧程序及配套说明。

完成 NUC 操作后，检查本次开启的 SSH 会话、后台连接、隧道及端口转发；用途结束的连接关闭并确认。只处理能确认归属本次操作的连接，不关闭用户或其他任务的会话。如果连接仍承载必要任务，应检查实际状态并说明保留原因。每次回答结束前如实报告检查及清理结果。
