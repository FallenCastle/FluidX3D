# P2 实现与 NUC 验证记录

2026-09-22。功能实现及 P1 回归通过；**生产 FP16S 的最细 Couette 网格未通过 4% 受力误差阈值，不能宣称全部数值精度验收通过**。独立 FP32 对照确认存在存储精度限制；固定松弛时间的 FP32 网格细化验收通过。这是运行时精度扩展前的历史验收记录。用户随后批准提前加入 FP16S/FP32 选择，最新生产能力与验收见 [运行时精度验收](runtime-storage-2026-09-22.md)。

## 产物与 Git

- 生产分支 `codex/config-runner-p2`。正式 EXE：`F:\01-Project\Opensource\01-FluidX3D\bin\config-runner-p2\FluidX3D.exe`。
- 生产构建代码提交 `cfb07d727721f936cdaff1b1a4c21abd79053707`，SHA256 `53a2283e75ac3c5204b1c5c3fda7207450b1a372c60466b0dea27925a6982a43`。其后提交修改测试、示例、脚本和文档，不改 C++ 源码。
- 诊断分支 `codex/p2-fp32-diagnostic`，提交 `0d67091`。只改变分布函数存储精度和相应能力/字节估算，构建名 `config-runner-p2-fp32-diagnostic`。用于误差归因，未把它包装成生产 EXE 的运行时精度选择。
- 所有代码经 Mac 提交推送，再由 NUC 拉取构建。Mac 未编译或运行 FluidX3D。
- 随代码交付的两个示例通过正式 run-nuc.ps1 入口完成：`workingdir/p2-poiseuille-example/20260921T164741289Z-cfb07d727721`、`workingdir/p2-couette-example/20260921T164742242Z-cfb07d727721`。

## 已通过的功能检查

- P1 全部 29 次程序调用通过。Boeing 初始与 1000 步的 flags/rho/u 数组继续逐字节匹配原硬编码控制台基线；Ahmed、周期流、SI、几何、边界与错误输入回归通过。
- P2 25 次直接程序调用的预期成功/失败状态正确：探针、非整除间隔、prepare-only 零样本、时间均值/总体标准差独立复算、非均匀初场、SI 密度/速度/压力/受力、中文路径、运动壁面、固体误采样及重叠部件拒绝等。
- 开启/关闭一般采样，以及开启/关闭几何受力采样时，最终场数组逐字节一致。统计不改变求解轨迹。
- 2×2 参数扫描 4 项成功；含负黏度的两项批次记录一项失败并继续完成另一项，整个批次正确返回非零。
- 单独的资产测试通过：原始 STL 移走后，生成批次的两个旋转组合仍运行成功；拒绝覆盖、篡改配置、不存在/重复/祖先冲突/非法转义的参数路径与 STL 路径扫描。未开启统计的结果不会指向不存在的 statistics.json。

## 同一网格、同一算法的精度对照

以下采用 H=8/16/32、U_l=0.1、nu_l=0.2*H/8，Re=4。速度误差为相对 L2；力误差取上下壁相对误差较大值。瞬态运行 1.6 H²/nu 步，末段含奇偶步采样。

| 算例 | H | FP16S 速度误差 | FP16S 受力误差 | FP32 受力误差 |
|---|---:|---:|---:|---:|
| poiseuille | 8 | 1.1520% | 0.3601% | 0.00021% |
| poiseuille | 16 | 2.5455% | 0.8179% | 0.00032% |
| poiseuille | 32 | 2.1032% | 1.8478% | 0.00052% |
| couette | 8 | 0.3760% | 1.9491% | 0.18818% |
| couette | 16 | 0.8814% | 3.4750% | 0.04802% |
| couette | 32 | 1.9412% | 8.1544% | 0.01404% |

Couette H=32 的 FP16S 受力误差约 8.15%，仅替换为 FP32 后约 0.0140%。FP32 的壁面力仍使用同一个诊断内核、相同运动壁面修正及分组代码，因此该对照支持将主要差异归因于存储精度，而非统计符号或力单位。

这组声学尺度的 tau 随细化增加，FP32 Poiseuille 速度误差也未单调降低（最细约 3.94%）。不能用“换 FP32”掩盖离散参数对速度剖面的影响，更不能据此宣称网格收敛。

## 固定 tau 的物理网格细化

追加 `--diffusive-refinement`：nu_l=0.1、U_l=0.05*8/H，Re=4，dt∝dx²，保持松弛时间不变。FP32 所有速度 L2/Linf<3%、壁面力误差<4% 的预定阈值均通过：

| 算例 | H | 速度相对 L2 | 受力相对误差 |
|---|---:|---:|---:|
| poiseuille | 8 | 1.61197% | 0.00058% |
| poiseuille | 16 | 0.40911% | 0.00114% |
| poiseuille | 32 | 0.11014% | 0.00661% |
| couette | 8 | 0.00034% | 0.18893% |
| couette | 16 | 0.00122% | 0.05146% |
| couette | 32 | 0.00664% | 0.03606% |

Poiseuille 速度误差随 H 翻倍约下降四倍，符合本次参数下接近二阶的网格细化表现。Couette 速度误差很小；不将其微小误差的增减解读为严格收敛阶。Smagorinsky 始终开启，没有为测试偷偷切换模型。

重现命令（NUC）：

```powershell
python scripts/test-config-runner.py --workspace-root F:\01-Project\Opensource\01-FluidX3D --build-name config-runner-p2
python scripts/test-config-p2.py --workspace-root F:\01-Project\Opensource\01-FluidX3D --build-name config-runner-p2
# 上述命令对应本报告的历史提交；当时 FP16S 精度验收非零退出。
# 当前脚本默认已改为 FP32 固定 tau 验收。
python scripts/test-config-p2.py --workspace-root F:\01-Project\Opensource\01-FluidX3D --build-name config-runner-p2-fp32-diagnostic --diffusive-refinement
python scripts/test-parameter-study.py --workspace-root F:\01-Project\Opensource\01-FluidX3D
```

## 存储与耗时

固定 96×64×96、2000 步，单设备；每种设置运行三次，首轮用于预热，取后两轮耗时中值。耗时包含进程启动、OpenCL 编译/缓存、初始化和最终输出，不是孤立内核吞吐率。

| 配置 | 设备字段字节 | 主机字段及并集掩码字节 | 耗时中值 |
|---|---:|---:|---:|
| P1 | 32,440,320 | 10,616,832 | 1.022 s |
| P2，无研究采样 | 39,518,208 | 17,694,720 | 1.075 s |
| P2，每100步采样含受力 | 39,518,208 | 17,694,720 | 3.900 s |

设备字段占用增加 21.8%（55→67 B/cell）；并非驱动总显存峰值。固定物理能力扩展的本次端到端耗时增加约 5.2%。含主机全域统计的频繁采样使本次短算耗时达到未采样 P2 的约 3.63 倍，因此采样间隔是明显的性能控制项。这组结果不外推为其它网格/设备的固定百分比。

## 证据位置

机器可读摘要见同目录 `config-runner-p2-2026-09-22.json`。原始报告在项目外层 `reports/config-runner-p2-2026-09-22/`，完整场和日志保留在 NUC：

- P1 回归：`workingdir/config-validation/20260921T163553Z`。
- FP16S 完整功能及声学尺度：`workingdir/p2-validation/20260921T163819477191Z`。
- FP32 同参数对照：`workingdir/p2-validation/20260921T164103306724Z`。
- FP32 固定 tau 通过：`workingdir/p2-validation/20260921T164401382586Z`。
- 资产完整性：`workingdir/study-validation/20260921T164633Z`。
- 性能：`workingdir/p2-overhead/20260921T163613Z`。

更早的两组试运行（固定 nu 改变 Re、低幅值声学尺度）也保留在原始报告目录；它们未达精度阈值，没有被丢弃或作为通过证据。
