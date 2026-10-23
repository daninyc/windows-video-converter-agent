# 转换闭环 009–019 实施与开发验收

日期：2026-10-21，北京时间。结论：转换闭环已实现，单元、真实 Qt 桌面及本地集成联合验收通过。最终结果见下方机器报告；未开始 020–039 Agent 路径。

本轮只复用已有 environment、FFmpeg/ffprobe 和自有素材，没有新增依赖、下载模型、启动 AI 服务、调用付费 API、连接业务 MySQL、初始化 Git 或发布。所有源码、数据、测试输出和截图均在 D 盘项目目录内。

后续补充：用户追加的 Xiph 真实素材项 X01 单独记录在 [XIPH_TEST.md](XIPH_TEST.md)，使用公开下载的完整 Crowd Run 1080p50 Y4M，并补齐 Y4M 导入。下面的 95 项和“自有素材”说明保留本轮历史口径，追加项及之后回归的结果以补充报告为准。

## 逐票交付

| 票 | 交付与固定行为 | 验收证据 |
|---|---|---|
| 009 | ImportService；文件多选/目录/拖入共用入口；默认不递归；真实路径与文件身份去重；来源根持久化；扫描排除结果目录和目录链接 | 中文、空格、同名不同文件、重复/硬链接、缺失项、实际 junction/symlink 循环测试；真实 Qt DropEvent 仅接受本地 URL |
| 010 | ProbeService；最多两个 ffprobe，执行/等待有界；原像素尺寸和旋转分别保存；未知值为 null；损坏只影响自己；变化后重探测并清除失效旧字段 | 五类封装与素材 manifest 对照；分数帧率、封面流、坏文件、源文件被替换的实测 |
| 011 | 最多两路缩略图；有界在途请求；源指纹与尺寸/算法版本缓存；代表帧失败回退开头；共享请求取消隔离；缓存限量 | 真实超短/旋转/坏视频；缓存失效、在途合并、取消订阅者、回退控制；素材移除后迟到图片不写入复用行 |
| 012 | 常用/高级参数表单与 SettingsService；MP4/MKV/WebM；CRF/固定码率互斥；尺寸范围/分数帧率/音频参数；能力缺失阻止执行；有效更改递增版本 | 三种格式默认编码；无效数值与组合；表单往返；真实码率、30000/1001 帧率和比例缩放输出 |
| 013 | 统一目录（扁平或保留来源层级）/源文件旁“转换结果”；同名根稳定分组；重名避让；独占尝试临时目录；同卷 no-replace 发布 | 原件不变；既有目标不变；目标在提交时被抢占仍避让；路径越界拒绝；既有临时目录不接管、不删除 |
| 014 | 显式映射单主视频及全部拟保留音轨/字幕；逐轨编码、语言和 default 标记；具体丢失清单；复选确认绑定 plan_hash | 双音轨+SubRip/ASS 的 MKV 保留；MP4/WebM 的不保留字幕明确确认；MP4 mov_text、WebM WebVTT 保留；多主视频拒绝；取消确认不能开始 |
| 015 | 参数数组启动唯一所属 FFmpeg；独立 progress/stderr；PID、启动时间、二进制/参数哈希；有界脱敏错误摘要 | 三目标真实执行；分块进度解析；未知时长不定进度；progress=end 不能直接标成功；生产日志写 data/events.jsonl |
| 016 | 持久化批次命令/计划/尝试；固定快照；逐项执行；ffprobe 验证流、容器、尺寸、语言/标志、时长；短样本完整解码后发布并保存终态/outbox | 同命令不重复；真实 FFmpeg 转换峰值并发 1；验证失败不成功；失败继续后项；发布后保存失败不删除结果或误报成功 |
| 017 | 取消当前/整批；先 q 正常结束，再限时停止所属进程；取消优先于退出码；重试新 attempt_id；源变化重新探测和确认 | 真实进程取消/重试；退出码 0 取消竞态；验证期间取消；整批不启动后项；重复重试合并；旧尝试保留 |
| 018 | 命名预设新增/更新；有效设置恢复；按当前能力重新校验；打开实际避让后的结果目录 | 两次启动、预设版本事件、旧字段默认恢复、编码器失效；Qt URL 断言及真实 Windows 目录分发调用 |
| 019 | MainWindow、TaskModel、ConversionController 完整接线；逐文件详情、缩略图、进度/状态、错误、移除、重读、开始、取消、重试、预设与结果动作 | 三种目标分别由真实 Qt 控件操作，实际转码与验证；坏文件保留且不阻止有效项；选择不串详情；运行中改表单不改批次；运行中关窗无所属进程/线程残留 |

## 最终测试结果

最终完整命令：

```powershell
Set-Location 'D:\CodexWorkspace\bossjinzhoubishiti'
. .\environment\activate.ps1
python -m pip check
python -m ruff check src tests
python -m ruff format --check src tests
python -m pytest tests/unit tests/gui tests/integration -q --fixture-root artifacts/fixtures --data-dir data --junitxml artifacts/reports/conversion-final.xml
```

实测 **95 passed、0 failed、0 errors、0 skipped、0 blocked**；按目录为单元 41、GUI 19、集成 35，pytest 报告耗时 **83.49 秒**。pip check 无依赖冲突，Ruff 检查和 80 个 Python 文件的格式检查均通过。该数量包含基础阶段回归，不是新增 95 项功能，也不是视频压力测试成绩。

- JUnit：`artifacts/reports/conversion-final.xml`。
- 汇总与检查环境：`artifacts/reports/conversion-summary.json`。
- 三种目标的真实输出、完成截图、确认弹窗、完整计划/验证结果和哈希：`artifacts/conversion-acceptance/1acb39a6-be7e-438f-af56-c4e074ce2606/{mp4,mkv,webm}/`。
- Windows 实际打开目录的返回记录：`artifacts/reports/open-output-location.json`。
- 基础阶段历史证据继续保留在 FOUNDATION_REPORT 与 foundation.xml，不覆盖为本轮结果。

桌面操作由自动化驱动真实 Qt Widgets，不以模拟结果替代 FFmpeg/ffprobe；报告不伪称有人手工点击、播放或签署验收。三种目标的按钮/确认/状态/结果位置已走通，并检查实际生成文件；最终用户体验仍待用户打开程序复核。

## 实际覆盖与证据边界

五种输入封装均已转换到三种目标：MP4/MOV/AVI/WebM 的 12 组合，加双音轨双字幕 MKV 的 3 组合。另测旋转、VFR、单帧超短、无音频、兼容文本字幕、坏输入、源变化后重试。短输出完整解码，未只看进度条或 FFmpeg 退出码。

轨道保留实测包括 AAC 双音轨及中英文语言、default 标志、MKV SubRip/ASS、MP4 mov_text、WebM WebVTT，以及音轨自动复制/转码。静态表还列出其它常见兼容编码，这些编码并未逐一提供真实样本；位图字幕、更多异常封装的对抗回归由 041 完成，不能将其记作本轮全部验证。

Qt 测试和实际截图发现了系统深色调色板透过新控件的问题：现在明确设置浅色调色板，表格、表单和确认框均目视检查。基础窗口 100%/150%/200% 的进程/尺寸回归仍通过；包含全部控件的最终多显示器、键盘与三档缩放交互验收仍属 047。

30 分钟/4K/50 队列性能压力、干净 Windows、便携包、损坏/断电/磁盘/目录链接的完整故障矩阵和发布均不在本次验收范围。不用小样本结果宣称性能或所有 Windows 环境通过。

## 关键实现决定

1. SQLite schema 升至 3，新增 import_roots、conversion_plans、batch_commands、archived_assets；从旧版本迁移保留原记录。关闭程序不自动恢复转换；历史中断/取消项只能显式重试。
2. 批次/计划/初始尝试同一事务登记。状态与 outbox 同事务；同一 batch_command_id 不再次执行。重试以旧 attempt_id 去重，生成新计划和尝试，沿用原设置快照。
3. 临时文件在最终目录同卷的 `.media-converter-{attempt_id}` 独占子目录内，保留真实扩展名。只有成功创建该目录的尝试能清理它；提交使用硬链接原子 no-replace，发生冲突重新分配名称；不使用覆盖式 replace。
4. 从最后取消检查到发布之间没有 await。发布开始后，当前取消请求明确返回不接受；整批取消仍阻止后项。退出先合作取消并保存转换，再关闭通用后台 loop，避免直接取消 SQLite 写入等待造成内存/持久化状态错位。
5. 输出已发布而本地终态保存失败时，保留输出，报告 STORE_WRITE_FAILED，不显示成功。若运行存储持续不可写，UI 的失败状态不会冒充已持久化；旧活动记录在下次打开存储时转 INTERRUPTED。清理失败记录错误且不影响下一项，也不扩大删除范围。
6. 原生帧率模式不加 -r，并采用 passthrough；指定目标帧率才转 CFR。旋转由 FFmpeg 解码侧应用一次，并清除输出旋转标记。尺寸为保持比例的范围，编码器需要偶数对齐；本机 160×90 在 80×80 范围内输出 80×46。
7. AVI 没有 default 标记时，MP4 会启用首个视频/音频轨。规划和验证显式处理这一目标容器语义；已有可用的多音轨 default 仍保留，不因正常容器行为把有效输出误报失败。
8. 目录扫描跳过已知输出根、“转换结果”和工具临时目录；用户显式选文件时允许再次转换。界面移除只归档素材，不删除源文件；迟到探测和缩略图按 asset_id/指纹更新，不能写进另一行。
9. 单一数据目录由 QLockFile 保护，防止第二实例把另一个仍在转换的实例误恢复为中断。核心进程不加载 Torch、MCP 或要求 AI 服务。

参数数组、手动映射、disposition 和进度的接口参考 [FFmpeg 官方说明](https://ffmpeg.org/ffmpeg.html)；WebVTT 规则另核对 [FFmpeg Matroska/WebM 源码](https://github.com/FFmpeg/FFmpeg/blob/master/libavformat/matroskaenc.c)。最终行为以本机锁定二进制和上述真实测试为证据，不把文档支持当成本机验证。

## 主要文件与下一阶段

- `media/importer.py`、`probe.py`、`thumbnail.py`、`settings.py`、`output_paths.py`、`compatibility.py`、`planner.py`、`presets.py`。
- `jobs/ffmpeg_process.py`、`output_commit.py`、`output_validator.py`、`job_service.py`。
- `ui/import_actions.py`、`settings_panel.py`、`loss_confirmation.py`、`preset_actions.py`、`task_model.py`、`conversion_controller.py`、`main_window.py`。
- `common/process.py`；错误/日志、运行桥、存储迁移和应用启动/关闭接线同步更新。
- 各票要求的 unit/gui/integration 测试及三目标桌面验收证据。

启动方法见 README。当前可由用户复核：添加真实视频，选择 MP4/MKV/WebM 和输出目录，确认不保留的轨道，开始/取消/重试，打开实际结果位置。

020–039 Agent、040–047 完整边界、048–056 收尾均未执行。按照用户本轮要求，先停在转换闭环供验收，再确定 Agent 的实施路径；没有提前修改 Agent 业务代码或消耗 API 窗口。
