# Solver-IBM 浏览器工作台

工作台版本为 `0.2.0-dev`，固定对接正式 `Solver-IBM 2.0.0`。基线标签 `v2.0.0`（`58f44e5013b7b1ffe105107cfa2a27f8d557e45d`）；不修改、编译或替换求解器。代码位于独立 `feature/web-workbench-v2` 分支。

## 开始使用

Windows 要求 Python 3.12+、已验收的 `package/V2.0.0` 及可用 OpenCL 设备。无需 pip/npm 安装。前端资源均从同一个本机服务提供，不依赖外部 CDN。

Windows 源码工作区使用 `F:\01-Project\Opensource\01-FluidX3D\web-src`，与原 `src` 及正在开发的续算分支分开。先在 Windows 同步本分支（需要包含 `manage-windows.ps1`）。Mac 需要 Python 3 和已可通过密钥登录的 `ssh desktop-msi`，无需安装 Python 第三方依赖。

在项目根目录双击 **启动工作台.command** / **关闭工作台.command**。这两个入口指向下列版本管理中的脚本，也可从终端运行：

```sh
./workbench/scripts/open-mac.command
./workbench/scripts/close-mac.command
```

启动入口启动或复用 Windows 后台服务，建立后台 SSH 隧道，等待 `http://127.0.0.1:8765` 返回正确的 V2.0.0 程序身份后自动打开默认浏览器。重复启动复用同一服务和隧道。终端提示完成后即可关闭窗口；关闭终端、浏览器不会停止后台连接或 Windows 计算。Mac 睡眠/网络断开可能使隧道退出，再次启动即可恢复访问。后台服务不随 Windows 重启自动启动。

关闭入口先检查工作台活动任务和 Windows 上实际的 `Solver-IBM.exe` / `FluidX3D.exe` 进程。有计算、校验或正在取消的任务时拒绝关闭，并显示任务/进程信息；请等待完成，或在网页使用“终止当前任务”后再次关闭。没有任务时通过服务关闭接口退出，核实进程与 Windows 端口释放，再关闭本脚本管理的隧道。接口锁同时防止检查后新任务插入。其他来源的求解器进程会阻止关闭，但脚本不会终止它们。无法连接 Windows 时保留隧道并报错，不把无法检查当成没有任务。

隧道通过用户私有 `/tmp/solver-ibm-<uid>-<标识>/ssh.sock` 管理，不按进程名称批量结束 SSH。日志在同目录 `ssh.log`。遇到其他程序或手动隧道占用 Mac 端口时提示处理，不接管它们。新建隧道失败时尝试撤回本次新启动的空闲服务；如果已出现任务则保留。关闭不会删除算例、结果或日志。

默认连接 `desktop-msi`、端口 `8765`。终端使用时可设置 `SOLVER_WEB_HOST`、`SOLVER_WEB_PORT`、`SOLVER_WEB_ROOT`、`SOLVER_WEB_CHECKOUT`、`SOLVER_WEB_DATA`；启动与关闭需使用相同设置。只读状态检查：

```sh
python3 workbench/scripts/mac-workbench.py status
```

启动/关闭的实际验收记录见 [mac-lifecycle-validation.md](mac-lifecycle-validation.md)。

也可在 Windows 单独启动服务并保持其终端运行，再从 Mac 只建立隧道：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\workbench\scripts\start-windows.ps1
```

```sh
ssh -N -L 8765:127.0.0.1:8765 desktop-msi
```

浏览器访问 `http://127.0.0.1:8765`。服务只监听 Windows 回环地址；不需要开放防火墙端口或公网访问。

也可单独关闭 Windows 服务（同样检查任务与实际计算进程，但不管理 Mac 隧道）：

```sh
ssh desktop-msi 'powershell.exe -NoProfile -ExecutionPolicy Bypass -File F:\01-Project\Opensource\01-FluidX3D\web-src\workbench\scripts\stop-windows.ps1'
```

## 首版功能

- 以审核后的工作台为基础：工程树、可旋转 STL 预览、属性栏、高级 JSON、运行状态、日志、真实监测曲线和结果下载。
- 默认 SI 物理单位；域尺寸与格距分离。改格距保留 STL 的物理尺寸和位置；显示向上取整后的格点数和实际域尺寸。
- 计算域六类流动边界，周期轴配对、区域、优先级与模型相关热条件；整个 STL 对象的无滑移表面、接触角、规定运动和共轭传热属性。未支持的分面属性等明确标注。
- 表单和高级 JSON 共用配置对象。常用表单覆盖 SI、显式黏度与按步数运行；更完整的底层接口由 V2.0.0 的 schema 和程序判断。当前编辑器拒绝改成 lattice 单位或 duration 运行，避免表单给出错误含义。
- 上传二进制 STL（每文件最多 50 MiB）；服务保存不可变内容路径及 SHA256，预览最多抽样 6000 个三角形。`geometry[].file` 和初始 STL 液体区域只能引用工作台内已上传资源，不接受服务器任意路径。
- 一次执行一个任务。提交时固定配置、STL、EXE、构建身份及独立输出目录；启动前执行正式程序 `--validate`，实际运行继续检查体素化和 GPU 资源。可选择实际枚举的 OpenCL 设备与 1–86400 秒超时。
- 运行成功要求进程退出码为 0、`completion.json` 确认成功且完成全部请求步数，并存在关键输出文件。失败、超时和终止分别记录。服务重启把未完成记录标为中断，不自动续算。
- 曲线来自真实 `probes.csv`、`forces.csv`、`analysis.csv`；约两秒刷新，鼠标查看采样值。长数据按对象分别抽样，原始 CSV 可完整下载。单次曲线查询最多读取最近 32 MiB，界面显示抽样提示。
- 局部加密作为独立草稿保存，运行记录明确 `applied: false`；不会写入传给 V2.0.0 的配置。没有编译、参数扫描或续算接口。

## 数据与身份

默认数据目录为包外 `workingdir/web-workbench/`：

```text
draft.json                    配置与局部加密草稿，带修订号
assets/                       已上传的二进制 STL
runs/<UTC-UUID>/
  run.json                    状态、设备、时间、程序身份、退出码
  build.json                  正式包构建记录
  inputs/                     提交配置、STL、SHA256 清单
  refinement-draft.json       未应用的局部加密草稿
  runtime/Solver-IBM.exe       当次正式程序快照
  logs/                       校验及运行标准输出/错误
  results/                    求解器实际输出
```

“保存草稿”将配置持久化到 Windows。浏览器保留未保存修改，且用服务端修订号避免覆盖其他窗口的更新。服务不删除历史任务；清理数据目前在确认计算结束后手动进行。运行不会改动正式包。

该服务用于单用户、SSH 回环访问，不作为多用户公网服务。写接口要求当前页面会话令牌并检查 Origin/Host；上传和下载限制在工作台目录；不接受任意命令。任务进程用 [Windows Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) 管理，关闭服务时只清理自己启动的进程树；进程参数以 [`subprocess` 参数数组](https://docs.python.org/3.12/library/subprocess.html) 传递。

## 开发验证

前端源文件位于 `web/src/`，修改后运行 `python3 workbench/scripts/build-web.py` 生成并提交 `web/app.js`。模型编辑器无需 npm。结果查看器使用本地打包的 vtk.js 37.4.6，重建时在 workbench 下运行 `npm ci`、`npm run build:results`；运行部署仍无需 npm。

```sh
python3 -m unittest discover -s workbench/tests -v
node --check workbench/web/app.js
```

单元测试使用明确的假执行器，不启动 EXE，可在 Mac 运行。真实服务启动、配置校验和计算只允许在 Windows。接口验证脚本 `tests/smoke_windows.py` 通过正在运行的真实 Windows 服务提交短算例，检查完成状态、曲线和下载；日志中记录服务及 EXE 身份。首版验证见 `validation.md`，结果查看验收见 `results-validation.md`。

## 结果查看（0.2.0-dev）

点击顶部“结果查看”，或打开 `/results.html`。任务完成时，若正处于该任务的运行监控页，会自动打开结果并加载最后一帧；编辑其他配置时只提示完成。结果页选中正在运行的任务，也会在成功后自动加载。刷新页面可恢复 URL 中所选数据集。

- 原生读取 V2.0.0 的 BINARY / STRUCTURED_POINTS / SCALARS 输出，包括三分量速度；按大端 float32 和 unsigned_char 解析。支持速度大小/XYZ 分量、压力、密度、温度、液相体积分数以及离散格点/材料/对象编号。只显示文件实际提供的字段。
- XY、XZ、YZ 正交切片；物理位置吸附至最近格点中心。三维旋转、平移、缩放、正视/等轴视角，自动或固定色标范围，STL 显隐和透明度，时间步选择与顺序播放。
- 场值不重复换算。坐标取 VTK 的 ORIGIN/SPACING；完整目录中的 effective-config 和 resolved-config 提供单位、dt 与 STL 变换。缺少元数据时明确显示单位/时间未知，裸 STL 按原始坐标叠加。
- 支持上传 Mac 文件夹、多个 VTK/STL 文件（也可同时选择对应元数据 JSON），以及只读引用 Windows workingdir 内的已有结果目录。目录导入只筛选 VTK、STL 与 effective-config/resolved-config/manifest JSON；不执行导入内容。同一次导入要求 VTK 位于同一目录，网格一致、同一步变量不重复。
- 上传单个 VTK ≤ 2 GiB、STL ≤ 50 MiB、单次总量 ≤ 10 GiB；文件流式保存到 imports，校验通过后发布，失败清理未完成导入。已有 Windows 目录不复制文件。已导入数据跨服务重启保留。
- 每次读取一张切片，每轴最多 257 个实际格点，保留两端；超出时标记“抽样预览”，不改动原文件。连续量在切片节点间插值，离散编号使用最近节点色块，非有限值留下空白并报告数量。色标默认只代表当前切片，固定范围用于跨帧比较。
- 首版叠加静态 STL。规定运动对象明确提示并隐藏，避免拿初始模型冒充当前位姿；动态位姿、斜切片、流线、体渲染和其他 VTK 格式暂不支持。

结果数据独立于当前编辑草稿。后处理失败只在结果页报告，不改写求解器任务的成功/失败状态。渲染库与许可证随前端分发，不需要浏览器连接 CDN。
