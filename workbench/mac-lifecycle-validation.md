# Mac 启动与关闭脚本验收

日期：2026-10-23（Asia/Shanghai）。运行代码提交 `1d9636f`。修改仅涉及工作台控制脚本、测试和使用说明，没有修改、编译或替换 V2.0.0 求解器。

## 使用入口

项目根目录的 `启动工作台.command` 和 `关闭工作台.command` 分别指向本 checkout 的 `workbench/scripts/open-mac.command` 和 `close-mac.command`。已设置执行权限，使用 zsh 解析软链接真实路径，路径含中文或空格仍可调用。

启动等待 Windows 服务和 Mac 转发访问均通过身份检查，再调用 macOS `open` 打开默认浏览器。后台隧道不依赖启动终端存活。关闭遇到运行、校验、取消中的任务或其他来源的求解器进程时拒绝执行；检查失败也保留连接。只有确认远端服务和计算进程退出后才关闭专属 SSH 控制连接。

## 验证结果

- 26 项单元/服务契约测试通过，其中新增 10 项覆盖活动任务、外部/遗留进程、断网、关闭顺序、外来端口占用、重复启动、失败回滚、并发调用和私有目录权限。使用 Python 3.12 和假执行器，不在 Mac 执行求解器。Mac 启动器本身及新增 10 项测试也通过系统 Python 3.9 验证。
- Windows PowerShell 5.1 解析和实际调用通过。Mac 根目录启动入口正常启动服务、建立后台隧道并调用默认浏览器；主脚本退出后隧道仍可使用。
- 再次启动复用相同 Windows 服务 PID 和 SSH master PID，没有创建第二条隧道。
- 独立小网格任务 `mac-lifecycle-busy-check`（`20261022T161636Z-5d7926d3a6e6`，任务 ID 为 UTC）在 Windows 上运行时，关闭脚本返回非零并显示任务与真实 `Solver-IBM.exe` PID；之后 API 仍确认任务为 `running`，隧道也保持运行。随即仅终止该验收任务，最终状态 `cancelled`，未改写用户草稿。
- 空闲关闭和再次关闭均成功。最终独立检查：Windows 服务 PID 列表为空、无 Solver-IBM / FluidX3D 进程、Windows 8765 未监听，Mac 专属隧道和 8765 监听均不存在；临时 SSH 检查连接已退出。
- 所有算例输入、历史结果、服务日志保留。验收任务记录保留用于复查。机器可读报告见 [mac-lifecycle-acceptance-20261023.json](mac-lifecycle-acceptance-20261023.json)。

Mac 默认 Python 3.9 不满足服务测试使用的 `hashlib.file_digest` 要求，完整服务测试使用已安装的 Python 3.12；启动/关闭脚本无需切换 Python 或安装第三方包。首次受限测试环境不允许绑定回环端口，授权回环测试后完整测试通过。
