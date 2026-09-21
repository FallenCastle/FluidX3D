# P0 + P1 配置执行器：实施契约

2026-09-21，设计已确定，实施从此文档提交之后开始。用户明确：纯命令行，同时支持格子/SI 单位，Agent 在 NUC 编译并完成短算验收，使用 Git 管理。本文件为本轮实施依据，取代前期建议中 PNG/相机及 SI 延后的安排。

## 范围

- 单 GPU、三维静态单相流，固定 D3Q19/SRT/FP16S/SUBGRID/EQUILIBRIUM_BOUNDARIES。
- 关闭 GRAPHICS、INTERACTIVE_GRAPHICS、INTERACTIVE_GRAPHICS_ASCII。输出 VTK、CSV、JSON 和日志，无图片。
- 支持零个/一个/多个二进制 STL 固体、静态固体并集、均匀初场和盒状初场覆盖。
- 六面/面上矩形区域的静止无滑移、固定 rho/u 的 equilibrium，以及整轴成对周期边界。
- 不加入压力出口、运动部件、自由液面、热传递、受力、重启动、多 GPU 或数值模型运行时切换。

## 输入契约

UTF-8 JSON，`schema_version=1`；未知字段、重复键、类型错误、不支持的枚举、非法组合均拒绝。采用固定版本 nlohmann/json v3.12.0 单头文件与许可证，纳入 Git，不在 NUC 构建时联网取依赖。官方来源：https://github.com/nlohmann/json/releases/tag/v3.12.0 ，集成说明：https://json.nlohmann.me/integration/ 。使用其解析事件检查重复键，项目自身负责语义校验。

- `case`: name（记录用途）。
- `solver`: 可省略；如提供，lattice/collision/storage/turbulence 必须匹配固定能力。
- `units`: mode 必填（lattice/si）。SI 还需 `reference_density`，以及 `dt` 或 `reference_velocity` + `lattice_velocity` 二选一，后者按 dt=u_lattice*dx/U_SI 计算。不得自动修改物理参数来提高稳定性。
- `domain`: lattice 模式为 `cells` 或 `aspect_ratio` + `memory_budget_mb`；SI 为 `length` + `dx`，向上取整到整数格点，输出实际域长度。两种模式均可指定 `origin`，默认为零。
- `fluid`: `rho` 为正；`nu` 或 `reynolds` + `reference_length` + `reference_velocity` 二选一。数值采用所选单位制。
- `initial`: velocity 必填；rho 缺省取 fluid.rho；可选 regions 数组，每项 box_min/box_max/rho/velocity，重叠以数组顺序覆盖并明确记录，仅用于初场，不覆盖固体或最终边界。
- `geometry`: 数组，允许为空；每项 id、file、transform。file 相对于配置目录解析。transform 支持 fit（size、center、axis、degrees）或 scale（factor、pivot、translation、axis、degrees）。fit 的 size/center 使用配置长度单位；scale.factor 为每 STL 坐标单位对应的配置长度。axis/degrees 可省略为不旋转。
- `boundaries`: 数组，每项 id、faces、type、priority（默认0）、可选 region 的 min/max（二个切向坐标）；equilibrium 需 rho/velocity。periodic 仅整轴成对且不可与同轴面上其它规则混用。
- `run`: steps 或 duration 二选一，duration 只用于 SI；monitor_every 为正步数间隔。
- `output`: vtk_fields（u/rho/flags）、vtk_every（0为仅最终）、initial（默认true）。prepare-only 强制导出初始 flags；正常运行始终记录最终状态。输出目录从 CLI 提供，缺省为配置旁 results，已有非空目录拒绝覆盖。

所有数值要求有限且在目标类型范围内；rho、nu、dt、dx 和尺度为正，轴角的非零转动必须有非零轴。网格各维至少3，格点数检查整数溢出及设备资源限制。显存预算用于网格推导，不宣称覆盖全部驱动峰值；预估包含已知字段、STL 缓冲和并集掩码，实际分配失败正确退出。

## 坐标与边界

统一用户坐标：domain.origin 为网格盒角点，格点中心为 origin+(i+0.5)*dx。格子模式 dx=1。

上游 voxelizer 射线使用整数索引格点；传入其顶点必须使用 `(p-origin)/dx-0.5`。上游 VTK 默认居中原点；配置执行器导出原点改为用户 origin+0.5*dx，以免错位。保留上游其它调用的默认行为。

fit：绕源原点旋转，旋转后包围盒最长边缩放为 size，包围盒中心放到 center。scale：p=translation+R*(factor*(p_stl-pivot))；用于固定尺寸及多部件装配。边界 region 采用格点中心判断、闭区间；切向坐标按剩余轴的 x/y/z 顺序。

多 STL 独立体素化到临时掩码，在主机合并固体位后一次写回；不能简单顺序调用当前 voxelizer（其清除旧标记的逻辑可能删除先前固体）。掩码增加的主机开销纳入估算。体素化前完成包围盒检查，初始化后检查固体格点非空、各边界覆盖数量及冲突。

每个非周期外表面格点都必须有规则覆盖。相同优先级相同赋值合并、不同赋值报错；不同优先级取较高者。周期规则只声明拓扑，不在与其它轴墙面交线处覆盖 flags。STL 固体与 equilibrium 冲突报错，与 no_slip 合并。域外几何拒绝裁剪。默认不自动修复 STL。

## CLI 与结果

`--help`、`--capabilities`、`--list-devices`；`--config FILE [--device ID] [--output DIR] [--validate | --prepare-only]`。

validate 不构造 LBM，不编译 GPU 内核；检查配置、STL 与可静态判断的约束。prepare-only 创建求解器、体素化和初场，输出 t=0 VTK，不推进步数。没有 config 时打印帮助，不执行旧算例。保留旧的数字设备参数入口仅用于明确的 legacy 构建，不在新配置执行器中静默接受。

SI 换算：rho_l=rho/reference_density，u_l=u*dt/dx，nu_l=nu*dt/dx²。记录 tau=0.5+3nu_l、参考 Re、最大指定速度的格子马赫数；非有限/不可表示数值拒绝。SI 运行时长向上取整为整数步，并记录实际完成物理时长。

每次运行保存 original-config.json、effective-config.json、resolved-config.json、inputs/assets、manifest.json、completion.json、monitor.csv、VTK 和状态报告。文件快照记录 SHA256；最终计算只使用快照输入。CSV 在监测时同步 rho/u 并检查有限值、正密度，记录非固体格点的质量、速度最大值和密度范围；开放边界不要求总质量严格恒定。步进到下一个输出或监测事件，最后一次输出不重复。

CLI 明确设备传给 LBM 设备选择，不能让 --config 混入全局设备编号数组。工作线程错误必须回传非零退出码；Windows 不等待按键。脚本超时继续使用现有按所属进程树清理机制。

## P0 对照与验收

基线提交 `1341990eda5ec2852915b69ff7fee8aa07781c60`，源代码不在原分支改写。Boeing STL SHA256 `e8fe5827330bc2adfd5161e42c9d5fd6850d909f7581e0d252e30e3dd623f93d`。

原 256 MiB 推导网格预计为 [170,339,85]（公式与舍入分析，NUC 实际运行需确认），Re=1e6、参考长度 Nx、速度[0,.075,0]、1000步。原生几何 center=[(Nx-1)/2,.55*Nx,(Nz-1)/2]，新角点坐标相应加0.5，fit size=Nx，绕x旋转-15度。六面 equilibrium 的速度应与旧初始化结果对照，不能仅比较名字。旧产物可供对照，但运行前核实哈希及输入，绝不假定历史运行已发生。

在 NUC 保存一个仅移除图形调用的硬编码基线构建，再与配置构建对照（基线由单独的 Git 提交/构建名保存，不混入最终运行模式）。比较初始 flags、rho/u 与最终场的数值；VTK header 原点差异单独核对，不能拿文件哈希误判场数据不同。同设备优先严格比对，若需要容差必须解释原因。该回归证明配置化保持行为，不等于验证 Boeing 的工程精度。

测试集合：

1. 错误/未知/重复字段、冲突单位、非法模型、缺文件/坏STL、负黏度、不配对周期边界、区域冲突、非空输出目录，验证非零退出且不等待按键。
2. 无 STL 均匀周期流：保持性；对应 SI/格子输入解析到相同格子参数并得到相同数值场。
3. 人造二进制盒体 STL：已知位置与体素范围、多实体并集和重叠、初场及边界优先级。
4. Boeing 基线比较、Ahmed 短算：同一最终 EXE 哈希切换几何/域/参数，达到计划步数并生成有效结果。
5. 空格/中文路径、不同启动目录、输入快照、非整除输出间隔（如23步/每7步）、prepare-only保持0步。

## Git 与 NUC

在现有源码仓库创建 `codex/config-runner-p0-p1`，保留 `codex/nuc-workflow` 不变。分阶段提交设计、基线、配置/执行模块、脚本/示例/验证。不重写旧历史，不初始化外层项目 Git。代码、方案、schema、示例和验证脚本入 Git；大型外部 STL、EXE、运行结果不入 Git，使用哈希和清单追踪。项目根 AGENTS.md 继续按既有约定不入 Git。

Mac 编辑并推送后，NUC 核实 src 工作区状态才切换/拉取；不覆盖用户未提交改动。显式使用 `-WorkspaceRoot 'F:\01-Project\Opensource\01-FluidX3D'`。构建输出独立 bin/config-runner，基线用另一个 BuildName，结果在 workingdir 独立 RunId 下。最后检查本任务 SSH/隧道并清理。
