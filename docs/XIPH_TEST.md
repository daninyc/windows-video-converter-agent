# X01：Xiph Crowd Run 真实素材补充测试

用户在转换闭环 009–019 之后追加一项 Xiph 媒体库测试。本项使用完整 Crowd Run 序列，通过现有 ImportService → ProbeService → ThumbnailService → ConversionPlanner → JobService → OutputValidator 执行，归入 SPEC 的 T01/T02/T05。

## 素材与许可

- 素材：[Xiph Derf 媒体库](https://media.xiph.org/video/derf/) 的 `crowd_run_1080p50.y4m`；目标为完整 1920×1080、50 fps、500 帧、10 秒、无音频的 Y4M 输入。
- 原作者：Sveriges Television AB（SVT）。[原始说明与使用限制 PDF](https://media.xiph.org/video/derf/vqeg.its.bldrdoc.gov/HDTV/SVT_MultiFormat/SVT_MultiFormat_v10.pdf) 将 CrowdRun 列为较难编码序列；用途限开发、测试和展示技术标准，再分发须附该说明且不得收取分发费。该说明针对 SVT 素材，不能据此推断整个 Xiph 媒体库的许可。
- 许可 PDF 随下载素材保存在同一目录。素材及输出只作本地编码技术测试，不加入项目分发包；若未来分发，须重新核对原始使用限制并随附完整说明。
- 固定来源、字节数、SHA-256 和本次下载时间保存在 [素材清单](test-media/xiph-crowd-run.json)。哈希由本次下载后本机计算，用于复现时检测变化，并非发行方签名或官方公布的校验值。

## 复现

先在项目目录单独下载公开素材。视频约 1.56 GB，另有许可 PDF；保留额外空间供输出和临时文件使用。以下命令只在目标文件不存在时下载，已有文件由测试核对，不覆盖：

```powershell
Set-Location 'D:\CodexWorkspace\bossjinzhoubishiti'
. .\environment\activate.ps1
$xiphRoot = Join-Path (Get-Location) 'artifacts\fixtures\xiph'
New-Item -ItemType Directory -Force -Path $xiphRoot | Out-Null
$xiphManifest = Get-Content 'docs\test-media\xiph-crowd-run.json' -Raw | ConvertFrom-Json
foreach ($xiphItem in @($xiphManifest.license, $xiphManifest.source)) {
    $xiphTarget = Join-Path $xiphRoot $xiphItem.file
    if (-not (Test-Path -LiteralPath $xiphTarget)) {
        Invoke-WebRequest -Uri $xiphItem.url -OutFile $xiphTarget
    }
}
python -m pytest tests/integration/test_xiph_conversion.py -q --xiph-root artifacts/fixtures/xiph --junitxml artifacts/reports/xiph.xml
```

下载不在 pytest 内执行，默认网络拦截持续有效。没有 `--xiph-root` 时本项明确跳过；显式启用后，缺文件、文件长度或哈希不符直接失败。中断下载留下的文件须先移走，再重新下载，不接受不完整输入。

联合回归命令（保留原转换报告，另写新报告）：

```powershell
python -m pip check
python -m ruff check src tests
python -m ruff format --check src tests
python -m pytest tests/unit tests/gui tests/integration -q --fixture-root artifacts/fixtures --data-dir data --xiph-root artifacts/fixtures/xiph --junitxml artifacts/reports/conversion-xiph.xml
```

## 检查内容与计时口径

业务参数为 MP4、libx264、CRF 23，保持原尺寸和帧率；现有规划器设置编码线程为 2。没有合成、裁切或缩短原始序列。检查输出 1920×1080、H.264、50 fps、500 帧、无额外音轨，执行完整解码，并检查原件 SHA-256 不变、SUCCEEDED 已持久化、转换峰值并发为 1、结束后无所属转换进程和临时目录。

每次测试在 `artifacts/xiph-acceptance/<UUID>/` 保存输出、缩略图、独立 SQLite 与 `evidence.json`；JUnit 记录该证据路径。证据含源元数据、完整参数快照、状态/进度、PID/启动时间/二进制及参数哈希、输出探测与哈希。

`ffmpeg_run_seconds` 是 RUNNING 到 VERIFYING 的本机墙钟时间，包含进程启动和相邻状态处理；平均 fps = 500 / 该时间，实时倍数 = 10 / 该时间。`batch_seconds` 包含批次登记、转码、输出验证与发布；`end_to_end_seconds` 从导入前计至帧数复核及原件复核完成，不包含下载、初始素材哈希和工具链检查。计时只描述本次机器和缓存条件，未做多轮统计，不设置未经确认的速度门槛。

本项不代表已完成 4K、30 分钟、50 文件队列、GUI 响应性、AI 并行或画质评价；也不替代三目标 GUI 原有验收。

## 本次结果

2026-10-21，本次按两条 pytest 命令分别执行：原有回归 **95 项通过**（83.04 秒），新增 Xiph 项 **1 项通过**（81.09 秒），接受的最终结果合计 **96 通过，0 失败、0 错误、0 跳过**。`pip check`、Ruff 检查及 81 个 Python 文件的格式检查通过。机器为 Windows 11 26100、Intel Core i5-12450H、8 核/12 逻辑处理器、RAM 16,911,847,424 字节，使用现有 FFmpeg 9.0.2 essentials。

| 项目 | 本次实测 |
|---|---|
| 原始文件 | 1,555,203,036 字节，1920×1080、50 fps、10 秒、500 帧、无音频 |
| 输出 | MP4/H.264、1920×1080、50 fps、500 帧，30,468,891 字节 |
| 编码阶段墙钟时间 | 63.97 秒，平均 7.82 fps，0.156 倍实时速度 |
| 批次时间（含输出验证、发布） | 65.74 秒 |
| 导入至帧数、原件复核完成 | 77.92 秒（计时边界见上文） |
| 完整解码、输出帧数/帧率 | 通过；完整解码计数为 500 帧、50/1 fps |
| 原件保护、持久化 | 转换前后 SHA-256 相同；SUCCEEDED 与 SQLite 一致 |
| 所属进程与临时目录 | 转换峰值并发 1；结束后活动转换进程为 0，所属临时目录清理完毕 |

实际测试命令（原有回归期间素材仍在单独下载）：

```powershell
python -m pytest tests/unit tests/gui tests/integration -q --fixture-root artifacts/fixtures --data-dir data --ignore=tests/integration/test_xiph_conversion.py --junitxml artifacts/reports/conversion-xiph-regression.xml
python -m pytest tests/integration/test_xiph_conversion.py -q --xiph-root artifacts/fixtures/xiph --junitxml artifacts/reports/xiph.xml
```

- [汇总 JSON](../artifacts/reports/xiph-summary.json)；[原有回归 JUnit](../artifacts/reports/conversion-xiph-regression.xml)；[新增项 JUnit](../artifacts/reports/xiph.xml)。
- [最终证据 JSON](../artifacts/xiph-acceptance/a5de236a-1c3b-45cd-b71d-38bbf5e6d31f/evidence.json)；[实际转换输出](../artifacts/xiph-acceptance/a5de236a-1c3b-45cd-b71d-38bbf5e6d31f/outputs/crowd_run_1080p50.mp4)。
- 源文件 SHA-256：`e056e01fc13906dd9a84f5cc686a36888436379476577965a0866821caaf55c8`。
- 输出 SHA-256：`a099617bddbc6100acf8c371cafcd56d15c6662b735114b103ed581af52a9e82`。

首次新增测试已经完成实际转换和完整解码，但新增断言误将启动阶段合法的未知进度 `None` 当作数字排序，测试因此失败。已修正为只检查已知时间戳的单调性，并要求结束时有有效时间戳，随后完整重跑通过。保留 [首次失败 JUnit](../artifacts/reports/xiph-first-failed.xml) 和对应运行产物，不计入上述接受结果。95 项回归未因这处测试断言修正重复执行；应用源码在其通过后没有再次变更。
