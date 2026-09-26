# Solver-IBM V2.0.0 交接文档

本文件用于 V2.0.0 发布交接和后续开发。当前产品为 **Solver-IBM**，主程序为 `Solver-IBM.exe`；它是 FluidX3D 的修改版本，上游作者、许可证及第三方许可继续保留。

## 固定身份

| 项目 | 值 |
|---|---|
| 正式版本 | V2.0.0 |
| Git 标签 | `v2.0.0` |
| 源码仓库 | `F:\01-Project\Opensource\01-FluidX3D\src` |
| 正式包 | `F:\01-Project\Opensource\01-FluidX3D\package\V2.0.0` |
| 版本唯一来源 | `src/version.hpp` |
| 上游基础 | FluidX3D 3.8 altered source version |

V1.0.0 的标签和正式包继续固定保留。V2.0.0 发现问题时发布新的补丁版本，不覆盖包或移动标签。

## 能力边界

V2.0.0 支持 V1 的配置驱动单相流接口，并增加：

- 流固共轭传热、强制/自然对流、常数多材料、四类热边界和固体体积热源。
- 单液相自由液面、固定环境气压、表面张力、固定静态接触角、液体入口和开口出口。
- 多个 STL 的规定平移、旋转、正弦往复和轨迹表；支持平移/旋转组合和启停。
- 三项功能的任意非空组合；新增功能统一要求 FP32，支持 8 种流动模型组合。

不支持气相流动、相变、动态接触角、温度相关物性、接触热阻、碰撞、变形或受力驱动的六自由度运动。具体字段和单位见[用户手册](user-manual-zh.md)。

## 代码入口

| 模块 | 责任 |
|---|---|
| `src/config.cpp` / `config.hpp` | JSON 解析、单位换算、能力与 resolved 配置 |
| `src/kernel.cpp` | LBM、自由液面、热输运与边界 OpenCL 内核源 |
| `src/lbm.cpp` / `lbm.hpp` | 运行时模型、字段分配、设备调度与动态表面质量接口 |
| `src/config_runner.cpp` | STL 体素化/动态重映射、运行循环、质量/显热投影、VTK/CSV/JSON 输出 |
| `src/config_analysis.hpp` | 探针、液位、全域统计和受力 |
| `schemas/case.schema.json` | 编辑器用配置结构；最终合法性仍由 EXE 判断 |
| `configs/` | V1 与 V2 便携示例、STL 和外部参考数据 |

运动固体热历史保存在材料坐标的固定采样序列中。体素重映射保持每个对象的目标单元数，并对被释放/占据格点进行一一配对。自由液面开口逐步累计离散质量和焓流目标；热自由液面按热源、边界热量与开口焓流投影显热。固定温度边界不参与全域温度修正。

## 验收入口

| 脚本 | 范围 |
|---|---|
| `test-config-runner.py` | V1 CLI、非法配置、周期流、SI、STL/边界、Boeing/Ahmed |
| `test-config-p2.py` | V1 压力、体积力、运动壁面、受力、解析通道和批次失败 |
| `test-runtime-storage.py` | V1 FP16S/FP32、内存估算、快照和固定历史对照 |
| `test-config-p3.py` | V1 16 模型组合、96 个剖面、Cs/Λ、剪切波、SI 和扫描 |
| `test-parameter-study.py` | 扫描资产自包含、JSON Pointer 与完整性 |
| `test-v2-physics.py` | 热/自由液面物理精度、守恒和随体温度 |
| `test-v2-scenarios.py` | MARIN、典型场景、规定运动和三项综合容器 |
| `test-v2.py` | 7 类功能组合 × 8 种 FP32 模型，共 56 项 |

正式结论和固定路径见 [V2.0.0 验收记录](validation/solver-ibm-v2.0.0-2026-09-27.md)。`test-package.py` 在候选包外运行两个包装器检查和上述八套回归，确认包内容在测试前后不变。不能用 56 项“能运行”矩阵代替物理精度套件。

## 外部参考

SPHERIC Test 2 / MARIN 溃坝的固定测点、时间窗、归一化和来源哈希记录在 `configs/reference/README.md`。紧凑参考表为 `configs/reference/spheric-test2-levels.csv`。自然对流 Ra=1000 使用 de Vahl Davis 平均 Nusselt 参考值 1.118。正式包保存必要参考，不保存全部外部下载缓存或所有历史 VTK。

## 接手步骤

1. 阅读项目根目录 `AGENTS.md`、本文件、[用户手册](user-manual-zh.md)和[发布说明](releases/V2.0.0.md)。
2. 核对 `v2.0.0`、`package/V2.0.0/manifest.json`、包内 `bin/build.json` 及 EXE SHA256。
3. 新开发从用户明确范围开始；V3.0 阶段开发版本使用 V2.x.x，完成验收后才发布 V3.0.0。
4. 按 Mac 编辑/提交/推送、NUC 拉取/构建/测试的流程工作；不在 Mac 运行求解器。
5. 新字段同步解析器、schema、手册、示例和测试；新增物理结论先固定阈值、网格、窗口与参考。
6. NUC 操作结束前检查并关闭本任务开启的 SSH 会话、隧道和后台连接。

## 发布包维护

`package/V2.0.0` 是只读正式归档。包内结果通过 `manifest.json` 校验；运行输出必须写到包外。历史对照程序保留 `FluidX3D.exe` 名称及原始 `build.json`，不能改名冒充当前产物。若源码文档提交晚于首次候选构建，应以正式包 `manifest.json` 中的精确发布提交、source tree 和最终 `build.json` 为准。
