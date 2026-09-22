# P3 模型与参数选择

同一 `config-runner-p3/FluidX3D.exe` 可通过配置选择 16 种模型组合：D3Q19/D3Q27、SRT/TRT、Smagorinsky 开/关、FP16S/FP32。每次运行选择一个组合；改变配置不需要重新编译 EXE。OpenCL 内核仍由设备驱动在实例创建时编译，原有驱动缓存行为不变。

## 配置字段

```json
"solver": {
  "lattice": "D3Q27",
  "collision": "TRT",
  "storage": "FP32",
  "turbulence": "smagorinsky",
  "smagorinsky_constant": 0.17,
  "trt_magic_parameter": 0.1875
}
```

| 字段 | 可用值/范围 | 缺省值 |
|---|---|---|
| lattice | D3Q19、D3Q27 | D3Q19 |
| collision | SRT、TRT | SRT |
| storage | FP16S、FP32 | FP16S |
| turbulence | none、smagorinsky | smagorinsky |
| smagorinsky_constant | 0 < Cs ≤ 1，仅在 smagorinsky 下使用 | 约 0.17326595533835415 |
| trt_magic_parameter | 0 < Λ ≤ 1，仅在 TRT 下使用 | 0.1875，即 3/16 |

Cs、Λ 是无量纲参数，格子/SI 两种输入使用相同数值。关闭亚格子模型时填 `"turbulence":"none"` 并删除 Cs；SRT 配置中删除 Λ。模型不匹配、未知值、布尔/字符串冒充参数以及不可表示的系数均报错。范围上限是当前软件契约，不是所有问题的稳定性保证。

旧配置及 schema_version=1 继续可用。保持缺省值时沿用原 SRT、Smagorinsky 和 FP16S 路径。默认 Cs 专门保留原内核系数 `0.76421222f`；自定义 Cs 使用 `18*sqrt(2)*Cs²`。TRT 开启亚格子时，另一松弛率随局部有效松弛时间计算，Λ 本身保持配置常数。

`resolved-config.json` 的 `solver` 保存实际组合、启用参数、真正用于内核的 FP32 系数，以及基础偶/奇松弛率。带亚格子模型时，基础松弛率不等于每个格点的局部有效松弛率。`completion.json`、`status.txt`、日志也记录实际选择。

## 内存与能力查询

| 速度集 | FP16S 设备字段 | FP32 设备字段 |
|---|---:|---:|
| D3Q19 | 67 B/cell | 105 B/cell |
| D3Q27 | 83 B/cell | 137 B/cell |

上述包含当前启用的体积力/受力等字段，不包括全部驱动额外占用。主机字段均为 29 B/cell，另计并集掩码、几何及统计分组。预算、单缓冲限制、实际分配和日志均使用选中的 Q 和存储位宽。`memory_budget_mb` 延续最近整数取整，仍是网格估算输入。

`--capabilities` 中 lattice/collision/turbulence 是支持值列表，defaults 给出默认值，parameters 给出参数范围及适用模型。`model_device_bytes_per_cell` 给出完整内存表；原 `device_bytes_per_cell` 保留为默认 D3Q19 的兼容字段。读取能力输出的外部脚本应适配这三个由字符串变成列表的字段。

## NUC 运行

```powershell
$root = 'F:\01-Project\Opensource\01-FluidX3D'
Set-Location "$root\src"
& "$root\bin\config-runner-p3\FluidX3D.exe" --capabilities
& "$root\bin\config-runner-p3\FluidX3D.exe" --list-devices
.\scripts\run-nuc.ps1 -WorkspaceRoot $root -BuildName config-runner-p3 `
  -CaseName models-periodic -ConfigPath "$root\src\configs\models-periodic.json" -DeviceId 0
```

示例 `models-periodic.json` 使用 D3Q27/TRT/FP32 和显式 Cs/Λ。所有 P1/P2 算例可改用新的 BuildName；原 P2 二进制保留用于回归。

扫描全部 16 种组合：

```powershell
python scripts/parameter-study.py generate --spec configs/study-models.json `
  --output "$root\workingdir\my-model-study"
python scripts/parameter-study.py run --study "$root\workingdir\my-model-study" `
  --workspace-root $root --build-name config-runner-p3 --device 0
```

Cs/Λ 也可用 JSON Pointer 扫描，但基础配置必须已含该字段，且组合满足适用模型约束。默认模型矩阵的基础配置不带这两个条件参数，避免生成 SRT+Λ 或 none+Cs 的无效组合。

## 验证与适用范围

`scripts/test-config-p3.py` 在 NUC 检查模型矩阵、实际分配、周期流、带 STL 的壁面/体积力/受力、Cs/Λ 作用、三维剪切波、SI、快照与扫描，并与旧 P2 产物对照。另运行原 P1、P2 和存储专项脚本。

通道解析验收沿用固定 tau、固定 Re 的三档网格；FP32 使用速度相对 L2/Linf <3%、壁面力误差 <4% 的阈值。FP16S 同样计算并记录误差，但保留 P2 已发现的弱强迫/细网格量化限制，不能由模型支持列表推导任意场景都满足同一精度阈值。性能记录包含进程启动与输出，首轮可能含内核编译，用同算例第二次运行作暖启动对照，不等同纯内核吞吐率。

本轮仍为单 GPU、命令行、静态单相；沿用 P2 的体积力、固定位置运动壁面、受力统计和全部单位/边界语义。对应配置说明见 [P2 手册](config-runner-p2.md)，设计与完成判据见 [P3 契约](config-runner-p3-design.md)。

本次实测结果、FP16S 精度限制及首次失败处理见 [P3 验收记录](validation/config-runner-p3-2026-09-22.md)。
