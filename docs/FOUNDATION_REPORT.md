# 基础阶段实施与验收

本文件保留基础阶段的历史结果。后续 009–019 已实施，当前转换状态见 [转换闭环验收记录](CONVERSION_REPORT.md)。

日期：2026-10-21，北京时间。用户本轮授权按 SPEC.md 实施基础 001–008；未扩展到核心、边界或收尾。复用已有 environment 和 `D:\ffmpeg_ffprobe`，没有重新安装依赖、下载模型、调用付费 API、修改环境探针数据库或发布 GitHub。

## 逐票结果

| 票 | 实际交付 | 验证与结果 |
|---|---|---|
| 001 | src 可安装工程、GUI/devtools 入口、AppPaths 注入、core/tools/cpu-rerank/dev 四组完整传递依赖锁、pytest 标记和参数 | editable 安装成功；pip check 无冲突；工程测试验证默认阻止外网、命令拒绝未知项、锁文件包含依赖 extras 和固定 CPU wheel 来源；真实 GUI 入口关闭后无后台线程 |
| 002 | ErrorCode/AppError/ErrorInfo、结果 envelope、CallContext 标识、stderr JSONL | 嵌套字段、异常文字、URL 查询串、路径、正文和伪装为状态的凭据均不原样输出；脱敏失败只输出安全 trace；取消继续传播 |
| 003 | 不可变媒体/设置/计划/尝试模型、计划哈希与丢失项、BatchCommand、状态机 | 微秒与分数帧率序列化往返；设置不允许 CRF/码率混用；计划变更令旧哈希/确认失效；四种终态、迟到成功、重复事件与新尝试重试均有验证 |
| 004 | SQLite schema v1→v2、WAL、独占写线程与有界串行队列、独立读连接、设置/预设/素材/尝试仓储、事务 outbox | 故障触发器证明业务/事件一起回滚；并发读写；迁移保留记录；终态不重复发事件；重启标记 INTERRUPTED；无 MySQL 连接前置条件 |
| 005 | Qt Widgets 主窗口、任务/详情/设置/底部进度、同一 AI dock 可浮动/隐藏、浅色样式、键盘入口、参考记录 | 实际打开/关闭、切换停靠、禁用状态和最小窗口测试；真实 Windows 插件下 100%/150%/200% 截图与退出检查；逐张目视确认基础容器和空态文字；参数区在最小窗口可滚动 |
| 006 | 专用 asyncio 线程/loop、带标识 RuntimeEvent、Qt queued signal、提交/取消/关闭、后台异常上报；GUI 退出接线 | 后台等待时 Qt 定时器持续运行；回调在 GUI 线程；取消/完成竞态每任务一个终态；关闭后拒绝新提交；入口退出时存储/运行桥线程均结束 |
| 007 | 便携/显式/开发路径定位、真实版本/编码器/封装快照、二进制身份与哈希缓存、prepare core | 隔离 PATH 使用真实 FFmpeg/ffprobe 9.0.2；libx264、aac、libvpx-vp9、libopus 与 mp4/matroska/webm 全部存在；替换二进制使缓存失效；缺编码器明确返回清单 |
| 008 | smoke 生成器、22 个自有素材、manifest、tests/fixture_support.py | 实际生成五种封装；ffprobe 核对编码、轨数、语言/默认标志、时长/尺寸/时间基、90° 旋转和帧时间戳差异；文字/加密/空白/损坏文档实测；重复运行校验复用、已改文件和非工具文件拒绝覆盖、路径越界拒绝 |

## 固定接口与目录

- `AppPaths.from_argument(...).ensure()`：默认项目 data，可传独立目录；不默认写用户 C 盘资料目录。
- `CallContext.new_turn()/new_invocation()`、`result_envelope(...)`、`JsonlLogger.event(...)`：调用标识与统一结果，日志只保留受控状态和哈希摘要，stdout 留给未来 MCP。
- `ConversionSettings/ConversionPlan`：冻结模型；`plan.confirm(expected_hash)` 只匹配当前计划。更新模型需重新校验，不能使用 Pydantic 的免校验拷贝来绕过不变量。
- `transition(attempt, state, **updates)`、`retry(attempt, plan_id=...)`：新尝试保留 job_id、生成新 attempt_id；原终态记录不被修改。
- `LocalStore(database_path)`：上下文管理器或显式 close；save/get settings、preset、asset、attempt；`pending_events()/acknowledge_event()/record_sync_failure()` 为后续 MySQL 投影预留本地事务契约，不发网络请求。
- `RuntimeBridge.submit(coroutine_factory, context)`：工厂在唯一后台 loop 创建连接；取消按返回 task_id。不要从 Qt 线程创建后再跨循环复用连接。信号接收方在 GUI 线程更新控件。
- `inspect_toolchain()/inspect_toolchain_async()`：结构化能力快照；`locate_binaries()` 支持显式路径；`run_tool()` 参数数组、无 shell、超时和错误码。
- `generate_smoke_fixtures(root, paths)`：素材和 manifest 位于 root。既有文件按哈希确认，不覆盖用户文件；重建使用新空目录，不靠文件逐字节相同判断等价。

核心/工具/CPU 推理/开发锁文件各含 11/45/43/96 个分发包，组间会重叠，数字不可相加。版本与 CPU wheel URL、SHA-256 来自本机安装记录；来源清单见 [dependency-sources.json](dependency-sources.json)，未在下载报告中找到的预存包明确标识为来源未记录。未用空白 venv 重新安装整套依赖。

## 实际命令与证据

以下均从项目根目录先执行 `. .\environment\activate.ps1`，确保 Python、临时目录和缓存使用项目隔离环境：

```powershell
python -m pip install --no-deps --no-build-isolation -e .
python -m pip check
python -m ruff check src tests
python -m ruff format --check src tests
python -m pytest tests/unit tests/gui tests/integration -q --junitxml artifacts/reports/foundation.xml
python -m media_converter.devtools prepare --components core --data-dir data
python -m media_converter.devtools fixtures --profile smoke --root artifacts/fixtures --data-dir data
python -m media_converter.devtools.capture_shell --scale 1 --output artifacts/ui/shell
python -m media_converter.devtools.capture_shell --scale 1.5 --output artifacts/ui/shell
python -m media_converter.devtools.capture_shell --scale 2 --output artifacts/ui/shell
```

最终结果：33 passed、0 failed、0 errors、0 skipped、0 blocked（单元 23、GUI 7、集成 3）；pip check、Ruff 检查及格式检查均通过。结果由 `artifacts/reports/foundation.xml` 和 `artifacts/reports/foundation-summary.json` 保存，区分 passed/failed/skipped/blocked。截图为 `artifacts/ui/shell/shell-{100,150,200}.png`；同名 JSON 保存真实 Windows 11 构建、Qt windows 插件、F24G3Q 屏幕、逻辑尺寸 1080×720、实际 DPR 1/1.5/2 和截图像素 1080×720/1620×1080/2160×1440。

本机系统原生是 125% 缩放，脚本用 Win32 获取基准 DPI、在独立进程中调整 QT_SCALE_FACTOR 到实际目标 DPR，不修改系统显示设置。以 QApplication 探测 DPI 的早期脚本出现过原生进程崩溃；现改用 Win32 基准、隔离截图子进程 PATH，并在退出前处理窗口延迟删除。后续三档截图及自动化退出回归均已通过；不能据此保证所有显卡和屏幕都已验证。

样本清单为 `artifacts/fixtures/manifest.json`，能力快照为 `data/toolchain-capabilities.json`，运行数据为 `data/state.sqlite3`。运行产物不提交源码仓库。

## 发现并修正的问题

1. pytest 默认临时目录缺少父目录：测试配置主动建立项目 artifacts/tmp，后续临时与缓存路径通过 environment/activate.ps1 注入 D 盘。首次 editable 安装曾使用 pip 自动清理的 C 盘临时 wheel 缓存，随后只读确认该目录不存在；没有将项目生成物留在该目录。
2. 单元/集成两个 test_toolchain 同名：将 tests 各目录设为包后，按票指定的联合命令正常收集。
3. FFmpeg rotate 元数据写入未生成预期显示矩阵：使用 `-display_rotation:v:0 90`，必须由 ffprobe 检出才接受样本。
4. 直接按 QT_SCALE_FACTOR 1/1.5/2 会叠加系统 125%：按实际基准校准，并由 JSON 的实际 DPR 和截图像素验证。
5. 依赖闭包必须处理诸如 `httpx[http2]` 的 extras：锁文件已包含 h2 等传递依赖，并有元数据递归测试。
6. 收窄日志可原样保留的字段和值，防止凭据被放在任意字典键或 tool_name/state 字段中漏出；脱敏故障保留合法 trace。

## 未实现与限制

009–056 尚未执行。当前尚不能通过界面导入或转换视频，没有聊天、MCP 业务工具、正式知识库、MySQL 业务投影、在线联调、压力验收、便携发布包或 GitHub 提交。窗口显示的默认参数仅为基础布局，相关编辑和执行均禁用。

后台取消可以停止等待，但不能强制停止已经进入原生线程的阻塞调用。`run_blocking()` 的调用者必须提供有界 I/O；长解析和推理后续按 Spec 使用独立工作进程。关闭测试覆盖合作取消与短工作任务，不声称 Python 可以安全强杀任意线程。

基础截图是实际 Qt 缩放，未切换 Windows 系统显示比例；最终交互/多显示器/干净 Windows 验收仍属后续票。环境服务/模型的早期探针结果没有计入本次应用验收。

下一票 009 可直接复用：MediaAsset/ImportRoot、LocalStore、MainWindow 容器、RuntimeBridge 和 smoke manifest，接入文件、拖入与目录导入；本轮没有提前接入导入业务。
