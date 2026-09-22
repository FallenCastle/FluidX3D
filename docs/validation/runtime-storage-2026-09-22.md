# P2 运行时 FP16S/FP32 验收

2026-09-22，用户批准的运行时精度扩展完成。**同一生产 EXE 的 FP16S/FP32 选择、P1 回归、P2 功能与 FP32 三档解析流动验收均通过。** 历史 FP16S 量化误差记录保留，本次没有放宽误差阈值。

## 产物与复现身份

- 分支：`codex/config-runner-p2`。
- 生产代码提交：`655b7dda02de3cb8de606d51c59e62431753ca06`。
- 源码树：`8fd896284025217e25ed8a12e7883c83d845ccb3`。
- 生产 EXE：`F:\01-Project\Opensource\01-FluidX3D\bin\config-runner-p2\FluidX3D.exe`。
- SHA256：`9fa70c53f0a5d73d159a9d65cfe2d72a7c232080bb72c94552940e4e5ecf4ec6`。
- 工具链：Release x64，MSVC v142 / 14.29.30133，Windows SDK 10.0.22621.0。
- 设备：OpenCL ID 0，NVIDIA GeForce RTX 3060，驱动 595.79。
- 专项脚本提交：`228464e`。后续仅补充脚本和文档，生产源码及 EXE 未改变。

## 同一 EXE 的精度选择

`solver.storage` 接受 `FP16S` / `FP32`，缺省 FP16S；两种模式均以 FP32 运算。专项验收执行 14 次直接调用（含 4 次预期拒绝和 1 次独立诊断 EXE 对照），另通过正式运行包装脚本执行 2 个 storage 扫描组合。所有生产调用均核对同一 EXE 哈希。

| 比较 | 检查结果 |
|---|---|
| 省略 storage 与显式 FP16S | 20 个 VTK 数组逐字节相同，统计 JSON 相同 |
| FP16S → FP32 → FP16S | 前后 FP16S 的 20 个数组及统计相同 |
| 与旧固定 FP16S STL 受力算例对照 | 20 个数组及统计相同 |
| 运行时 FP32 与独立固定 FP32 构建 | 28 个数组及统计相同 |
| FP32 输入快照从另一工作目录重放 | 28 个数组及统计相同 |
| 非法 FP16C、fp32、数值、null | 全部非零退出，错误指出 storage |
| `/solver/storage` 参数扫描 | 两种精度均成功，运行记录中的 EXE 哈希相同 |

FP32 对照算例使用 16×18×16 网格、37 步，包含 STL 立方体、恒定体积力、静止/运动壁面、探针及墙面/部件/全部固体受力分组；多个输出时间覆盖奇偶流动步。独立诊断构建来自 `0d67091`，与生产 EXE 是不同构建，完整身份见配套 JSON。

实际 DDF 缓冲区容量与预期 `N*19*2` / `N*19*4` 相同。16³ 网格的 FP16S / FP32 分别为 155648 / 311296 字节；设备场总量为 274432 / 430080 字节（67 / 105 B/cell）。主机场及并集掩码均为 30 B/cell，另计几何与统计分组。

同为 1 MiB、1:1:1 的预算输入，FP16S 推导 25³、FP32 推导 22³ 网格，两者实际分配与各自精度一致。沿用的最近整数取整可能超过预算值，因此 `memory_budget_mb` 是估算输入，不是严格的显存上限；实际设备容量及最大单缓冲限制另行检查。

## P1 与 P2 回归

P1 共 29 次调用通过，包括格子/SI、配置与 STL 检查、局部边界、快照、Boeing/Ahmed 短算。Boeing 原网格 170×339×85 在第 0 / 1000 步的 rho/u/flags 共 6 个数组与原始基线逐字节相同。

P2 共 25 次直接调用达到预期结果，4 个正常扫描组合成功；故意加入非法黏度的批次保留失败项，随后合法项仍成功且批次返回非零。覆盖体积力、固定位置运动壁面、SI 换算、探针及时间统计、表压、受力分组、采样不扰动流场、错误配置拒绝。

解析验收使用 FP32、固定 tau：`nu_l=0.1`、`U_l=0.05*8/H`，H=8/16/32，Re=4，步数为 `ceil(1.6*H²/nu_l)`。比较半格反弹墙之间的流体高度及格点中心位置。阈值为速度相对 L2 <3%、速度 Linf/U <3%、两壁最大相对力误差 <4%。

| 算例 | H | 速度相对 L2 | 速度 Linf/U | 最大壁面受力误差 |
|---|---:|---:|---:|---:|
| poiseuille | 8 | 1.611973% | 1.296718% | 0.000580% |
| poiseuille | 16 | 0.409115% | 0.328682% | 0.001138% |
| poiseuille | 32 | 0.110141% | 0.090626% | 0.006615% |
| couette | 8 | 0.000340% | 0.000273% | 0.188926% |
| couette | 16 | 0.001222% | 0.000969% | 0.051463% |
| couette | 32 | 0.006645% | 0.005386% | 0.036065% |

Poiseuille 的剖面误差随细化下降；Couette 的误差已较小，但不能由这组数据宣称所有量严格二阶收敛。相同生产 EXE 也通过两类通道的 SI 换算对照。

## 验收命令与原始结果

在 NUC，先核实设备编号。以下命令复用现有生产 EXE，无需重建：

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
Set-Location "$root\src"
python scripts/test-config-runner.py --workspace-root $root --build-name config-runner-p2 --device 0
python scripts/test-config-p2.py --workspace-root $root --build-name config-runner-p2 --device 0
python scripts/test-runtime-storage.py --workspace-root $root --device 0 `
  --fp16-reference "$root\workingdir\p2-validation\20260921T163819477191Z"
```

最后一条需保留已有的 `config-runner-p2-fp32-diagnostic` 独立构建和指定 FP16S 基线目录。三套原始报告分别位于 NUC `workingdir/` 下：

- `config-validation/20260921T170555Z/report.json`
- `p2-validation/20260921T170536807715Z/report.json`
- `storage-validation/20260922T010505711141Z/report.json`

Mac 项目外层 `reports/runtime-storage-2026-09-22/` 保存原始报告副本。仓库内 [配套 JSON](runtime-storage-2026-09-22.json) 保存构建身份、原始报告 SHA256、对照结果和数值误差；[使用说明](../config-runner-p2.md) 给出配置接口。

此前 FP16S 的 Couette 细网格受力误差及声学尺度 FP32 Poiseuille 的速度误差仍是有效的历史失败结果，见 [原 P2 验收记录](config-runner-p2-2026-09-22.md)。本次解决的是通过配置选择 FP32 的能力，不能据此断言任意算例精度或稳定性已经得到验证。
