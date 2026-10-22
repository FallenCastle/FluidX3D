# Solver-IBM 浏览器工作台

工作台版本为 `0.1.0-dev`，固定对接正式 `Solver-IBM 2.0.0`。基线标签 `v2.0.0`（`58f44e5013b7b1ffe105107cfa2a27f8d557e45d`）；不修改、编译或替换求解器。代码位于独立 `feature/web-workbench-v2` 分支。

## 开始使用

Windows 要求 Python 3.12+、已验收的 `package/V2.0.0` 及可用 OpenCL 设备。无需 pip/npm 安装。前端资源均从同一个本机服务提供，不依赖外部 CDN。

Windows 源码工作区使用 `F:\01-Project\Opensource\01-FluidX3D\web-src`，与原 `src` 及正在开发的续算分支分开。同步本分支后，在 Mac 双击 `workbench/scripts/open-mac.command`，或执行：

```sh
./workbench/scripts/open-mac.command
```

命令启动或复用 Windows 后台执行服务，把 `127.0.0.1:8765` 通过 SSH 转发到 Mac，并自动打开浏览器。保持终端和连接运行以访问网页。关闭终端只断开 SSH 隧道；浏览器关闭、刷新或网络断开均不会终止 Windows 中的任务。重新打开页面会读取已有任务与结果；需要结束计算时使用“终止当前任务”。服务退出则清理自己启动的求解器进程树，不提供续算。后台服务不随 Windows 重启自动启动。

也可在 Windows 单独启动服务并保持其终端运行，再从 Mac 只建立隧道：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\workbench\scripts\start-windows.ps1
```

```sh
ssh -N -L 8765:127.0.0.1:8765 desktop-msi
```

浏览器访问 `http://127.0.0.1:8765`。服务只监听 Windows 回环地址；不需要开放防火墙端口或公网访问。

计算结束后，可关闭 Windows 服务（有活动任务时会拒绝关闭）：

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

前端源文件位于 `web/src/`，修改后运行 `python3 workbench/scripts/build-web.py` 生成并提交 `web/app.js`。不需要 npm 或网络依赖。

```sh
python3 -m unittest discover -s workbench/tests -v
node --check workbench/web/app.js
```

单元测试使用明确的假执行器，不启动 EXE，可在 Mac 运行。真实服务启动、配置校验和计算只允许在 Windows。接口验证脚本 `tests/smoke_windows.py` 通过正在运行的真实 Windows 服务提交短算例，检查完成状态、曲线和下载；日志中记录服务及 EXE 身份。正式验证结论见 `validation.md`。
