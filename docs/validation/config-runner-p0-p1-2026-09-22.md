# P0 + P1 验收记录

2026-09-22（Asia/Shanghai）。状态：本轮范围已完成。

## 版本与产物

- 功能分支：`codex/config-runner-p0-p1`，fork：`FallenCastle/FluidX3D`。
- 设计先行提交：`bd8a253`；纯命令行硬编码基线：`f038c65`。
- 已验证源码提交：`c7cde15bbc2e8cd16f9767b89a8f58037d994d40`。
- 源码树：`2aafa8e3375695656d729790046f16c469c36987`。
- EXE：`F:\01-Project\Opensource\01-FluidX3D\bin\config-runner\FluidX3D.exe`。
- EXE SHA256：`6e274ea066773c9769c17dbf9ed7cfba9bb23c86641e0c3526ece5b22943c24a`。
- NUC Release/x64、v142 构建成功。后续验收文档提交不改变该源码树或二进制。

机器可读摘要见 [同名 JSON](config-runner-p0-p1-2026-09-22.json)。操作方法见 [配置执行器说明](../config-runner.md)。

## 完成范围

纯命令行、固定 D3Q19/SRT/FP16S/SUBGRID。JSON 选择格子或 SI 单位、规则网格、黏度或 Re、多 STL 静态固体、初场、无滑移/equilibrium/周期边界、局部面片、步数或 SI 时长，以及 VTK/CSV/JSON 输出。

支持严格校验、零步 prepare、输入快照、哈希追踪、批处理非交互失败退出，以及现有 NUC 运行脚本的 ConfigPath/PrepareOnly 参数。图形、动态物体、专门压力出口、其它求解模型不属于本轮。

## 证据

最终集成验证目录：

`F:\01-Project\Opensource\01-FluidX3D\workingdir\config-validation\20260921T160241Z`

该目录的 report.json 状态 succeeded，29 次程序调用均符合预期，包括故意输入错误时的非零退出。除退出状态外，脚本还检查数值、几何、快照和步数：

- 相同 EXE 完成均匀周期流、SI 等价问题、Boeing 1000步及 Ahmed 37步。
- 均匀周期流保持空间均匀；FP16S 测试判据为密度相对误差<1e-4、速度绝对误差<1e-5。SI 转回格子单位与格子算例一致到1e-7以内。
- Boeing 在0步及1000步的 flags/rho/u 六组数组与硬编码基线逐字节一致。只比较 VTK 数组载荷；新输出的原点采用已明确的角点坐标语义，header 不要求与旧版居中坐标相同。
- 相交 STL 的固体并集未丢失格点；移动域原点（包括1e9量级）不改变相对几何；局部入口覆盖数量与位置正确。
- 输出间隔7步、总23步时，正确产生0/7/14/21/23步数据。
- 中文/空格路径、输入快照再运行、非空输出目录保护通过。
- 不支持模型、未知/重复字段、非法黏度、单位混用、过小网格、未配对周期边界、边界冲突、缺失/损坏/越界STL正确失败。

独立验证运行脚本：

- `workingdir/config-runner-script/20260921T160300227Z-c7cde15bbc2e/run.json`：succeeded，完成23步。
- `workingdir/config-runner-prepare/20260921T160301040Z-c7cde15bbc2e/run.json`：succeeded，求解器状态prepared，实际0步，Boeing体素化与VTK输出成功。

Mac 仅执行 JSON/Python语法/工程XML/差异检查，未编译或运行 FluidX3D。官方第三方许可证保留原始字节及哈希（其首行有上游自带尾空格）；自有修改的差异检查通过。

## 限制

这是配置化行为与短算验收，不是网格收敛或工程物理精度结论。FP16S 的量化误差、体素壁面、equilibrium 边界语义保留；不能将该边界当作通用压力出口。当前 SHA256 快照实现使用 Windows CryptoAPI，配置执行器的验收和运行平台为 Windows NUC。

失败构建和早期失败测试日志保留在 NUC 供追溯，最终结论仅依据上述已验证产物。外层项目 reports/config-runner-p0-p1-2026-09-22 保存取回的完整构建和验收记录；大体积结果留在 NUC，不纳入源码 Git。
