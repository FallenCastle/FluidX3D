# P3 数值模型选择验收

2026-09-22。用户确认的三维单相模型选择及 Cs/Λ 参数接口完成。16 组合功能验证、48 组 FP32 通道精度验收、P1/P2/存储回归和追加三维网格细化通过。**FP16S 对照的 48 组中有 32 组未达到相同的速度/受力阈值，保留这一精度限制。**

## 产物

- 分支 `codex/config-runner-p3`，生产代码提交 `98cdd1cffdbc8d9105a9f51b677c1a8507f8d1df`。
- 源码树 `0009ff4afdf02903881d7b44467dcbc34f6d0307`。
- NUC 产物 `F:\01-Project\Opensource\01-FluidX3D\bin\config-runner-p3\FluidX3D.exe`。
- EXE SHA256 `e324f859774827970098d70954ccc5a8e8c60e52aed067ef66bc312158bceeb4`。
- Release x64，MSVC v142，OpenCL 设备 0 / NVIDIA GeForce RTX 3060。
- 初始矩阵脚本提交 `4f369ac`；追加细化脚本提交 `eea89c1`。追加过程中没有修改 C++ 或重建 EXE。

## 功能与兼容

完整矩阵为 D3Q19/D3Q27 × SRT/TRT × none/smagorinsky × FP16S/FP32。矩阵直接执行 176 次：每组合包含周期均匀流、带 STL/体积力/运动壁面/受力的组合算例、关闭采样的严格对照、两次资源/耗时记录和六个通道剖面。实际缓冲容量及设备字段占用均匹配所选 Q/精度，日志与结果元数据一致。

首轮总共执行 209 次，在后续 24³ 三维剪切波精度断言处失败。已完成的 16 组合、96 个通道剖面和 16 项性能记录保留。追加执行引用这份完整矩阵，核对同一 EXE 哈希并保存报告 SHA256，再执行 38 次直接调用与正式运行脚本的 16 组合扫描；追加流程通过。引用数据没有冒充重新执行的数据。

- P1：29 次调用通过，Boeing 第 0/1000 步的 rho/u/flags 共 6 个数组与原始基线逐字节一致。
- P2：25 次直接调用、正常扫描与预期失败批次达到各自判据。
- 存储专项：14 次直接调用和两组合扫描通过，包含独立 FP32 构建对照。
- 默认 FP16S、FP32 分别与保留的 P2 EXE 比较：各 28 个 VTK 数组及统计 JSON 完全相同；显式默认 Cs 也相同。
- 修改 Cs 0.1→0.3、Λ 0.1→0.25 时，最大速度差分别为约 2.0970e-4、4.5626e-4，确认参数实际参与计算。
- 无亚格子、Λ=(3nu)² 时的 SRT/TRT 退化对照：密度最大差 1.1921e-7，速度最大差 2.9802e-8，均低于 3e-6 判据。
- D3Q27/TRT 的 SI 换算覆盖 STL、体积力、运动壁面和分组受力；输入快照从另一工作目录重放的 28 个数组及统计完全一致。
- 非法模型、参数类型/范围、不可表示值和模型不匹配的参数均非零退出。

## FP32 通道精度

每种 FP32 模型组合运行 Poiseuille/Couette、H=8/16/32，共 48 组。nu_l=0.1、U_l=0.05*8/H，Re=4，固定 tau 的扩散尺度细化。速度相对 L2 和 Linf/U 均要求 <3%，两壁最大相对受力误差要求 <4%；全部通过。

下表为每个模型组合六组测试的最大值：

| 速度集 | 碰撞 | 亚格子 | 最大速度 L2 | 最大 Linf/U | 最大受力误差 |
|---|---|---|---:|---:|---:|
| D3Q19 | SRT | none | 1.113078% | 0.813213% | 0.030303% |
| D3Q19 | SRT | smagorinsky | 1.611973% | 1.296718% | 0.188926% |
| D3Q19 | TRT | none | 0.006491% | 0.006653% | 0.019375% |
| D3Q19 | TRT | smagorinsky | 0.531876% | 0.486341% | 0.189298% |
| D3Q27 | SRT | none | 1.113358% | 0.813563% | 0.051761% |
| D3Q27 | SRT | smagorinsky | 1.612810% | 1.297672% | 0.190118% |
| D3Q27 | TRT | none | 0.013298% | 0.013855% | 0.033134% |
| D3Q27 | TRT | smagorinsky | 0.531929% | 0.486401% | 0.190006% |

FP16S 的相同网格/参数对照有 32/48 组未达到上述阈值。最差速度 L2 约 14.26%，最差壁面力误差约 45.43%，均出现在本次弱强迫/低速度细网格条件；这不是所有 FP16S 算例的普遍误差。对应 FP32 测试全部达标。FP16S 保留为显存优先及兼容模式，本次数据不支持使用它保证这些参数下的精确剪切力。完整逐项误差见配套 JSON，未删去失败项或放宽容差。

## 三维剪切波与首次失败

采用波向量 (1,1,1)、速度方向 (1,-1,0) 的周期横向剪切波，D3Q27/TRT/none/FP32；三个空间方向均参与变化。解析振幅按 `exp(-nu*3*(2*pi/N)^2*steps)` 衰减。

首轮 24³、32 步的误差为 3.0107788%，略超 3%，因此首轮脚本明确返回失败。追加采用固定物理时间的扩散尺度细化，nu_l=0.1、U_l=0.001*24/N、steps=round(32*(N/24)²)，解析解使用实际整数步数：

| 网格 | 步数 | 相对 L2 |
|---|---:|---:|
| 16³ | 14 | 6.647674% |
| 24³ | 32 | 3.010779% |
| 32³ | 57 | 1.704901% |

误差逐档下降，32³ 达到原 3% 阈值。24³ 的失败仍有效；这组细化支持误差随空间/时间分辨率改善，不把首次失败改写成通过，也不据此声称任意三维问题都达到该精度。

## 资源与耗时

每组合使用 64×32×64、500 步、周期均匀流，关闭 analysis，只输出最终 rho。每组连续运行两次，下表记录第二次整进程耗时；包括初始化、监视和磁盘输出，不能当作纯内核吞吐率或精确性能排名。

| 速度集 | 碰撞 | 亚格子 | 存储 | 设备字段字节 | 第二次耗时/s |
|---|---|---|---|---:|---:|
| D3Q19 | SRT | none | FP16S | 8781824 | 0.7454 |
| D3Q19 | SRT | none | FP32 | 13762560 | 0.6874 |
| D3Q19 | SRT | smagorinsky | FP16S | 8781824 | 0.7055 |
| D3Q19 | SRT | smagorinsky | FP32 | 13762560 | 0.6536 |
| D3Q19 | TRT | none | FP16S | 8781824 | 0.7022 |
| D3Q19 | TRT | none | FP32 | 13762560 | 0.7076 |
| D3Q19 | TRT | smagorinsky | FP16S | 8781824 | 0.6910 |
| D3Q19 | TRT | smagorinsky | FP32 | 13762560 | 0.7021 |
| D3Q27 | SRT | none | FP16S | 10878976 | 0.6951 |
| D3Q27 | SRT | none | FP32 | 17956864 | 0.6775 |
| D3Q27 | SRT | smagorinsky | FP16S | 10878976 | 0.6901 |
| D3Q27 | SRT | smagorinsky | FP32 | 17956864 | 0.7118 |
| D3Q27 | TRT | none | FP16S | 10878976 | 0.6681 |
| D3Q27 | TRT | none | FP32 | 17956864 | 0.6906 |
| D3Q27 | TRT | smagorinsky | FP16S | 10878976 | 0.6871 |
| D3Q27 | TRT | smagorinsky | FP32 | 17956864 | 0.7226 |

## 复现与报告

在 NUC 核实实际设备编号后运行：

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
Set-Location "$root\src"
python scripts/test-config-p3.py --workspace-root $root --device 0
python scripts/test-config-runner.py --workspace-root $root --build-name config-runner-p3 --device 0
python scripts/test-config-p2.py --workspace-root $root --build-name config-runner-p3 --device 0
python scripts/test-runtime-storage.py --workspace-root $root --build-name config-runner-p3 --device 0 `
  --fp16-reference "$root\workingdir\p2-validation\20260921T163819477191Z"
```

P3 脚本默认重新执行完整矩阵；本次追加执行使用 `--matrix-reference` 指向首次已完成的矩阵报告。兼容对照需要保留 P2 EXE；存储专项还需要独立 FP32 诊断构建。

NUC `workingdir/` 原始报告：

- P1：`config-validation/20260922T013751Z/report.json`
- P2：`p2-validation/20260922T013730178226Z/report.json`
- 存储：`storage-validation/20260922T014624590941Z/report.json`
- 首次矩阵及失败：`p3-validation/20260922T014248610040Z/report.json`
- 追加通过：`p3-validation/20260922T015005051696Z/report.json`

Mac 外层 `reports/config-runner-p3-2026-09-22/` 保存原始副本；仓库内 [配套 JSON](config-runner-p3-2026-09-22.json) 保存身份、原始文件哈希、完整通道误差及对照数据。[P3 使用说明](../config-runner-p3.md) 给出配置字段和运行入口。
