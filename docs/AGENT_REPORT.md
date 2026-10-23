# Agent 020–039 实施与本地开发验收

日期：2026-10-22，北京时间。结论：tickets020–039 已实施并通过本地开发验收。完整联合回归 **145 passed、0 failed、0 errors、0 skipped**，包含已有转换链及 Xiph 真实素材；JUnit 耗时 **322.662 秒**，分组为 unit 68、GUI 23、integration 54。真实供应商验收未执行。

用户已授权按 Spec 顺序实施，并明确要求真实 API 留到最后验收阶段。本轮复用现有环境、模型和私有服务，没有调用付费 DeepSeek 或搜索 API，没有发布或启动多个开发 agent。以下“本地开发验收”不等于 tickets054 的真实供应商验收，也不等于人工签署验收。

## 逐票交付与证据

| 票 | 已实现行为 | 测试与本机证据 |
|---|---|---|
| 020 | SQLite schema 4；会话、顺序消息、provider_items、引用、轮次、工具调用和建议持久化；冻结引用/设置/作用域/期限；启动只恢复活动轮次为中断 | `test_conversation_store.py`、`test_reference_context.py`；五组会话隔离、撤销、文件变化与历史恢复 |
| 021 | 可替换地址/模型/连接设置；Windows 当前用户 DPAPI 加密及私密目录 ACL；更换/清除 Key；显式连接测试入口 | `test_credentials.py`、`test_api_settings.py`；哨兵 Key，不使用真实凭据 |
| 022 | 异步 Responses/SSE；分块与 CRLF、序号、完成/断流判定；保留 reasoning/function 配对字段；记录实际模型与原始 usage，缺失为未知 | `test_deepseek_adapter.py`，供应商响应均明确为模拟；401/402/429、断流不重放 |
| 023 | 官方 MCP SDK 的 stdio 子进程；一个后台任务拥有并复用连接；Host 签名 metadata 与模型业务参数分离；只读校验提交状态 | `test_mcp_context.py`、真实 `test_mcp.py`；缺失/伪造上下文和越权拒绝，实际协议写入 JUnit |
| 024 | 全局 16、队列 128、分类轮转；RAG 1/SQL 4/文件 2/搜索 2；排队/执行/整轮期限和取消 | `test_tool_dispatcher.py` 使用受控处理器；这不是 100 个真实请求压力结论 |
| 025 | 按作用域/设置/参数/数据版本合并在途请求；成功缓存有界/限时；订阅者独立取消；调用身份重新绑定 | `test_tool_dedup.py`；取消、版本、错误不缓存；Agent 重复命中仍计入 16 次预算 |
| 026 | 20 节应用原创事实摘要；来源章节/路径/外链/原文哈希；6 条规则；20 个有答案及 5 个库外问题预先固定 | `test_knowledge_manifest.py`；人工标签状态为 pending，未拿检索结果倒填；项目分发许可 C05 待所有者决定 |
| 027 | 从实际 Ollama GGUF 元数据重建 embedding 的 SentencePiece tokenizer；650 目标/800 上限/80 重叠；1024 维、digest 校验；Qdrant staging 完整后切换活动 manifest | `test_chunking.py`、真实 `test_rag_index.py`；重复复用、版本切换、中断 staging 不损伤活动库；短章节保留原长 |
| 028 | 同一固定版本实际执行 dense 与 Qdrant 原生 BM25，各取 20；按 chunk_id 去重，以 RRF k=60 融合至最多 20 候选 | `test_rrf.py`、真实 `test_rag_retrieval.py`；保留双路排名、融合分数和阶段结果 |
| 029 | 独立 CPU CrossEncoder worker；固定 revision、7 文件校验、4 线程、单并发；完整重排 Top5 和证据不足标志；关闭/故障回收 | 真实 `test_rag.py`；冷/热复用、终止自身 worker 后重建、活动索引不变；阶段耗时见 JSON |
| 030 | 隔离 `video_converter_app` 库与独立读/同步账号；来源规则；预设和转换尝试 outbox 投影；目标事务成功后本地确认，事件/版本/水位保护 | 真实 `test_mysql.py`；重复及乱序旧事件、目标提交后本地确认失败再补同步；原环境库和系统 MySQL80 保持独立 |
| 031 | 三个固定模板 MySQL 查询工具；参数化过滤、默认 20/最多 100；4 线程/连接；10 秒期限；实例范围和同步滞后提示 | 真实 MCP 查询规则/预设/历史；注入无结果，读账号写入与跨库查询实际被拒 |
| 032 | 仅 file_ref_id；打开时复核授权、真实文件身份/指纹；TXT/MD/LOG；UTF-8 或 BOM 明确编码；20 MiB/20,000 字符及续读位置 | `test_file_authorization.py`、真实 `test_files.py` 与 `test_mcp.py`；路径注入、替换/撤销拒绝 |
| 033 | PDF 按页与 DOCX 段落/表格顺序解析；独立工作进程；20 页/30 秒、展开体积与条目上限；损坏/加密/无文字明确错误 | `test_document_limits.py`、真实文档集成测试；分页续读、全文字符含分隔符限额；无 OCR |
| 034 | 独立 Search API，query/count 1–5，20 秒；拒绝本地路径、凭据与整段日志；校验真实来源字段；空结果与失败区分 | `test_web_search.py` 只用模拟 HTTP；实际 MCP 无 Key 返回 AUTH_FAILED；真实搜索留 054 |
| 035 | 目录恰好六工具，Host/MCP schema 同源；完整 RAG 接入统一 envelope；缺组件明确失败 | `test_mcp.py` 实际 stdio 调用完整 RAG：双路、融合、独立重排、来源/版本齐全；无生产测试探针 |
| 036 | 每会话 1、在线 5；8 次模型往返、16 次工具、最多 4 分支、整轮 300 秒；调用结果配对；依据不足自动受控搜索；终态保存 | `test_agent_turn.py`、`test_agent_mcp.py`；供应商为替身，MCP 本地真实；重复预算、并发/乱序、停止/排队取消 |
| 037 | 32k 输入保守 UTF-8 字节估算、8k 输出/推理预算；完整工具对、最近两轮及固定引用保留；旧轮次可追溯摘要，原消息不删除 | `test_context_budget.py`；按 user 序号分组处理排队追问；确定性摘录摘要没有额外模型费用；usage 校准留 054 |
| 038 | 同一侧栏/浮窗与 AgentService；会话历史、固定引用、流式显示、工具/来源、显式停止与重试；浮窗关闭不重交或取消 | 真实 Windows Qt `test_agent_panel.py`；截图 `artifacts/agent-acceptance/agent-completed.png`；在线文字为模拟且明确标注 |
| 039 | 白名单 settings_proposal；来源和理由必填；中文差异/下一批影响；勾选确认、版本冲突/重复确认保护；设置和应用状态同事务 | `test_settings_proposals.py`、真实 Qt `test_proposal_confirmation.py`；确认前无变化，应用后不自动转换；截图 `proposal-confirmation.png` |

## 复现命令与结果

在 PowerShell 7.4+ 执行；已有服务未启动时先运行环境提供的启动脚本。

```powershell
Set-Location 'D:\CodexWorkspace\bossjinzhoubishiti'
. .\environment\activate.ps1
.\environment\start-services.ps1
python -m media_converter.devtools configure-ai --environment-root environment --data-dir data --output artifacts/reports/agent-configure-ai.json
python -m media_converter.devtools knowledge-build --root knowledge --data-dir data --output artifacts/reports/agent-knowledge-reuse.json
python -m media_converter.devtools sync-mysql --data-dir data --output artifacts/reports/agent-sync.json
python -m pip check
python -m ruff check src tests
python -m ruff format --check src tests
python -m pytest tests/unit tests/gui tests/integration -q --fixture-root artifacts/fixtures --data-dir data --xiph-root artifacts/fixtures/xiph --junitxml artifacts/reports/agent-final.xml
```

`configure-ai` 只复用现有 Ollama 模型和 environment manifest 中的 reranker，不下载。`knowledge-build` 当前返回 reused=true，20 个片段，1024 维；活动版本为 `92e75c9c0e46ec2df9f46025807ebbc983c0569d7d9f32f6ef453d6452cc1880`。现有测试含本地真实服务，缺组件时的 skip 不能算本地验收通过。Xiph 输入已经完整下载并校验，见 [XIPH_TEST.md](XIPH_TEST.md)。

项目库初始化命令为 `python -m media_converter.devtools init-agent-db --stdin-credentials --root knowledge --data-dir data`，仅从 stdin 读取 `{"root":"初始化口令"}`；不要把口令写到 shell 参数、源码或报告。本机已完成初始化，日常运行只读/同步角色，不需要 root。凭据引用存于 `data/mysql.json`，密文存于 `data/private`。

当前分项历史报告已收取：`agent-local-tools.xml` 13 项、`agent-loop.xml` 5 项、`agent-gui.xml` 3 项、`agent-index-lifecycle.xml` 2 项，均 0 failed/errors/skipped；追加 `agent-last-checks.xml` 16 项通过。各批有重复用例，不相加当作新增测试数；最终联合报告为本轮统一口径。失败的历史 GUI 报告留作问题记录，未用来充当通过证据。

本轮最终报告为 `artifacts/reports/agent-final.xml`、`agent-summary.json`；完整控制台记录为 `agent-final-console.txt`，其中保留 MySQL 可选原生扩展导入诊断，详见下文。pip check、Ruff 检查及当时 144 个 Python 文件的格式检查均通过。实际 MCP 协议为 **2026-07-28**。

本机真实 RAG 单次冷启动全链 **36.150 秒**、复用 worker 热请求 **12.501 秒**；冷请求 20 对重排推理 **10.494 秒**、模型加载 **5.220 秒**、无 pair 截断。故障测试主动终止本应用 worker 后，重建进程并完成 2 对重排，活动知识版本保持不变。以上为本机样本耗时，不作为固定速度或压力性能承诺；未记录整轮内存峰值。

## 实测范围与限制

- 真实本地链：Ollama bge-m3 → Qdrant dense/原生词法 → RRF → 独立 CPU reranker；完整链也实际经 MCP stdio 调用。模型 revision/digest 与阶段数据记录在 `agent-rag-acceptance.json`、`agent-rag-real.json` 和 JUnit。
- 真实桌面和文件/数据库：Windows Qt 控件、当前用户 DPAPI、SQLite、私有 MySQL 查询/同步/权限、pypdf/python-docx；截图已目视检查。没有伪称人工点击或跨机器验收。
- 模拟供应商：Responses、流式回答、错误响应、函数调用、usage、搜索响应及 GUI 建议内容。没有真实模型/搜索请求，因此真实模型能力、返回模型、费用和网上来源真实性均未验收。默认模型仍按 Spec 配置，不以模拟返回值证明供应商可用。
- 相关性阈值 0.5 只是明确记录的起点；20+5 标签人工核对、最终检索质量/消融、usage 估算偏差留到 050/054。短资料检索能返回正确 MP4 片段，不代表质量门槛已达标。
- 本地转换与 Agent 保持独立。当前计划使用原设置快照，确认建议只改下一批；Agent 没有转换/取消任务或 shell 工具。
- 完整故障矩阵、5 个真实在线会话及 100 请求、长视频/4K/50 文件并行压力、便携包/干净 Windows/真实 API/发布属于 040–056 的后续工作。

## 本轮查明和修复的问题

1. 前次索引测试实际完成并写出 `agent-index-lifecycle.xml`，测试不是仍在阻塞。停滞出现在结果收取后的工作衔接，未继续进入全量回归与文档交接。本轮主动收取报告并启动后续检查；没有发现服务不可达、待批准动作或缺失凭据阻止离线工作。客户端为何结束先前执行需要运行日志，现有证据不能确定。
2. 修复 MCP SDK v2 服务注册/结构化字段、AsyncQdrantClient 关闭方式和 Qt 槽名称误覆盖 QObject.event；这些中间失败记录不充作验收成功。
3. 修复实际 embedding tokenizer 身份、知识文件 CRLF 哈希口径、分段字符分隔符计数和空白 PDF 页续读；避免错误切片、超长返回或静默漏页。
4. 修复 queued 用户追问插入时的历史分组、启动恢复与 MCP 只读连接边界、缓存命中前的撤销/文件指纹复核，以及各订阅者自己的调用身份。
5. 目视检查后把建议框的内部字段名/原始 JSON 改为中文设置、理由和来源，确认按钮明确为“应用到下一批”。
6. Windows 可选 MySQL C 扩展在已加载 Miniconda OpenSSL 后导入失败（0xc0000139/找不到指定程序），可以在独立进程复现。Connector 捕获 ImportError，`HAVE_CEXT=False`；本项目连接明确 `use_pure=True`，真实查询/同步仍通过。未修改全局 DLL、第三方包或掩盖诊断；此环境原生扩展兼容性不作为已修复，后续便携环境验收需单独处理。

## 交接

主要入口：`agent/service.py`、`agent/turn_runner.py`、`mcp_client.py`/`mcp_server.py`、`tools/registry.py`、`rag/*`、`storage/conversations.py`/`mysql_sync.py`、`ui/agent_controller.py`/`settings_diff.py`。

按用户“收取结果并启动下一项”的要求，联合结果收取后已启动 040 文件系统故障和输出保护边界，交接见 [FILESYSTEM_REPORT.md](FILESYSTEM_REPORT.md)；真实在线 API 仍按用户要求安排在 054。没有因缺 Key 中止可离线实施的工作。
