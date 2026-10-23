# 收尾测试总表

本阶段已完成本地 Windows 候选包交接，用户明确反馈“已通过，进行真实模型选择工具、多轮回答测试”，本机桌面与媒体人工验收据此记为通过。真实 API 已接入并实际执行 deepseek-v4-pro 模型生成与搜索；RAG 人工标签、干净 Windows 与分发许可仍待分别收口。

2026-10-23 主报告 `artifacts/reports/agent-5-sessions.json` 的 15 个逻辑轮次现已全部通过目标判定，`automatic_passed=true`，六项报告审计通过；修复与重试的失败原件保留。打包桌面重新打开原数据目录后，也通过真实模型历史追问。具体调用、历史失败与复现见 [真实模型报告](LIVE_MODEL_REPORT.md) 和 [脱敏证据](evidence/live-model-summary.json)；个人决策与 AI 执行边界见根目录 [AI 协作开发复盘](../AI协作开发复盘.md)。

人工验收反馈后的私有组件复用修复、21 项相关回归与原数据目录的实际恢复检查，见 [SETUP_RECOVERY.md](SETUP_RECOVERY.md)。本页原收尾汇总和原包摘要保留为历史结果；当前启动版本以 `artifacts/review-target.json` 为准，最新主程序与工具同源标识 `96560392f810e795c578a74048d56ba389f8e81b47df4b1ce0cd9e29ec2ae873`。`live-frozen-local.json` 五项实际检查通过，CLI 退出后所属服务已清理。

用户随后明确要求“最后一轮压力测试不进行，默认通过”。已停止该轮及所属转换 / 工具进程，按用户决定采纳此前已测通过的压力基线；不再重跑压力，也不把取消的轮次计为新实测。记录见 `artifacts/reports/pressure-retest-waiver.json`。

## 证据与命令

原本地收尾阶段的机器可读汇总见 `artifacts/reports/closing-summary.json`；它不覆盖后来的人工确认、复用修复或真实在线结果。所有计数以对应阶段实际 JUnit / JSON 为准；同一用例在多份报告出现时不重复累加。中间失败报告保留，不能当作最终成功。

| 范围 | 报告 | 复现入口 |
|---|---|---|
| 041–047 联合回归 | `boundary-final.xml`、`boundary-supplement.xml`、`boundary-summary.json` | 见 `BOUNDARY_REPORT.md`；两报告去重 225 个通过 |
| 本轮联合回归 | `closing-regression.xml` | README 的 pytest 命令；`test_ai_package.py` 另行依次运行 |
| 新建 / 受影响逻辑 | `finishing-first.xml` | 新工具、下载、调度、去重、真实 RAG；20 项通过 |
| 基础包真实 EXE 转换 | `package-smoke.json` | `smoke-package --without-dev-path` |
| 新目录打包 Host / Worker / 私有 AI | `ai-package.xml`、`ai-package.json` | `pytest tests/integration/test_ai_package.py -q --data-dir data` |
| 固定 RAG 20+5 | `rag-eval.json` | `eval-rag --dataset knowledge/eval.jsonl` |
| MCP 3×100 | `mcp-real-local.json` | `bench-mcp --profile real-local --requests 100 --client-concurrency 100 --rounds 3 --faults` |
| 52 视频与 Qt / 本地 AI | `video-pressure.json` | `bench-video --profile agreed --fixture-root artifacts/fixtures/pressure` |
| 静态与依赖检查 | `closing-lint.txt`、`closing-format.txt`、`closing-pip-check.txt` | `ruff check`、`ruff format --check`、`pip check` |
| 在线准备状态（历史） | `live-api-readiness.json` | 当时未传 `--live-api` 的 preflight；`online_called=false`，不代表当前状态 |
| 真实模型与搜索（本轮） | `live-model-connection.json`、`agent-5-sessions.json` | 实际模型列表、Responses / Search 调用；15 个目标轮次全部通过；失败重试另存，见 `LIVE_MODEL_REPORT.md` |
| 在线修复相关回归 | `live-evidence-final.xml` | 109 项通过；与其他分项有重复，不相加；不等同在线 15 轮全通过 |
| 后续在线协议与 Windows 修复 | `live-protocol-fixes.xml`、`live-windows-recovery.xml`、`live-service-native-integration.xml` | 分别 141 / 23 / 2 项通过；范围有重叠，不相加；后两项覆盖 WMI 回退和所属进程保护 |
| 实际打包后追问与本地链 | `live-desktop-online.json`、`live-frozen-local.json` | 原会话真实追问通过；最新 Host/Worker 的五项实际检查通过 |
| 文档 / 资产核对 | `delivery.xml` | `pytest tests/unit/test_delivery_manifest.py -q` |

本机当前实测 Windows 版本、构建源码标识、包 SHA、精确计数与最新压力数值由 `closing-summary.json` 保存。完整包版本为候选 `0.1.0-rc1`，没有编造 Git commit / tag / URL。

## 已观察到的结果与限度

- 基础 ZIP 经新目录解压、仅系统 PATH 启动 Qt Windows 插件，实际导入、缩略图、转换及完整解码；没有在核心进程导入 Torch。它仍是在开发宿主机上执行，不是干净 Windows 证明。
- RAG 自动 dense 20/20、词法 19/20、混合 20/20、混合+重排 20/20；5 个库外案例均标记本地依据不足。没有观察到比 dense 更高的命中，不能宣称提升。阈值未按这批答案反复调整；所有人工标签仍 pending，正式 T08 待核对。
- MCP 改动前正常三轮分别只有 97 / 96 / 95 成功；排队超时真实存在。复用 HTTP 客户端后，同规模三轮各 100/100，后端各执行 80 次，同作用域合并各 20 次；峰值全局 7 / 队列 73，RAG 1 / SQL 4 / 文件 2。七个单列故障场景通过。负载是三个原创短章节，未把长文本 / 网页搜索混入同一个性能结论。
- 视频完整队列为 30 分钟 1080p、1 分钟 4K、50 短片，共 52 个，全部实际转换并校验。GUI 心跳、取消、AI 次数与资源以最新 JSON 为准。素材为合成色条 / 循环，不宣称自然场景普遍速度。
- 当前 `video-pressure.json` 明确引用先前通过基线（原始副本 `video-pressure-before-pooling.json`），总耗时 559.125 秒，心跳 p95 65.187ms / 最大 119.999ms，取消反馈 49.207ms / FFmpeg 停止 1299.219ms，24 次本地 AI。接续期间停服导致的一轮失败单列为 `video-pressure-services-offline.json`；服务已恢复，最后一轮被用户取消，没有生成新的完整成绩。
- 对通过基线的 30 分钟和 4K 输出另执行完整解码，均 exit 0，见 `pressure-full-decode.json`。应用内对短片完整解码，对长片先核对流、编码、尺寸和时长；不把“有 ffprobe 信息”写成“长片已完整解码”。
- 资源为每 250ms 对所属进程树及共享本地服务采样。CPU 是观察到的计时差，RSS 是采样峰值；短进程可能漏采，共享服务可能有无关负载，不能当成全机精确资源归因。

## 功能 F01–F25

| 功能 | 当前结论 | 主要证据 / 未完成边界 |
|---|---|---|
| F01 桌面操作 | 自动通过，本机桌面人工通过 | 三档实际 Qt、键盘、窗口与压力报告；用户本机总体确认 |
| F02 导入 | 自动通过 | 五类视频、目录 / 递归 / 去重、50 文件和 Xiph |
| F03 元数据 | 自动通过 | ffprobe 对照、旋转 / 未知 / 失败边界 |
| F04 缩略图 | 自动通过，本机媒体人工通过 | 真实截图与缓存、实际包导入；用户本机总体确认 |
| F05 参数 | 自动通过 | 三目标、高级参数、非法组合与冻结快照 |
| F06 轨道确认 | 自动通过，本机转换人工总体确认 | 兼容保留与不兼容拒绝 / 确认；不代填额外逐样本签核 |
| F07 输出与原件保护 | 自动通过 | 层级 / 旁置 / 重名、指纹、junction 与提交故障 |
| F08 顺序队列 / 进度 | 自动通过 | 完整 52 队列、并发 1 与持久化 |
| F09 取消 / 重试 | 自动通过 | 真实停止耗时、整批 / 当前、重试幂等 |
| F10 预设 / 恢复 / 打开位置 | 自动通过，本机桌面人工总体确认 | Qt 控件与 SQLite 恢复、实际位置打开 |
| F11 首次准备 | 本机冻结链与复用恢复通过；独立机待验 | 新短 ASCII 数据根、校验缓存、私有初始化；人工反馈的停服复用问题已修复，见 `SETUP_RECOVERY.md` |
| F12 AI 视图 | 自动通过，本机桌面人工总体确认 | 停靠 / 浮动 / 隐藏共用状态；真实在线流程另记 F13–F15 |
| F13 多轮 / 历史 | 真实目标检查通过 | 五会话各三轮；实际打包桌面重开原目录并通过历史追问；历史失败另存 |
| F14 在线配置 / 问答 | 本机真实接入和目标验收通过 | DPAPI 凭据、实际模型列表与 deepseek-v4-pro 返回 / usage；不等同生产或干净机验收 |
| F15 建议确认 | 本地 / 替身通过，真实提案阶段已有记录 | 第二轮实际 SQL 与建议校验；不自动应用，真实 GUI 确认专项以单独证据为准 |
| F16 资料 / 索引 | 实际构建通过，人工标签待核 | 固定版本 / 摘要、重复构建与切换 |
| F17 混合 / 重排 | 本地实际执行通过，正式质量验收待核 | 双路、RRF、CPU worker、固定 20+5 |
| F18 MySQL | 本地实际执行通过 | 隔离库、只读 / 写入角色、outbox、乱序重放 |
| F19 本地文档 | 自动通过 | TXT / MD / LOG / PDF / DOCX、授权 / 指纹 / 游标与拒绝 |
| F20 自动搜索 | 真实搜索和回答闭环通过 | 保存实际搜索参数 / 来源；区分模型主动选择与主机兜底；未知格式如实说明无法确认 |
| F21 MCP | 本地实际执行通过 | 真 stdio / 六工具 / 协议与包入口 |
| F22 并发与恢复 | MCP / 本地自动通过；真实五会话目标检查通过 | 原有负载基线；五会话功能验证与历史隔离通过，不新增压力成绩 |
| F23 去重与预算 | 本地自动与真实在线目标检查通过 | 20% 合并、作用域隔离、调用上限 / 截断；真实超预算失败与后续摘要修复保留 |
| F24 观测与异常 | 自动通过，导出真人待核 | 错误层、trace、白名单诊断与哨兵检查 |
| F25 构建与交付 | 最新本地候选通过检查；源码已提交 GitHub | 已验证匿名可读；二进制公开分发另待干净 Windows 与许可核验 |

## 验收 T01–T16

| 验收 | 状态 | 说明 |
|---|---|---|
| T01 信息 / 导入 / 缩略图 | 自动通过，本机人工通过 | 媒体边界、52 队列及实际 EXE；用户本机总体确认 |
| T02 格式 / 轨道 | 自动通过，本机转换人工总体确认 | 三目标输出和轨道确认；未另行逐样本签核 |
| T03 保存保护 | 自动通过 | 040 文件系统报告与后续回归 |
| T04 队列 / 取消 / 重试 | 自动通过 | 真实转换、故障、取消与压力 |
| T05 输出完整性 | 自动解码通过，本机媒体人工通过 | 完整解码与声画标记通过；用户明确人工验收通过，限本机范围 |
| T06 桌面与准备视图 | 本机自动与桌面人工通过 | 三档缩放、停靠 / 浮窗和向导；复用故障修复后用户确认通过 |
| T07 真实多会话 / 建议 | 在线目标检查通过；人工应用确认待核 | 15 轮全部判定通过；四个 PENDING、一个保持原值；未代用户点击应用 |
| T08 固定 RAG | 自动达标，人工标签待核 | `human_review_complete=false` |
| T09 检索对照 / 版本 | 自动通过 | 20/19/20/20 命中，实际三阶段与版本切换 |
| T10 MySQL | 本地通过 | 真库及权限 / 同步故障 |
| T11 文档授权 / 异常 | 自动通过 | 正常格式 / 越权 / 无文字 / 过大 / 提示注入 |
| T12 真实搜索 / 接入异常 | 真实回答闭环通过 | 有真实链接、参数与 usage；认证等故障仍按各自替身 / 真实证据分开记录 |
| T13 MCP 负载 | 自动通过 | 正常三轮全成功，故障单列 |
| T14 视频压力 | 既有基线自动通过；最后复测用户豁免 | 不增加新成绩，完整规模和响应以原始报告为准 |
| T15 干净 Windows 全链 | 未验证 | 本机新目录 + PATH 隔离不替代独立机；本机在线已执行，不代表干净机在线验证 |
| T16 文档 / 脱敏 / 发布 | 源码与文档已提交；公开读取已验证 | 实际仓库及 commit 见 `evidence/github-delivery.json`；二进制 Release 单独待核 |

## 票据与发布状态

048 / 049：最新候选 Host/Worker 同源，五项实际本地检查通过。050：自动评估完成，正式验收待用户核对标签。051 / 052：已有实测；最后压力复测按用户要求停止并采纳基线。053：没有可验证的干净 Windows 结果，未宣称通过。054：真实五会话各三轮的目标判定、六项报告审计及打包后历史追问通过，人工应用建议另列。055：本机桌面/媒体人工通过，未完成的独立门槛继续保留。056：用户已授权测试无误后提交源码，本轮测试已收口，仓库已创建于 [daninyc/windows-video-converter-agent](https://github.com/daninyc/windows-video-converter-agent)，提交结果另存交付回执。

在线入口已检查本机人工记录和显式 opt-in，使用用户保存的接入配置实际调用。独立机资源不是本机真实 API 验证或已授权源码提交的前置；干净 Windows、第三方二进制分发许可及对应源码材料仍是完整便携包公开发布的单独门槛。源码仓库提交与二进制 Release 分开处理，提交前仍核对实际源码清单与敏感内容，不默认上传模型、数据库、原生归档或候选 ZIP。

最终短 ASCII 存储根的包测试已通过：`ai-package.xml` 1 passed，384.66 秒，实际基础 EXE → 打包工具 → 新私有 MySQL / Qdrant / Ollama → 索引 → 六工具发现 / RAG 重排 / 只读 SQL / 授权文件检查。CLI 完成后所属服务记录清空。模型 / 原生归档复用已校验缓存，不是独立机联网首次下载证明。基础 / AI 包同源标识为 `441a49480462bd0846f49b578eecd6b968dd5a9452629e9a12023b8d5e293faa`。

## 已知限制

首版只做 Windows x64、SDR、单主视频轨；没有 macOS / 移动端、HDR 色调映射、硬件编码、并行转码、OCR、任意 SQL / shell 工具、自动升级、签名或商店发布。本机 LongPathsEnabled=0，超长路径创建可能被 Windows 拒绝，未修改系统开关。

一次运行多个独立 CPU 重排模型曾触发页面文件不足。失败记录保留，常规应用限制为单重排进程；不同时开多套压力 / 推理测试。干净系统最低资源和不同 Windows 版本兼容性未被证明。MySQL Connector 明确使用纯 Python 驱动，未修改系统 DLL。

新增实际边界：本机原生 MySQL 26.7.0 无法在中文数据目录初始化，日志提示无法找到该路径下的消息文件 / datadir；短路径查询没有得到 ASCII 别名。保留失败记录 `ai-package-before-unicode-data-limit.json`，当前 AI 本机验收使用 ASCII 数据目录（保留空格验证），不宣称中文 AI 存储路径已支持。输入视频 / 文档的中文路径不受这个原生数据库存储限制的约束。

同轮又复现 Qdrant Gridstore 在较深 ASCII 路径建集合返回 500 / Windows 路径错误。交付入口使用项目 `artifacts/rv-*` 的短 ASCII 存储根；保留 `ai-package-before-short-data-root.json` 及 worker 索引错误链。MySQL 的 ASCII 空格目录初始化已经越过，最终使用更短目录完成整链，不把路径失败误归因于缺 Python 包。

许可 / 精确对应源码材料尚未核清，见 `THIRD_PARTY.md`，二进制候选仍不标记可公开分发。本机人工已确认，本轮真实模型与搜索目标验收通过，源码已提交并验证匿名可读；没有把源码提交等同于二进制 Release。
