# 041–047 边界与桌面开发记录

本轮按用户“依照开发手册依次完成 41–47 工作”的授权实施，日期为北京时间 2026-10-23。实现范围止于 047，不执行便携包构建、GitHub 发布或真实收费 API 验收。

## 范围与证据

| 票 | 已实现与实际验证 | 对应代码 / 测试 |
| --- | --- | --- |
| 041 | 三目标媒体边界、语言/default/forced 标志、旋转一次、VFR 保留、严格时长与完整解码；真实多视频轨与 HDR 标记拒绝规划；合成闪光/声音标记检查 | `media/probe.py`、`media/planner.py`、`jobs/output_validator.py`；`test_media_edges.py` |
| 042 | 一个连接拥有者；五路实际 MCP 调用断连后共享重连，只读调用最多重试一次；调用期限、关闭、取消无回复和不兼容协议 | `mcp_client.py`、`mcp_server.py`；`test_mcp_recovery.py`、`test_mcp_client_policy.py` |
| 043 | 认证/额度错误按配置版本阻止后续在线请求；显式测试或配置更新恢复；限流不自动重放模型；取消后迟到文本/建议不落库；恶意文档不能扩大本地读取范围或增加命令工具 | `services/config.py`、`agent/`、`tools/web_search.py`；`test_agent_failure_policy.py`、`test_agent_isolation.py` |
| 044 | 五项真实本地健康检查；实际 embedding、双路检索与重排；协议/SDK/模型/索引/tokenizer 版本；MySQL 只读权限；授权文件读取。私有服务按 PID、启动时间、可执行路径管理 | `services/health.py`、`process_manager.py`、`mysql_instance.py`；`test_service_ownership.py`、`test_local_doctor.py` |
| 045 | 固定来源/版本/大小/哈希/许可；缓存复用、Range 续传、取消、错误哈希拒绝、安全解压、安装标记、提交中断恢复；私有 Ollama/Qdrant/MySQL/模型和索引准备 | `services/component_manifest.py`、`components.json`、`downloads.py`、`preparer.py`；组件与原生 MySQL 集成测试 |
| 046 | 首次检查与准备向导、复用/私有选择、来源/空间/阶段提示、取消与重试、重开同一操作、接入配置/连接测试；可选 AI 包缺失时仍能打开转换 GUI | `ui/setup_wizard.py`、应用接线；`test_setup_wizard.py`、`test_application_entry.py` |
| 047 | 真实 Windows 100%/150%/200% 控件与键盘操作、停靠/浮动收回；窄窗口滚动与可见输入/发送；工具摘要、trace；白名单诊断 ZIP | 主窗口/助手布局、`services/diagnostics.py`、`ui/diagnostics_dialog.py`；`test_desktop_acceptance.py`、`test_diagnostics_export.py` |

测试文件路径分别位于 `tests/unit`、`tests/gui` 和 `tests/integration`。所有测试默认禁止非 loopback 网络；供应商响应、限流/额度、恶意模型和部分 UI 准备时序使用明确的测试替身。MCP 崩溃、媒体转换、下载 HTTP、模型检索、MySQL 初始化/权限/取消、窗口操作使用真实本地实现。

## 修复依据与边界

- 旧输出检查允许 3% 时长误差，本轮按 Spec 收紧为 `max(250000 微秒, 2 帧)`。HDR/PQ/HLG 或相关动态元数据不进入 SDR 管线，避免静默丢失色彩信息；没有新增 HDR 映射能力。
- MCP 的 Windows venv Python 存在启动重定向进程，不能把监听/工具 PID 的直接父进程等于 GUI PID 当成唯一所有权依据。工具使用随机实例标记和父宿主记录，实际 stdio 进程仍由 SDK 拥有和关闭。
- Windows 服务端口/父子进程识别改用原生接口。MySQL 监控父子关系另用真实监听子进程场景验证，外部复用进程不被终止。
- Qdrant 当前原生发布二进制只加载 YAML 配置；写入兼容 YAML 的 JSON 内容并使用 `.yaml` 后缀。错误后缀的实测失败保留在初期报告中。
- 联合回归发现 Windows 在目录提交和删除 MySQL 初始化脚本时会短暂拒绝访问；加入有上限的共享冲突重试，并在数据库可用后删除初始化脚本。不更改目录权限、不结束他人进程。
- MySQL Connector 即使指定 `use_pure=True`，仍会尝试加载可选 C 扩展。本工程明确禁用该可选模块并使用 Python 驱动，避开此前已复现的 Miniconda/OpenSSL 加载错误；没有修改全局 DLL 或第三方安装文件。
- 下载安装在暂存区完成校验和标记，再提交到目标；取消先等写入线程关闭句柄后清理。相同版本的组件重开会重新检查，不重复安装；磁盘空间按未安装组件估算。

## 组件来源与私有实测

组件清单位于 `src/media_converter/services/components.json`，包含已有开发环境核验过的 FFmpeg、Ollama、Qdrant、bge-m3 blob 和重排模型/tokenizer 文件。Git 小文件按 git-blob SHA-1 校验，大文件与原生归档按 SHA-256 校验。固定版本的 FFmpeg 下载地址若内容变化会校验失败，不会接受新哈希。

本轮另从 [MySQL 官方归档页](https://downloads.mysql.com/archives/community/) 获取原生 Windows ZIP，匹配官方页面的 MD5 后计算并固定 SHA-256，证据见 `artifacts/reports/mysql-archive-045.txt`。清单中的新私有引擎为 26.7.0；已有独立 8.0.46 数据目录继续使用其原引擎，不做静默升级。两种原生二进制均实际创建过隔离项目数据目录、执行只读查询并关闭。取消初始化另核对真实进程退出与新目录清理。

完整开发环境私有准备目录为 `artifacts/private-ai-045`，模型、缓存、数据库、临时文件、Ollama profile 均落在该目录或项目内。完整准备经过真实五项健康检查。CLI 私有准备检查结束后关闭所属服务；GUI 内准备的服务在应用退出时关闭。既有开发服务继续复用，不被本轮产品进程管理器关闭。

**049 尚未生成可发布的 AI 运行包。** 非开发环境或 frozen 运行环境缺少该组件时明确报告缺失，不会提示假就绪，也不要求评审运行 pip。最终无开发环境的分包/下载/离线演练仍归 048、049、053。

## 运行与复验

在项目根目录的 PowerShell 执行：

```powershell
. .\environment\activate.ps1
.\environment\start-services.ps1
python -m media_converter.devtools doctor --require all-local --data-dir data --output artifacts/reports/doctor-local.json
python -m media_converter.devtools prepare --components core --data-dir data
python -m media_converter.devtools prepare --components ai --mode reuse --data-dir data
python -m media_converter.devtools prepare --components ai --mode private --data-dir artifacts/private-ai-045
python -m ruff check src tests
python -m ruff format --check src tests
python -m pip check
python -m pytest tests/unit tests/gui tests/integration -q --data-dir data --fixture-root artifacts/fixtures --xiph-root artifacts/fixtures/xiph --junitxml artifacts/reports/boundary-final.xml
```

不要在同一时刻启动两个使用相同 pytest basetemp 的测试进程。测试目录会在新一轮测试时重新创建，需保留的截图统一复制到 `artifacts/ui/boundary-047`。三档完整窗口截图命令为：

```powershell
python -m media_converter.devtools.capture_shell --full --scale 1 --output artifacts/ui/boundary-047
python -m media_converter.devtools.capture_shell --full --scale 1.5 --output artifacts/ui/boundary-047
python -m media_converter.devtools.capture_shell --full --scale 2 --output artifacts/ui/boundary-047
```

## 结果记录

最终结果已收取：

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 联合回归，含真实 Xiph 素材 | **224 passed，0 failed/error/skipped**；JUnit 482.567 秒 | `artifacts/reports/boundary-final.xml` |
| 最后补充回归：D 盘 TEMP/TMP、端口冲突提示、初始化取消、组件提交、桌面与准备并行 | **109 passed，0 failed/error/skipped**；JUnit 103.555 秒 | `artifacts/reports/boundary-supplement.xml` |
| 两份报告按 classname/name 去重 | **225 个通过用例**；补充组仅新增 1 个准备/真实转换并行场景，其余为重复回归 | `artifacts/reports/boundary-summary.json` |
| 真实本地 doctor | 视频、六工具协议、双路检索/独立重排、只读 SQL、授权文件读取均通过；无在线调用 | `artifacts/reports/doctor-local.json` |
| 完整私有准备 | 五项真实检查通过，CLI 检查结束后私有服务已关闭；所属记录和端口均核对无残留 | `artifacts/reports/prepare-private-045.json` |
| 三档实际窗口 | 100%/150%/200%，关键操作、输入和发送均有可见像素；Tab、Alt+A、浮动收回、向导检查通过；截图已目视检查 | `artifacts/ui/boundary-047/desktop-*.json` 及对应 PNG |
| 合成声画标记 | 三目标最大绝对偏差 **19.938ms**，低于本样本 100ms 目标；不是所有媒体的通用承诺 | 最终 JUnit 的 `av_marker_offset_ms` |
| 静态与环境检查 | Ruff 通过；169 个 Python 文件格式通过；pip check 无损坏依赖 | `boundary-lint.txt`、`boundary-format.txt`、`boundary-pip-check.txt` |

源开发服务的监听 PID 仍为 MySQL 11460、Qdrant 6824、Ollama 9644，与本轮开始核对一致。没有调用真实 DeepSeek/Search API，也没有发布。最后的 D 盘 TEMP/TMP 补验直接检查真实原生初始化子进程环境，而非依赖开发终端已激活环境这一偶然条件。

已收取的早期分组结果：041 为 24 passed，043 新增/关联回归为 20 passed，故障修复定向组为 32 passed，启动/下载补充组为 23 passed；分组含重复用例，不能累加为项目总数。初次联合结果 `boundary-all.xml` 为 215 passed / 2 failed，作为修复前证据保留，不当作最终通过。

## 仍待验证

- 媒体完整解码和声画标记是自动检查，没有真人观看/听辨签字；人工播放核对待补，不宣称已完成。
- 三档截图使用独立进程的真实 Windows Qt 插件和 `QT_SCALE_FACTOR`，不是修改系统显示设置。已验证 Tab、快捷键、鼠标、窗口切换；不代表所有多显示器/辅助技术组合都测过。
- 真实 DeepSeek/Search 供应商、临时 Key 窗口、usage 与端到端在线回答仍归 054，本轮未消费真实 API。
- 长视频压力、RAG 人工标注/校准、干净 Windows、分发许可 C05、便携包与 GitHub 发布仍由后续票处理。源码已含组件许可元数据，不表示已完成整个项目的分发许可审核。
