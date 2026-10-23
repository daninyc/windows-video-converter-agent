# 本地 AI 组件复用恢复修复

2026-10-23，用户在人工验收时反馈“知识检索和结构化查询依赖未就绪”，并提供准备向导截图。

## 原因与修复

当前验收数据目录是 `artifacts/rv-1e789301`，此前已准备私有 Ollama、Qdrant、MySQL。排查时，配置中的三个私有端口均未监听；开发环境的另三个端口虽然在运行，但不是该验收目录配置的服务。关闭应用会正常停止所属私有服务。

原来的 `SetupService.prepare(mode="reuse")` 发现配置文件存在就直接构建索引，没有恢复该目录已经安装的私有服务。因此索引调用失败，MySQL 健康检查也不能连接。不是缺少 Python 包或需要配置在线 API。

修复后，有 `private-components.json` 的目录在两种准备选项下都会先恢复私有服务，再构建/核对索引并检查实际能力。没有私有标记的外部复用保持原有行为，需外部服务先运行。命令行准备检查结束后，无论选项和成功失败，均清理所属服务并释放目录锁；不按进程名结束外部服务。

## 已实测

- `artifacts/reports/setup-recovery-regression.xml`：21 项相关测试通过，包含新增加的 8 项回归；两者不能相加。
- `artifacts/reports/setup-recovery-local.json`：使用原验收目录，从三个私有端口均未监听恢复，五项实际检查通过。
- `artifacts/reports/setup-recovery-frozen.json`：修复版 EXE 在原窗口正常关闭、私有服务停止后，使用 `--mode reuse` 恢复原目录，五项实际检查通过；结束时关闭所属服务。
- 实际检索包含向量召回、词法召回、RRF 和 CPU 重排；MySQL 查询返回 6 条技术规则，并检查只读账号授权。没有用端口监听代替功能检查。
- 本次修改文件及新增测试的 Ruff 检查和格式检查通过。
- 已重新打开修复版客户端，目视核对 `artifacts/ui/setup-recovery.png`：显示“本地 AI 已就绪”，五项能力均为“可用”。原三个外部开发服务的 PID 和监听端口保持不变。

相关回归命令：

```powershell
. .\environment\activate.ps1
python -m pytest tests/unit/test_setup_service.py tests/unit/test_service_ownership.py tests/integration/test_component_prepare.py tests/gui/test_setup_wizard.py --basetemp artifacts/tmp/setup-recovery --junitxml artifacts/reports/setup-recovery-regression.xml -q
```

## 使用与边界

使用项目根目录 `启动验收.cmd`，实际客户端和数据目录以 `artifacts/review-target.json` 为准。在“准备 AI”窗口点击“按所选方式准备”，完成后应显示知识检索与重排、结构化查询均可用。应用正常退出会停止所属私有服务，下次仍通过准备操作恢复；“重新检查”只检查状态。

保留原数据目录、模型、已有数据库和索引；没有重置数据库、重设 root 或改系统服务。真实 API、人工播放、独立 Windows 验收仍是未完成的独立项目。本次没有调用在线模型或搜索，没有重跑已被用户取消的压力测试。

新版启动、最终包摘要和界面证据由 `artifacts/reports/setup-recovery-summary.json` 单独记录。历史 `closing-summary.json` 与原候选包保留，不能用旧包证据冒充本次修复验证。

新候选包位于 `dist/setup-recovery`。本机实际运行的是其中已测的新桌面 Host，继续使用原先已验证的已安装 AI worker；两者源码标识分别记录在入口元数据，未声称已将新工具候选升级到验收数据目录。
