# 断点续算验收阈值表（冻结版）

**状态：已冻结** — 2026-10-15，于 `feature/checkpoint-restart` 分支实施开始前定稿。依据 r2 开发计划 §9/§17（用户批准 D3 采用数值容差判据）制定本表；**实施后任何测试失败不得放宽本表阈值**（AGENTS 规则），阈值变更只能通过新版本计划文档修订并重新冻结。

## 1. 比较模式

| 模式 | 适用 | 判据 |
|---|---|---|
| **模式 A：同构建比较**（主判据） | 全部 T1/T2 等价性测试：参考运行 A 与恢复运行 C 使用**同一 EXE、同一 GPU、同一驱动** | Tier1 数值状态**逐字节一致**；Tier2 共同调度输出**逐字节一致**；`statistics.json` 逐字节一致 |
| **模式 B：跨构建比较**（容差判据） | 仅用于：T5-29 基线对照（V2.0.0 正式 EXE vs 候选 EXE）、开发期跨驱动/跨工具链重建后的复核 | 第 3 节容差表 |

模式 A 是缺陷检出主力：同构建下 LBM 步进与宿主双精度累计均确定性可复现，任何非零偏差即为状态恢复缺陷。模式 B 的容差仅吸收编译器/驱动代码生成的可变性。两种模式的测试报告都必须记录**实际观测最大偏差**（模式 A 预期为 0）。

## 2. 离散字段规则（两种模式通用，不容差）

`flags`、`material`、`object_id` 必须**逐单元精确一致**；`body-<i>-cells`（单元索引数组）必须逐元素一致。任何离散字段不一致即判失败。

## 3. 模式 B 容差表（冻结值）

场量比较在相同网格全域上进行；`L2_rel = ‖a−b‖₂ / max(‖a‖₂, ε)`，`ε=1e-30`。

| 量 | 范数/度量 | 阈值 |
|---|---|---|
| `fi`（DDF，按存储格式解码为 float 后比较） | L2_rel / max 绝对 | 1e-4 / 1e-5 |
| `rho` | max 绝对 / L2_rel | 1e-5 / 1e-6 |
| `u`（各分量） | max 绝对 / L2_rel | 1e-6 / 1e-6 |
| `T` | max 绝对 / L2_rel | 1e-5 / 1e-6 |
| `phi` | max 绝对 | 1e-5 |
| `mass`、`massex` | max 绝对；总质量相对偏差 | 1e-5；1e-6 |
| `contact_angle` | max 绝对（弧度） | 1e-6 |
| `thermal_capacity`、`thermal_conductivity`、`thermal_source` | max 绝对 | 1e-6 |
| `body-<i>-temperatures`、`body-<i>-positions` | max 绝对 | 1e-5；1e-6 |
| 宿主标量（budget 6 项、4 个守恒目标、`dynamic_energy_source_per_step`、Moments 的 mean/m2） | 逐项：\|x\|>1e-12 时相对偏差，否则绝对 | 1e-9 / 1e-12 |
| CSV 数值列（monitor、free-surface、conservation-budget、boundary-flux、object-motion、probes、analysis、forces、surface-levels） | 逐行逐列相对偏差（\|x\|>1e-12）或绝对偏差 | 1e-6 / 1e-9 |
| `statistics.json` 的 mean、std_population | 相对 | 1e-6 |
| VTK 浮点数组 | 同对应场量行 | 同上 |
| VTK 维度/origin/spacing/元数据、CSV 文本列（id 等） | 精确一致 | — |

**CSV 比较窗口（仅模式 B）**：混沌敏感算例（自由液面晃荡/溃坝、Smagorinsky 湍流）取恢复点 S 后前 500 个输出行；层流/扩散/稳态类算例取全程。模式 A 无窗口限制（全程逐字节）。

## 4. Tier3 运行元信息（两种模式通用）

`completion.json.restarts[]`（次数、来源步、时间戳递增、配置哈希）、`used_snapshot_assets`、退出码、警告日志、锁行为：按字段断言正确性，不与连续运行做字节比较。

## 5. 等价性测试的定点约定

- 比较终点 N 相同（模式 A/B 均是）；延长续算场景按 r2 §7.2 枚举 S 步历史记录后，在共同调度步集合上比较。
- 参与 Tier1 比较的检查点 = A、C 各自 `t == N` 的终态检查点；字段清单 = r2 §4.1 全部保存项 + §4.2 宿主数值项。
- 模式 B 基线对照的冻结用例集（T5-29）：`configs/` 中三项综合容器算例、一个共轭传热算例、一个自由液面算例、一个 FP16S 单相算例；具体文件名在 `scripts/test-checkpoint.py` 中固定并随代码入库。

## 6. 审计要求

每次验收运行输出 `observed-deviations.json`：全部被比较量的实际偏差（模式 A 亦输出，预期恒为 0），与判定结果一并归档 `reports/`。失败时不得调整本表；只能修复实现或按修订流程重新冻结阈值。
