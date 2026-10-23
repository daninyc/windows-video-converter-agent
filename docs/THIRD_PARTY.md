# 第三方与发布许可清单

本文件是工程来源盘点，不构成“全部可分发”的结论。自有源码许可证 C05 尚未由用户指定；候选包仅用于本机审阅，`BUILD.json` 的 `release_ready=false`，不得据此宣称已完成公开 Release。

## 候选包现有材料

每个候选包内 `THIRD_PARTY.json` 记录构建环境的包版本、已安装元数据中的许可与复制的文本路径。该表是构建环境的**超集**，不代表所有记录都实际打入包。`THIRD_PARTY/` 保留 wheel 自带许可 / 声明，保留相对目录以防同名文本互相覆盖；另附 Python PSF 文本与 Conda 原生运行库来源、版本、SHA 和可取得的上游许可文件。

基础包使用 onedir，Qt DLL 保持独立文件，FFmpeg / ffprobe 作为子进程执行；没有更改上游 DLL 或模型代码。FFmpeg 附带的 LICENSE 也复制进基础包。没有代码签名、自动更新或商店上架声明。

## 组件盘点

| 组件 | 来源依据 | 当前处理 / 待核对 |
|---|---|---|
| Python / PySide6 / Shiboken6 / Pydantic | 当前安装元数据、锁文件与包内文本 | 核对实际打包模块、各模块许可及对应源码提供方式 |
| Conda Python 的底层 DLL | `conda-meta` 的 python、expat、libffi、openssl、bzip2、xz、sqlite 记录 | 固定少量必要 DLL，未把整个 Conda Library/bin 混入；原文缺失项仍需补查 |
| FFmpeg / ffprobe | `services/components.json` 的 Gyan 固定归档与 SHA，二进制自身 build configuration、归档 LICENSE | 当前构建启用 GPL 组件；公开分发前核清该精确构建的对应源码 / 构建配置与自有项目许可安排 |
| MCP / HTTPX / MySQL Connector / 文档解析 / Qdrant client | 锁文件、`dependency-sources.json` 与已安装 wheel 元数据 | 保留版本与上游文本；实际分发闭包仍需最终审阅 |
| CPU Torch / Transformers / Sentence Transformers / Tokenizers / SentencePiece | CPU wheel 实际下载报告与锁文件 | 只放 AI 运行包，不放模型权重；许可文本按原样保留 |
| Qdrant / Ollama / MySQL 原生服务 | `services/components.json` 的版本、URL、摘要与许可字段 | 分别下载 / 校验 / 私有部署，归档文本仍需结合实际版本核验；不预装或分发已初始化数据库 |
| bge-m3 / bge-reranker-v2-m3 | 固定 Ollama digest 与 Hugging Face revision、逐文件摘要 | 权重独立准备；模型卡与原文许可随组件保存，不能把模型许可当自有源码许可 |
| Xiph Crowd Run | `docs/XIPH_TEST.md`、随附 SVT PDF 与固定摘要 | 仅本地测试素材，不进入源码 / Release 附件 |
| 本项目基础 / 压力视频与知识文本 | 自生成指令、manifest / 原创项目说明 | 不含私人视频；本地测试大文件不提交 Git |
| 界面参考 | `docs/UI_REFERENCE.md` | 只参考分区，没有复制模板源代码、图标、图片或样式，不将参考项目许可冒认为本项目许可 |

上游事实以精确版本原文为准。FFmpeg 对其启用组件的许可说明见 [FFmpeg 法律说明](https://ffmpeg.org/legal.html)；Qt for Python 的组件许可入口见 [官方许可清单](https://doc.qt.io/qtforpython-6/licenses.html)。本轮 Qt 官方页可访问，FFmpeg 页面工具读取超时；FFmpeg 构建许可字段同时来自本机已下载归档，网页内容本轮未成功复核，不补造源码下载包或公开源码 URL。

## 公开发布前仍需完成

1. 用户明确选择自有源码许可证；据实际分发组件核对兼容安排。
2. 把“构建环境超集”收敛为精确分发清单；补齐缺失许可 / notice、精确版本对应源码获取或提供方式。
3. 核清原生服务与模型再分发条件。当前清单是下载来源记录，不是项目维护者代替上游授予分发许可。
4. 包、源码、许可证材料与最终 commit 对齐后重新核验 SHA，再公开上传。

未知事项保持 pending，不为了完成票据把整个项目自动写成 MIT / LGPL，也不把未完成核验的候选包发布到 GitHub。
