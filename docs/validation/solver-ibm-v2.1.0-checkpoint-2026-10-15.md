# Solver-IBM V2.1.0 断点续算验收记录（开发版）

**状态：开发版本验收（`release_status="development"`）。** 依据用户决策 D5（2026-10-15），本版本验收后先作为开发版本试用，不建立 `package/V2.1.0` 与 `v2.1.0` 标签；正式封版另行决定，届时本记录随封版复核。

## 1. 固定身份

| 项目 | 值 |
|---|---|
| 产品 / 版本 | Solver-IBM 2.1.0（development） |
| 分支 | `feature/checkpoint-restart`（基线 `58f44e5` = 标签 `v2.0.0`） |
| 验收提交 | `4e15cf2`（Fix cross-version VTK comparison (payload-level) and suite UTF-8 IO encoding） |
| 构建 | `bin/checkpoint-v2.1.0-dev`，`build.json.gitCommit = 4e15cf2`，status succeeded |
| EXE SHA256（前缀） | `121480b09951dcd0…`（套件报告的 `executable_sha256` 与构建记录一致） |
| 工具链 | MSBuild 18.9.1（VS 18 Community），平台工具集 v142 / MSVC 14.29.30133，Windows SDK 10.0.26100.0，Release\|x64 |
| 服务器 / 设备 | desktop-msi（SEVERUS）；OpenCL device 0 = NVIDIA GeForce RTX 4070 Ti SUPER 16376 MiB，驱动 610.88 |
| 基线对照 EXE | `package/V2.0.0/bin/Solver-IBM.exe`，SHA256 `3ab5c696aa38e5fd919a6b1236e0b330347058a097f99f40b2a606d3d908c4cd`（与 V2.0.0 交接固定身份一致） |

## 2. 验收判据

`docs/validation/checkpoint-tolerance-thresholds.md`（实施前冻结）。本轮全部等价性比较为**模式 A（同构建逐字节）**：Tier1 数值状态逐字节 + Tier2 数值输出逐字节 + Tier3 元信息字段断言；离散字段（flags/material/object_id/body cells）任何模式均精确一致。模式 B 容差表本轮未触发（无跨构建比较需求），保留用于开发期跨驱动/跨工具链复核。

## 3. 验收结果（九套，全部通过）

| 套件 | 结果 | 证据 |
|---|---|---|
| `test-checkpoint.py`（45 项） | **45/45 passed** | 服务器 `workingdir/checkpoint-validation/20261015T123026096326Z/report.json`（Mac 归档 `reports/checkpoint-m5-regression-baseline-2026-10-15/checkpoint-suite-report.json`） |
| t5-baseline-comparison（含于上） | 通过：V2.0.0 正式 EXE vs 候选，4 个冻结用例（FP16S 单相 / 共轭传热 / 自由液面晃荡 / 三项综合容器）共 78 个数据产物（VTK 结构+载荷、CSV、statistics.json）逐字节一致；身份文件按设计排除 | 同上 |
| P1 `test-config-runner.py` | exit 0 | `workingdir/checkpoint-m5/p1.log`（首轮链） |
| P2 `test-config-p2.py` | succeeded（25 tests / 6 profiles） | `workingdir/p2-validation/20261015T123159266707Z/report.json` |
| 存储 `test-runtime-storage.py` | exit 0 | `workingdir/checkpoint-m5/storage.log` |
| P3 `test-config-p3.py` | succeeded（214 tests / 96 profiles） | `workingdir/p3-validation/20261015T123208158813Z/report.json` |
| 扫描 `test-parameter-study.py` | exit 0 | `workingdir/checkpoint-m5/study.log` |
| V2 物理 `test-v2-physics.py` | exit 0 | `workingdir/checkpoint-m5/v2-physics.log` |
| V2 场景 `test-v2-scenarios.py` | exit 0 | `workingdir/checkpoint-m5/v2-scenarios.log` |
| V2 矩阵 `test-v2.py` | exit 0 | `workingdir/checkpoint-m5/v2-matrix.log` |

重跑说明：首轮链中 checkpoint/p2/p3 三套失败，根因均非产品缺陷——p2/p3 为测试脚本打印中文用例名在重定向 stdout 下的 cp1252 编码崩溃（修复：运行环境注入 `PYTHONIOENCODING=utf-8`，并同步修复 `test-package.py` 的子进程环境，否则九套封包验收在本机同样崩溃）；checkpoint 套件的 t5 基线对照因 VTK 文件头内嵌版本字符串而跨版本必败（修复：改为结构字段+二进制载荷比较，口径与 `test-runtime-storage.py` 一致）。修复后三套重跑全绿；其余六套首轮已用同一数值二进制通过（两次运行之间仅脚本/文档变更，`build.json.sourceTree` 不变），不重复执行。

## 4. 检查点套件覆盖摘要（45 项）

- **T1 数值等价（16）**：FP32/FP16S 单相、共轭传热、热边界累计、晃荡（3000 步、massex 非零）、充排液（开放边界目标+焓流）、溃坝、平移启停（纯动态质量投影）、多体正弦、运动物体+非默认接触角 60°、动态热历史闭环、三项综合容器、稀疏统计（count=1 Welford）、奇数间隔同相/错相调度；**真实强杀**（首检查点后 0.3 s TerminateProcess → 恢复续算 20000 步与连续参考逐字节一致）；**双重启链**（40→80→120，restarts 链断言）。
- **T2 提交/恢复协议（15）**：fail_write/short_write/fail_verify（退出码 4、tmp 清理、旧检查点可续）；crash_before_rename（70，tmp 残留被忽略）；crash_after_rename（71，已发布未指向目录按 newest-first 采用）；crash_during_cleanup（72，超保留在下次提交收敛）；latest.json 损坏；字段损坏 → 隔离+回退+跨原步号重放；全部损坏 → 退出码 3；host-state 损坏回退；CSV 半行截断+杂散 VTK 清理；修复可重入（修复后续算中再强杀 → 二次重启收敛）；finish-only 收尾（statistics 与连续参考逐字节一致，不推进一步）；stale lock 破除；active lock 拒绝。
- **T3 契约拒绝（13）**：steps 收缩、物理参数/存储/analysis 变更、steps↔duration 切换、资产内容变化 → 退出码 5 且既有输出与检查点零修改（前后哈希断言）；数值身份/产品版本/字段缺失/尺寸/字节序元数据篡改 → 退出码 5；资产缺失 → 快照回退 + `used_snapshot_assets` 记录 + 续算逐字节一致。
- **T4 资源策略（2）+ T5 基线对照（1）**：keep=1 保留；开销信息性测量；禁用路径同 GPU 基线对照（见上）。

## 5. 过程证据（Mac 侧 reports/）

| 目录 | 内容 |
|---|---|
| `reports/checkpoint-m0-baseline-2026-10-15/` | desktop-msi 前置核验：仓库状态、v2.0.0 基线构建（sourceTree `b3b27571…` 与发布身份一致）、冒烟、V2.0.0 包完整性（8152 文件、manifest SHA256 与交接一致） |
| `reports/checkpoint-m1-skeleton-2026-10-15/` | 单相 FP32 续算三层判据验证 + Windows 目录 fsync 处置记录 |
| `reports/checkpoint-m2-allmodules-2026-10-15/` | 全模块 13/13 + 两个根因（RC1 `t_last_update_fields`、RC2 F 场跨步状态）完整证据链 |
| `reports/checkpoint-m3-m4-protocol-integration-2026-10-15/` | 正式套件 44/44（M3 时点）+ wrapper 恢复实测记录 + M3 期缺陷修复清单 |
| `reports/checkpoint-m5-regression-baseline-2026-10-15/` | 九套结果：首轮链 summary、重跑三套报告、构建记录 |

## 6. 实施期设计修订

见开发计划 r2 §18（DEV-1…DEV-6）：F 场重分类（格式版本 2）、`set_time_step` 缓存对齐、Windows 目录 fsync 不可行的文档化处置、拒绝/回退退出码分类、sparse-moments 替代空统计用例、git bundle 中转通道。全部由实测证据驱动，未放宽任何冻结阈值。

## 7. 遗留与试用注意

- 开发版检查点格式版本 2、产品版本 2.1.0-development：正式封版（版本/状态字符串变化）后旧开发检查点按契约拒绝加载，属预期。
- `package-release.py`/`test-package.py` 九套门槛已就位，但因 D5 暂不打包，未走完整封包演练；正式封版时随 `test-package.py` 全量执行。
- 服务器 `workingdir/checkpoint-*` 开发产物与根目录 `cr-thin.bundle` 为过程工件，试用期结束后清理。
