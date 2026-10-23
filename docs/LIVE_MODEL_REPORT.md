# 真实模型工具选择与多轮验收

状态：五会话各三轮的全部目标判定通过，六项报告审计通过；打包桌面重启后通过真实历史追问。原始报告 `artifacts/reports/agent-5-sessions.json` 保留为 `manual_review_required`，因为逐项人工确认等门槛没有代填。可提交的脱敏结果见 [机器可读证据](evidence/live-model-summary.json)。历史失败不会合并为通过。

## 本轮结果

- 15 个目标轮次均成功，来源、工具参数、会话隔离、实际模型和 usage 判定通过；四个参数提案为 PENDING，一个有来源的空 patch 保持原值，均没有自动应用。
- 主运行包含重试共 24 个不同 turn；所选 15 轮为 186,878 tokens，主运行包含重试为 282,704 tokens。前两批失败分别记录 25,418 和 76,514 tokens，不能删掉或算成成功。以上仅为提供方实际返回的模型 usage，不是账单或搜索费用估算。
- 实际打包 EXE 重新打开同一数据目录，通过 UI 发送原会话追问，正确复述随机标记与 MP4/保留音频目标；实际 deepseek-v4-pro 返回，6,246 tokens、零工具调用。此前两次自动化只高亮而未提交会话选择，问题进入无文档的预检查会话，模型明确拒绝编造历史；两次额外实际用量 2,232 / 2,373 tokens 亦保留。这是自动化操作修正，不归为模型回忆原会话失败。
- 本次不重跑压力测试；RAG 人工标签、人工应用参数建议、干净 Windows 和二进制分发许可继续单列。

## 授权与测试范围

2026-10-23，用户明确反馈“已通过，进行真实模型选择工具、多轮回答测试”。据此记录本机桌面和媒体人工验收通过；RAG 25 题标签、干净 Windows、打包在线验收等未独立确认的字段保持未测。真实 Key 已由用户保存在应用内，仅由当前 Windows 用户的 DPAPI 解密使用，没有写入代码、命令行、截图或报告。

实际 `/models` 请求成功，已配置的 `deepseek-v4-pro` 在官方返回列表中。连接证据见 `artifacts/reports/live-model-connection.json`。生成走 [Responses API](https://api-docs.deepseek.com/zh-cn/guides/responses_api/)，搜索走同 Key 的 [Search API](https://api-docs.deepseek.com/zh-cn/guides/search/)，最终报告记录提供方实际返回模型名和 usage，不使用模拟回答。

| 轮次 | 实际请求 | 判断内容 |
|---|---|---|
| 1 | 读取本会话授权文档，检索 MP4 默认设置 | 模型选择文件/RAG 工具，文档随机标记、工具结果、来源和上下文归属正确 |
| 2 | 复述标记，实际查 MySQL 规则并提出参数建议 | SQL 非空、有来源；需要变更时进入 PENDING，已满足目标时允许有来源的空 patch，均不自动应用 |
| 3 | 重建 AgentService，不再附文档引用，回忆标记并核实未知扩展名 | 持久化历史重载、会话隔离、无重读文件、真实搜索参数与来源、如实说明无法确认 |

共 5 个会话、各 3 轮。先完成首个会话首轮，判定通过才扩展其余 4 个。五会话是约定的功能验收，不重跑已取消的压力复测。每个运行使用独立目录和随机标记，保留完整答案、调用参数、模型/主机搜索归因、trace 和实际 token 数。

本流程重建的是 AgentService，并继续使用已提交的 SQLite 历史；不能单凭它声称桌面进程重启已经测试。测试独占 application.lock，运行前正常关闭同数据目录 GUI，防止另一个 ConversationStore 把活动轮次恢复成 INTERRUPTED；恢复并实际检查私有服务后才发模型请求，结束清理所属服务。

## 真实测试发现和修复

1. 首次 5 个首轮中，3 个成功、2 个失败。部分模型调用把 `src-*` 来源编号当成文件授权 UUID，正确被拒绝，但主机将权限错误误当缺少证据而额外搜索。已在固定上下文和字段说明中区分 `file_ref_id` 与 `source_id`，保留严格授权校验；权限/参数/文件变化不再触发主机搜索，允许模型纠正参数。历史报告：`agent-5-sessions-before-reference-fix.json`，实际 usage 合计 25,418 tokens。
2. 下一次首轮 5/5 通过。第二轮暴露规则分类/编码筛选猜错、空结果被当成缺少知识的问题；一个并行查询已有充分规则时，也会额外搜索。现明确筛选按 AND 组合，说明实际内置分类和编码名/编码器名的区别；空筛选由模型放宽条件或检索，不直接触发搜索。历史报告：`agent-5-sessions-before-sql-proposal-fix.json`，实际执行 10 轮，usage 合计 76,514 tokens。
3. 两个已完成的真实回答使用合法 `json` 代码块表达建议，旧解析只接受 `settings_proposal` 因而不生成预览。解析兼容这两种标签，仍完整校验参数、来源和权限，只生成待确认提案；系统提示同时给出准确代码块示例。
4. 保存的真实搜索工具输出达到 33,296–39,510 UTF-8 字节，单条就可能超过上下文预算。现在优先使用提供方短 snippet，必要时截取前 400 字符并标记 `snippet_truncated`，保留标题、URL 与检索时间。搜索摘要不等于完整阅读网页，不用摘要杜撰支持结论。
5. 自动补搜索保留问题中的独立 `.xyzvideo` 后缀，同时过滤路径、文件名和凭据，不再只发泛化的编码关键词。调用记录区分模型选择与 `host-search-*` 主机兜底，不把后者算成模型选择。
6. 第二轮五个真实回答均完成：四个产生 PENDING 提案，一个基于实际规则判断当前参数已满足目标，返回有来源的空 patch。旧验收额外要求每轮必须产生提案，这会把合理的“保持原值”判失败；现在明确这两种合法结果，空 patch 不创建提案、不写设置，来源和字段仍严格校验。此项是验收判定澄清，不能把空 patch 写成已产生待确认提案。
7. 第三轮首次尝试一个成功、四个失败，工具输出与旧会话一起超出预算的记录单列。上下文构建现在先尝试保留最近两个完整轮次，不够时再压缩已结束的旧轮次；当前轮的工具调用与结果成对保留，摘要保存旧轮次状态、最后回答及随机标记，原始历史不删除。相同会话上仅重试未通过轮次；模型可能直接复用先前失败轮留下的来源，因此重试提示明确要求本轮重新调用检索和搜索，原提示与新提示均记录，不冒充全新三轮一次通过。
8. 后续真实搜索返回 HTTP 200，但一条来源的 `title` 为空字符串，旧代码因此拒绝整批结果。实际同词查询保存于 `live-search-shape.json`，可确认其他条目有效。官方 [Search 响应 Schema](https://api-docs.deepseek.com/zh-cn/guides/search/) 定义标题为 string，没有要求非空；现在空白标题使用实际 URL 的 hostname 展示，并标记 `title_fallback=true`，原链接不变，不杜撰网页标题。含凭据的链接仍拒绝。新增回归覆盖混合有标题/无标题结果与危险链接；相关联合回归 `live-final-fixes.xml` 为 128 项通过。
9. 随后另一个会话在工具均成功后仍收到 HTTP 400；本次安全观察记录了明确的 `invalid_request_error`：思考模式工具续答缺少 `reasoning_text`。检查保存的协议项发现，模型原调用保留了推理项，但主机补搜索单独追加成一个没有推理项的 assistant 调用段。按 [Responses 输入项的归并规则](https://api-docs.deepseek.com/zh-cn/guides/responses_api/) 将补搜索调用归入原 assistant 工具批次，全部调用排列在对应输出之前，沿用原始推理项，不生成或补写推理文本；读取旧历史时也只在请求中归并旧主机批次，数据库原件保持不变。新增续答排列和旧记录不变的回归，联合 `live-protocol-fixes.xml` 为 141 项通过。本次 400 有确切证据，不能据此断定较早所有泛化错误均为相同原因。
10. 另保留两类本地失败：Ollama 日志明确记录一次 CUDA 初始化失败、`/api/embed` 返回 500；之后真实向量预检查恢复，不能把这一事实推断成所有后续 RAG 失败的原因。另一项启动超时通过 30 秒 faulthandler 堆栈定位到 CPython 3.13 `platform._wmi_query → win32_ver → machine → torch._load_dll_libraries`，构建的隔离导入也停在相同环境阶段。项目进程屏蔽可选 `_wmi` 扩展，使 platform 使用自身原生/注册表回退，已加载的 platform 引用同步处理；源码入口、冻结运行钩子和构建隔离进程保持一致，不改标准库文件或系统 WMI 服务。真实导入 Torch 2.14.1+cpu 和 AMD64 查询恢复。系统 taskkill 超时另增加核对 PID、创建时间和所属子树的原生停止兜底；23 项相关回归、两项真实父子进程/外部进程保护集成通过，原超时与 CUDA 错误仍保留。

第一次 `DEPENDENCY_UNAVAILABLE` 未保留具体 HTTP 失败细节，不能进一步断言对应的提供方错误原因；文件编号混淆、拒绝、超预算与搜索参数均有本地原始记录支持。两份历史失败的 usage 不得删掉，也不计入最终成功轮次。

## 可复现检查

先关闭使用同一数据目录的客户端；在项目根目录执行：

```powershell
. .\environment\activate.ps1
python -m media_converter.devtools bench-agent --live-api --data-dir artifacts/rv-1e789301 --output artifacts/reports/agent-5-sessions.json
python -m pytest tests/live_api/test_acceptance_report.py --live-api -q --junitxml artifacts/reports/live-model-acceptance.xml
```

第一条会消耗实际模型及搜索用量；第二条只审计已生成报告，不再发模型请求。缺少人工记录、显式开关或凭据时阻断，不选择模拟模型。在线协议相关回归 141 项，后续 Windows 回退相关回归 23 项、所属进程集成 2 项，各分项有重复，不相加。

最终主程序与工具重新构建为同一源码标识 `96560392f810e795c578a74048d56ba389f8e81b47df4b1ce0cd9e29ec2ae873`，原数据、模型和数据库保留。最新冻结本地链五项实际检查全部通过，含混合检索、CPU 重排及 MySQL 只读授权；CLI 结束后所属服务清理。安装验证最初由脚本和实际 CLI 重复持有 application.lock，被正确拒绝为 INVALID_STATE；改为转交锁后通过，拒绝原件与回滚材料保留，不归为依赖缺失或放松锁校验。

源码已提交 [GitHub](https://github.com/daninyc/windows-video-converter-agent)，已验证远端 main 与本地提交一致、README/复盘/证据可匿名读取，见 [回执](evidence/github-delivery.json)。没有发布二进制 Release，没有代填干净 Windows、许可核验或人工应用参数确认，也没有向 HR 发送消息。
