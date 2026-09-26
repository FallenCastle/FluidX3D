# Solver-IBM V1.0.0 交接文档

本文件用于 V1.0.0 发布交接及新对话进入 V2.0 阶段。当前产品名为 **Solver-IBM**，主程序为 **Solver-IBM.exe**；它是在 FluidX3D 基础上的修改版本，上游作者、算法来源、许可证和第三方许可继续保留。

## 接手后的第一步

1. 阅读 Mac 项目根目录 `AGENTS.md`；操作 NUC 前读取 NUC 根目录对应规则。
2. 核对工作区实际 Git 状态、远端、分支和提交，读取发布包 `manifest.json`、原始 `bin/build.json` 和本版本验收记录。
3. 阅读 [用户手册](user-manual-zh.md) 与 [发布说明](releases/V1.0.0.md)，确认当前字段和支持边界。
4. **先与用户确定 V2.0 具体功能、范围、接口及验收标准，再开始功能开发。** 收敛监测、升阻力系数、报告、续算、出口边界等此前只作为候选建议，尚未自动构成下一阶段需求。

## 发布基线与目录

| 项目 | 约定 |
|---|---|
| 正式版本 | V1.0.0 |
| Git 标签 | `v1.0.0` |
| 统一版本源 | `src/version.hpp` |
| 主程序 | `Solver-IBM.exe`，通过 `--version` 查询 |
| 发布构建名 | `solver-ibm-v1.0.0` |
| Mac 项目根目录 | `/Users/czy/Data/01-work/02-project/02-opensource/05-FluidX3D` |
| Mac 源码仓库 | 上述目录的 `FluidX3D/` |
| NUC 连接 | `ssh NUC` |
| NUC 工作根目录 | `F:\01-Project\Opensource\01-FluidX3D` |
| NUC 源码 | `src/` Git 仓库 |
| 构建与运行 | `bin/<BuildName>/`、`workingdir/<CaseName>/<RunId>/` |
| 正式包 | `package/V1.0.0/` |

提交号、EXE SHA256、实际工具链和验证报告以包内记录为准，不仅凭目录名判断版本。`source/` 是不含 `.git` 的原样源码快照，重建时从 `source.git.bundle` 克隆到包外新工作区。详细流程见 [NUC 工作说明](nuc-workflow.md)。

Mac 只编辑、阅读、维护 Git；编译、求解器运行及测试都在 NUC，不能在 Mac 调用 EXE 或开展计算。执行顺序为 Mac 修改 → Git 提交推送 → NUC 拉取 → NUC 编译与验收。连接 NUC 后必须在每次工作结束前检查本次 SSH、隧道和转发，关闭已完成用途的自有连接。

## 当前产品能力

已经实现“编译一次，通过 JSON 配置和 STL 运行所支持的算例”：

- 单 GPU、三维单相流，格子/SI 单位，黏度或 Re 与参考尺度输入。
- D3Q19/D3Q27 × SRT/TRT × none/smagorinsky × FP16S/FP32 共 16 种模型组合。
- Cs、Λ 可配置，FP16S/FP32 在同一 EXE 中选择。
- 长方体计算域，静态 STL 变换与并集。
- 六外表面支持周期、静止无滑移、平衡边界和固定位置运动壁面；支持面内矩形区域、优先级及冲突检查。
- 常量体积力、探针、压力、分组受力、时间均值和总体标准差。
- VTK/CSV/JSON、输入快照和 Git/二进制/设备来源追溯。
- 参数扫描生成、资产完整性检查、顺序运行及失败保留。

默认模型为 D3Q19/SRT/Smagorinsky/FP16S。JSON `schema_version=1` 是配置格式版本，不随产品版本号机械递增。

产品名称中的 IBM 不代表已在本轮新增某种浸入边界实现。STL 仍按现有体素固体机制处理；固定运动壁面不等同于物体在空间中移动。

## 代码入口与职责

| 文件 | 职责 |
|---|---|
| `src/version.hpp` | 产品名称、版本和上游来源定义 |
| `src/config.hpp`、`src/config.cpp` | 配置结构、严格解析、单位换算、范围及条件约束 |
| `src/config_runner.cpp` | CLI、设备、STL 预检/快照、初始化、边界、步进及输出组织 |
| `src/config_analysis.hpp` | 探针、全域与受力采样、CSV 和 Welford 时间统计 |
| `src/solver_options.hpp` | 运行时数值模型选择及模型参数 |
| `src/lbm.hpp`、`src/lbm.cpp` | LBM 主机端、内存和运行时内核参数 |
| `src/kernel.cpp` | OpenCL 数值与诊断内核 |
| `src/defines.hpp` | 编译宿主能力；用户切换模型应改 JSON |
| `schemas/case.schema.json` | 编辑器辅助 schema；不能代替程序的单位/几何/边界检查 |
| `configs/` | 配置及参数扫描模板 |
| `scripts/build-nuc.ps1` | Git/工具链核对、构建、身份记录 |
| `scripts/run-nuc.ps1` | 独立运行目录、EXE 快照、超时、日志与完成检查 |
| `scripts/parameter-study.py` | 参数笛卡尔积、资产快照、完整性检查及批次运行 |
| `scripts/package-release.py`、`scripts/run-package.ps1`、`scripts/test-package.py` | 发布包组装、包内程序运行和包验证入口 |

新增字段需同步更新解析器、schema、用户手册、示例及有关测试。输出中的派生配置不是再次运行的输入；重放使用 `effective-config.json`。统计采样不能改变求解结果，这一性质已有严格数组对照测试。

## 验证资料与复现依赖

历史设计与验收在 `docs/config-runner*.md`、`docs/validation/`，包内 `tests/reports/` 保存历史及本版本报告。历史失败实验原样保留，不覆盖或仅保留最终成功摘要。

| 验证脚本 | 覆盖内容 | 包内必要基准 |
|---|---|---|
| `test-config-runner.py` | CLI、非法配置、周期流、SI、STL/边界、快照、Boeing/Ahmed | `reference/boeing-baseline/` 的 run.json 和 6 个必要 VTK |
| `test-config-p2.py` | 统计、压力换算、体积力、运动壁面、受力、通道解析解及批次失败 | 解析解为主，脚本生成 cube STL |
| `test-runtime-storage.py` | 默认/显式 FP16S、FP32、内存估算、快照及独立精度对照 | `reference/fp16-reference/`、`fp32-diagnostic-build/` |
| `test-config-p3.py` | 16 模型组合、Cs/Λ、默认兼容、剪切波细化、SI 和扫描 | `reference/p2-build/` |
| `test-parameter-study.py` | 资产自包含、JSON Pointer 拒绝、输入篡改检测 | 脚本生成资产和负向输入 |
| `measure-p2-overhead.py` | 历史 P1/P2 含启动与 I/O 的对照耗时 | `reference/p1-build/`、`p2-build/` |

包内脚本可通过 `--repository-root`、`--configs-root`、`--executable` 等显式路径运行；需要基准的套件使用 `--reference-root`，具体参数以脚本 `--help` 为准。临时计算输出放包外。测试脚本彼此导入辅助函数，应保留整套相邻文件。

必要基准中的历史程序保留 `FluidX3D.exe` 与原始 `build.json`，不改名或伪造 V1.0.0 身份。固定 FP16S 参考配置和 cube 文件要一起保存；Boeing 的第 0/1000 步 rho/u/flags 是数组一致性基准，属于必要对照资料。其余历史 VTK 不纳入正式包。

`tests/historical-inputs/` 保留历史输入原字节：重复 JSON key、损坏 STL、故意缺文件和篡改 study 都可能是正确的负向测试。不要统一解析重写或自动修复它们。历史文件中的旧绝对路径是来源记录，不意味着包要求依赖旧计算目录；复现套件通过独立包内路径重新组织输入。

P3 `--matrix-reference` 仅允许引用与当前 EXE SHA256 完全相同的完整矩阵。重新编译产品后不能复用旧 EXE 的报告跳过模型矩阵。

<!-- RELEASE_VALIDATION: 本次发布完成后由发布负责人填写实际验收位置与结论。 -->
**V1.0.0 本次发布状态与验证结论待最终记录填充。** 接手时必须查看发布说明和 `tests/reports/` 中本次报告，不能将以下历史证据当作新 EXE 的验收结果。

## 已知数值和接口限制

历史 P3 48 组 FP32 通道达到既定速度/受力阈值；FP16S 的 48 组中有 32 组未达到相同阈值，弱强迫及细通道中量化误差明显。保留这一限制，不把运行成功等同于精度通过。历史三维剪切波曾在 24³ 网格略超过 3% 阈值，后续三网格细化显示误差下降，32³ 通过；初次失败报告与追加记录同时保留。

`equilibrium` 固定密度与速度；当前没有独立压力出口/零梯度出口。`moving_wall` 只允许固定几何位置和切向速度，并要求换算后的指定密度为 1。STL 为静态体素固体，不能给部分三角面单独指定入口或运动。几何素材的结构检查不等同于封闭性、全局法向、体素或 CFD 精度验收；14 类素材只有部分具有本接口的运行配置。

当前未开放图形、动态 STL、自由液面、热、多 GPU、自动收敛停止、断点续算。V1.0.0 的输入快照用于重新初始化，不能当作分布函数 checkpoint。Boeing/Ahmed 回归和短算不构成外流场工程精度验证。

## 版本与发布规则

- 每个正式版本放在 NUC `package/V<major>.<minor>.<patch>/`，包含源码、手册、程序、交接、全部算例输入、测试脚本、必要基准和验收报告。
- 已发布包和标签固定保留；修复后发布新版本，不覆盖既有证据。
- V2.0 阶段开发使用 V1.x.x，功能全部完成且测试通过后发布 V2.0.0；后续 V3.0 开发使用 V2.x.x，正式验收后发布 V3.0.0，依次执行。
- 小版本/补丁版本随实际变更递增。产品版本以 `src/version.hpp` 为唯一代码来源；构建、程序、文档、标签和 manifest 保持对应。
- 阶段名称不等于已发布版本，不提前把开发包标为下一个主版本正式发布。

这些长期规则应同时存在于 Mac 和 NUC 项目根目录 `AGENTS.md`；规则文件暂不纳入源码 Git。

## 新对话的起始任务

新对话名称建议为“Solver-IBM V2.0 开发”。初始输入为本交接文档、V1.0.0 发布目录、Git 标签和最终验收记录。先梳理需求和验收标准，向用户确认未确定项，然后在发布基线之上开发。保留已有工作，不移动发布标签、不更改 V1.0.0 正式归档。
