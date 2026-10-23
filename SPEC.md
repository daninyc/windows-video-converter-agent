# Windows 视频转换器与 Agent 开发 Spec

- 版本：0.7；001–047 历史见 [BOUNDARY_REPORT.md](docs/BOUNDARY_REPORT.md)，048–052 本地收尾及保留门槛见 [TEST_REPORT.md](docs/TEST_REPORT.md)。050 人工标签、053 干净 Windows、054 真实 API、055 整体验收、056 公开发布尚未全部完成。
- 整理日期：2026-10-21；本轮更新：2026-10-23，北京时间。
- 项目目录：D:/CodexWorkspace/bossjinzhoubishiti。
- 用户指定交付期限：北京时间 2026-10-23 12:00 前。
- 当前实施授权：用户在 041–047 后要求“继续完成收尾，完成后给出完整验收流程，测试视频位置，真人核对通过后会给出真实api验证”。因此推进本地包、离线压力和交付材料，不提前调用真实 API，不伪称用户已人工确认或项目已发布。
- 最新验收调整：用户要求“最后一轮压力测试不进行，默认通过”。停止该复测，采纳已有通过基线，不新增实测成绩；记录见 `artifacts/reports/pressure-retest-waiver.json`，不再重复压力测试。
- 状态说明：020–039 历史见 [AGENT_REPORT.md](docs/AGENT_REPORT.md)，040 见 [FILESYSTEM_REPORT.md](docs/FILESYSTEM_REPORT.md)，041–047 见 [BOUNDARY_REPORT.md](docs/BOUNDARY_REPORT.md)；各分组包含重复用例，不累加计数。
- 文档中的“建议”是本 Spec 提出的工程决策，确认后纳入实现基线；数字阈值是建议验收标准，不是已经测得的性能。
- 相关记录：[会话总结与决策变更](docs/SESSION_SUMMARY.md)。
- 环境状态（2026-10-21）：复用已完成的[开发环境检查记录](docs/ENVIRONMENT_CHECK.md)；当前阶段实施授权另记于[会话记录](docs/SESSION_SUMMARY.md)。
- 执行任务：[第 11 节开发 tickets](#development-tickets)，包含拆分依据、依赖顺序、修改范围与逐票验收；不改变 F01–F25 的产品范围。

## 1. 产品目标与已确认边界

做一款面向实际使用者的 Windows 桌面视频转换工具，先让导入、查看信息、转换、排障这条路径清楚可用，再通过 Agent 提供有依据的解释和参数建议。Agent、RAG、MySQL 查询、MCP 管理属于首版必交能力。

### 1.1 需求结构

~~~text
桌面客户端
├─ 转换：导入 → 探测/缩略图 → 共享参数 → 兼容性确认 → 顺序转换 → 检查输出
├─ Agent：侧栏/独立窗口 → 明确引用 → 多轮问答 → 工具取证 → 建议 → 用户确认应用
├─ 知识：内置资料 → 解析切片 → 本地向量化 → 双路检索 → 融合 → 独立重排
├─ 工具：RAG / MySQL / 本地文件 / 网页搜索，经 MCP 暴露
├─ 可靠性：上下文隔离 / 幂等与去重 / 限量执行与排队 / 取消 / 错误 / 可追踪
└─ 交付：便携包 / 首次 AI 准备引导 / 真实测试 / GitHub / 决策与会话总结
~~~

### 1.2 固定产品选择

| 维度 | 基线 |
| --- | --- |
| 平台、框架 | Windows 桌面；Python、PySide6、Qt Widgets；浅色工具界面 |
| 主布局 | 左侧任务列表和选中项详情，右侧参数，底部总进度与操作 |
| AI 入口 | 默认侧栏，按钮展开为独立窗口；共用会话状态 |
| 转换策略 | 一批一套参数、逐个转换；MCP 并发不改变视频转换的顺序执行 |
| 输出 | MP4 默认，另有 MKV、WebM |
| 保存方式 | 统一输出目录，附选保留来源层级；或各源视频旁的“转换结果”目录 |
| 音轨、字幕 | 保留兼容的多音轨和内嵌字幕；丢弃前列明具体内容并由用户确认 |
| Agent 权限 | 查询、解释、提出参数方案；用户确认后应用到设置；不自主启动、取消转换任务 |
| 多轮、多会话 | 多会话并行，同一会话逐轮处理；历史可持久化；中断轮次供用户重试 |
| 引用 | 显式绑定视频、任务、文档；不随主列表选中项变化而偷偷切换 |
| 问答模型 | DeepSeek 官方 deepseek-v4-pro；评审可替换 API 接入配置 |
| 临时 API | 用户按需提供一小时使用窗口，由提供方设置服务端有效期或到期撤销 |
| RAG | 内置精选知识；本地 Qdrant 服务、Ollama、bge-m3；混合检索和独立 rerank |
| 联网搜索 | 当前视频信息、本机能力、MySQL、RAG 依据不足或冲突时自动搜索，回答附来源 |
| 并发验收目标 | 5 个真实问答会话；另测同时提交 100 个 MCP 工具请求 |
| 文档与提交 | 公开 GitHub 仓库、便携 ZIP、README、测试证据、会话总结与决策记录 |

沿用上一轮提出的默认值：首次使用统一目录，保留层级默认关闭；默认保持原分辨率和帧率；以后记住有效设置；输入样本覆盖 MP4/MOV/MKV/AVI/WebM；MySQL 默认连接本机独立项目库。这些默认值随本 Spec 一并确认。

### 1.3 完整用户路径

1. 解压便携包，启动客户端，选择或拖入视频；不要求先准备 AI 服务。
2. 查看缩略图、时长、分辨率及详细流信息，设置整批输出参数和目录。
3. 若有不兼容轨道，先看到将丢失的轨道清单，确认后才允许开始。
4. 转换中看进度、取消或查看错误；一个任务失败后继续其余任务。
5. 从任务进入 AI 侧栏，引用固定为该任务；可以加入选中的说明文档。
6. 首次使用完整 Agent 时，按引导准备本地服务、模型、知识索引和 API 配置。
7. Agent 显示正在使用的工具和来源；建议用“参数修改预览”呈现，确认后填入设置。
8. 用户主动开始下一次转换；能打开输出位置、保存预设、重新打开历史对话。

## 2. 功能拆分：做什么、影响哪里、怎样完成

下列功能全部属于首版。F 编号用于关联任务和验收证据，不能把“界面上有按钮”作为完成。

| 编号 | 要做什么 | 影响的模块/界面 | 完成判定 |
| --- | --- | --- | --- |
| F01 | 实现主窗口、空态、处理中/成功/失败状态，文字清楚，键盘可操作 | ui、任务模型、样式 | 主路径可用；100%/150%/200% 缩放无关键控件遮挡，Tab 焦点与禁用状态正确 |
| F02 | 多选文件、拖入文件、导入目录；可选扫描子目录；去除重复输入 | import、ui、MediaAsset | 中文、空格、重名、重复导入均正确；默认不扫描子目录；不递归进入目录链接造成循环 |
| F03 | 获取容器、时长、尺寸、大小、编码、帧率、码率、音轨/字幕信息 | media/probe、详情、StreamInfo | 与 ffprobe 实际结果一致；缺字段显示“未知”；坏文件有错误且不阻塞其它文件 |
| F04 | 异步提取并缓存缩略图，失败使用占位图 | media/thumbnail、任务列表、缓存 | 50 个文件导入时界面仍可操作；缓存键随源文件变化失效；超短视频也有回退取帧策略 |
| F05 | 输出 MP4/MKV/WebM，常用质量/分辨率及高级编码、码率、帧率、音频设置 | settings、planner、ui | 不合法组合在执行前提示；实际输出符合已选设置；默认不无故改变分辨率/帧率 |
| F06 | 显式保留兼容多音轨和内嵌字幕，保留可用语言与默认轨标志 | probe、compatibility、planner、确认框 | 兼容样本流数量正确；不兼容清单包含轨道与原因；未确认不执行，确认仅作用于对应计划 |
| F07 | 两种保存方式、附选来源层级、重名避让、保护源文件 | output、planner、设置、文件系统 | 不覆盖原件或既有输出；来源根同名能区分；单独添加文件有单独分组；无目录穿越 |
| F08 | 固定整批参数快照，按序执行 FFmpeg，更新单项/总体进度 | jobs、ffmpeg、ui、持久化 | 同时最多一个转换；FFmpeg 退出且输出验证通过才显示成功；未知时长显示不定进度 |
| F09 | 取消当前/整批、失败继续、失败重试 | jobs、进程管理、状态机 | 取消当前后后续仍可执行；取消整批不再启动下一项；失败重试生成新尝试且不重复跑同一尝试 |
| F10 | 保存/复用预设，记住有效设置，打开输出目录 | settings、store、ui | 重启后恢复；废弃编码器不会盲目复用；打开的是实际输出位置，失败可解释 |
| F11 | AI 首次准备与健康检查，支持已有服务或项目私有组件 | setup、services、config、ui | 每项状态可见；下载/连接失败可重试；准备完成以真实请求验证；失败不阻止基本转换 |
| F12 | 侧栏和独立窗口共享问答、引用、执行状态 | ui/agent、AgentService、store | 展开、收回、关闭独立窗口不产生重复模型请求；任务仍可在主窗口观察和取消 |
| F13 | 多轮、多会话、历史恢复、固定引用 | agent、store、引用选择器 | 五会话不串内容；同会话串行；重启可追问；中断显示中断，不声称自动恢复执行步骤 |
| F14 | DeepSeek 流式问答、配置替换、连接测试、调用量记录 | llm、config、ui | 真正完成一次含工具结果的多轮问答；无效/到期 Key、余额/网络错误有对应提示 |
| F15 | 结构化参数建议、差异预览、确认应用 | agent、settings、compatibility、ui | 用户确认前设置不变；确认后重新校验；不自动启动转换，不改变正在运行批次的快照 |
| F16 | 管理内置资料、来源、版本、许可及索引构建 | knowledge、rag/ingest、manifest | 能追溯片段原文；重复构建不重复入库；版本变更触发新索引；无密钥/私人文件混入 |
| F17 | Ollama/bge-m3 本地向量化、Qdrant 双路召回、融合、独立重排 | rag、Ollama、Qdrant、reranker | 日志能证明两路候选、融合、重排均执行；返回片段与来源；单路退化须标明且不算完整验收通过 |
| F18 | MySQL 查询兼容规则、常见错误、内置/用户预设及任务记录 | db、同步、MCP、Agent | 查询的是真实项目库；正常结构化问答能定位记录；数据滞后有标识；无任意写 SQL 能力 |
| F19 | 读取授权的 TXT/MD/LOG/PDF/DOCX 文字 | files、解析进程、MCP、引用 | 有页码/段落/偏移定位；越权、文件变化、加密、无文字、超限均明确返回，不静默省略 |
| F20 | 缺乏依据时网页搜索并保留可核验链接 | web、MCP、agent、引用展示 | 本地依据充分时无需搜索；不足时真实搜索；空结果/失败不伪造引用，不泄露日志或完整路径 |
| F21 | 工具经 MCP 暴露并由应用调度，职责单一 | mcp_client、mcp_server、tool registry | 实际完成工具发现与调用；正常产品路径不绕过 MCP 直接调用工具业务函数冒充集成 |
| F22 | 限量执行、排队、公平调度、超时、取消、重连和上下文隔离 | agent/runtime、MCP、各适配器 | 100 请求压力及故障场景有证据；队列有界；慢 RAG 不饿死数据库/文件读取；连接重建不丢聊天 |
| F23 | 幂等、同作用域在途合并、缓存与调用循环限制 | tool middleware、缓存、agent | 重复调用不会增加业务副作用；不同引用/版本不误复用；一个订阅者取消不取消其它订阅者 |
| F24 | 每个工具有可观测信息和统一异常层，用户可查看摘要/导出诊断 | logs、errors、ui、测试报告 | 能按 trace/turn/call 还原执行；错误有代码、可重试性和操作建议；诊断导出屏蔽凭据 |
| F25 | Windows 构建、干净环境验证、GitHub 与会话文档 | packaging、tests、docs、release | 无开发机 Python/FFmpeg PATH 仍能转换；完整 AI 引导能复现；结果、限制、链接和文件校验值齐全 |

## 3. 实现建议与核心模块

### 3.1 技术选择及证据边界

| 组件 | 建议 | 依据与限制 |
| --- | --- | --- |
| GUI | PySide6 / Qt Widgets，QSplitter、任务模型视图、QDockWidget、QProcess | Qt 控件承载真实桌面交互；侧栏浮动/停靠共享同一状态，不维护两套 Agent |
| 转换 | FFmpeg/ffprobe 外部进程，参数数组调用，使用机器可读进度 | ffprobe 获取元数据，FFmpeg 的 progress 输出供解析；不通过 shell 拼接命令。[官方说明](https://ffmpeg.org/ffmpeg.html) |
| 异步 | Qt 主线程负责 UI/进程信号；专用后台线程承载一个 asyncio 循环 | 网络/MCP/队列在后台；阻塞 SQL、解析、推理有独立限量工作单元，不堵事件循环 |
| MCP | 官方 Python SDK，建议锁定 mcp 2.3.0，采用桌面自管 stdio 工具子进程 | 已核实正式发布标签；目标协议 2026-07-28。接口实际兼容以最小集成测试和锁文件为准。[SDK 发布](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.3.0) |
| 模型 | 异步 HTTP 客户端适配 DeepSeek Responses API；模型 deepseek-v4-pro | 应用负责历史与函数调用桥接；其内置 mcp 类型不受支持，工具次数限制也须由应用执行。[兼容说明](https://api-docs.deepseek.com/zh-cn/guides/responses_api/) |
| 向量化 | Ollama /api/embed，模型 bge-m3 | 传入应用已经切好的片段；标准接口返回向量，不假定包含稀疏/ColBERT 输出。[接口](https://docs.ollama.com/api/embed)、[模型](https://ollama.com/library/bge-m3) |
| 双路召回 | Qdrant 1.19.2 服务：dense 向量＋原生 BM25 词法分支，RRF 融合 | 这是 Spec 的建议；不引入 rank_bm25 包，不用词法召回替代向量或重排。中文预处理和锁定版接口必须先验证。[原生 BM25](https://qdrant.tech/documentation/inference/inference-bm25/)、[融合](https://qdrant.tech/documentation/search/hybrid-queries/) |
| 独立重排 | 建议 BAAI/bge-reranker-v2-m3，由 sentence-transformers CrossEncoder 在独立工作进程执行 | 与 bge-m3 是两个模型；先用 CPU 和单并发，不承诺特定耗时。[模型作者说明](https://huggingface.co/BAAI/bge-reranker-v2-m3) |
| 持久化 | 标准库 SQLite 保存本地运行状态；MySQL 保存结构化查询读库 | 解决便携转换与 AI 数据库尚未准备的冲突；同步方案见 5.2，不把 SQLite 当成已交付的 MySQL |
| 数据库访问 | mysql-connector-python 的限量线程池＋连接池 | 每次借独立连接，finally 归还；不跨并发请求共享 cursor。[官方连接池说明](https://dev.mysql.com/doc/connectors/en/connector-python-connection-pooling.html) |
| 文档解析 | pypdf、python-docx；TXT/MD/LOG 标准文本读取 | 首版读取文字，不引入 OCR、宏执行或远程附件抓取 |
| 打包 | PyInstaller onedir；基础客户端与可选下载的 AI 工作组件分包 | 基础包携带 Python/Qt/FFmpeg/ffprobe；AI 依赖在首次引导中准备。[官方打包行为](https://pyinstaller.org/en/stable/operating-mode.html) |

版本与环境记录：2026-10-21 已单独完成 Python 3.13.9 隔离环境及依赖安装，实际版本、CPU Torch 来源、模型 revision/digest、哈希及探针结果见 [ENVIRONMENT_CHECK.md](docs/ENVIRONMENT_CHECK.md)。开发 tickets 复用该输入，生成受版本管理的应用依赖锁文件；不重新安装一套环境，不安装浮动 main 分支。环境探针通过不代表正式应用的导入、MCP、RAG 或便携交付已经完成。

### 3.2 进程和模块结构

~~~text
Qt 主窗口：任务/设置/AI 侧栏（可浮动）
   │
   ├─ ImportService / ProbeService / ThumbnailService
   ├─ ConversionPlanner → JobRunner → FFmpeg 外部进程（转换并发 1）
   ├─ LocalStore（SQLite）→ 待同步记录 → MySQL 项目库
   │
   └─ AgentService（专用 asyncio 循环）
        ├─ ConversationStore / immutable TurnContext
        ├─ DeepSeekAdapter（HTTP 流式输出）
        └─ ToolDispatcher → MCP Client → stdio → MediaConverterTools
             ├─ rag_search → Ollama + Qdrant + 独立重排工作进程
             ├─ 结构化查询 → MySQL 只读账号/模板
             ├─ read_local_file → 限量解析工作进程
             └─ search_web → DeepSeek Search API
~~~

一个产品内工具服务已足够，不按每个函数拆成独立部署的微服务。工具目录按职责分模块，允许独立测试。父进程只管理自己启动的子进程；不得通过进程名批量结束用户已有的 MySQL/Ollama/Qdrant。

不加入通用多 Agent 框架；用有界的“模型响应 → 工具调度 → 回传结果 → 继续回答”循环完成现有职责。

### 3.3 建议目录契约

以下为目录契约；基础相关目录已创建，其余模块随对应票实施：

~~~text
src/media_converter/
  __main__.py                 GUI 启动入口
  ui/                         窗口、任务视图、设置、Agent 停靠组件
  media/                      导入、ffprobe、缩略图、兼容规则、参数计划
  jobs/                       状态机、顺序队列、FFmpeg 进程和取消
  agent/                      会话、单轮上下文、模型适配、建议校验
  mcp_client.py               客户端连接拥有者
  mcp_server.py               工具服务入口与统一中间层
  tools/                      RAG、结构化查询、文件读取、网页搜索
  rag/                        切片、索引、双路召回、融合、独立重排
  storage/                    SQLite、本机 MySQL、同步与迁移
  services/                   首次准备、进程生命周期、健康检查
  devtools/                   测试数据、诊断、压力、评估、打包入口
knowledge/                    内置资料、来源清单、固定评估集
tests/{unit,gui,integration,live_api}/
packaging/                    Windows 客户端和工具组件构建说明
docs/                         会话总结、测试报告、使用与开发说明
artifacts/                    测试输出、诊断、压力报告；不提交大视频/密钥
~~~

### 3.4 视频处理流程

1. 导入时解析真实路径和来源根，识别重复输入；目录扫描排除链接循环和本应用输出目录。
2. 探测与缩略图分别排队，探测失败不阻断其它文件；缩略图不阻挡用户配置转换。
3. 开始批次前冻结设置快照，生成每个文件的 ConversionPlan：输入指纹、流映射、参数、最终路径和可能丢失项。
4. 验证本机实际 FFmpeg 能力与封装规则；静态兼容表只能辅助，不能承诺未编入的编码器可用。
5. 有丢失项时用户明确确认；确认绑定计划摘要，参数或源文件变化后必须重做计划。
6. 逐项执行，解析 progress，显示“已完成/失败/取消/总数”和当前项进度；估算百分比不冒充精确剩余时间。
7. 临时输出使用带 job_id 且保留真实扩展名的文件，放在最终目录同卷，例如 name.job_id.partial.mp4。
8. 进程结束后执行 ffprobe 与基础输出验证，通过后以禁止覆盖的方式改为最终名称；遇到重名重新分配后缀，不使用会覆盖既有文件的替换操作。
9. SQLite 记录终态，再异步同步到 MySQL；同步失败不会抹掉转换结果。

流映射建议：首版转换一个主视频流，显式映射全部拟保留音轨/内嵌字幕，避免 FFmpeg 默认只选一条。多主视频流样本明确标为暂不支持。音频“自动”可转为目标允许的编码并保留轨数；不兼容字幕按已确认的丢弃确认流程处理，不偷偷烧录、转纯文本或丢失样式。

建议默认编码组合：MP4 为 libx264＋AAC，MKV 为 libx264＋AAC，WebM 为 libvpx-vp9＋libopus；字幕仅按已验证兼容表保留。兼容且不需改参数的音轨可复制，需重编码时仍保留全部拟保留音轨。质量起点建议 H.264 CRF 23、VP9 CRF 32；质量模式与固定码率模式互斥，不将不同编码器的质量数值视为同一量纲。以上均需随包能力探测和小样本转换验证，缺指定编码器属于构建缺陷，不能悄悄换编码器或删去目标格式。

手机旋转视频的可视方向和原始像素尺寸分别保存；缩略图与输出只应用一次旋转。默认保留帧率时不强制把变帧率转成固定帧率；用户设置目标尺寸时保持宽高比，并满足目标编码器尺寸约束，不拉伸画面。

输出层级按导入根分组保留相对路径，根同名加稳定后缀；单独添加的文件放“单独添加”组。统一目录且关闭层级时仅使用文件名并避让重名。旁置模式写各源目录的“转换结果”，不再套用统一目录的层级选项。

取消当前项先请求 FFmpeg 正常停止，超时后终止本应用拥有的进程；取消标志优先于退出码，不能因为退出码为 0 把取消判作成功。只清理确定属于该尝试的临时文件。取消整批同时标记未开始项，不启动下一项。

正在运行的批次始终使用原快照。UI 或 Agent 修改设置用于下一批；重试默认重用失败项的快照，源文件变化时重新探测和确认。

### 3.5 RAG 构建与检索流程

建议完整流程如下；BM25 仅作为双路中的词法分支，不等于采用被撤回的 rank_bm25 替代方案。

~~~text
构建：
内置资料清单 → 许可/来源校验 → 正文解析 → 按章节切片与定位
  → Ollama/bge-m3 dense 向量
  → 同步构建 Qdrant 原生 BM25 词法表示
  → 校验数量/维度/版本 → 切换知识库活动版本

查询：
问题＋明确引用的必要上下文
  → 查询改写（需要时，用明确名词补全“刚才/这个”，不改原始问题）
  → dense 召回 ＋ 词法召回
  → RRF 融合去重 → 独立 CrossEncoder 重排
  → 返回片段、分数来源、原文定位、knowledge_version
  → Agent 组织回答并引用
~~~

建议起始参数：按标题/段落切片，目标 500～800 个模型 token、重叠 80 个 token；每路召回 20 条，融合后最多 20 条进入重排，返回前 5 条。以实际 tokenizer 计数，超过模型限制先切分，Ollama 请求关闭静默截断。以上为可调建议，须用固定评估集验证，不宣称是最佳值。

中文与 FFmpeg 参数混合文本必须在文档和查询上使用一致的预处理；保护 libx264、AV1、mov_text、-map 等标识符。建议中文预分词后供词法分支使用，先验证 Qdrant 锁定版本的分词/配置行为，不能仅根据英文示例假定中文效果。

Qdrant payload 至少保存 chunk_id、document_id、text、source_url/source_path、section/page、content_hash、knowledge_version。dense 向量维度以模型实际输出校验并写入 manifest；模型/digest、切片版本不一致时拒绝混用索引。新版本索引完成后再切换活动引用，不边删旧库边提供服务。

内置资料包括软件说明、格式/编码概念、FFmpeg 官方说明和整理后的常见错误。发布包记录来源 URL、抓取日期、原文许可及处理方式；不整站复制未知授权内容。用户选中文档用于当前会话参考，不自动导入知识库。

评估或调试模式可以分别运行 dense、词法、混合、混合＋重排用于对照，但正常完整模式必须执行已选双路与重排。依赖失效时可显示受限状态和剩余证据；不得无提示地降成单路并声称完整 RAG 已通过。

### 3.6 Agent 一轮问答与历史

1. 用户发送消息后，生成 turn_id 并保存用户消息、引用快照和当前设置版本；同一会话上一轮未终结时，新消息排队。
2. 构建不可变 TurnContext；从本地恢复该会话历史及可引用的工具结果，不依赖模型服务替应用保存聊天。
3. 向模型提供工具业务 schema、当前视频/任务快照及允许引用资料；文件内容按需读取，不把全部本地文件预塞进上下文。
4. 模型函数调用由应用校验后转发至 MCP。模型生成的参数不能覆盖可信的 conversation_id、权限范围或 trace_id。
5. 同一轮中相互独立的工具可以并行；依赖前一个结果的调用依次进行。按 call_id 配对回传，不能按完成顺序随意拼接。
6. 证据不足、冲突或需核实最新支持时开放网页搜索。搜索仍失败则说“目前无法确认”，明确已查范围。
7. 回答展示来源、必要限制和可操作建议；工具执行摘要可展开，诊断详情可导出；不把模型推理文本当作已核实事实。
8. 参数建议必须形成 ConversionSettingsPatch，列出旧值、新值、原因及影响批次；用户确认后经过同一兼容性校验器应用。
9. 终态落库；取消或中断保留已得到的消息与工具摘要，下一次由用户重试，创建新的 turn_id。

建议每轮最多 8 次模型往返、16 次工具调用、4 个并行工具分支，整轮总期限 300 秒；达到限制给出已完成部分与下一步建议。需回传的推理/函数配对字段按 DeepSeek 锁定接口要求保存，不能简单删除所有 reasoning 字段导致工具链无效。

上下文建议预算 32k token、单次可见输出连同模型推理合计上限 8k token。优先保留系统约束、当前引用、最近消息及完整工具调用/结果配对；较早历史压缩成有来源定位的摘要，完整原记录仍保存在本机。压缩不能把失败工具改写成成功，不能拆散调用与结果。只声明已测试过的多轮长度，不承诺无限聊天。

### 3.7 首次准备、配置与降级

- 基础客户端独立携带 Qt/Python/FFmpeg/ffprobe；首次启动能导入和转换，AI 组件缺失只影响对应 AI 能力。
- 向导先检查已有服务与模型，再由用户选择复用或准备项目私有组件；显示空间需求、下载来源、版本、进度、重试与日志。
- 优先验证 Windows 原生 Qdrant 发布包、Ollama 独立 ZIP，避免把 Docker/WSL 设置为用户必须安装的前提。官方存在这些分发方式，不代表本项目已经验证成功。[Qdrant Windows 构建](https://github.com/qdrant/qdrant/blob/master/.github/workflows/release-artifacts.yml)、[Ollama Windows](https://docs.ollama.com/windows)
- AI 工具工作组件及 CPU 重排运行库可独立打包下载，不能要求评审安装开发机的 Python、pip 或编译工具。
- MySQL 默认使用项目独立库；优先复用已运行服务，也可由引导准备私有实例。初始化不能重置现有数据库、修改 root 账号或占用端口后强停已有服务。
- 下载先落 .partial 文件，校验发布清单中的真实哈希后原子落盘；重复准备检查版本和完成标识。解压验证路径，拒绝越出目标目录的条目。
- 开发与验收产生的运行数据、模型缓存、第三方缓存和日志统一指定到 D:/CodexWorkspace/bossjinzhoubishiti 下，不能任由默认缓存写入 C:/Users/33072。分发后的程序允许使用者选定可写数据目录。
- 密钥仅通过本机设置配置并加密保存，建议使用 Windows DPAPI；配置文件保存凭据引用，命令行、公开仓库、测试报告不含实际 Key。复制便携包到另一台电脑时重新配置凭据。
- “一小时”是提供方给评审的临时接入窗口，不构建发卡、计费或长期托管平台。是否支持提供方原生自动过期尚未核实，不把客户端倒计时当作 API Key 已真实失效。
- 关闭 UI 侧栏/浮动窗口不取消问答；显式“停止回答”才取消。退出整个应用时取消未完成轮次、保存状态并清理自己拥有的进程；共享外部服务保持原状。

## 4. 数据结构与状态机

### 4.1 核心对象

字段类型建议使用明确的数据类/Pydantic 模型；数值单位写在字段名中，缺失信息用 null，不用 0 冒充未知。

| 对象 | 必要字段 |
| --- | --- |
| ImportRoot | root_id、resolved_path、display_group、recursive、kind(directory/single) |
| MediaAsset | asset_id、root_id、relative_path、resolved_path、fingerprint(size_bytes/mtime_ns/file_identity)、container、duration_us、width、height、rotation_deg、bitrate_bps、frame_rate(numerator/denominator)、average_frame_rate、color_info、streams、probe_status、probe_error_code |
| StreamInfo | stream_index、kind、codec、language、disposition、channels/sample_rate_hz、subtitle_type、attached_picture |
| ConversionSettings | settings_version、container、video_encoder、quality_mode/quality_value、video_bitrate_bps、resolution、frame_rate、audio_encoder/audio_bitrate_bps、output_mode、output_dir、preserve_hierarchy |
| ConversionPlan | plan_id、plan_hash、attempt_id、source_asset、output_root、source_fingerprint、settings_snapshot、stream_mapping、loss_items、consent_plan_hash、ffmpeg_args、temporary_path、final_path |
| JobAttempt | job_id、attempt_id、batch_id、asset_id、plan_id、state、progress_us、started_at、finished_at、exit_code、error_code、output_path |
| Conversation | conversation_id、title、created_at、updated_at、reference_set、settings_version |
| Message | message_id、conversation_id、turn_id、role、sequence、content、source_refs、provider_items、status |
| TurnContext | conversation_id、turn_id、trace_id、reference_snapshot、data_scope、settings_version、deadline、cancellation_handle |
| ToolInvocation | invocation_id、provider_call_id、tool_name、argument_hash、scope_hash、state、queue_ms、execution_ms、retry_count、cache_state、error_code、result_ref |
| KnowledgeChunk | chunk_id、document_id、knowledge_version、text、source_ref、location、content_hash |
| SettingsProposal | proposal_id、turn_id、base_settings_version、patch、reasons/source_refs、validation_result、applied_at |

约束：UI 两种视图绑定同一 Conversation/TurnContext；工具不能使用进程级可变的 current_conversation。源文件指纹用于识别变化，不宣称 size/mtime 等于密码学内容哈希。

### 4.2 状态机

~~~text
转换尝试：
QUEUED → PREPARING → NEEDS_CONFIRMATION → READY → RUNNING → VERIFYING → SUCCEEDED
                   └─ 无丢失项可直接 READY
任意执行前状态 → FAILED 或 CANCELLED
RUNNING/VERIFYING → CANCELLING → CANCELLED
应用异常退出后的活动尝试 → INTERRUPTED
FAILED/CANCELLED/INTERRUPTED → 用户重试 → 新 attempt_id

问答轮次：
QUEUED → GENERATING ↔ TOOL_WAITING/TOOL_RUNNING → COMPLETED
活动状态 → CANCELLING → CANCELLED
活动状态 → FAILED / INTERRUPTED / LIMIT_REACHED
~~~

重试保留原记录，不覆盖失败证据。完成/失败/取消状态的写入需防重复，且取消后到达的旧回调不能把状态改回成功。应用重启只恢复历史和可重试入口，不自动重跑转换或恢复 Agent 中断步骤。

## 5. 接口与数据边界

### 5.1 应用内部接口契约

下列是实现时应满足的逻辑接口，不要求建立额外网络 API：

~~~text
ImportService.import_paths(paths, recursive=False) -> ImportResult
await ProbeService.probe(asset) -> MediaAsset
ConversionPlanner.plan(batch_settings, assets, roots) -> tuple[ConversionPlan, ...]
await JobService.start_batch(plans, batch_command_id) -> batch_id
await JobService.cancel_current(batch_id) / cancel_batch(batch_id)
await JobService.prepare_retry(attempt_id) -> new_plan
await JobService.retry(attempt_id, confirmed_plan) -> retry_batch_id
AgentService.submit(conversation_id, message, reference_ids) -> turn_id
AgentService.cancel(turn_id)
SettingsService.validate_patch(proposal, current_version) -> ValidationResult
SettingsService.apply_confirmed_patch(proposal_id, expected_version)
SetupService.inspect() / prepare(selected_components) -> status events
~~~

所有有副作用的应用操作由 UI 服务调用；MCP 读取工具不获得 start_batch、文件写入、shell 或设置写入入口。双击“开始”、重复点击“应用建议”分别以 batch_command_id、proposal_id 防重复提交。

### 5.2 本地持久化与 MySQL 查询库

建议保留两个职责明确的数据存储：

1. SQLite 是无需外部服务的本地运行记录，保存设置、预设、转换尝试、会话、消息、引用和待同步事件；标准库即可访问。
2. MySQL 是用户要求的结构化查询库，真实保存技术规则、错误分类、预设和转换记录，供 MCP 查询。它不是空壳，也不作为基本转换启动的前置条件。

最小同步方式：写本地业务记录和 outbox 事件使用同一个 SQLite 事务；后台按 event_id 顺序写 MySQL，目标使用主键/版本 upsert，并将目标业务记录和 sync_events 在同一个 MySQL 事务中提交；收到提交成功后才在本地标记已同步。不要为此引入消息中间件。重复重放同一 event_id 不增加记录，老版本事件不能覆盖新版本。

| 存储 | 表/索引建议 | 说明 |
| --- | --- | --- |
| SQLite | settings、presets、assets、job_attempts | attempt_id 唯一；任务终态和输入/输出信息持久化 |
| SQLite | conversations、messages、references、tool_invocations | message(conversation_id, sequence) 唯一；对话历史顺序可复现 |
| SQLite | outbox_events(event_id, entity_id, version, payload, synced_at) | 与业务写入同事务；保留失败与重试信息 |
| MySQL | technical_rules(rule_id, rule_kind, version, source_ref, rule_json) | 规则来自可追溯资料，与 FFmpeg 实测能力区分 |
| MySQL | presets(preset_id, version, owner_scope, settings_json) | 内置与用户预设区分；唯一键防重复同步 |
| MySQL | conversion_attempts(attempt_id, asset_id, status, settings_json, timing, error, version) | 查询“刚才失败/上次参数”；时间/状态建立索引 |
| MySQL | sync_events(event_id)、sync_state(instance_id, watermark) | 同步水位与幂等确认，不把过时结果说成最新 |

MySQL 工具账号只允许 SELECT 指定项目表；初始化/同步使用单独账号。查询模板参数化、限制行数和时间，不允许模型生成任意 SQL，也不暴露 DDL、UPDATE、DELETE、文件读取或跨库入口。

查询结果携带 freshness：同步水位、待同步事件数、数据时间。刚完成任务尚未同步时，回答显示记录滞后，并可使用当前明确引用的本地任务快照说明现状；不能将“查不到”解释成任务不存在。服务恢复后补同步。

SQLite 开启适合并发读取的模式，由本地写入队列串行提交；MCP 服务读取已提交的引用授权快照。避免多个线程共享一个未加协调的数据库连接。

### 5.3 MCP 工具契约

业务输入 schema 与可信执行上下文分开。下表参数允许模型提供；conversation_id、turn_id、scope、trace_id、deadline 由 Host 放入应用命名空间的调用元数据，服务端校验。MCP 自身协议字段由 SDK 管理，不能手写伪协议。

| 工具 | 业务输入 | 返回 | 边界 |
| --- | --- | --- | --- |
| rag_search | query、top_k（建议 1～5） | chunks、source_refs、knowledge_version、retrieval_stages | 只检索已激活内置库；不在工具内生成最终答案或执行转换 |
| lookup_technical_rules | rule_kind、format/codec/error_code 等已定义过滤项 | rules、source_refs、version | 预定义参数化查询；返回数据，不混入模型编造规则 |
| list_conversion_presets | preset_name、container、limit | presets、freshness | 只返回作用域内内置/用户预设 |
| query_conversion_history | task_id 或时间/状态过滤、limit | attempts、freshness | 默认最多 20 行，上限建议 100；跨实例/未授权范围拒绝 |
| read_local_file | file_ref_id、页/段范围或字符偏移、max_chars | text、location、fingerprint、truncated、next_cursor | 只读明确授权引用；不接受任意磁盘路径，不执行文件 |
| search_web | query、count（建议 1～5） | title、url、snippet/content、retrieved_at | 只做搜索，应用验证查询长度；优先官方/一手资料；不输出最终诊断 |

网页工具建议封装 DeepSeek 独立 Search API，并经 MCP 执行，不让模型内置搜索绕开统一日志和限额。官方提供独立 Search/Fetch 接口；首版先暴露 Search，正文缺失时说明证据不足，不偷偷扩展成浏览器抓取器。[接口说明](https://api-docs.deepseek.com/zh-cn/guides/search/)

文件读取先核对实际文件身份与授权引用，再解析。建议限制为单文件 20 MiB、PDF 每次最多 20 页、工具返回文字最多 20,000 字符；超出返回可继续定位的游标。DOCX 解压体积也有限制，防止压缩炸弹。非 UTF-8 文本先尝试明确的编码检测，失败说明原因，不以乱码当成功。无文字 PDF、加密文件、损坏文档和文件被替换都返回明确错误。

来源文档、网页、日志均作为不可信资料；其中“忽略指令/执行命令/读取其它文件”的文字不能提升工具权限。网页查询仅发送通用格式、编码、错误特征，过滤已知私有路径和凭据；不直接转发整份日志。

### 5.4 通用结果和异常层

应用层结构示意如下，不是已发生的调用数据：

~~~json
{
  "ok": false,
  "data": null,
  "sources": [],
  "error": {
    "code": "DEPENDENCY_UNAVAILABLE",
    "message": "知识检索服务未就绪",
    "retryable": true,
    "suggested_action": "在设置中检查本地知识服务"
  },
  "meta": {
    "trace_id": "<host-generated>",
    "invocation_id": "<host-generated>",
    "data_version": "<actual-version>"
  }
}
~~~

工具执行/业务错误按 MCP tool result 的错误机制返回；协议、消息格式、连接错误按 SDK/JSON-RPC 处理，不能全部包装成“空结果”。取消信号须传递给 SDK，不应被通用异常捕获后错误地回发正常结果；应用自身可保存 CANCELLED 终态。

| 错误代码 | 行为 |
| --- | --- |
| INVALID_ARGUMENT / ACCESS_DENIED | 指出参数/作用域问题，不原样自动重试 |
| FILE_CHANGED / FILE_TOO_LARGE / NO_EXTRACTABLE_TEXT | 说明重新选择、缩小范围或提供文字版；不伪装已读全文 |
| DEPENDENCY_UNAVAILABLE / TIMEOUT / RATE_LIMITED | 限次重试或明确重试入口；显示是哪个依赖失败 |
| AUTH_FAILED / QUOTA_EXHAUSTED | 停止该配置的新在线请求，指向配置/提供方；不无限重试 |
| INCOMPATIBLE_STREAM / CONSENT_REQUIRED | 在转换规划阶段阻止执行并显示影响 |
| QUEUE_FULL / TURN_LIMIT_REACHED | 立即可见地返回排队容量/调用预算问题 |
| MCP_DISCONNECTED / PROTOCOL_MISMATCH | 记录 SDK、协议与子进程状态，重建连接或明确结束该轮 |

日志至少记录事件时间、应用实例、conversation_id、turn_id、trace_id、invocation_id、工具名、参数摘要哈希、引用/版本、排队/执行耗时、缓存/合并命中、重试次数和错误码。stdout 专用于 stdio MCP 协议，工具服务诊断写 stderr 或独立 JSONL。原始密钥、数据库口令和完整私有文件正文不写日志。

## 6. 并发、连接、幂等与恢复

### 6.1 建议初始执行限制

以下是等待本 Spec 确认的起始配置，实施后按实测调优并记录理由：

| 资源 | 初始限制 | 等待与终止 |
| --- | --- | --- |
| 视频转换 | 1 | 一个文件失败后继续；取消当前项可继续后项，取消整批不启动下一项 |
| ffprobe/缩略图 | 各 2 | 有界队列，缩略图超时返回占位 |
| 在线问答 | 5；每会话 1 轮 | 同会话有序排队，整轮期限建议 300 秒 |
| 工具总执行 | 16；待执行队列 128 | 能容纳 100 请求测试；超量明确 QUEUE_FULL |
| 单轮工具分支 | 4 | 模型一次返回更多调用时由 Host 排队，不全量放行 |
| 本地 embedding / rerank | 各 1 | 独立限量，避免大模型重复载入挤占内存 |
| MySQL 查询 | 4 连接/工作线程 | 限时借还连接，不共享 cursor |
| 文档解析 | 2 工作进程 | 大文件/坏文件可隔离终止 |
| 网页搜索 | 2 | 外部限速后有限退避 |

工具排队最长建议 120 秒；RAG 执行最长 120 秒，SQL 10 秒，文件解析 30 秒，搜索 20 秒。整轮期限优先于单工具期限；启动冷模型的准备耗时单独显示。对不能立即抢占的推理，取消先停止当前轮等待及后续调用；迟到结果被丢弃，不能声称服务端计算和计费已经撤销。

调度须按工具分组公平取出，未获得工具专属名额的请求不长期占用全部全局名额。并发目标衡量的是“同时提交后被正确排队/执行/取消”，不是每秒完成 100 次重排。

### 6.2 连接与上下文生命周期

当前官方 MCP 最新规范为 2026-07-28：请求自包含，不应将聊天持久化寄托在协议会话上；官方 SDK v2 支持新旧协议路径。[规范](https://modelcontextprotocol.io/specification/2026-07-28)、[SDK 协议选择](https://py.sdk.modelcontextprotocol.io/protocol-versions/)

建议客户端与自带工具服务锁定相同 SDK，验收明确记录使用 2026-07-28 的 stdio 路径。连接由应用生命周期内的一个后台任务拥有，复用至正常退出或进程故障；不为每个问题重建服务器、不跨事件循环复用异步连接对象。

“持续连接”“执行上下文”“多次调用找不到会话”是需要验证的故障类别，不是已经诊断出的现有缺陷：

- 聊天消息、执行轮次、JSON-RPC request_id、模型 provider_call_id 使用不同标识。
- 每次调用带完整可信业务作用域，连接重建不改变 conversation_id。
- MCP 子进程退出时，先把在途请求置为明确未知/中断，重启时只有一个重连拥有者，避免五会话启动五个重连风暴。
- 只读调用允许在剩余期限内重试一次；新协议下不编造 Mcp-Session-Id，也不把旧版 HTTP 404 恢复逻辑硬套到 stdio。
- 暂不实现旧版 HTTP 远程服务兼容；未来若增加，单独测试初始化、会话过期与状态恢复。
- 新协议取消可能没有服务端结果回复，客户端要结束自己的等待，不能为了等取消“返回值”而永久悬挂。

### 6.3 幂等不等于不调用

- 工具均为业务只读；相同调用不增加转换任务、修改文件或改数据库。日志追加不算业务重复写入。
- 同作用域、同工具、规范化参数及数据版本一致时，可合并在途请求。不能仅以 query 字符串全局共享结果。
- 一个消费者取消只移除其订阅；其它消费者仍需结果时不取消底层共享调用。
- 成功缓存受容量、有效期和数据版本约束；历史查询随同步水位失效，文件读取随文件身份/修改失效。
- 错误不作为成功缓存；瞬时失败不长时间负缓存；重连后不承诺网络级 exactly-once。
- 建议最多重试一次，带退避且受总期限约束；认证、余额、权限和确定性参数错误不重试。
- 已经流出部分回答或发生费用的模型请求，不因重连无条件重放。重试可能重复计费，须记录尝试次数和实际 usage。
- 同一轮相同输入无新证据地反复调同一工具时，返回已知结果并计入循环预算；达到上限结束该轮而不是无限循环。

## 7. 风险、首版不做与后续考虑

### 7.1 风险登记

| 编号 | 容易出问题的地方 | 应对与验证 | 对交付的影响 |
| --- | --- | --- | --- |
| R01 | Qt/Python/原生库、CPU torch 或 PyInstaller 组合不兼容 | M0 先做最小 GUI、子进程、MCP、CPU 重排和打包验证；锁版本与哈希 | 未验证不得把“存在 wheel”写成可运行 |
| R02 | FFmpeg 退出成功但流少了、文件未写完或进度假满 | 显式映射、丢失确认、输出探测与解码；验证后才成功 | 数据丢失、防覆盖、无确认丢轨为阻塞 |
| R03 | 中文/特殊路径、长路径、重名、只读目录、磁盘不足 | 参数数组、真实路径、临时文件、禁止覆盖；异常注入 | 不支持的路径明确失败，不修改原件 |
| R04 | UI 被探测、模型或解析堵住 | 阻塞工作离开 UI/asyncio 循环；限并发与响应性测量 | 主路径卡死为阻塞 |
| R05 | 局部取消波及其它会话，共享请求被提前取消 | 订阅计数与请求级取消；取消与迟到结果竞态测试 | 串会话、误取消、状态回退为阻塞 |
| R06 | 误用旧版 MCP 生命周期，断连后请求悬挂 | 锁 SDK/协议，单连接拥有者，进程故障与取消测试 | 不以新建会话掩盖历史丢失 |
| R07 | 双路检索“有调用但无效果”、中文词法无效 | 固定标注集、中文/编码标识案例、检索阶段日志与消融对照 | 不把单路或随机片段冒充完整 RAG |
| R08 | 同时载入 embedding 与 reranker 挤占资源 | 初始各 1 并发，CPU 重排独立进程，记录冷/热耗时与内存 | 不预先保证 100 个模型推理同时运行 |
| R09 | MySQL 不可用、重放重复写、查询滞后 | 本地事务与 outbox、目标唯一键/版本、同步水位提示 | 不阻止转换；MySQL 真查询仍须验收 |
| R10 | 引用文件被替换、越权读取、文档提示注入 | 引用授权、打开文件身份核验、解析限额、资料不提升权限 | 越权/密钥泄露为阻塞 |
| R11 | API 到期、限流、余额不足或网络断开 | 错误分类、有限重试、保留历史、显示配置入口 | 无真实模型验证不得宣称 Agent 已验收 |
| R12 | AI 首次下载失败、包体过大、服务端口冲突 | 分包、来源/哈希校验、复用已安装组件、可见状态与重试 | 无完整首次准备演练不得声明“一键可用” |
| R13 | 将本机测试误写为全 Windows 兼容 | 记录系统/硬件/驱动/构建版本；干净机器另测 | 未测平台只列目标，不列已支持事实 |
| R14 | FFmpeg、Qt、MySQL、模型及模板分发许可不同 | 按真实构建整理 LICENSE/NOTICE、来源与适用义务，不复制不明模板 | 未完成分发清单不发布依赖包 |
| R15 | 扩展需求使截止时间承诺失真 | 先验证高风险，再按完整链路推进；遇阻报告具体未完成项 | 不擅自删 Agent、rerank、测试来宣称完成 |
| R16 | 日志/公开仓库包含 Key、私有路径、视频大文件 | 诊断脱敏、提交前人工与自动检查、测试哨兵 | 泄露为阻塞；录屏也检查设置页与日志 |

FFmpeg 的许可取决于实际启用的组件，不能把任何下载包一概称为 LGPL 或 MIT；文档只要求核对与履行实际分发义务，不替具体分发作法律结论。[FFmpeg 官方说明](https://www.ffmpeg.org/legal.html)

### 7.2 首版明确不做

- macOS、Linux、移动端或浏览器版产品。
- 账号体系、多人共享业务平台、长期在线演示服务、发卡/计费后台。
- Agent 自主执行转换、任意 shell、任意 SQL、修改或删除用户文件。
- 中断 Agent 的执行检查点恢复；重启自动恢复转换队列执行。
- 用户资料自动入库、目录监控、私人文档批量索引。
- 扫描 PDF OCR、图片理解、旧 DOC/DOCM、文档宏、复杂版面完整还原。
- 外挂字幕导入、字幕烧录、ASS 样式转换、多主视频轨选择与编辑。
- 剪辑、拼接、滤镜编辑、下载在线视频、DRM 绕过。
- 未经实测的任意编码器/任意格式保证；HDR/Dolby Vision 自动色彩映射等复杂色彩处理。
- 并行 FFmpeg 转换、强依赖显卡加速、自动更新、商店上架和代码签名。
- 将 rank_bm25 或纯词法搜索作为完整混合＋独立重排的替代交付。
- 默认复制 GPL/商业控件模板代码；GitHub 界面参考用于布局和控件研究，具体依赖另核许可。

### 7.3 后续可考虑

在本版完成后，再根据证据考虑硬件编码、快速转封装、自动更新、用户知识导入、更多文档格式、远程 MCP/多设备、模型与检索调优、可选 GPU 重排。

本版优先优化：缩略图缓存、探测去重、批次预检、参数预设、来源定位、受控工具并行和可解释错误。这些优化直接改善已确认路径，不增加新的业务平台。

## 8. 测试与验收

### 8.1 测试层次与结果规则

- unit：参数规划、路径、状态机、去重、数据同步、权限与预算等纯逻辑。
- gui：使用 pytest-qt 验证真实 Qt 控件和交互；图片/录屏用于补充实际观感。
- integration：真实 FFmpeg、stdio MCP、Ollama、Qdrant、reranker、MySQL 与文档解析。
- live_api：真实 DeepSeek/搜索；须显式启用，仅在可用凭据的窗口内运行。
- stress：协议/排队压力与实际后端压力分开；mock 测试必须标注，不能算真实依赖性能。

缺依赖可以令日常开发测试 skip，但发布验收所要求的 integration/live_api/stress 不能通过 skip 获得“全部通过”。报告分别列 passed/failed/skipped/blocked、真实依赖版本和未覆盖内容。

### 8.2 计划交付的运行命令

**当前状态：GUI 转换闭环、pytest 参数、media/conversion 集成测试、devtools --help、prepare core 和 fixtures smoke 已实现并验证。** 其余命令待对应 tickets 实现，当前请求会明确非零退出，不冒充成功。已有 `environment/smoke` 命令只用于环境检查；基础结果另见 FOUNDATION_REPORT。

所有示例从项目根目录运行；路径和输出都落在 D 盘项目目录。命令中的 prepare、doctor、fixtures、bench-*、eval-rag、build-windows、smoke-package 是统一 devtools 入口的计划子命令；--data-dir/--fixture-root/--live-api 等项目参数须实际实现并在 --help 中说明。

#### A. 安装已锁定开发依赖并启动

~~~powershell
Set-Location 'D:\CodexWorkspace\bossjinzhoubishiti'
. .\environment\activate.ps1
$taskPython = Join-Path (Get-Location) 'environment\venv\Scripts\python.exe'
& $taskPython -m pip install -r requirements-dev.lock
& $taskPython -m pip install --no-deps -e .
& $taskPython -m pip check
& $taskPython -m media_converter
~~~

requirements-dev.lock 必须固定完整开发依赖及实际 CPU 推理 wheel 来源，包含 pytest、pytest-qt、异步测试支持、ruff、打包依赖；不能仅固定顶层包或隐含安装 CUDA 大包。普通使用者不运行这些开发命令。

#### B. 静态检查、单元与 GUI 自动测试

~~~powershell
& $taskPython -m ruff check src tests
& $taskPython -m ruff format --check src tests
& $taskPython -m pytest tests/unit tests/gui -q --strict-markers --strict-config --junitxml artifacts/reports/unit-gui.xml
~~~

GUI 自动测试不能代替 Windows 实际缩放、播放和首次准备检查。

#### C. 准备基础组件、生成可重现小样本、测试转换

~~~powershell
& $taskPython -m media_converter.devtools prepare --components core --data-dir data
& $taskPython -m media_converter.devtools fixtures --profile smoke --root artifacts/fixtures --data-dir data
& $taskPython -m pytest tests/integration/test_media.py tests/integration/test_conversion.py -q --strict-markers --data-dir data --fixture-root artifacts/fixtures --junitxml artifacts/reports/media.xml
~~~

样本生成器记录 FFmpeg 命令、时长、尺寸、编码与文件哈希；包含 MP4/MOV/MKV/AVI/WebM、无音频、双音轨、可兼容/不兼容字幕、旋转信息、变帧率、坏文件和中文/空格路径。样本许可明确，优先使用自生成测试画面和声音，不把工作视频上传 GitHub。

#### D. 本地 AI 组件与真实工具集成

先在向导配置本地项目服务和独立测试库，必要时准备模型；不能把现有个人数据库作为测试清理目标。

~~~powershell
& $taskPython -m media_converter.devtools prepare --components ai --data-dir data
& $taskPython -m media_converter.devtools doctor --require all-local --data-dir data --output artifacts/reports/doctor-local.json
& $taskPython -m pytest tests/integration/test_mcp.py tests/integration/test_rag.py tests/integration/test_mysql.py tests/integration/test_files.py -q --strict-markers --data-dir data --fixture-root artifacts/fixtures --junitxml artifacts/reports/local-ai.xml
~~~

doctor 的 all-local 检查 FFmpeg/ffprobe、MCP 协议与发现、Ollama 模型向量、Qdrant 两路查询、独立重排、MySQL 权限/真实查询和文件读取。它不因“端口能连”就判定准备成功。

#### E. MCP 100 请求与故障测试

~~~powershell
& $taskPython -m media_converter.devtools bench-mcp --profile real-local --requests 100 --client-concurrency 100 --rounds 3 --data-dir data --output artifacts/reports/mcp-real-local.json
& $taskPython -m media_converter.devtools bench-mcp --profile faults --requests 100 --client-concurrency 100 --data-dir data --output artifacts/reports/mcp-faults.json
~~~

real-local：预热后，在同一 stdio 连接上用提交屏障发出 100 请求；建议每轮 40 次 RAG、30 次 MySQL、30 次文件读取，含约 20% 同作用域重复输入。使用真实短资料、真实服务，单独报告去重后实际后端执行数；网页接口另做小规模真实验证，不用 mock 冒充外部搜索性能。

faults：覆盖队列超量、依赖延迟/超时、取消、重复请求、一个消费者取消、工具进程崩溃重启和错误参数。注明注入故障与模拟外部响应，不能将该报告称为真实模型服务压力结果。

#### F. 固定 RAG 评估与真实多会话

~~~powershell
& $taskPython -m media_converter.devtools eval-rag --dataset knowledge/eval.jsonl --data-dir data --output artifacts/reports/rag-eval.json
& $taskPython -m pytest tests/live_api -q --strict-markers --live-api --data-dir data --junitxml artifacts/reports/live-api.xml
& $taskPython -m media_converter.devtools bench-agent --sessions 5 --turns-per-session 3 --live-api --data-dir data --output artifacts/reports/agent-5-sessions.json
~~~

先通过 GUI 配置评审自有 API 或用户按需提供的临时接入；命令行不写真实 Key。--live-api 默认关闭，需要显式打开；到期/余额不足标记阻塞，不悄悄改 mock 或其它模型。记录供应商、返回模型标识、usage、工具轨迹和耗时，不预设调用费用。

#### G. 已约定视频压力样本

~~~powershell
& $taskPython -m media_converter.devtools fixtures --profile pressure --root artifacts/fixtures/pressure --data-dir data
& $taskPython -m media_converter.devtools bench-video --profile agreed --fixture-root artifacts/fixtures/pressure --data-dir data --output artifacts/reports/video-pressure.json
~~~

agreed 固定包含 30 分钟 1080p、1 分钟 3840×2160、50 个短视频队列；长视频先用 MP4/H.264 基线测主路径，三种输出格式的兼容验证由小样本覆盖。记录是否合成/循环素材、帧率、码率、CPU/线程参数、资源和总耗时，不用文件时长冒充内容复杂度。

#### H. Windows 打包和路径隔离冒烟

~~~powershell
& $taskPython -m media_converter.devtools build-windows --data-dir data --output dist
& $taskPython -m media_converter.devtools smoke-package --package dist/MediaConverter-Windows-x64.zip --without-dev-path --output artifacts/reports/package-smoke.json
~~~

build-windows 必须实际调用已锁定的 PyInstaller 配置，生成基础 ZIP、AI 工具组件包、版本/哈希/第三方许可清单。smoke-package 在新目录解压，子进程不继承开发机 Python/FFmpeg 路径，执行真实导入、转换与结果验证。

PATH 隔离仍不能代替一台干净 Windows 虚拟机/独立机器：另在未安装开发依赖的环境按 README 完整演练并记录环境。没有该条件就将该项标记未验证，不能写“所有 Windows 均可运行”。

### 8.3 关键场景与验收矩阵

以下阈值除已确认压力规模外均为建议验收门槛，随本 Spec 确认；需要改动时记录原因，不覆盖旧结果。

| 测试编号 | 覆盖功能 | 关键场景 | 通过标准/证据 |
| --- | --- | --- | --- |
| T01 | F01–F04 | 首次空态、五类输入、50 文件、未知元数据、坏文件、超短/旋转视频 | 信息与实际探测一致，未知不造值，缩略图/占位正确，单文件失败不阻塞其它 |
| T02 | F05–F06 | 三种目标封装，高级设置，无音频、双音轨、内嵌字幕、参数冲突 | 每种目标至少一个可解码输出；轨数/语言符合计划；不兼容须确认，拒绝后无输出 |
| T03 | F07 | 同名源根、扁平/层级、旁置、已有输出、输入输出同路径、并发重名 | 原文件与已有文件哈希不变；层级和分组正确，无覆盖/目录穿越 |
| T04 | F08–F09 | 取消当前、取消整批、失败后下一项、重复开始/重试、写盘失败 | 一个转换进程；终态正确；取消后无误报成功和未授权新进程；仅清理所属临时文件 |
| T05 | F08–F10 | 输出完整性与预设重启恢复 | 短样本完整解码无错误；尺寸/编码/流数符合计划；时长误差建议≤max(0.25秒,2帧时长)；合成声画标记偏差≤100ms，人工播放核对 |
| T06 | F01/F11/F12 | 100%/150%/200% 缩放、键盘、冷启动、准备失败重试、浮动/收回 | 无遮挡关键操作；不重复问答；无 AI 依赖仍能转换；截图/录屏齐全 |
| T07 | F13–F15 | 5 会话各 3 轮、切选中项、模型返回工具乱序、建议应用、重启/中断 | 真实供应商 15 轮记录；引用/工具结果零串线；无确认不改设置；运行中批次快照不变；历史正确恢复 |
| T08 | F16–F17 | 固定知识评估、中文同义问法、精确编码/错误标识、库外问题 | 至少20个有答案＋5个无依据案例；人工核对期望来源；最终Top5命中≥17/20，5个库外案例明确无本地依据；来源定位可核验 |
| T09 | F17/F23 | 双路与 rerank 对照、同数据重复构建、索引版本切换 | 正常链路三阶段证据齐全；不重复入库；不混维度/版本；报告dense/词法/混合/重排对照，不编造提升 |
| T10 | F18 | 真 MySQL 查询、只读权限、SQL 注入、停服、同步重放/乱序 | 主键不重复、老事件不覆盖新事件；写/跨库被拒；滞后可见；恢复后可补同步 |
| T11 | F19/F24 | 各文档格式、无文字/加密 PDF、DOCX 压缩超限、路径链接/文件替换、提示注入 | 正常可定位读取；越权拒绝；截断有标记与游标；不执行资料内命令；错误非空成功 |
| T12 | F20/F14 | 本地依据充分/不足、真实搜索、空结果、401/限流/断网、临时接入到期 | 搜索触发符合约定；至少一条真实可核验结果；失败如实说明，无伪造链接；历史仍可查看 |
| T13 | F21–F24 | 100 同时提交、在途合并、跨作用域同参、取消/超时/进程崩溃 | 正常预热短资料3轮各100请求成功，无串线/悬挂；故障请求全部有应用终态；正常/故障统计分开，重连后新请求可成功 |
| T14 | F01/F08/F22 | 长视频、4K、50队列与AI同时工作 | UI定时采样建议p95间隔≤200ms，最长无响应≤1秒；取消按钮状态≤1秒更新；FFmpeg取消处理建议≤5秒；记录资源和实际总耗时 |
| T15 | F25 | 便携包、新数据目录、无开发PATH、干净Windows、AI首次准备 | 基本转换不需装Python/FFmpeg；完整AI在引导后真实可用；仅列实际测过的系统；记录初次准备和冷/热耗时 |
| T16 | F23–F25 | 诊断脱敏、源码/构建包/录屏凭据检查、README照做 | 测试哨兵密钥不出现在导出物；无真实Key/私人视频；操作步骤与实际一致；GitHub和Release链接可访问 |

补充真实素材项 X01（用户在 009–019 后追加，归入 T01/T02/T05）：使用 [Xiph Derf](https://media.xiph.org/video/derf/) 的完整 Crowd Run 1080p50 Y4M 序列，验证导入、探测、缩略图、MP4/H.264 CRF 23 转换、完整解码及 500 帧/50 fps 保持。校验源文件与随附 SVT 许可的 SHA-256，确认原件不变、成功状态持久化、转换并发为 1，保留来源、命令、进程证据和本机耗时。通过显式 `--xiph-root` 使用已下载素材，pytest 不联网；缺失或哈希不符必须失败。复现与实测见 [XIPH_TEST.md](docs/XIPH_TEST.md)。本项不替代 T14 的长视频、4K、50 文件及 AI 同时工作压力验收。

T08 的“Top5命中”指至少包含一条人工标注的正确证据，不用模型自评当标准；5 个库外案例在关闭网页搜索时评估本地知识边界，启用搜索后的回答另走 T12。完整混合＋重排应达到绝对门槛，并对比 dense 基线；未观察到提升也如实记录，不为包装项目捏造收益。

T13 除成功数外须报告：提交数、准入/拒绝数、实际执行数、合并命中数、排队长度峰值、执行并发峰值、成功/错误/取消/超时数、p50/p95耗时、重试和重连次数、CPU/内存。真实短资料正常场景若超时/失败，则视为对应验收未通过；不能把“都有报错返回”当作正常吞吐达标。故障场景中已取消请求的应用终态不要求协议再回一个结果。

### 8.4 发布门槛与证据

- F01–F25 必须有实现和相应 T 场景证据；尚未完成的项标记 failed/blocked，不暗中降为选做。
- 原件覆盖、静默丢轨、跨会话泄露、越权读取、密钥泄露、不能启动/转换、工具路径绕开 MCP、正常链路缺混合或重排，均阻止宣称完整交付。
- 正常端到端测试与压力报告不能由 mock 或 skip 代替。已有外部限制单列条件、错误和复现方法。
- 至少从空数据目录按 README 完整操作一遍：解压→导入→转换→查看结果→准备AI→含工具问答→应用建议→重启追问。
- TEST_REPORT.md 记录测试日期、提交版本、环境、依赖/模型版本、命令、结果、报告路径、截图/录屏、资源数据及已知限制。
- GitHub 不提交 .venv、模型权重、大视频、私密数据、运行数据库和凭据；发布合适的便携包、可选组件与校验清单。

## 9. 实施顺序与完成条件

这是一条依赖顺序，不是已承诺的小时工时；全部首版能力仍受 10月23日中午期限约束。

| 阶段 | 工作与交付 | 退出条件 |
| --- | --- | --- |
| 基础（M0） | tickets001–008：工程契约、错误与追踪、视频对象、SQLite、桌面骨架、后台运行桥、能力探测、测试素材 | 应用可启动，接口与数据单位固定，测试入口和素材可复用；复用已完成环境检查，不冒充正式产品通过 |
| 核心（M1/M2） | tickets009–039：完整转换链、会话与模型、MCP 调度、六个工具入口、本地知识、Agent 闭环和建议确认 | 两条主路径可逐项演示，工具真实经 MCP，转换与设置快照隔离，正常路径各票验收通过 |
| 边界（M1–M3） | tickets040–047：文件与媒体故障、MCP/Agent 恢复、服务与下载、首次准备、桌面交互回归 | 故障不损坏原件、不串会话、不悬挂；组件缺失可解释；关键操作和缩放可用 |
| 收尾（M3） | tickets048–056：两类包、RAG 评估、并发与真实 API、视频压力、干净机器、交付文档和 GitHub | T01–T16 证据逐项核对；外部阻塞单列；取得真实仓库/Release 链接后才记录发布完成 |

遇到阻塞时反馈：哪个功能/测试未过、可复现证据、影响、建议处理和剩余风险。任何变更如删除独立重排、更换框架、缩减测试或改变 API 接入方式，都要更新 Spec 与决策记录；不能以内部“简化”为由改变已确认需求。

### 9.1 最终交付物

1. 应用源码、完整依赖锁文件、可复现 Windows 构建入口。
2. MediaConverter-Windows-x64.zip；AI 工作组件和模型/服务准备清单。
3. README.md：下载启动、操作、API替换、本地AI准备、示例问答、故障排查。
4. docs/TEST_REPORT.md 和 artifacts 中可分享的真实结果、界面图/演示。
5. docs/SESSION_SUMMARY.md：原始题目、框架和范围选择、用户反馈、改动原因及真实进展。
6. 依赖/模型来源、版本、哈希、许可和已知限制。
7. 公开 GitHub 项目与对应 Release 链接，供用户交付 HR；不自动发送外部消息。

## 10. 事实来源与确认状态

### 10.1 已查证的一手资料

以下资料用于工程事实核验；不会把文档存在等同于本机验证通过。查阅日期均为 2026-10-21；前序需求阶段另有同源查阅。

| 来源 | 本 Spec 使用的事实 |
| --- | --- |
| [Qt QProcess](https://doc.qt.io/qtforpython-6/PySide6/QtCore/QProcess.html) | 外部进程、信号和输入输出机制 |
| [FFmpeg](https://ffmpeg.org/ffmpeg.html)、[ffprobe](https://ffmpeg.org/ffprobe.html) | 流映射、进度及媒体信息接口 |
| [DeepSeek模型](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)、[Responses兼容](https://api-docs.deepseek.com/zh-cn/guides/responses_api/) | 模型选择与应用自管上下文、工具调度限制 |
| [DeepSeek搜索](https://api-docs.deepseek.com/zh-cn/guides/search/) | 可独立封装的搜索接口 |
| [Ollama embed](https://docs.ollama.com/api/embed)、[Windows](https://docs.ollama.com/windows) | 向量接口、截断选项及独立分发方式 |
| [BGE-M3](https://huggingface.co/BAAI/bge-m3)、[独立reranker](https://huggingface.co/BAAI/bge-reranker-v2-m3) | 嵌入与重排角色不同，不假定Ollama暴露全部原模型能力 |
| [Qdrant BM25](https://qdrant.tech/documentation/inference/inference-bm25/)、[混合查询](https://qdrant.tech/documentation/search/hybrid-queries/)、[1.19.2发布](https://github.com/qdrant/qdrant/releases/tag/v1.19.2) | 词法分支、融合和Windows发布资产 |
| [MCP规范](https://modelcontextprotocol.io/specification/2026-07-28)、[SDK协议](https://py.sdk.modelcontextprotocol.io/protocol-versions/)、[2.3.0发布](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.3.0) | 协议代际与正式SDK版本，取消/重连按对应版本实现 |
| [MySQL连接池](https://dev.mysql.com/doc/connectors/en/connector-python-connection-pooling.html) | 连接借还与并发边界 |
| [PyInstaller](https://pyinstaller.org/en/stable/operating-mode.html)、[FFmpeg许可](https://www.ffmpeg.org/legal.html) | Windows打包与真实组件许可核验 |
| [PySide6分发元数据](https://pypi.org/pypi/PySide6/json)、[torch分发元数据](https://pypi.org/pypi/torch/json)、[mcp分发元数据](https://pypi.org/pypi/mcp/json) | 候选版本/适用wheel；不是安装或推理结果 |
| [sentence-transformers](https://pypi.org/pypi/sentence-transformers/json)、[qdrant-client](https://pypi.org/pypi/qdrant-client/json)、[MySQL connector](https://pypi.org/pypi/mysql-connector-python/json)、[PyInstaller元数据](https://pypi.org/pypi/PyInstaller/json) | 其余候选分发版本 |
| [WinUI Gallery](https://github.com/microsoft/WinUI-Gallery)、[QFluentWidgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets) | 前序选定的桌面视觉参考；未据此宣称模板已运行或已采用其依赖 |

### 10.2 当前文档状态与实施边界

用户已明确产品需求，并要求先审阅开发 Spec。本文件将新增的工程建议集中为：桌面自管 stdio MCP、SQLite本地持久化＋MySQL查询读库、Qdrant原生词法分支＋RRF、独立 bge-reranker-v2-m3、分包准备方式，以及具体队列/超时/评估阈值。

规格拆分阶段按用户指示将现有 Spec 拆成 tickets，不改变技术选型。原文标注“建议”的参数保留其性质，作为实现起点和验收目标；变更需说明依据。后续用户已授权按编号继续，001–047 已实施对应本地开发范围；041 真人播放核对待补。真实 DeepSeek/Search 验收仍按用户要求留在 054。048–056、交付包与 GitHub 发布尚未完成。

<a id="development-tickets"></a>

## 11. 可执行开发 tickets

### 11.1 拆分思路、执行顺序和风险

拆分采用“一个会话交付一个可验证结果”。每票明确主责模块、接口或数据变更，并把调用方接线和该结果所需测试放在同一票。先定义稳定的数据/错误/持久化边界，再做转换与问答两条链；核心安全约束从首次实现就生效，边界阶段负责故障回归，不将安全措施推迟到收尾。

执行顺序为基础 001–008 → 核心 009–039 → 边界 040–047 → 收尾 048–056。编号已经按依赖拓扑排列，默认按编号执行；单票只要求其“依赖”列出的前置票验收完成，不要求实现未来票。核心内部的两条链是 009–019 转换闭环与 020–039 Agent 闭环。这里不授权启动多个 agent 或同时修改共享文件。

已有环境作为输入：`environment/manifest.json`、版本冻结、模型与服务配置、环境测试结果。不得把环境目录整体复制进源码，不再次下载相同模型，也不得把 `video_converter_env` 探针数据库当作正式业务库。应用源码、测试、构建规则和锁文件需要纳入项目；运行数据与凭据继续隔离。

主要风险与执行办法：

- R01/R12/R14：环境探针不能证明产品包可分发。001 固定核心/AI 依赖边界，048/049 分别构建基础包和 AI 工作组件，053 在干净 Windows 验证，并检查真实许可。
- R02/R03/R05：丢轨、覆盖、取消竞态属于阻塞缺陷。013–017 首次实现即防护，040/041 做破坏性场景的隔离测试；不得先交付会覆盖文件的临时方案。
- R06/R10/R16：上下文、权限和脱敏必须在 002/020/023 建立。测试替身只用于测试，生产路径不能绕过 MCP、吞掉权限错误或记录凭据。
- R07/R08：先完成有来源的资料与固定评估集，再实现双路召回和独立重排。050 报真实指标；100 请求是有界排队目标，不是 100 个模型同时推理。
- R09：SQLite 的事务与 outbox 在基础阶段确定，030 负责 MySQL 投影；断库不得阻止转换，也不能把滞后记录称为最新结果。
- R11/R13：054 依赖有效 API Key，053 依赖干净 Windows 执行条件。缺少条件就记录 blocked，不以 mock、skip 或开发机 PATH 隔离替代。
- 临时 Key 的一小时窗口不能夹在长视频压力与组件下载之间：先完成无需 Key 的压力、包和干净机准备，再集中执行真实在线验收，具体编号见收尾票。
- R15：56 张票是会话边界，不是工时承诺；截止时间仍以 §9 为准。遇到超出单会话的未预见改动，保留父票未完成状态并拆明确子票，不删功能或降低门槛凑完成。

### 11.2 每张票的执行与完成规则

- 001–047 已实现对应本地开发范围，详见 FOUNDATION_REPORT/CONVERSION_REPORT/AGENT_REPORT/FILESYSTEM_REPORT/BOUNDARY_REPORT；041 真人播放核对待补，Agent 真实 API 验收仍归 054。本轮止于 047，下一开发票为 048，不因没有 Key 停止离线工作。
- 某票因外部条件 blocked 时，可以执行其它依赖已满足的票；不能把未通过的前置票当作完成。先完成下载、长视频和干净机本地准备，再开启一次集中的在线测试窗口。
- 下列文件名是计划修改范围，不表示文件已存在。编号避免使用 T 前缀，防止与 §8.3 的验收编号 T01–T16 混淆。
- `ui/`、`media/`、`jobs/`、`agent/`、`rag/`、`tools/`、`services/`、`storage/`、`common/`、`devtools/` 及 MCP 入口均相对 `src/media_converter/`；`tests/`、`knowledge/`、`packaging/`、`docs/` 相对项目根目录。
- 测试命令均为完成该票后必须可运行的命令；001 交付 `pyproject.toml`、pytest 标记与 `--data-dir/--fixture-root/--live-api` 参数契约。未实现的子命令明确报错，不返回虚构成功。
- 命令从项目根目录、加载 `environment/activate.ps1` 后运行。应用测试数据使用独立 `data`/`artifacts` 目录，不能清理现有个人库或环境探针数据；真实服务与 API 测试不得暗中改为替身。
- 通用完成条件：列出改动文件、命令、真实结果与产物；更新 `docs/SESSION_SUMMARY.md`；接口/数据变更同步调用方和迁移；不得留下生产空实现、无主 TODO 或“以后接线”的按钮。
- 测试结果区分 passed/failed/skipped/blocked。依赖不具备时可以编写并验证隔离逻辑，但需要真实依赖的验收不能记为完成。
- 交接下一票需保留：已完成范围、固定接口、实际测试、未完成项、发现的问题。需要变更产品范围时单独记录到 §11.8，不在票内悄悄扩大或削减。

### 11.3 基础：tickets001–008

<a id="tickets001"></a>

#### tickets001：建立可安装工程、依赖锁和测试入口

- **状态**：已完成（2026-10-21），实现、命令和证据见 [基础验收记录](docs/FOUNDATION_REPORT.md)。
- **目标**：提供可启动、可测试的 Python 应用工程，复用已准备的开发环境。
- **背景**：对应 §3.1、§3.3、§8.2A/B，F25，R01；输入为环境检查记录，不重复安装。
- **修改范围**：`pyproject.toml`、`requirements-*.lock`、`src/media_converter/__main__.py`、`devtools/__main__.py`、`tests/conftest.py`、`.gitignore`。
- **具体任务**：定义核心、工具、CPU 重排依赖组和完整锁定来源；建立 GUI/devtools 入口与配置路径注入；注册 unit/gui/integration/live_api/stress 标记、自定义参数及显式在线开关；运行产物均留在项目 D 盘目录。
- **验收标准**：editable 安装后应用入口可运行并正常退出；核心启动不导入 Torch 或要求 AI 服务；`devtools --help` 只列已有命令，未知命令非零退出；未启用在线测试时不发 API 请求。
- **测试要求**：`python -m pip check`；`python -m pytest tests/unit/test_project_bootstrap.py -q`，检查入口、数据路径、依赖组及默认禁止在线请求。
- **依赖**：已完成的开发环境。
- **不包含**：具体页面、转换、聊天、业务数据库、最终发布包。

<a id="tickets002"></a>

#### tickets002：建立统一错误、调用标识和脱敏日志

- **状态**：已完成（2026-10-21），实现、命令和证据见 [基础验收记录](docs/FOUNDATION_REPORT.md)。
- **目标**：让后续模块使用同一错误与观测契约。
- **背景**：对应 §5.4、§6.3，F24，T16，R16。
- **修改范围**：`common/errors.py`、`common/context.py`、`common/logging.py`；工具结果与事件的共享类型。
- **具体任务**：定义 §5.4 错误码、可重试性、用户建议与结果 envelope；生成实例/trace/turn/invocation 标识；输出结构化 JSONL，隔离协议 stdout；实现凭据、路径和正文摘要的统一脱敏规则。
- **验收标准**：每条调用事件可关联到 trace；异常不能伪装为空成功；哨兵 Key/口令不出现在日志；取消异常继续传播；脱敏失败时不退回输出原文。
- **测试要求**：`python -m pytest tests/unit/test_errors_logging.py -q`，覆盖嵌套参数、异常文本、URL 查询串与取消透传。
- **依赖**：tickets001。
- **不包含**：诊断导出界面、各工具业务实现、完整遥测平台。

<a id="tickets003"></a>

#### tickets003：定义视频对象、转换计划和尝试状态机

- **状态**：已完成（2026-10-21），实现、命令和证据见 [基础验收记录](docs/FOUNDATION_REPORT.md)。
- **目标**：固定转换链的数据单位、不变量和状态转换。
- **背景**：对应 §4.1 中 ImportRoot/MediaAsset/StreamInfo/ConversionSettings/ConversionPlan/JobAttempt、§4.2，F02–F09，T04。
- **修改范围**：`media/models.py`、`jobs/models.py`、`jobs/state_machine.py`。
- **具体任务**：实现明确类型、null 未知值、分数帧率和微秒进度；定义不可变设置快照、计划哈希输入与轨道丢失项；实现合法迁移、终态保护、重试新 attempt_id 和批次命令标识。
- **验收标准**：非法迁移被拒绝；取消后的迟到成功不能回退终态；重试保留旧尝试；序列化往返不改变单位、流映射或哈希语义。
- **测试要求**：`python -m pytest tests/unit/test_conversion_models.py -q`，包含所有终态、未知时长、变帧率和重复事件。
- **依赖**：tickets001、tickets002。
- **不包含**：数据库读写、FFmpeg 调用、实际兼容表和界面。

<a id="tickets004"></a>

#### tickets004：实现本地 SQLite 存储和事务内 outbox

- **状态**：已完成（2026-10-21），实现、命令和证据见 [基础验收记录](docs/FOUNDATION_REPORT.md)。
- **目标**：基本转换在没有外部服务时也能保存状态，并为后续同步留下可靠事件。
- **背景**：对应 §5.2 的 SQLite 设置/预设/素材/转换尝试/outbox，§4.2，F08/F10/F18，T05/T10。
- **修改范围**：`storage/local_store.py`、`storage/migrations/`、`storage/outbox.py`。
- **具体任务**：建立 schema 版本迁移和串行写队列；实现设置、预设、素材与尝试仓储；业务更新与 outbox 同事务提交；启动时将活动尝试转 INTERRUPTED，保留用户重试入口。
- **验收标准**：事务失败时业务记录和事件同时回滚；重复终态不产生重复事件；多读取者不共享写连接；重启不自动重跑转换；不依赖 MySQL 启动。
- **测试要求**：`python -m pytest tests/unit/test_local_store.py -q`，覆盖旧版本迁移、事务中断、并发读写和异常退出恢复。
- **依赖**：tickets002、tickets003。
- **不包含**：聊天表、MySQL 投影、后台同步网络连接。

<a id="tickets005"></a>

#### tickets005：建立 Windows 主窗口和桌面视觉基线

- **状态**：已完成（2026-10-21），实现、命令和证据见 [基础验收记录](docs/FOUNDATION_REPORT.md)。
- **目标**：交付符合已定桌面布局的可运行窗口，固定后续页面的容器边界。
- **背景**：对应 §1.2、§3.1、§3.3，F01/F12，T06；参考 §10.1 已列桌面项目。
- **修改范围**：`ui/main_window.py`、`ui/theme.py`、任务/详情/设置容器和 Agent dock 容器；`docs/UI_REFERENCE.md`。
- **具体任务**：落实左任务与详情、右参数、底部进度、AI 停靠区；研究已列 GitHub 桌面参考，记录采用的布局规律和许可边界；建立浅色样式、空态、Tab 顺序和最小窗口尺寸。
- **验收标准**：应用可打开/关闭；核心区不做网页外壳；100%/150%/200% 的基础布局无关键容器遮挡；未实现的业务控件不伪装可用；参考记录不复制不明许可代码。
- **测试要求**：`python -m pytest tests/gui/test_window_shell.py -q`；保存三档缩放的窗口截图到 `artifacts/ui/shell/`，记录真实显示环境。
- **依赖**：tickets001。
- **不包含**：导入、设置业务、聊天请求、最终交互验收。

<a id="tickets006"></a>

#### tickets006：实现 Qt 与后台 asyncio 的运行桥

- **状态**：已完成（2026-10-21），实现、命令和证据见 [基础验收记录](docs/FOUNDATION_REPORT.md)。
- **目标**：后续网络/MCP 工作不会占用 GUI 线程，应用关闭有统一收口点。
- **背景**：对应 §3.1/§3.2、§3.7、§6.2，F01/F22，T14，R04。
- **修改范围**：`services/async_runtime.py`、`ui/runtime_bridge.py`、应用启动/退出接线。
- **具体任务**：建立一个专用后台线程及 asyncio loop；用带标识的信号回传事件；提供提交、取消、关闭与异常上报；定义阻塞任务转工作单元的调用边界，避免跨循环复用连接。
- **验收标准**：后台延迟任务期间 Qt 定时器持续运行；事件在 GUI 线程更新控件；关闭后不接受新任务；同一任务取消/完成竞态只产生一个终态，退出无残留后台线程。
- **测试要求**：`python -m pytest tests/gui/test_runtime_bridge.py -q`，包含后台异常、取消与退出竞态。
- **依赖**：tickets002、tickets005。
- **不包含**：MCP 实际连接、工具公平队列、推理进程、自动重连。

<a id="tickets007"></a>

#### tickets007：实现 FFmpeg 定位和真实能力探测

- **状态**：已完成（2026-10-21），实现、命令和证据见 [基础验收记录](docs/FOUNDATION_REPORT.md)。
- **目标**：转换规划只使用实际存在的二进制与编码能力。
- **背景**：对应 §3.4、§3.7、§8.2C，F03/F05/F11，T02，R01。
- **修改范围**：`media/toolchain.py`、运行路径配置、`devtools prepare --components core` 的已有组件检查部分。
- **具体任务**：支持便携相对路径与开发配置的 FFmpeg/ffprobe；以参数数组读取版本、编码器及目标封装能力；生成带二进制身份的能力快照；缺 libx264/AAC/libvpx-vp9/libopus 时明确报告。
- **验收标准**：开发时能使用 `D:\ffmpeg_ffprobe` 的现有安装；无 PATH 时仍可通过显式路径探测；版本变化使缓存失效；缺编码器不能静默换方案；所有进程调用不经过 shell。
- **测试要求**：`python -m pytest tests/unit/test_toolchain.py tests/integration/test_toolchain.py -q`，后者使用真实 FFmpeg，并隔离 PATH 验证。
- **依赖**：tickets001、tickets002、tickets006。
- **不包含**：自动下载、用户首次准备向导、转换执行。

<a id="tickets008"></a>

#### tickets008：生成可追溯的小型媒体与文档测试素材

- **状态**：已完成（2026-10-21），实现、命令和证据见 [基础验收记录](docs/FOUNDATION_REPORT.md)。
- **目标**：后续票使用统一、有已知期望值的真实样本。
- **背景**：对应 §8.2C、§8.3 T01–T05/T11，F02–F09/F19。
- **修改范围**：`devtools/fixtures.py`、测试素材 manifest、`tests/fixture_support.py`；实现 `fixtures --profile smoke`。
- **具体任务**：自生成五类输入封装、无音频/双音轨/字幕兼容与不兼容样本、旋转/VFR/超短/坏文件；创建五类文字文档与加密/无文字/损坏案例；记录命令、期望流/时间基、哈希和许可。
- **验收标准**：同一 manifest 可重建同类期望数据，不要求有时间戳的封装逐字节相同；输出不越过指定 root；已有非本工具文件不被覆盖；素材不包含私人视频或实际密钥。
- **测试要求**：`python -m media_converter.devtools fixtures --profile smoke --root artifacts/fixtures --data-dir data`；`python -m pytest tests/integration/test_fixtures.py -q`。
- **依赖**：tickets001、tickets007。
- **不包含**：30 分钟/4K/50 队列压力素材、生产文档解析器、正式知识库。

### 11.4 核心：tickets009–039

<a id="tickets009"></a>

#### tickets009：实现文件、拖入和目录导入

- **状态**：已实现并通过开发验收（2026-10-21），见 [转换闭环验收记录](docs/CONVERSION_REPORT.md)；真实 Qt 操作、输出和截图已保留，供用户复核。
- **目标**：将三种用户入口统一转换为稳定的素材与来源根记录。
- **背景**：对应 §2 F02、§3.4、§4.1 ImportRoot/MediaAsset，T01/T03。
- **修改范围**：`media/importer.py`、`ui/import_actions.py`、素材仓储与导入结果事件。
- **具体任务**：多选/拖入/目录选择共用 ImportService；默认仅扫描当前层，勾选后递归；规范化真实路径与文件身份，去重并保留来源根；跳过目录链接循环与本应用结果目录，逐项报告拒绝原因。
- **验收标准**：中文、空格、同名不同文件、重复添加均正确；未勾选时不读子目录；递归不形成死循环；单文件拒绝不取消其余导入；单独添加分组可供层级输出使用。
- **测试要求**：`python -m pytest tests/unit/test_importer.py tests/gui/test_import_actions.py -q`，包含可创建时的 junction/symlink 案例，无法创建时记录限制。
- **依赖**：tickets003、tickets004、tickets005、tickets006、tickets008。
- **不包含**：ffprobe、缩略图、目录监控或自动知识入库。

<a id="tickets010"></a>

#### tickets010：实现异步 ffprobe 与视频详情

- **状态**：已实现并通过开发验收（2026-10-21），见 [转换闭环验收记录](docs/CONVERSION_REPORT.md)；真实 Qt 操作、输出和截图已保留，供用户复核。
- **目标**：素材详情来自真实探测，未知字段不造值。
- **背景**：对应 F03、§3.4、§4.1 MediaAsset/StreamInfo，T01/T02。
- **修改范围**：`media/probe.py`、详情模型/视图、素材探测状态持久化。
- **具体任务**：限并发 2 调用 ffprobe JSON；解析容器、尺寸、可视旋转、时间、码率、分数帧率、音频/字幕和封面流；设置超时与可解释坏文件状态；文件指纹改变时重新探测。
- **验收标准**：五类输入的已知字段与样本 manifest/ffprobe 一致；缺字段显示“未知”；封面不误判为第二主视频；超时/损坏仅影响自身；GUI 可继续操作。
- **测试要求**：`python -m pytest tests/unit/test_probe_parser.py tests/integration/test_media.py -k probe -q --fixture-root artifacts/fixtures --data-dir data`。
- **依赖**：tickets007、tickets008、tickets009。
- **不包含**：编码兼容决策、缩略图、格式推荐问答。

<a id="tickets011"></a>

#### tickets011：实现缩略图队列、缓存与占位图

- **状态**：已实现并通过开发验收（2026-10-21），见 [转换闭环验收记录](docs/CONVERSION_REPORT.md)；真实 Qt 操作、输出和截图已保留，供用户复核。
- **目标**：列表能持续显示真实缩略图，生成过程不阻塞导入。
- **背景**：对应 F04、§3.4、§6.1，T01/T14。
- **修改范围**：`media/thumbnail.py`、缩略图缓存索引、任务列表图片委托。
- **具体任务**：限并发 2、设置有界队列与超时；优先代表帧，失败回退开头帧；按源身份/修改/尺寸和取帧版本缓存；统一处理旋转、图片释放与任务移除后的迟到结果。
- **验收标准**：超短视频可回退；失败有占位图；源改变不使用旧图；同源重复请求不重复解码；移除素材后迟到图片不写回其它行。
- **测试要求**：`python -m pytest tests/unit/test_thumbnail_cache.py tests/integration/test_media.py -k thumbnail -q --fixture-root artifacts/fixtures --data-dir data`；50 文件响应性最终由 052 验证。
- **依赖**：tickets008、tickets010。
- **不包含**：视频播放器、封面编辑、无限缓存或后台预览转码。

<a id="tickets012"></a>

#### tickets012：实现常用与高级参数表单和统一校验

- **状态**：已实现并通过开发验收（2026-10-21），见 [转换闭环验收记录](docs/CONVERSION_REPORT.md)；真实 Qt 操作、输出和截图已保留，供用户复核。
- **目标**：用户能清楚设置整批转换参数，UI 与 Agent 将来复用同一验证器。
- **背景**：对应 F05、§3.4 默认组合、§4.1 ConversionSettings、§5.1，T02。
- **修改范围**：`media/settings.py`、`ui/settings_panel.py`、设置版本管理。
- **具体任务**：提供 MP4/MKV/WebM、质量/码率互斥、分辨率/帧率和音频选项；结合真实能力限制选择；默认保持尺寸和帧率；提供字段级验证结果和版本递增，不直接改运行计划。
- **验收标准**：无效数值/组合在开始前被拒绝；三种目标默认编码符合 §3.4；质量值不跨编码器误用；表单往返能保留有效设置与未知/自动语义。
- **测试要求**：`python -m pytest tests/unit/test_settings_validation.py tests/gui/test_settings_panel.py -q`。
- **依赖**：tickets003、tickets005、tickets007。
- **不包含**：用户预设保存、流映射、Agent 建议应用、启动转换。

<a id="tickets013"></a>

#### tickets013：实现输出路径规划与禁止覆盖提交

- **状态**：已实现并通过开发验收（2026-10-21），见 [转换闭环验收记录](docs/CONVERSION_REPORT.md)；真实 Qt 操作、输出和截图已保留，供用户复核。
- **目标**：两种保存方式均能保留来源关系，并保护源文件与现有输出。
- **背景**：对应 F07、§3.4 输出规则、§5.1，T03，R03。
- **修改范围**：`media/output_paths.py`、`jobs/output_commit.py`、输出模式表单。
- **具体任务**：统一目录支持扁平/来源层级，旁置固定“转换结果”；稳定区分同名来源根和单独添加组；生成带 attempt_id 的同卷临时名；通过禁止覆盖的提交操作处理竞态重名与目录穿越。
- **验收标准**：已有目标与源文件哈希不变；并发抢占目标时重新避让或可解释失败；旁置不再套层级选项；不使用会覆盖现有文件的替换操作；只清理所属临时文件。
- **测试要求**：`python -m pytest tests/unit/test_output_paths.py tests/integration/test_output_commit.py -q`，包含同路径、同名根、路径逃逸与提交竞态。
- **依赖**：tickets003、tickets009、tickets012。
- **不包含**：网络盘完整兼容、实际转码、删除用户旧结果。

<a id="tickets014"></a>

#### tickets014：实现轨道兼容规则、转换计划和丢失确认

- **状态**：已实现并通过开发验收（2026-10-21），见 [转换闭环验收记录](docs/CONVERSION_REPORT.md)；真实 Qt 操作、输出和截图已保留，供用户复核。
- **目标**：生成可验证的整批计划，未经确认不得丢弃轨道。
- **背景**：对应 F05/F06、§3.4、§4.1 ConversionPlan、§5.1，T02，R02。
- **修改范围**：`media/compatibility.py`、`media/planner.py`、`ui/loss_confirmation.py`。
- **具体任务**：基于探测与本机能力显式映射主视频及全部拟保留音轨/内嵌字幕；保留语言/default 标志；生成参数数组与具体 loss_items；确认绑定 plan_hash，源或设置变化后使确认失效。
- **验收标准**：兼容双音轨与字幕不被默认映射丢失；不兼容项显示轨号和原因；取消确认不能进入 READY；不支持多主视频轨明确拒绝；音轨自动重编码仍保留拟保留数量。
- **测试要求**：`python -m pytest tests/unit/test_conversion_planner.py tests/gui/test_loss_confirmation.py -q`，用 008 的轨道清单检查计划和参数数组。
- **依赖**：tickets007、tickets008、tickets010、tickets012、tickets013。
- **不包含**：字幕烧录、外挂字幕、ASS 样式转换、FFmpeg 执行。

<a id="tickets015"></a>

#### tickets015：实现单次 FFmpeg 执行与机器可读进度

- **状态**：已实现并通过开发验收（2026-10-21），见 [转换闭环验收记录](docs/CONVERSION_REPORT.md)；真实 Qt 操作、输出和截图已保留，供用户复核。
- **目标**：可靠运行一个已确认计划并输出真实进度和执行证据。
- **背景**：对应 F08、§3.4、§4.2，T04/T05。
- **修改范围**：`jobs/ffmpeg_process.py`、progress 解析器与 stderr 限量日志。
- **具体任务**：以参数数组和显式二进制路径启动所属进程；使用 progress 通道与独立 stderr；解析已处理时间、速度、退出码；处理分块行、未知时长和进度完成但进程未退出的情况。
- **验收标准**：记录实际 PID、启动身份和参数摘要；未知时长显示不定进度；progress end 不等于任务成功；标准错误有界保存且已脱敏；源路径特殊字符不进入 shell。
- **测试要求**：`python -m pytest tests/unit/test_ffmpeg_progress.py tests/integration/test_conversion.py -k process -q --fixture-root artifacts/fixtures --data-dir data`。
- **依赖**：tickets002、tickets003、tickets007、tickets014。
- **不包含**：多项调度、最终文件发布、失败重试和完整取消策略。

<a id="tickets016"></a>

#### tickets016：实现顺序批次、输出验证和终态提交

- **状态**：已实现并通过开发验收（2026-10-21），见 [转换闭环验收记录](docs/CONVERSION_REPORT.md)；真实 Qt 操作、输出和截图已保留，供用户复核。
- **目标**：从一组计划执行到可信结果，任何时刻最多一个转换进程。
- **背景**：对应 F08、§3.4、§4.2、§5.1/§5.2，T04/T05。
- **修改范围**：`jobs/job_service.py`、`jobs/output_validator.py`、批次/尝试仓储与事件。
- **具体任务**：冻结批次设置和源指纹，防重复 batch_command_id；逐项 PREPARING/RUNNING/VERIFYING；用 ffprobe 检查尺寸、编码、流与时长，小样本完整解码；通过后调用禁止覆盖提交并事务保存终态/outbox。
- **验收标准**：重复开始只有一个批次；失败项保留原因并继续后项；输出验证失败不能显示成功；进度计数与终态一致；运行时修改表单不改变快照。
- **测试要求**：`python -m pytest tests/unit/test_batch_runner.py tests/integration/test_conversion.py -k batch -q --fixture-root artifacts/fixtures --data-dir data`，记录执行并发峰值为 1。
- **依赖**：tickets003、tickets004、tickets010、tickets013、tickets014、tickets015。
- **不包含**：用户取消/重试入口、并行 FFmpeg、恢复后自动续跑。

<a id="tickets017"></a>

#### tickets017：实现取消当前、取消整批和失败重试

- **状态**：已实现并通过开发验收（2026-10-21），见 [转换闭环验收记录](docs/CONVERSION_REPORT.md)；真实 Qt 操作、输出和截图已保留，供用户复核。
- **目标**：用户能停止或重试明确范围的转换，不污染原尝试。
- **背景**：对应 F09、§3.4 取消语义、§4.2，T04，R05。
- **修改范围**：`jobs/job_service.py`、所属进程停止逻辑、重试计划生成与操作状态。
- **具体任务**：当前取消先正常停止再限时终止；整批取消同时禁止后项启动；取消标志优先于退出码；重试创建新 attempt_id，默认沿用失败快照，源改变重新探测和确认。
- **验收标准**：当前取消后后项能继续，整批取消后没有新进程；退出码 0 不能覆盖 CANCELLED；重复重试按钮不启动同一新尝试两次；只清理该尝试临时文件。
- **测试要求**：`python -m pytest tests/unit/test_job_cancellation.py tests/integration/test_conversion.py -k 'cancel or retry' -q --fixture-root artifacts/fixtures --data-dir data`，注入取消与验证完成竞态。
- **依赖**：tickets016。
- **不包含**：暂停/恢复编码、自动重试所有失败项、结束非本应用进程。

<a id="tickets018"></a>

#### tickets018：实现预设、有效设置恢复和打开输出位置

- **状态**：已实现并通过开发验收（2026-10-21），见 [转换闭环验收记录](docs/CONVERSION_REPORT.md)；真实 Qt 操作、输出和截图已保留，供用户复核。
- **目标**：让重复转换少配置，结果位置可直接访问。
- **背景**：对应 F10、§1.2 默认值、§5.2，T05。
- **修改范围**：`media/presets.py`、设置/预设仓储、预设表单与结果操作。
- **具体任务**：保存命名预设与有效设置；重启时按当前能力重新验证；无效项显示修复原因而非盲目复用；用系统文件管理入口打开真实最终目录并处理失败。
- **验收标准**：预设新增/更新和设置恢复可重现；编码器缺失时不会启动错误计划；打开的是实际避让后的结果位置；预设变更产生可同步版本事件。
- **测试要求**：`python -m pytest tests/unit/test_presets.py tests/gui/test_preset_actions.py -q`，覆盖两次启动、旧版本迁移、失效能力和目录不存在。
- **依赖**：tickets004、tickets007、tickets012、tickets013、tickets016。
- **不包含**：云端预设、预设分享市场、MySQL 同步实现。

<a id="tickets019"></a>

#### tickets019：接通完整桌面转换操作

- **状态**：已实现并通过开发验收（2026-10-21），见 [转换闭环验收记录](docs/CONVERSION_REPORT.md)；真实 Qt 操作、输出和截图已保留，供用户复核。
- **目标**：用户从导入到查看结果能走通一条真实桌面路径。
- **背景**：对应 F01–F10、§1.3 步骤 1–4、§3.4，T01–T06。
- **修改范围**：`ui/task_model.py`、列表/详情/设置/进度容器、主窗口动作接线。
- **具体任务**：接入导入事件、探测和图片更新、批次预检/丢失确认、开始/取消/重试/打开目录；区分处理中/失败/取消/验证中/成功状态；根据真实状态设置操作可用性。
- **验收标准**：无 AI 服务也能完成导入→设置→确认→转换→打开结果；没有只改视觉而未接线的按钮；选中变化不串详情；错误可定位到文件并保留其它任务。
- **测试要求**：`python -m pytest tests/gui/test_conversion_flow.py -q --fixture-root artifacts/fixtures --data-dir data`；人工用三种目标各操作一次，保存截图和实际输出检查。
- **依赖**：tickets005、tickets006、tickets009、tickets010、tickets011、tickets012、tickets014、tickets016、tickets017、tickets018。
- **不包含**：AI 侧栏逻辑、压力结论、最终界面验收和发布包。

<a id="tickets020"></a>

#### tickets020：实现会话存储、明确引用和不可变轮次上下文

- **状态**：已实施并通过本地开发验收（测试日期 2026-10-22），见 [Agent 验收记录](docs/AGENT_REPORT.md)；真实在线验收归 054，人工 RAG 标签/校准归 050。

- **目标**：让聊天历史、当前引用和权限范围拥有独立、持久的身份。
- **背景**：对应 F13、§3.6、§4.1 Conversation/Message/TurnContext、§5.2，T07/T11，R10。
- **修改范围**：`agent/models.py`、`agent/references.py`、聊天/引用迁移与仓储、ToolInvocation/SettingsProposal 类型。
- **具体任务**：定义会话、消息序号、provider_items、轮次和工具标识；保存显式视频/任务/文件引用及文件指纹；提交时冻结引用、设置版本、数据作用域和 deadline；启动时仅将活动轮次标为 INTERRUPTED。
- **验收标准**：切换主列表选中项不改变已有轮次引用；同会话消息序号唯一；重启恢复已提交历史；不同会话不能访问彼此未授权引用；重试创建新 turn_id，不覆盖旧轮次。
- **测试要求**：`python -m pytest tests/unit/test_conversation_store.py tests/unit/test_reference_context.py -q`，包含文件替换、引用撤销和五组会话数据隔离。
- **依赖**：tickets002、tickets004、tickets010、tickets016。
- **不包含**：模型调用、会话执行调度、文档正文读取、UI 历史列表。

<a id="tickets021"></a>

#### tickets021：实现可替换的在线模型配置与凭据存储

- **状态**：已实施并通过本地开发验收（测试日期 2026-10-22），见 [Agent 验收记录](docs/AGENT_REPORT.md)；真实在线验收归 054，人工 RAG 标签/校准归 050。

- **目标**：评审能在设置中配置自己的接入，凭据不会进入公开文件。
- **背景**：对应 F14、§1.2 临时 API、§3.7，T12/T16，R11/R16。
- **修改范围**：`services/config.py`、`storage/credentials.py`、`ui/api_settings.py`；配置版本与凭据引用。
- **具体任务**：配置 API 地址、模型默认 `deepseek-v4-pro` 与连接设置；用 DPAPI 加密凭据并限制私密文件权限；支持替换/清除/失败重配；让后续适配器取得凭据引用而非把 Key 写进参数或日志。
- **验收标准**：同一 Windows 用户可重启恢复；复制到另一用户/机器时提示重新配置；无 Key 时基本转换可用；清除后新在线请求不能继续使用旧 Key；客户端不虚构服务端一小时自动失效。
- **测试要求**：`python -m pytest tests/unit/test_credentials.py tests/gui/test_api_settings.py -q`，用哨兵值检查序列化、日志和配置导出。
- **依赖**：tickets002、tickets004、tickets005、tickets006。
- **不包含**：发卡、计费、真实 API 调用、提供方账号管理。

<a id="tickets022"></a>

#### tickets022：实现 DeepSeek 流式响应与工具调用适配器

- **状态**：已实施并通过本地开发验收（测试日期 2026-10-22），见 [Agent 验收记录](docs/AGENT_REPORT.md)；真实在线验收归 054，人工 RAG 标签/校准归 050。

- **目标**：把供应商响应规范化为应用可消费的文本、函数调用和用量事件。
- **背景**：对应 F14、§3.1/§3.6、§5.4，T07/T12。
- **修改范围**：`agent/deepseek_adapter.py`、供应商 item/事件类型、连接测试服务接线。
- **具体任务**：按 Spec 所指官方 Responses 兼容契约实现异步流解析；保留需要回传的 reasoning/function 配对字段；校验工具参数 JSON 并区分流结束、函数请求和最终答案；分类认证/限流/余额/断网错误，记录返回模型和实际 usage。
- **验收标准**：分块事件、乱序函数结果准备和中途断流可重现；部分输出不自动重放；缺失 usage 标为未知，不编造费用；连接测试真实访问当前配置且不泄露凭据。
- **测试要求**：`python -m pytest tests/unit/test_deepseek_adapter.py -q`，使用标明为模拟的流与错误响应；真实供应商验收归 054，无 Key 不宣称通过。
- **依赖**：tickets002、tickets006、tickets020、tickets021。
- **不包含**：Agent 循环、工具执行、无限重试、切换其它供应商模型。

<a id="tickets023"></a>

#### tickets023：建立真实 stdio MCP 连接与可信上下文边界

- **状态**：已实施并通过本地开发验收（测试日期 2026-10-22），见 [Agent 验收记录](docs/AGENT_REPORT.md)；真实在线验收归 054，人工 RAG 标签/校准归 050。

- **目标**：应用通过实际 MCP 协议发现和调用已实现工具，连接不绑定聊天历史。
- **背景**：对应 F21/F24、§5.3/§5.4、§6.2，T13，R06。
- **修改范围**：`mcp_client.py`、`mcp_server.py`、`tools/registry.py`、可信 metadata 校验及统一结果转换。
- **具体任务**：由一个后台任务拥有 SDK 连接与子进程；记录实际协商协议；注册器仅暴露有真实处理器的工具；业务参数与 Host metadata 分离，校验轮次/引用/作用域；显式结构化输出，协议 stdout 不写诊断。
- **验收标准**：测试进程可真实发现/调用/报错；多个轮次复用同一连接；模型参数不能覆盖 Host 身份；伪造/缺失授权上下文被拒；没有把测试探针注册成生产工具，也没有生产路径直接调用工具函数。
- **测试要求**：`python -m pytest tests/unit/test_mcp_context.py tests/integration/test_mcp.py -k 'discovery or context or result' -q --data-dir data`；测试专用工具留在 tests。
- **依赖**：tickets001、tickets002、tickets006、tickets020。
- **不包含**：六个业务工具、自动重连、并发压力结论、远程 HTTP MCP。

<a id="tickets024"></a>

#### tickets024：实现有界、公平的工具调度器

- **状态**：已实施并通过本地开发验收（测试日期 2026-10-22），见 [Agent 验收记录](docs/AGENT_REPORT.md)；真实在线验收归 054，人工 RAG 标签/校准归 050。

- **目标**：100 个提交可以有界排队，慢推理不占满其它工具的执行名额。
- **背景**：对应 F22、§6.1、§5.4，T13/T14，R04/R08。
- **修改范围**：`agent/tool_dispatcher.py`、调度配置、队列/执行指标。
- **具体任务**：实现全局 16 执行名额、128 待执行容量与分类轮转；落实 embedding/rerank 各 1、SQL 4、文件 2、搜索 2 的限制接口；传播排队/工具/整轮 deadline；队列满立即返回错误，取消能移出等待队列。
- **验收标准**：等待分类名额的请求不长期占据全部全局名额；峰值不超过配置；排队时间计入期限；取消/超时后有应用终态；独立的 SQL/文件请求不会被一批慢 RAG 永久饿死。
- **测试要求**：`python -m pytest tests/unit/test_tool_dispatcher.py -q`，用可控时钟/处理器证明公平、队满和期限；不将替身结果当作真实后端性能。
- **依赖**：tickets002、tickets006、tickets020、tickets023。
- **不包含**：单会话轮次调度、缓存合并、真实 100 请求验收或动态自适应限流。

<a id="tickets025"></a>

#### tickets025：实现在途合并、版本缓存和订阅者取消

- **状态**：已实施并通过本地开发验收（测试日期 2026-10-22），见 [Agent 验收记录](docs/AGENT_REPORT.md)；真实在线验收归 054，人工 RAG 标签/校准归 050。

- **目标**：减少重复只读工作，同时不串权限或错误取消共享任务。
- **背景**：对应 F23、§6.3、§5.4，T09/T13，R05。
- **修改范围**：`agent/tool_dedup.py`、缓存键/失效策略、ToolInvocation 合并与缓存字段。
- **具体任务**：按作用域、工具、规范化参数和数据版本构造键；合并同键在途调用；为每个订阅者单独取消和截止；有界保存成功结果，按文件指纹/知识版本/同步水位失效；记录后端执行次数。
- **验收标准**：同作用域重复只执行一次；跨作用域/不同版本不共用；一个消费者取消不影响其它消费者；全部消费者结束才取消可取消底层任务；错误不成为成功缓存；不承诺网络 exactly-once。
- **测试要求**：`python -m pytest tests/unit/test_tool_dedup.py -q`，覆盖取消与完成竞态、版本切换、容量淘汰和瞬时失败。
- **依赖**：tickets002、tickets020、tickets024。
- **不包含**：跨应用分布式缓存、模型回答缓存、网络调用零计费保证。

<a id="tickets026"></a>

#### tickets026：整理有来源的内置资料和固定 RAG 评估集

- **状态**：已实施并通过本地开发验收（测试日期 2026-10-22），见 [Agent 验收记录](docs/AGENT_REPORT.md)；真实在线验收归 054，人工 RAG 标签/校准归 050。

- **目标**：为检索提供可分发、有定位的事实材料和预先定义的评估问题。
- **背景**：对应 F16、§3.5、§8.3 T08/T09、R07/R14。
- **修改范围**：`knowledge/manifest.json`、资料正文、`knowledge/eval.jsonl`、来源/许可记录与结构化规则种子。
- **具体任务**：整理应用操作、格式/编码、FFmpeg 参数和常见错误；记录来源 URL、日期、许可、章节及内容版本；建立至少 20 个有答案和 5 个库外问题，标注期望文档/片段与理由；供人工核对，禁止按检索结果倒填标准答案。
- **验收标准**：每条正文和规则能定位来源；没有整站未知授权复制或私人资料；评估集包含中文同义问法与 libx264/mov_text/-map 等精确标识；无依据问题与有答案问题明确分开；人工未核对的标签如实标为待核对。
- **测试要求**：`python -m pytest tests/unit/test_knowledge_manifest.py -q`，检查字段、来源定位、重复 ID、许可信息和评估覆盖数量；保留人工核对记录供 050 使用。
- **依赖**：tickets001、tickets002。
- **不包含**：向量构建、网页自动抓取器、用户文档自动入库、模型自动评判标签正确性。

<a id="tickets027"></a>

#### tickets027：实现切片、向量构建与活动索引切换

- **状态**：已实施并通过本地开发验收（测试日期 2026-10-22），见 [Agent 验收记录](docs/AGENT_REPORT.md)；真实在线验收归 054，人工 RAG 标签/校准归 050。

- **目标**：可重复构建完整知识版本，查询期间不混用新旧索引。
- **背景**：对应 F16/F17、§3.5、§4.1 KnowledgeChunk，T08/T09。
- **修改范围**：`rag/ingest.py`、`rag/embedding.py`、`rag/index_store.py`、索引 manifest 和构建入口。
- **具体任务**：按真实 tokenizer 和章节切片，落实目标 500–800 token/重叠 80；Ollama 关闭静默截断，校验向量维度与模型 digest；在 Qdrant staging collection 写 dense/原生 BM25 与定位 payload；数量/版本校验完成后切换活动引用。
- **验收标准**：重复同版本构建不增加重复片段；失败/取消不删除当前可用库；不同模型/维度/切片版本拒绝混用；查询取得固定活动版本；中文与编码标识预处理一致。
- **测试要求**：`python -m pytest tests/unit/test_chunking.py tests/integration/test_rag_index.py -q --data-dir data`，使用真实 Ollama/Qdrant，并测试构建中断与版本切换。
- **依赖**：tickets002、tickets006、tickets020、tickets026；已有本地 AI 环境。
- **不包含**：检索排序、独立重排、私人文档导入或边查边删旧库。

<a id="tickets028"></a>

#### tickets028：实现 dense、原生词法召回和 RRF 融合

- **状态**：已实施并通过本地开发验收（测试日期 2026-10-22），见 [Agent 验收记录](docs/AGENT_REPORT.md)；真实在线验收归 054，人工 RAG 标签/校准归 050。

- **目标**：对同一知识版本实际执行两路召回并输出可解释候选。
- **背景**：对应 F17、§3.5、§5.3 rag_search 返回契约，T08/T09。
- **修改范围**：`rag/retrieval.py`、`rag/fusion.py`、召回阶段追踪与候选数据类型。
- **具体任务**：每路默认 20 条，保护中文与精确参数标识；以 chunk_id 去重后 RRF 融合，最多输出 20 个重排候选；携带两个原始排名、融合分数、来源与 knowledge_version；显式报告单路失败和受限状态。
- **验收标准**：真实调用证据能区分两路与融合；精确编码标识和中文查询有可核查候选；活动版本一致；任何一路不可用都不能声称完整检索成功；不安装 rank_bm25 替代方案。
- **测试要求**：`python -m pytest tests/unit/test_rrf.py tests/integration/test_rag_retrieval.py -q --data-dir data`，对照 dense-only/lexical-only/融合结果并保留阶段统计。
- **依赖**：tickets025、tickets027。
- **不包含**：最终答案生成、独立 reranker、最终质量门槛结论。

<a id="tickets029"></a>

#### tickets029：实现独立 CPU 重排进程和完整检索结果

- **状态**：已实施并通过本地开发验收（测试日期 2026-10-22），见 [Agent 验收记录](docs/AGENT_REPORT.md)；真实在线验收归 054，人工 RAG 标签/校准归 050。

- **目标**：完成双路→融合→独立重排→Top5 的正常 RAG 链路。
- **背景**：对应 F17、§3.1/§3.5/§6.1，T08/T09，R08。
- **修改范围**：`rag/reranker_worker.py`、`rag/service.py`、重排进程生命周期与结果 DTO。
- **具体任务**：固定本地 reranker revision，仅在独立 worker 加载 CrossEncoder 与重排依赖；单并发、预热与冷/热耗时；重排后返回前 5 条原文定位及证据不足标记，不能把非空候选自动当有答案；相关性判定规则/门槛可配置并记录依据；取消等待后丢弃迟到结果。
- **验收标准**：GUI/MCP asyncio 线程不执行 CPU 推理；正常响应有两路、融合、重排阶段；模型错误/超时明确返回受限或失败，不静默跳过；worker 崩溃不会损坏索引或其它会话。
- **测试要求**：`python -m pytest tests/integration/test_rag.py -q --data-dir data`，使用真实 CPU 模型并记录内存与冷/热时间，不承诺固定速度。
- **依赖**：tickets006、tickets024、tickets025、tickets028。
- **不包含**：GPU 重排、训练/微调、用纯词法代替独立模型、最终评估报告。

<a id="tickets030"></a>

#### tickets030：实现 MySQL 项目 schema 和可靠同步投影

- **状态**：已实施并通过本地开发验收（测试日期 2026-10-22），见 [Agent 验收记录](docs/AGENT_REPORT.md)；真实在线验收归 054，人工 RAG 标签/校准归 050。

- **目标**：让结构化查询读取真实业务数据，而非空表或仅环境探针数据。
- **背景**：对应 F18、§5.2，T10，R09。
- **修改范围**：`storage/mysql_migrations/`、`storage/mysql_sync.py`、同步状态与项目账号配置；规则/预设/转换记录投影。
- **具体任务**：以有权的初始化连接建立隔离项目库及单独读/同步账号；写入 026 的来源规则；按 SQLite outbox 同步预设和尝试；目标业务 upsert 与 sync_events 同事务，版本保护、水位及补同步。
- **验收标准**：重复事件不重复增行，老事件不覆盖新值；目标提交后才确认本地同步；断网/断库不阻止转换；恢复可补齐；测试只使用自身命名空间，不改现有 MySQL80 或环境探针表。
- **测试要求**：`python -m pytest tests/integration/test_mysql.py -q --data-dir data`，注入提交后未确认、乱序重放和停库。
- **依赖**：tickets004、tickets016、tickets018、tickets026；已有独立 MySQL 环境。
- **不包含**：模型生成 SQL、网页管理后台、消息中间件、MCP 查询工具。

<a id="tickets031"></a>

#### tickets031：通过 MCP 提供三个受限 MySQL 查询工具

- **状态**：已实施并通过本地开发验收（测试日期 2026-10-22），见 [Agent 验收记录](docs/AGENT_REPORT.md)；真实在线验收归 054，人工 RAG 标签/校准归 050。

- **目标**：Agent 可查询规则、预设与历史，但没有任意 SQL 或写库权限。
- **背景**：对应 F18/F21、§5.2/§5.3，T10。
- **修改范围**：`tools/mysql_queries.py`、查询模板、4 连接/线程池、MCP 注册与结果类型。
- **具体任务**：实现 lookup_technical_rules/list_conversion_presets/query_conversion_history；参数化过滤、默认 20 行/最高 100 行及 10 秒期限；每请求借还独立连接/cursor；校验实例/会话授权，返回来源与 freshness。
- **验收标准**：三个工具可经真实 MCP 发现和调用；注入字段不成为 SQL；写/跨库查询被 schema 与数据库双重拒绝；刚完成未同步任务标注滞后，不把查不到当不存在；取消/异常后连接归还。
- **测试要求**：`python -m pytest tests/integration/test_mysql.py -k query -q --data-dir data`，用真实只读账号验证权限和连接池回收。
- **依赖**：tickets020、tickets023、tickets024、tickets025、tickets030。
- **不包含**：任意 SQL 控制台、写工具、修改规则数据、直接回最终答案。

<a id="tickets032"></a>

#### tickets032：通过 MCP 读取已授权 TXT/MD/LOG

- **状态**：已实施并通过本地开发验收（测试日期 2026-10-22），见 [Agent 验收记录](docs/AGENT_REPORT.md)；真实在线验收归 054，人工 RAG 标签/校准归 050。

- **目标**：工具只读取用户明确引用的文本文件，并支持可定位的分段读取。
- **背景**：对应 F19/F21、§5.3、§3.6，T11，R10。
- **修改范围**：`tools/local_files.py`、`tools/text_reader.py`、授权快照读取、文件结果/游标 DTO。
- **具体任务**：实现 read_local_file 的 file_ref_id 输入；打开时核对真实文件身份与授权；处理明确的文本编码策略、字符偏移、20 MiB/20,000 字符限额和下一游标；解析在限量工作单元执行。
- **验收标准**：任意原始路径、越权 ID、文件替换或链接逃逸被拒；文本有偏移定位；截断明确标记并可继续；编码失败不以乱码成功；文档内容不能变成命令或新的文件授权。
- **测试要求**：`python -m pytest tests/unit/test_file_authorization.py tests/integration/test_files.py -k text -q --fixture-root artifacts/fixtures --data-dir data`。
- **依赖**：tickets008、tickets020、tickets023、tickets024、tickets025。
- **不包含**：PDF/DOCX 正文、OCR、执行脚本、任意路径浏览、自动入库。

<a id="tickets033"></a>

#### tickets033：扩展授权文件工具的 PDF/DOCX 解析

- **状态**：已实施并通过本地开发验收（测试日期 2026-10-22），见 [Agent 验收记录](docs/AGENT_REPORT.md)；真实在线验收归 054，人工 RAG 标签/校准归 050。

- **目标**：在相同授权和定位契约下读取两种文档文字。
- **背景**：对应 F19、§5.3、§7.2，T11。
- **修改范围**：`tools/document_worker.py`、PDF/DOCX 解析器、工作进程池和 read_local_file 分发。
- **具体任务**：PDF 按页定位、每次最多 20 页；DOCX 按段落/表格单元顺序定位；限制压缩展开体积、总返回字符及 30 秒期限；隔离损坏解析，返回加密/无文字/超限错误及合法续读游标。
- **验收标准**：正常文档位置可复核；扫描 PDF 不伪装有正文；坏包与压缩超限可终止自身 worker；继续读取不静默漏段；权限和文件变化检查仍在打开时执行。
- **测试要求**：`python -m pytest tests/unit/test_document_limits.py tests/integration/test_files.py -k document -q --fixture-root artifacts/fixtures --data-dir data`，真实 pypdf/python-docx 解析，不使用空成功替代失败。
- **依赖**：tickets006、tickets008、tickets032。
- **不包含**：OCR、DOC/DOCM、宏执行、页面视觉还原、远程附件下载。

<a id="tickets034"></a>

#### tickets034：通过 MCP 封装可核验的网页搜索

- **状态**：已实施并通过本地开发验收（测试日期 2026-10-22），见 [Agent 验收记录](docs/AGENT_REPORT.md)；真实在线验收归 054，人工 RAG 标签/校准归 050。

- **目标**：本地依据不足时具备受控、可追踪的真实搜索入口。
- **背景**：对应 F20/F21、§5.3、§3.6，T12，R10/R11。
- **修改范围**：`tools/web_search.py`、DeepSeek Search 适配器、查询脱敏与来源 DTO。
- **具体任务**：按官方独立 Search 接口封装 query/count，数量限制 1–5；过滤已知私密路径/凭据和整份日志；返回真实标题、链接、摘要和时间；落实搜索 2 并发、20 秒期限与统一错误。
- **验收标准**：只返回供应商真实结果；空结果和失败可区分；认证失败不循环重试；MCP 路径与追踪完整；没有无提示调用 Fetch 或浏览器抓取；生产请求不携带本地全文。
- **测试要求**：`python -m pytest tests/unit/test_web_search.py -q`，模拟并标明 401/429/空结果/不完整来源；真实结果和链接核验归 054。
- **依赖**：tickets002、tickets021、tickets023、tickets024、tickets025。
- **不包含**：搜索触发决策、网页抓取器、最终格式建议或模型内置搜索绕过 MCP。

<a id="tickets035"></a>

#### tickets035：接入 RAG MCP 工具并锁定六工具目录

- **状态**：已实施并通过本地开发验收（测试日期 2026-10-22），见 [Agent 验收记录](docs/AGENT_REPORT.md)；真实在线验收归 054，人工 RAG 标签/校准归 050。

- **目标**：四类职责对应的六个工具均能通过统一真实协议路径调用。
- **背景**：对应 F17/F21/F24、§5.3/§5.4，T09/T13。
- **修改范围**：`tools/rag_search.py`、生产工具注册表、Host 业务 schema 导出与集成测试。
- **具体任务**：将完整 RAG service 接入 rag_search，限制 top_k 为 1–5；合并已实现的三个 SQL、一个文件和一个搜索入口；校验 discover schema 与模型业务 schema 同源；依赖缺失返回明确状态，不能消失或假成功。
- **验收标准**：发现目录恰好包含六个既定工具；rag_search 结果有来源/knowledge_version/阶段记录；无模型答案混入工具；正常 UI/Agent 只能走 MCP；各工具错误 envelope 与协议错误可区分。
- **测试要求**：`python -m pytest tests/integration/test_mcp.py -k catalog -q --data-dir data`，真实调用本地四类中的可离线部分；搜索替身仅用于 schema 检查，在线验收留到 054。
- **依赖**：tickets023、tickets029、tickets031、tickets033、tickets034。
- **不包含**：第七个泛用工具、任意 shell、直接工具调用捷径、Agent 问答循环。

<a id="tickets036"></a>

#### tickets036：实现有界多轮 Agent 与模型到 MCP 的桥接

- **状态**：已实施并通过本地开发验收（测试日期 2026-10-22），见 [Agent 验收记录](docs/AGENT_REPORT.md)；真实在线验收归 054，人工 RAG 标签/校准归 050。

- **目标**：保存的会话能执行“模型→工具→回传→回答”，且同会话串行、不同会话可并行。
- **背景**：对应 F13/F14/F20/F21/F22/F23、§3.6、§6.1/§6.3，T07/T12。
- **修改范围**：`agent/service.py`、`agent/turn_runner.py`、轮次状态和模型工具消息配对。
- **具体任务**：限制在线轮次 5/每会话 1；按 provider_call_id 配对工具结果，独立分支最多 4；落实每轮 8 次模型往返、16 次工具调用和 300 秒总期限；依据不足/冲突时自动经 MCP 搜索，充分时不额外搜索；统一持久化终态与实际 usage。
- **验收标准**：乱序返回不串调用；模型不能改可信作用域；资料中指令不提升权限；重复工具无新证据计入预算并复用已知结果；达限给部分完成说明；基本转换操作不受 Agent 服务失败影响。
- **测试要求**：`python -m pytest tests/unit/test_agent_turn.py tests/integration/test_agent_mcp.py -q --data-dir data`，供应商使用标明替身、本地 MCP 为真实进程；真实多轮交给 054。
- **依赖**：tickets020、tickets022、tickets024、tickets025、tickets035。
- **不包含**：超长上下文压缩、UI、Agent 自动转换/取消、执行检查点恢复。

<a id="tickets037"></a>

#### tickets037：实现上下文预算和可追溯历史压缩

- **状态**：已实施并通过本地开发验收（测试日期 2026-10-22），见 [Agent 验收记录](docs/AGENT_REPORT.md)；真实在线验收归 054，人工 RAG 标签/校准归 050。

- **目标**：多轮追问可继续，同时保持系统约束、引用和工具配对完整。
- **背景**：对应 F13/F14、§3.6 上下文预算、§4.1 Message，T07。
- **修改范围**：`agent/context_builder.py`、历史摘要存储与预算统计；模型请求构建接线。
- **具体任务**：落实 32k 输入预算及 8k 可见输出连同推理上限的配置；保留当前引用/最近消息/完整调用结果对；对旧历史生成带消息定位的摘要，原记录不删除；明确 token 计数或保守估算方式，并用供应商 usage 核对偏差。
- **验收标准**：不拆开函数调用与结果，不把失败摘要成成功；预算不足有可解释终态；摘要失败不删除历史；必要的 provider_items 不被一刀切清除；压缩消耗计入轮次预算和 usage。
- **测试要求**：`python -m pytest tests/unit/test_context_budget.py -q`，覆盖长中文、连续工具对、摘要失败、旧失败记录及超预算输入；真实长度能力只按 054 测得结果声明。
- **依赖**：tickets020、tickets022、tickets036。
- **不包含**：无限上下文承诺、自动恢复中断步骤、跨会话共享摘要。

<a id="tickets038"></a>

#### tickets038：实现 Agent 侧栏、浮动窗口和来源展示

- **状态**：已实施并通过本地开发验收（测试日期 2026-10-22），见 [Agent 验收记录](docs/AGENT_REPORT.md)；真实在线验收归 054，人工 RAG 标签/校准归 050。

- **目标**：用户能在桌面里问答、查历史和看依据，展开窗口不会重复请求。
- **背景**：对应 F12/F13/F24、§1.3、§3.6/§3.7，T06/T07。
- **修改范围**：`ui/agent_panel.py`、会话列表、消息/工具摘要/来源视图、停靠/浮动操作。
- **具体任务**：绑定同一 AgentService 与会话模型；发送时展示固定引用；显示流式文字、排队/执行状态和停止回答；支持历史切换、展开/收回/关闭浮动视图；来源可定位文档、任务或真实网页。
- **验收标准**：展开、收回或关闭浮窗不重新 submit、不取消正在回答；显式停止才取消；选中视频变化不偷换引用；错误/中断有重试入口；转换进度在主窗口继续可见。
- **测试要求**：`python -m pytest tests/gui/test_agent_panel.py -q`，断言 submit 调用次数、共享消息状态、引用固定和窗口生命周期；不以模拟回答作为真实供应商证据。
- **依赖**：tickets005、tickets006、tickets019、tickets020、tickets036、tickets037。
- **不包含**：建议应用按钮、独立第二套聊天状态、诊断文件导出。

<a id="tickets039"></a>

#### tickets039：实现结构化参数建议、差异预览和确认应用

- **状态**：已实施并通过本地开发验收（测试日期 2026-10-22），见 [Agent 验收记录](docs/AGENT_REPORT.md)；真实在线验收归 054，人工 RAG 标签/校准归 050。

- **目标**：Agent 只能提出可校验的设置变更，由用户确认后用于下一批转换。
- **背景**：对应 F15、§3.6、§4.1 SettingsProposal、§5.1，T07，R02。
- **修改范围**：`agent/settings_proposals.py`、`ui/settings_diff.py`、设置验证/应用服务和建议仓储。
- **具体任务**：将模型建议转成白名单 patch，拒绝任意命令/授权/API 配置/任务操作；展示旧值、新值、理由、来源与影响批次；用 base_settings_version 做冲突检查；以 proposal_id 防重复确认并重新兼容性校验。
- **验收标准**：确认前设置完全不变；拒绝/过期/非法建议不生效；双击确认只应用一次；当前运行计划不变；应用后仍需用户主动开始转换，必要的轨道确认不能绕过。
- **测试要求**：`python -m pytest tests/unit/test_settings_proposals.py tests/gui/test_proposal_confirmation.py -q`，覆盖版本冲突、重复确认、运行中批次、模型额外字段及非法值。
- **依赖**：tickets012、tickets014、tickets016、tickets020、tickets036、tickets038。
- **不包含**：Agent 自动执行 FFmpeg、自动取消任务、任意设置字典覆盖。

### 11.5 边界：tickets040–047

<a id="tickets040"></a>

#### tickets040：验证文件系统故障和输出保护边界

- **状态**：已完成本机开发验收（测试日期 2026-10-22、结果收取确认 2026-10-23），9 项新增场景及相关回归共 46 passed，见 [文件系统边界记录](docs/FILESYSTEM_REPORT.md)。

- **目标**：证明转换面对路径与磁盘异常时仍保护原件、现有输出和其它任务。
- **背景**：对应 F02/F07/F09、§3.4、§7.1 R03，T03/T04。
- **修改范围**：导入/路径/提交模块的必要修复、隔离文件系统故障夹具与回归测试。
- **具体任务**：测试只读目录、输出被抢占、磁盘不足注入、源移动/替换、大小写等价、中文/特殊/长路径与链接；覆盖提交前后中断和重复取消；记录实际 Windows 长路径配置，不宣称所有路径可用。
- **验收标准**：源与旧结果哈希不变；失败原因和受影响项明确；没有越界创建/清理；不支持路径可解释失败；故障样本后仍能成功转换正常样本。
- **测试要求**：`python -m pytest tests/integration/test_filesystem_faults.py -q --fixture-root artifacts/fixtures --data-dir data`；磁盘不足用隔离写入失败注入，不填满用户磁盘。
- **依赖**：tickets009、tickets013、tickets017、tickets019。
- **不包含**：修复系统权限、改变全局长路径策略、访问个人测试目录、网络文件系统全兼容承诺。

<a id="tickets041"></a>

#### tickets041：验证媒体轨道、旋转、VFR 和输出完整性

- **状态**：开发及自动媒体检查完成；真人播放核对待补，未把自动解码/声画标记等同于人工观看听辨。见 [本轮记录](docs/BOUNDARY_REPORT.md)。

- **目标**：让真实输出与确认计划一致，特殊媒体不产生静默损失。
- **背景**：对应 F03–F06/F08、§3.4、§7.2，T01/T02/T05，R02。
- **修改范围**：探测/规划/输出验证的必要修复、媒体回归样本与检查器。
- **具体任务**：真实转换无音频、双音轨、兼容/不兼容字幕、旋转、VFR、超短和多主视频轨；验证语言/default 标志；检查尺寸、编码、流数、时长及合成声画标记；明确超出首版色彩/轨道支持范围的结果。
- **验收标准**：三种目标均有可解码输出；未确认丢轨不生成输出；旋转只应用一次，默认不强制 CFR；时长误差目标 ≤max(0.25 秒,2 帧)，合成声画标记偏差目标 ≤100ms；人工播放核对并如实记录。
- **测试要求**：`python -m pytest tests/integration/test_media_edges.py -q --fixture-root artifacts/fixtures --data-dir data`；短样本完整解码，报告自动检查与人工播放分别完成哪些项。
- **依赖**：tickets008、tickets010、tickets011、tickets014、tickets016、tickets019。
- **不包含**：HDR/Dolby Vision 自动映射、视频编辑、多主视频轨选择、擅自降低已确认的保轨标准。

<a id="tickets042"></a>

#### tickets042：实现 MCP 故障终结、单拥有者重连和退出清理

- **状态**：已实现并完成本地故障检查，包括真实工具进程杀停、并发重连、取消与协议错误策略；见 [本轮记录](docs/BOUNDARY_REPORT.md)。

- **目标**：工具子进程故障不造成永久等待、聊天丢失或重连风暴。
- **背景**：对应 F21/F22、§6.2/§6.3，T13，R06。
- **修改范围**：`mcp_client.py` 连接状态、重连协调器、调用失败归档与应用关闭接线。
- **具体任务**：进程崩溃时终结在途等待并记录未知/中断；由一个拥有者重建连接；只读工具在剩余 deadline 内最多重试一次；保留原 conversation/turn 与调用对应关系；不等待新协议取消后的虚构响应。
- **验收标准**：五个并发轮次故障时只有一次重连流程；故障请求均有应用终态；新请求重连后能成功；聊天历史不重建/清空；退出只结束自己拥有的工具进程，不重放部分流式模型请求。
- **测试要求**：`python -m pytest tests/integration/test_mcp_recovery.py tests/unit/test_mcp_client_policy.py -q --data-dir data`，真实杀停测试工具子进程，覆盖重连期间取消、协议不兼容、退出及无取消回复。
- **依赖**：tickets023、tickets024、tickets025、tickets035、tickets036。
- **不包含**：HTTP session 404 恢复、远程旧协议兼容、恢复中断执行检查点、无限自动重试。

<a id="tickets043"></a>

#### tickets043：验证 Agent 错误、取消竞态和资料注入边界

- **状态**：本地失败/取消/注入边界完成，供应商响应使用明确测试替身；真实在线验收仍归 054。见 [本轮记录](docs/BOUNDARY_REPORT.md)。

- **目标**：问答失败时保留可靠历史与权限，不误操作或误回写。
- **背景**：对应 F13–F15/F19/F20/F22/F23、§3.6/§5.4/§6.3，T07/T11/T12/T13。
- **修改范围**：轮次错误策略、在线配置可用状态、迟到事件过滤和安全回归测试。
- **具体任务**：覆盖 401/余额不足/429/断网/总期限、模型反复调用、同会话排队取消、多个订阅者取消；用文件/网页/日志注入“改权限/执行命令/读其它文件”；确保切换配置后能重新测试，不无条件重播已输出内容。
- **验收标准**：确定性错误不重试；瞬时只读调用最多一次重试且受总期限限制；取消后迟到回答/建议不能回写；其它会话与转换继续；资料不提升权限，未知事实如实说明；用量缺失不补造。
- **测试要求**：`python -m pytest tests/unit/test_agent_failure_policy.py tests/integration/test_agent_isolation.py -q --data-dir data`，标明模拟外部错误与真实本地 MCP 部分；真实认证/搜索归 054。
- **依赖**：tickets022、tickets025、tickets032、tickets033、tickets034、tickets036、tickets037、tickets039、tickets042。
- **不包含**：额外攻击执行工具、替用户处理余额或账号、把模拟故障报告称为供应商真实压力。

<a id="tickets044"></a>

#### tickets044：实现依赖健康检查与私有服务生命周期

- **状态**：实际本地健康检查、独立数据库初始化和所属进程清理完成；见 [本轮记录](docs/BOUNDARY_REPORT.md)。

- **目标**：应用能判断本地 AI 是否真正可用，并只管理自己启动的服务。
- **背景**：对应 F11/F22、§3.7、§5.1 SetupService，T06/T15，R12。
- **修改范围**：`services/health.py`、`services/process_manager.py`、服务/数据目录配置、`devtools doctor`。
- **具体任务**：区分外部复用/应用私有进程并记录路径、启动身份和端口；检查真实向量、双路检索、重排、SQL 权限与授权文件读取；实现 `doctor --require all-local` 结构化报告；支持独立 MySQL 数据目录和账号初始化，不重置现有库。
- **验收标准**：端口可连不等于健康；端口冲突不会结束他人进程；MySQL 监控/监听进程被正确识别；模型/SDK/协议/索引版本可见；关闭应用只清理所属资源；本地检查不偷偷访问在线模型。
- **测试要求**：`python -m pytest tests/unit/test_service_ownership.py tests/integration/test_local_doctor.py -q --data-dir data`；`python -m media_converter.devtools doctor --require all-local --data-dir data --output artifacts/reports/doctor-local.json`。
- **依赖**：tickets007、tickets020、tickets021、tickets027、tickets029、tickets030、tickets035、tickets042。
- **不包含**：下载器、向导页面、系统服务安装、自动升级或重置外部 MySQL root。

<a id="tickets045"></a>

#### tickets045：实现可恢复下载、校验和组件准备

- **状态**：下载/安装/私有准备开发闭环完成；官方原生归档和真实模型服务已验证。049 可发布 AI 运行包尚不存在时明确报缺失，完整分发与干净机演练归 048/049/053。见 [本轮记录](docs/BOUNDARY_REPORT.md)。

- **目标**：从无 AI 组件到本地可检查状态的准备过程可取消、重试和复用。
- **背景**：对应 F11、§3.7、§8.2C/D，T06/T15，R12/R14。
- **修改范围**：`services/component_manifest.py`、`services/downloads.py`、`services/preparer.py`；完成 `prepare --components core/ai`。
- **具体任务**：定义来源/版本/哈希/大小/许可与安装标记；优先复用已验证组件，再准备私有 Ollama/Qdrant/MySQL/模型/工具组件与 tokenizer；`.partial` 续传和哈希后提交；验证解压路径、链接及展开限额；传递进度和可恢复错误。
- **验收标准**：同版本已就绪不重复下载；错误哈希不安装；取消保留可续传状态但不伪装成功；压缩路径逃逸被拒；不会向 C 盘用户目录落模型/临时产物；使用者不需要 pip 或编译器。049 尚无组件产物时明确缺失，不返回假完成。
- **测试要求**：`python -m pytest tests/unit/test_component_downloads.py tests/integration/test_component_prepare.py tests/integration/test_mysql_archive_prepare.py -q --data-dir data`，本地受控 HTTP 测断点/损坏/取消，另用真实官方组件验证；最终整套离线/在线准备归 053。
- **依赖**：tickets002、tickets006、tickets021、tickets026、tickets027、tickets044。
- **不包含**：下载无校验第三方镜像、擅自换服务/模型、创建长期托管后台、要求评审安装开发环境。

<a id="tickets046"></a>

#### tickets046：实现首次 AI 准备向导和降级入口

- **状态**：向导、降级、取消/重试/重开、接入配置与基本转换接线完成；无可选 AI 包的启动另有真实 GUI 进程检查。见 [本轮记录](docs/BOUNDARY_REPORT.md)。

- **目标**：用户知道缺什么、准备到哪一步、失败后怎么继续，同时始终能基本转换。
- **背景**：对应 F11/F14、§1.3 步骤 6、§3.7，T06/T15。
- **修改范围**：`ui/setup_wizard.py`、组件状态模型、配置页与 SetupService 接线。
- **具体任务**：先检查再让用户复用/准备私有组件；展示空间、来源、下载/校验/启动/模型/索引阶段；接入 API 配置/连接测试；准备中可取消/重试，重开恢复已完成步骤；解释单个依赖影响的能力。
- **验收标准**：AI 缺失、服务拒绝或 Key 无效时仍能导入/转换；端口冲突和磁盘空间问题有可操作提示；仅真实健康检查通过才显示就绪；不把内部协议细节堆进主要使用流程；不会因重开页面重复启动服务。
- **测试要求**：`python -m pytest tests/gui/test_setup_wizard.py -q --data-dir data`，覆盖空环境、部分就绪、失败重试与基本转换并行；完整无开发环境路径由 053 演练。
- **依赖**：tickets019、tickets021、tickets022、tickets038、tickets044、tickets045。
- **不包含**：账号/计费/临时 Key 发放平台、自动更新、Windows 系统设置向导。

<a id="tickets047"></a>

#### tickets047：完成桌面交互回归和脱敏诊断导出

- **状态**：三档实际 Windows Qt 缩放/键盘/浮动操作、工具摘要和诊断导出完成；报告与截图见 [本轮记录](docs/BOUNDARY_REPORT.md)。不替代其它设备与真人媒体播放验收。

- **目标**：主路径清楚可操作，发生错误时用户可导出安全、可定位的诊断。
- **背景**：对应 F01/F12/F24、§5.4、§8.3 T06/T16，R04/R16。
- **修改范围**：主窗口/Agent/向导的布局与焦点必要修复、`services/diagnostics.py`、诊断查看/导出动作。
- **具体任务**：验证三档缩放、键盘、空态、处理中/错误/中断状态和浮动收回；展示工具摘要与 trace；导出白名单日志/版本/匿名化上下文，排除密钥、数据库、原文和私人视频；退出按既定语义保存和取消所属任务。
- **验收标准**：关键操作不遮挡，禁用/焦点状态一致；看得懂下一步和失败原因；测试哨兵凭据/完整私有路径不出现在导出物；关闭视图不误取消；应用退出无所属转换/工具进程残留。
- **测试要求**：`python -m pytest tests/gui/test_desktop_acceptance.py tests/unit/test_diagnostics_export.py -q`；人工完成 T06 三档截图与键盘检查，记录实测；UI 压力响应由 052 度量。
- **依赖**：tickets002、tickets019、tickets038、tickets039、tickets042、tickets043、tickets046。
- **不包含**：监控云平台、远程上传诊断、重做框架/视觉选型、用截图替代真实操作。

### 11.6 收尾：tickets048–056

<a id="tickets048"></a>

#### tickets048：构建独立可运行的 Windows 基础便携包

- **目标**：无开发机 Python/FFmpeg PATH 时仍能完成转换。
- **背景**：对应 F25、§3.7、§8.2H、§9.1，T15，R01/R14。
- **修改范围**：`packaging/core.spec`、`devtools/build_windows.py`、`devtools/smoke_package.py`、基础 ZIP 与第三方清单。
- **具体任务**：固定 PyInstaller onedir 配置，收集 Qt/Python/FFmpeg/ffprobe 与许可；隔离构建 PATH 防 ICU 污染；排除非核心大模型运行库；实现 `build-windows --components core` 和 `smoke-package --without-dev-path`，记录版本/源码标识/哈希。
- **验收标准**：`MediaConverter-Windows-x64.zip` 可在新目录解压并导入/转换/校验；不含 Key、数据库或开发绝对路径；缺 AI 时显示引导而不是导入 Torch 失败；Qt Windows 插件可加载；缺许可项不能标记可发布。
- **测试要求**：`python -m media_converter.devtools build-windows --components core --data-dir data --output dist`；`python -m media_converter.devtools smoke-package --package dist/MediaConverter-Windows-x64.zip --without-dev-path --output artifacts/reports/package-smoke.json`。
- **依赖**：tickets001、tickets007、tickets019、tickets039、tickets046、tickets047。
- **不包含**：已验证干净 Windows 的声明、AI 运行库打包、代码签名/商店上架/自动更新。

<a id="tickets049"></a>

#### tickets049：构建 AI 工具组件包并接通准备清单

- **目标**：普通使用者能取得自带 Python/依赖的工具与重排运行时，无需安装开发工具。
- **背景**：对应 F11/F25、§3.2/§3.7、§8.2H、§9.1，T15，R12/R14。
- **修改范围**：`packaging/tools.spec`、AI worker 启动入口、分包 manifest、build-windows 完整构建与 prepare 接线。
- **具体任务**：打包 MCP 工具/解析/CPU 重排依赖；模型和原生服务按已校验清单独立准备，不塞进基础包；消除 worker 对开发路径和私密配置的依赖；支持相邻组件 ZIP 或清单中的发布来源；默认完整构建同时生成基础与组件产物。
- **验收标准**：新数据目录能启动打包 worker、发现六工具，并用真实本地组件检索；大模型缺失显示准备状态；每个组件有版本/哈希/许可/来源；缺失或损坏组件不会冒充完整 AI；不依赖 `D:\miniconda`、项目 venv 或开发显卡运行库。
- **测试要求**：`python -m media_converter.devtools build-windows --data-dir data --output dist`；`python -m pytest tests/integration/test_ai_package.py -q --data-dir data`，用打包后 exe 真实执行，不调用源码入口代替。
- **依赖**：tickets027、tickets029、tickets035、tickets044、tickets045、tickets048。
- **不包含**：托管模型服务、捆绑评审 API Key、把本机已有 MySQL 当作评审必备前提。

<a id="tickets050"></a>

#### tickets050：执行固定 RAG 质量评估和检索消融对照

- **目标**：用人工核对的来源答案验证检索质量，保留不达标证据。
- **背景**：对应 F16/F17、§8.2F、§8.3 T08/T09，R07。
- **修改范围**：`devtools/eval_rag.py`、评估报告生成；仅在定位失败后修复切片/检索实现并保留变更记录。
- **具体任务**：冻结 026 的人工核对数据版本；分别运行 dense/词法/混合/混合+重排；记录逐题候选、期望来源命中、冷/热时间与版本；库外 5 题关闭搜索评估本地边界，不靠模型自评分。
- **验收标准**：完整链最终 Top5 至少命中 17/20；人工核对 5 个库外案例的候选与证据不足标记，不能因为 Top5 非空就判有依据；正常结果都有双路和重排证据；重复构建/版本切换通过；不在冻结评估集上反复调门槛再报同集泛化收益；未核对或未达标不能记完成。
- **测试要求**：`python -m media_converter.devtools eval-rag --dataset knowledge/eval.jsonl --data-dir data --output artifacts/reports/rag-eval.json`；`python -m pytest tests/integration/test_rag_evaluation.py -q --data-dir data`。
- **依赖**：tickets026、tickets027、tickets028、tickets029、tickets035。
- **不包含**：按结果修改标准答案、无依据提高命中率、训练模型或把网页搜索结果计入本地得分。

<a id="tickets051"></a>

#### tickets051：执行真实 MCP 100 请求压力与故障验收

- **目标**：证明真实工具链在既定负载下有界、隔离、可取消并可恢复。
- **背景**：对应 F21–F24、§6、§8.2E、§8.3 T13，R05/R06/R08。
- **修改范围**：`devtools/bench_mcp.py`、压力/故障驱动、资源采样与 JSON 报告。
- **具体任务**：提交屏障后同一连接每轮 100 请求，共 3 轮；按 40 RAG/30 MySQL/30 文件及约 20% 同作用域重复输入运行预热真实短资料；单列队满/超时/取消/单订阅取消/进程重启故障。队满注入可用独立较小容量，必须记录覆盖值并恢复，不能污染正常指标。
- **验收标准**：正常三轮全部成功且零串线/悬挂；队列/分类/全局峰值不超过配置；故障请求都有应用终态且恢复后新请求成功；报告提交/准入/执行/合并/重试/重连、结果分类、p50/p95、CPU/内存。正常失败不能改称故障通过。
- **测试要求**：执行 §8.2E 两条 bench-mcp 命令；`python -m pytest tests/integration/test_mcp_load_report.py -q --data-dir data` 校验报告计数守恒及终态，不用探针替代真实后端。
- **依赖**：tickets024、tickets025、tickets029、tickets031、tickets033、tickets035、tickets042、tickets043、tickets044。
- **不包含**：100 个推理同时运行的承诺、真实搜索服务大规模压测、用缓存命中冒充实际后端执行数。

<a id="tickets052"></a>

#### tickets052：完成约定视频压力与 GUI 响应性验收

- **目标**：验证长视频、4K 和批量队列与 AI 同时工作时仍可操作。
- **背景**：对应 F01/F04/F08/F09/F22、§8.2G、§8.3 T14，R04/R08。
- **修改范围**：`devtools/fixtures.py` pressure 配置、`devtools/bench_video.py`、Qt 心跳/资源采样与报告。
- **具体任务**：生成并记录 30 分钟 1080p、1 分钟 3840×2160、50 短视频；长视频用 MP4/H.264 基线，完整队列与本地 AI 同时工作；采样 UI 定时器、取消状态、FFmpeg 停止耗时、资源和总耗时；区分合成/循环素材与真实复杂度。
- **验收标准**：转换并发仍为 1；无丢任务/假成功；UI p95 采样间隔目标 ≤200ms、最长无响应 ≤1 秒；取消状态更新目标 ≤1 秒，所属 FFmpeg 停止目标 ≤5 秒；全部记录实测，超标修复后复测，不降低样本规模。
- **测试要求**：执行 §8.2G 两条 fixtures/bench-video 命令；`python -m pytest tests/integration/test_video_pressure_report.py -q --data-dir data`；压力视频仅存 artifacts，不提交大文件。
- **依赖**：tickets008、tickets011、tickets016、tickets017、tickets019、tickets029、tickets036、tickets047。
- **不包含**：硬件编码优化、并行转码、所有素材实时处理承诺、以视频时长冒充转码性能。

<a id="tickets053"></a>

#### tickets053：在干净 Windows 演练便携包与离线 AI 准备

- **目标**：检验评审从下载包开始的转换与本地 AI 准备路径，为一次性在线窗口做好预置。
- **背景**：对应 F11/F25、§3.7、§8.2H/§8.4，T15，R12/R13。
- **修改范围**：干净环境演练说明、执行记录/录屏、必要缺陷修复及对应包重建。
- **具体任务**：按当前源码重建 048/049 产物；在未装开发 Python/FFmpeg 的 Windows VM/独立机使用新数据目录；实际完成解压、五类输入、转换和本地 AI 组件/索引准备；从打包工具入口验证本地检索、SQL、文件读取，不以开发机服务代替；记录下载/空间/冷热时间和系统配置。
- **验收标准**：基本转换无需开发工具；AI 本地后端从未准备状态按引导可用，不靠开发机已有模型/数据库；已有外部服务不被破坏；说明包、源码标识和测试机器；无干净资源则 blocked，不能以 PATH 隔离替代。本票只收口 T15 离线部分，真实在线问答仍须 054 完成。
- **测试要求**：重跑 smoke-package；按 T15 离线清单人工实机操作并保存证据，不索取或消耗 API Key；修复后重建并复查受影响场景，不复用旧包结果。
- **依赖**：tickets040、tickets041、tickets046、tickets047、tickets048、tickets049、tickets050、tickets051、tickets052；外部条件为干净 Windows 资源。
- **不包含**：未经测试的所有 Windows 支持声明、宿主系统重装、购买云机器或启动付费资源的默认授权。

<a id="tickets054"></a>

#### tickets054：完成真实 API、多会话问答和自动搜索验收

- **目标**：使用有效接入实际验证模型、工具、历史与参数建议的完整链。
- **背景**：对应 F12–F15/F18–F23、§8.2F、§8.3 T07/T12。
- **修改范围**：`tests/live_api/`、`devtools/bench_agent.py`、真实用例/问答轨迹报告。
- **具体任务**：待长视频压力、包和干净机离线准备完成后再启用 Key；显式 `--live-api`，用 5 会话各 3 轮实际问答验证固定引用、真工具、乱序配对、重启追问和确认建议；在干净 Windows 包中另走含工具问答→确认建议→重启追问路径，收口 T15 在线部分；安排本地充分/不足/冲突案例，不足时真实搜索并核验链接；标明真实与注入的错误测试。
- **验收标准**：保留真实供应商 15 轮、返回模型标识、usage 和 MCP 轨迹，零串线；无确认不改设置、运行快照不变；本地充分不无故搜索；失败不编链接；无 Key/到期时标 blocked，不替换模型或悄悄改 mock。临时有效期以提供方撤销/响应为据。
- **测试要求**：`python -m pytest tests/live_api -q --strict-markers --live-api --data-dir data --junitxml artifacts/reports/live-api.xml`；执行 §8.2F 的 bench-agent 命令；凭据仅从安全配置读取。
- **依赖**：tickets022、tickets031、tickets034、tickets036、tickets037、tickets038、tickets039、tickets043、tickets046、tickets050、tickets052、tickets053；外部条件为有效 API Key。
- **不包含**：提前索要或消耗一小时 Key、把客户端倒计时作为到期证明、费用估算冒充实际 usage、完整应用未过时宣称 Agent 已交付。

<a id="tickets055"></a>

#### tickets055：整理可复现交付文档、测试总表和演示材料

- **目标**：评审能照 README 使用，并能核对需求、决策和真实结果。
- **背景**：对应 F24/F25、§8.4、§9.1，T16，R14/R16。
- **修改范围**：`README.md`、`docs/TEST_REPORT.md`、`docs/SESSION_SUMMARY.md`、第三方许可/来源/已知限制清单与可分享演示。
- **具体任务**：写普通使用者的下载/启动/转换/API 替换/本地准备/排障步骤；按 F01–F25 和 T01–T16 汇总结果、命令、源码标识和证据；补齐用户反馈/实际决策/失败修复；核验许可，脱敏截图、录屏和诊断，列出 blocked 项。
- **验收标准**：按 README 从空数据目录复走步骤；没有虚构成功、URL、基准提升或人工 review；没有真实 Key/私人视频/口令；许可未确定的组件不进入待发布包；文档与当前可用命令、文件名和实际包一致。
- **测试要求**：`python -m pytest tests/unit/test_delivery_manifest.py -q` 校验本地链接、必备清单和凭据哨兵；人工复核 README 与演示、T/F 总表及第三方声明。
- **依赖**：tickets047、tickets048、tickets049、tickets050、tickets051、tickets052、tickets053、tickets054。
- **不包含**：美化未实现功能、伪造逐字需求对话、发布 GitHub 或代发 HR 消息。

<a id="tickets056"></a>

#### tickets056：提交 GitHub 并发布经过核验的交付产物

- **目标**：取得用户可提交给 HR 的真实项目和下载链接。
- **背景**：对应 F25、§8.4、§9.1，T16，R14/R16。
- **修改范围**：本地 Git/远程配置、提交/tag、GitHub 仓库/Release、校验文件与最终链接记录。
- **具体任务**：先检查现有 GitHub 登录/remote，仍不明确时确认目标账号与仓库名；扫描源码、历史和产物，不上传 environment/模型/数据库/私人视频；绑定最终源码提交与已测源码清单，必要时重建并冒烟；发布公开仓库、基础 ZIP、AI 组件及真实 SHA-256 清单；更新组件下载来源后验证可获取。
- **验收标准**：远程源码可访问，Release 附件可下载且哈希一致；下载基础包能做真实转换，组件清单不指向本机路径或不存在资产；记录实际 commit/tag/URL；F/T 总表仍有必做项 blocked/failed 时不能标记完整交付或伪造成功发布。
- **测试要求**：发布前复查 §8.4 门槛及秘密扫描；对实际下载的 Release 包执行 smoke-package 并核验 SHA-256；用可访问状态验证仓库与附件链接，保留失败信息。
- **依赖**：tickets048、tickets049、tickets050、tickets051、tickets052、tickets053、tickets054、tickets055；外部条件为目标账号权限及可发布许可清单。
- **不包含**：向 HR/招聘平台发送消息、修改用户其它仓库、推送真实 Key、把无权限/失败状态写成已发布。

### 11.7 功能与验收覆盖索引

主责票负责实现，回归/收尾票负责补充场景和证据；下表不将重复覆盖算作重复开发。

| Spec 功能 | 主责及集成 tickets |
|---|---|
| F01 桌面操作 | 005、006、019、047、052 |
| F02 导入 | 003、009、019、040 |
| F03 元数据 | 007、010、019、041 |
| F04 缩略图 | 011、019、052 |
| F05 输出参数 | 012、014、019、041 |
| F06 保留轨道与确认 | 014、019、041 |
| F07 保存与保护原件 | 013、019、040 |
| F08 顺序批次与进度 | 003、004、015、016、019、052 |
| F09 取消/重试 | 017、019、040、052 |
| F10 预设/恢复/打开位置 | 004、018、019 |
| F11 首次准备 | 007、044、045、046、049、053 |
| F12 AI 视图 | 005、038、047 |
| F13 多轮与历史 | 020、036、037、038、043、054 |
| F14 模型配置与问答 | 021、022、036、037、046、054 |
| F15 建议确认 | 039、043、054 |
| F16 内置资料与索引 | 026、027、050 |
| F17 混合检索与重排 | 027、028、029、035、050 |
| F18 MySQL | 004、030、031、044、054 |
| F19 本地文字 | 020、032、033、043 |
| F20 自动搜索 | 034、036、043、054 |
| F21 MCP | 023、031、032、033、034、035、036、042、051 |
| F22 并发与恢复 | 006、024、029、036、042、043、044、051、052 |
| F23 去重与预算 | 025、036、039、043、051 |
| F24 观测与异常 | 002、023、024、035、038、043、047、055 |
| F25 构建与交付 | 001、048、049、053、055、056 |

| Spec 验收 | 负责汇总证据的 tickets | 前序票提供的结果 |
|---|---|---|
| T01 | 019、041、052 | 008–011 素材、导入、探测、图片 |
| T02 | 019、041 | 012、014–016 参数/计划/输出 |
| T03 | 040 | 009、013 路径与保护 |
| T04 | 040、052 | 015–017 状态、顺序、取消/重试 |
| T05 | 041 | 016、018 完整性与恢复 |
| T06 | 047、053 | 005、038、044–046 视图与准备 |
| T07 | 054 | 020–022、036–039、043 历史/桥接/建议 |
| T08 | 050 | 026–029、035 资料与完整检索 |
| T09 | 050 | 025、027–029 版本/去重/各阶段 |
| T10 | 030、031、051 | 004 事务事件与本地记录 |
| T11 | 032、033、043 | 008、020 文档样本与授权 |
| T12 | 054 | 021、022、034、036、043 在线错误与触发 |
| T13 | 051 | 023–025、035、042、043 调度与恢复 |
| T14 | 052 | 006、011、016、017、024、029 后台与限额 |
| T15 | 053、054 | 044–049 准备、向导和包；053 收离线部分，054 收真实问答部分 |
| T16 | 055、056 | 002、047 脱敏与诊断 |

命令归属：001 管理入口/pytest 参数，007 与 045 合成 prepare，008/052 合成 fixtures，044 管理 doctor，048/049 管理 build-windows 与 smoke-package，050 管理 eval-rag，051 管理 bench-mcp，054 管理 bench-agent，052 管理 bench-video。后票修改已有入口时保持前票命令可用，不建立第二套重复 CLI。

### 11.8 需要确认或外部落实的问题

本节只登记当前不能凭现有文件确定的事项，不在本轮追问，不影响拆票。执行到相应票前先自行检查已有配置、权限或资源；仍缺失才提出具体问题，不要求用户重复提供工具可查事实。

| 编号 | 未确定内容 | 何时落实 | 缺少时的处理 |
|---|---|---|---|
| C01 | 有效 DeepSeek 接入与可使用时间窗口；目前未提供 Key | 052 压力及 053 干净机本地准备完成后，在 054 按已有“一小时临时接入或评审自备”安排 | 本地实现可先做，真实在线验收保持 blocked；不提前消耗窗口 |
| C02 | 可用于实际演练的干净 Windows VM/独立机器及使用条件 | 053 前先查可用本地资源；若不存在再确认资源来源 | 不购买/重装/启动付费资源；本机 PATH 隔离结果单列，不能替代 T15 |
| C03 | GitHub 目标账号、仓库名及实际写权限 | 056 先读现有登录与 remote，无法确定才确认目标 | 不猜远程地址或改其它仓库，不生成假链接 |
| C04 | 固定 RAG 数据标签的人工核对记录 | 026 产出可审阅标签后、050 计分前落实 | 自动结构检查可做，未人工核对的得分不算正式验收 |
| C05 | 自有源码许可证尚未指定；各实际依赖/模型/模板分发条件需形成清单 | 048/049 查证实际依赖，055 提交可审阅许可清单，必要时确认自有源码授权选择 | 不擅自宣称 MIT/LGPL，不把许可未核清的组件作为可分发资产发布 |

其它缺口按“发现位置→证据→影响票→建议处理→是否需要用户决策”记录；事实调查由开发执行者承担。不能借本节重开已定的 Windows/PySide6、DeepSeek、Qdrant/Ollama/bge-m3、混合检索与独立重排选型。
