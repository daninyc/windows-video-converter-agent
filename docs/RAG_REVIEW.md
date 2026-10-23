# RAG 25 题人工核对表

以下全部未人工确认。请核对问题、期望依据和实际候选；候选非空不代表足够回答。分数来自冻结数据的自动执行，不能当成人工判断。

核对人：________  日期：________

原始标签：`knowledge/eval.jsonl`；实际候选与各路分数：`artifacts/reports/rag-eval.json`；正文：`knowledge/application.md`。

| 核对 | 编号 / 问题 | 期望来源 | 实际混合＋重排 Top5 | 本地依据足够 |
|---|---|---|---|---|
| [ ] | answer-01 怎样把一个目录里的子目录视频一起加入？ | import: src/media_converter/media/importer.py | import / output / container / evidence / batch | True |
| [ ] | answer-02 有个文件没读出帧率，界面应该显示什么？ | probe: src/media_converter/media/probe.py | probe / framerate / validation / evidence / presets | True |
| [ ] | answer-03 把 mkv 文件直接改名为 mp4 可以完成转换吗？ | container: src/media_converter/media/compatibility.py | container / mp4 / import / framerate / output | True |
| [ ] | answer-04 想转换成通用的 mp4，这个软件默认选什么？ | mp4: src/media_converter/media/settings.py | mp4 / container / mapping / framerate / mkv | True |
| [ ] | answer-05 我有两条音轨和 ASS 字幕，怎样检查 MKV 会保留什么？ | mkv: src/media_converter/media/compatibility.py | mkv / mapping / probe / subtitles / container | True |
| [ ] | answer-06 改选 webm 后为什么音频编码变成了 Opus？ | webm: src/media_converter/media/compatibility.py | webm / container / mp4 / presets / evidence | False |
| [ ] | answer-07 为什么设了 CRF 还是不知道最终文件会有多大？ | crf: src/media_converter/media/settings.py | crf / resolution / mp4 / evidence / presets | False |
| [ ] | answer-08 设成 80×80 为什么 160×90 的视频输出成 80×46？ | resolution: src/media_converter/media/planner.py | resolution / container / validation / framerate / presets | True |
| [ ] | answer-09 默认会把变帧率视频强制变成 30fps 吗？ | framerate: src/media_converter/media/planner.py | framerate / mp4 / validation / mkv / webm | False |
| [ ] | answer-10 -map 的用途是什么，为什么需要明确映射全部音轨？ | mapping: src/media_converter/media/planner.py | mapping / container / mp4 / mkv / import | True |
| [ ] | answer-11 mov_text 是什么？为什么转 MP4 要确认丢弃 ASS？ | subtitles: src/media_converter/media/compatibility.py | subtitles / container / webm / validation / output | True |
| [ ] | answer-12 输出目录里已经有同名视频会被覆盖吗？ | output: src/media_converter/media/output_paths.py | output / presets / container / import / evidence | True |
| [ ] | answer-13 开始后改右侧 CRF 会影响正在转换的文件吗？ | batch: src/media_converter/jobs/job_service.py | batch / crf / container / evidence / cancel | True |
| [ ] | answer-14 取消当前和取消整批有何区别，失败重试用哪套参数？ | cancel: src/media_converter/jobs/job_service.py | cancel / evidence / batch / presets / storage | True |
| [ ] | answer-15 显示转码结束是否说明输出已经验收成功？ | validation: src/media_converter/jobs/output_validator.py | validation / container / storage / batch / presets | False |
| [ ] | answer-16 STORE_WRITE_FAILED 之后输出文件会被删除吗？ | storage: src/media_converter/jobs/job_service.py | storage / output / import / presets / validation | True |
| [ ] | answer-17 另一台电脑缺少预设的编码器时会自动换一种吗？ | presets: src/media_converter/media/presets.py | presets / evidence / container / crf / cancel | True |
| [ ] | answer-18 AI 能自己启动转换或跟随我点击的视频偷换引用吗？ | authority: SPEC.md#3.6 | authority / batch / cancel / container / import | True |
| [ ] | answer-19 我的扫描 PDF 没有文字，AI 能直接读取图片里的内容吗？ | files: SPEC.md#5.3 | files / evidence / import / authority / probe | False |
| [ ] | answer-20 检索返回了五条片段是否就能证明回答有依据？ | evidence: SPEC.md#3.5 | evidence / storage / container / presets / validation | True |
| [ ] | outside-01 2027 年所有手机的 AV1 硬件支持排名？ | 库外，应该说明缺少本地依据 | mp4 / container / import / webm / mkv | False |
| [ ] | outside-02 某品牌尚未公布的芯片实际功耗？ | 库外，应该说明缺少本地依据 | evidence / presets / storage / validation / mp4 | False |
| [ ] | outside-03 今天某云厂商编码服务的最新价格？ | 库外，应该说明缺少本地依据 | evidence / container / presets / crf / validation | False |
| [ ] | outside-04 如何从没有授权的私人文件恢复密码？ | 库外，应该说明缺少本地依据 | presets / import / evidence / files / storage | False |
| [ ] | outside-05 我的视频主角叫什么名字？ | 库外，应该说明缺少本地依据 | mapping / import / container / mp4 / subtitles | False |

逐题检查：期望章节确实支持问题；实际候选包含该来源；引用正文与应用行为一致；库外五题不能只凭相似词就答为支持。记录错误标签和原因，保留原始评估，不根据机器得分修改答案。

本页勾选只记录人工意见。开发者收到实际反馈后再更新标签确认状态、冻结新版本并重跑；本阶段不会自动把 pending 改成 confirmed。
