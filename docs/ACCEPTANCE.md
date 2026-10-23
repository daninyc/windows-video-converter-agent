# 真人验收流程

当前先验收桌面、媒体和本地 AI；真实 DeepSeek / 搜索凭据等你核对通过后再配置。自动测试通过不能替代本页的人耳、人眼检查。每项记录“通过 / 失败 / 未测”，不要把未测改成通过。

## 1. 启动与文件位置

项目根目录：`D:\CodexWorkspace\bossjinzhoubishiti`。

本机直接双击根目录的 **`启动验收.cmd`**。它读取 `artifacts/review-target.json` 并启动指定的打包 EXE 和独立验收数据目录，不需要激活 Python 环境；当前验收入口以该文件为准。原打包验证保留在 `artifacts/reports/ai-package.json`，本次服务恢复修复的冻结包验证见 `artifacts/reports/setup-recovery-frozen.json`，原目录复用恢复的五项实际检查通过；详细记录见 [SETUP_RECOVERY.md](SETUP_RECOVERY.md)。不要移动该目录内的 exe 或 `_internal`，请保留完整文件夹。

本机验收已复用校验过的下载缓存准备本地组件；这不是一台干净 Windows 的证明。转换基本功能不需要 API。若出现“准备 AI”窗口，已经准备过私有组件的数据目录选择“复用已配置的本地组件”或“私有组件”都会恢复本目录所属服务，等待索引与本地检查完成。纯外部配置的复用仍要求外部服务先运行。也可以关闭该窗口先验收转换；关闭准备页面不会停止准备，主动“取消准备”才取消。

本机原生 MySQL 26.7.0 在中文数据目录初始化失败，Qdrant Gridstore 在过深的存储路径创建集合失败，当前 AI 验收入口使用短 ASCII 数据目录。请保持该数据目录位置；这些限制针对原生 AI 组件存储路径，视频 / 文档输入可用中文路径。独立机请把便携目录解压到 `D:\VideoConverter` 等短位置，数据可指定为 `D:\ConverterData`，不宣称上述上游路径限制已修复。

建议统一选择输出目录 **`D:\CodexWorkspace\bossjinzhoubishiti\artifacts\人工验收结果`**，在资源管理器创建即可。不要把输出放进测试输入目录。关闭程序后保存结果与诊断，暂时不要清理数据目录。

| 用途 | 绝对位置 |
|---|---|
| 小型视频 | `D:\CodexWorkspace\bossjinzhoubishiti\artifacts\fixtures\media` |
| 文档样本 | `D:\CodexWorkspace\bossjinzhoubishiti\artifacts\fixtures\documents`，精确文件名见 `artifacts/fixtures/manifest.json` |
| 长视频 / 4K / 50 个短视频 | `D:\CodexWorkspace\bossjinzhoubishiti\artifacts\fixtures\pressure` |
| 自有声画同步标记与输出 | `D:\CodexWorkspace\bossjinzhoubishiti\artifacts\fixtures\av-sync`；三个子目录各有原始 `sync.mkv` 和 `conversion/out` 转换结果，见同目录 manifest |
| 真实摄影素材 | `D:\CodexWorkspace\bossjinzhoubishiti\artifacts\fixtures\xiph\crowd_run_1080p50.y4m` |
| 基础便携 ZIP | `D:\CodexWorkspace\bossjinzhoubishiti\dist\MediaConverter-Windows-x64.zip` |
| AI 运行时 ZIP / 对应清单 | `dist/MediaConverter-AI-Windows-x64.zip`、`dist/MediaConverter-AI-manifest.json` |
| 包哈希 / 构建源码清单 | `dist/SHA256SUMS.txt`、`dist/BUILD_REPORT.json`、包内 `BUILD.json` |

基础 ZIP 和 AI ZIP 为本地审阅候选，分发许可审查未完成，尚未公开发布。AI ZIP 不包含模型、数据库、Key；模型和原生服务通过固定清单准备。

## 2. 一次最短转换

1. 打开应用，确认任务列表空态、参数区、AI 侧栏和底部操作可读。基本操作未就绪时应说明原因。
2. 点击“添加文件”，选择 `artifacts\fixtures\media\中文 空格\基础.mp4`。
3. 等信息读取完成。选中该行，核对时长、尺寸、帧率、视频 / 音频轨道与缩略图。不要仅看扩展名判断编码。
4. 输出选“统一目录”，选择上面的“人工验收结果”；目标 MP4，默认 H.264 / AAC、CRF 23。
5. 点击“开始转换”，观察进度、成功数和状态。点击“打开位置”，确认实际文件存在。
6. 用 Windows 可用的播放器播放输出。应有画面、声音，能拖到结尾；核对方向、时长、音画对应，无明显冻结或尾部缺失。播放器不支持某种编码时记录播放器名称和失败现象，不能直接判定转码器已通过或损坏。
7. 同样参数再转换一次，应自动产生带编号的新文件，旧结果与源文件保持原样。

## 3. 格式与边界

| 检查 | 输入 / 操作 | 判断标准 |
|---|---|---|
| 五类封装 | `基础.mp4`、`基础.mov`、`基础.avi`、`基础.webm`、`双音轨 双字幕.mkv` | 均能显示实际信息和缩略图；坏文件单列失败 |
| 三种输出 | 普通短视频分别转换 MP4、MKV、WebM | 三个实际输出；播放器播放或 FFmpeg 完整解码，无伪成功 |
| 无音频 | `无音频.mp4` → MP4 | 不要求凭空增加音轨，转换完成 |
| 多音轨 / 字幕 | `双音轨 双字幕.mkv` → MKV；再 → MP4 / WebM | 轨道信息可读；不兼容或要丢弃的轨道先列清单，拒绝后不开始；确认仅适用于该计划 |
| MP4 兼容字幕 | `兼容字幕.mp4` → MP4 | 输出可核对字幕轨道，不把所有字幕一概丢弃 |
| 方向 | `旋转.mov` | 缩略图、像素尺寸、可视方向说明合理；输出无错误旋转 / 拉伸 |
| 帧率 / 极短 | `变帧率.mp4`、`超短.mp4` | 可读取与转换，显示实际或未知值，不编帧率 |
| 损坏输入 | `损坏.mp4` 和一个正常视频同时导入 | 损坏项给明确错误，正常项仍可转换 |
| 高级参数 | 选择尺寸 / 帧率 / 固定码率；再输入非法值 | 合法设置进入下一批，非法设置说明原因且不能启动 |

查看 `artifacts/fixtures/manifest.json` 可获得样本的实际探测结果和哈希。Y4M 的 1080p50 / 500 帧真实摄影样本约定单独导入；来源许可见 `docs/XIPH_TEST.md`。Y4M 不是普通播放器普遍支持的容器，可播放它转出的 MP4。

人耳 / 人眼声画核对：播放 `av-sync\mp4\sync.mkv` 与 `av-sync\mp4\conversion\out\sync.mp4`，再检查 MKV / WebM 对应输出。这段自有样本 1.2 秒，0.5–0.58 秒出现白色闪屏与蜂鸣声；可重复播放，核对闪屏 / 声音是否基本同步。自动样本测量最大偏差 19.938ms，不替代人工听看，也不代表所有来源。

## 4. 保存策略、取消与恢复

1. “统一目录”分别关闭 / 开启“保留来源层级”，从含子目录的文件夹导入并比较输出结构；再选择“源旁转换结果”，应写入各原视频旁的“转换结果”子目录。源和已有输出不得被覆盖。
2. 目录导入分别关闭 / 开启递归；重复导入不应悄悄产生重复任务，跳过原因可查看。
3. 添加 `pressure\01_30分钟_1080p.mp4` 和两个短视频。开始后“取消当前”，应停止当前所属进程，随后继续短视频。
4. 重做一个批次，点击“取消整批”，后项不再开始。取消项不能显示成功，临时文件由应用清理，不能删除源文件或其他任务结果。
5. 选失败 / 取消项重试。应生成新尝试，沿用原尝试参数。批次开始后编辑右侧参数，不得改动正在运行的批次。
6. 保存命名预设、修改设置后加载；退出再打开，核对设置 / 历史恢复。若测试运行中退出，应停止所属进程，重启后标为中断，不自动重跑。
7. 另外打开同一验收数据目录，应用应阻止双实例写入。不要为了测试强制结束无关 Python、MySQL、Qdrant 或 Ollama 进程。

## 5. 桌面体验与诊断

在 Windows 显示缩放 100% / 150% / 200% 下检查主按钮、参数滚动、错误说明和侧栏；也可参考已生成的三档真实桌面截图 `artifacts/ui/boundary-047`。用 Tab 切换焦点，关键操作应可到达。导入多视频或转换时拖动窗口、编辑下一批参数，窗口仍能响应。

把 AI 侧栏展开为独立窗口，收回、隐藏、关闭再打开，历史与输入应一致；关闭视图不应等同于停止回答。“停止回答”才取消对应轮次。当前没有真实 Key 时，不能用这些离线操作宣称真实问答已经通过。

“帮助 → 查看 / 导出本地诊断”应能生成 ZIP。检查只含版本、状态、匿名上下文 / 日志摘要，没有视频、文档原文、数据库、凭据或完整私人路径。诊断不自动上传。

## 6. 本地 AI 与 RAG 人工核对

“准备 AI”完成时，视频、MCP、知识库、MySQL、文件五项都应以真实检查显示通过；端口可连不等于准备完成。若提示失败，保存错误码和诊断，修正后重试。

本地链使用 Qdrant 双路召回、RRF 融合、Ollama bge-m3 向量和独立 CPU 重排。`artifacts/reports/rag-eval.json` 是自动逐题报告，`docs/RAG_REVIEW.md` 是便于人工审阅的清单。逐项比对问题、期望章节、实际 Top5、来源与库外证据不足。全部未签字前，20/20 只能称自动结果，不能称人工验收通过。

没有在线 API 时，聊天不会自动变成本地大模型。文件 / SQL / RAG 工具已由本地集成测试验证；本阶段可通过准备检查和报告核对，真实模型选择工具、多轮回答和建议需要下一阶段验证。

## 7. 压力素材与复现

- `pressure\01_30分钟_1080p.mp4`：30 分钟 1920×1080、30 fps，合成色条 / 脉冲循环。
- `pressure\02_1分钟_4K.mp4`：60 秒 3840×2160、30 fps 合成色条。
- `pressure\50短视频\短视频_01.mp4` 至 `短视频_50.mp4`：50 个短样本。

完整 52 文件队列已自动执行并发本地 AI，实测见 `artifacts/reports/video-pressure.json`。它验证该合成负载的正确性和响应，不代表高运动真实影片的普遍速度。

用户已豁免最后一轮压力复测，现阶段不需要再次运行压力命令。下面只供以后开发复现（在项目根 PowerShell 先 `. .\environment\activate.ps1`）：

```powershell
python -m media_converter.devtools smoke-package --package dist/MediaConverter-Windows-x64.zip --without-dev-path --output artifacts/reports/package-smoke.json
python -m media_converter.devtools eval-rag --dataset knowledge/eval.jsonl --data-dir data --output artifacts/reports/rag-eval.json
python -m media_converter.devtools bench-mcp --profile real-local --requests 100 --client-concurrency 100 --rounds 3 --faults --data-dir data --output artifacts/reports/mcp-real-local.json
python -m media_converter.devtools bench-video --profile agreed --fixture-root artifacts/fixtures/pressure --data-dir data --output artifacts/reports/video-pressure.json
```

推理验收依次运行；不要同时启动几套独立重排进程。本机曾因测试并行加载多套权重触发 Windows 页面文件不足，失败记录已保留。以上命令不调用在线 API。

## 8. 干净 Windows（独立待验）

当前没有已验证的干净 Windows 资源，不能用本机清空 PATH 的结果代替。

在没有开发 Python / FFmpeg / 项目环境的新 Windows VM 或另一台机器上：记录系统版本、CPU / RAM、空闲磁盘、网络与开始时间；复制基础 ZIP、AI ZIP、AI manifest、SHA256SUMS 到 D 盘同一位置；核对哈希；解压基础 ZIP，把 AI ZIP 和 manifest 放在 `MediaConverter.exe` 旁边；不要复制本机的 `data`、凭据或数据库。

双击 EXE，先走第 2–4 节基础转换；再从向导选择私有准备，查看来源 / 空间，实际下载、初始化私有数据库、构建索引及五项健康检查；记录初次准备和冷热耗时。主动取消 / 重试一次，退出确认只停止本应用所属服务。保存截图、诊断和完整失败信息。API 在线步骤仍等人工离线通过后再做。

独立机证据模板为 `docs/clean-windows.template.json`，默认全部未测；本机 PATH 隔离结果不能用于填写该模板的通过项。

## 9. 人工反馈与下一阶段

按下面格式直接回复即可，无须现在给 API：

```text
使用的入口：启动验收.cmd
桌面与基础转换：通过 / 失败（步骤、输入、错误码、现象）
播放器与声画核对：通过 / 失败（播放器、输入 / 输出）
轨道确认 / 输出保护 / 取消 / 重试 / 恢复：各项结果
本地准备：通过 / 失败
RAG 25 题来源核对：通过 / 待核对 / 具体问题
干净 Windows：已测通过 / 未测 / 失败
```

确认后，由开发者把你的实际反馈写入验收数据目录的 `manual-acceptance.json`（模板在本目录；不得自行填通过）。然后在应用“接入设置”保存你提供的真实 API，确认地址和 `deepseek-v4-pro`；Key 仅存当前 Windows 用户 DPAPI，不写命令行、Git、报告或截图。有效期以提供方撤销 / 响应为准。

届时先恢复并检查该数据目录的本地服务，再执行真实 5 会话 ×3 轮、实际 usage / 模型标识 / MCP 调用、跨会话隔离、自动搜索和建议确认，另走打包 GUI 重启追问。官方 [Search 接口](https://api-docs.deepseek.com/zh-cn/guides/search/) 使用同一 DeepSeek Key；当前工具调用 `/v1/tools/search`，模型走 [Responses API](https://api-docs.deepseek.com/zh-cn/guides/responses_api/)。若评审替换代理地址，需实际核验这两个入口，不能伪造支持或链接。相关入口已准备，私有服务在 CLI 验收中的生命周期仍须在真实阶段核对，本阶段未执行 `--live-api`。

真实 API、RAG 人工标签、干净 Windows、许可和 GitHub 发布各自记录，不以其中一项替代其他验收。尚无 GitHub 发布链接，完成发布门槛后才生成实际仓库 / Release 地址；本阶段不会代发 HR 消息。
