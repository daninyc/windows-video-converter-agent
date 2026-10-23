# 开发环境配置与实测记录

检查日期：2026-10-21，北京时间。范围：仅准备开发环境，尚未开始客户端、Agent 或业务工具实现。

结论：本地开发依赖、视频处理、MCP 通信与 RAG 组件已安装并实际运行。DeepSeek 模型问答和网页搜索尚未认证联调，需要在联调时配置有效 API Key。环境检查不能替代应用验收。

## 1. 用户指定位置与隔离方式

用户要求 FFmpeg/ffprobe 使用 `D:\ffmpeg_ffprobe`，其余项在本项目内新建目录。因此采用：

| 内容 | 实际位置 |
|---|---|
| FFmpeg、ffprobe、构建包附带说明与许可 | `D:\ffmpeg_ffprobe\ffmpeg-9.0.2-essentials_build`，可执行文件在 `bin` |
| Python 隔离环境 | `D:\CodexWorkspace\bossjinzhoubishiti\environment\venv` |
| Ollama、Qdrant 可执行文件 | `environment\apps\ollama`、`environment\apps\qdrant` |
| bge-m3 模型 | `environment\models\ollama` |
| 独立重排模型 | `environment\models\reranker` |
| Qdrant、独立 MySQL 数据 | `environment\data\qdrant`、`environment\data\mysql` |
| 包缓存、模型缓存、构建缓存与临时文件 | `environment\cache`、`environment\tmp` |
| 下载包、日志、校验与测试结果 | `environment\downloads`、`environment\logs`、`environment\reports` |
| MySQL 加密凭据 | `environment\private\mysql-credentials.json` |

Python 复用 `D:\miniconda\python.exe` 创建独立 venv，没有向原 Python 环境安装本项目依赖。MySQL 复用现有安装的服务端二进制，使用独立数据目录、端口和账号。原来的 `MySQL80` 服务仍在运行，没有重置其密码或改动其数据库。

`activate.ps1` 设置的是当前进程的路径和缓存变量，没有修改系统 PATH、安装系统服务或添加开机启动。Ollama 子进程的个人配置目录单独指向项目内，模型和生成的私钥均位于 D 盘。下载复用了 Windows 已配置的代理，没有写死代理地址。

`environment/` 已加入项目 `.gitignore`。模型、大型二进制、数据库和私密配置不应随源码提交。

## 2. 已确认版本

以下版本来自本机命令、包清单和实际服务响应；完整清单与下载哈希见 [manifest.json](../environment/manifest.json) 和 [requirements.freeze.txt](../environment/requirements.freeze.txt)。

| 组件 | 实际版本或标识 | 状态 |
|---|---|---|
| Windows | Windows 11，系统构建 26100 | 本机运行 |
| Python | 3.13.9，x64 | venv 可用 |
| PowerShell | 7.6.5 | 本轮脚本运行版本；脚本使用 7.4+ 的能力 |
| PySide6 / Qt | 6.12.0 | Widgets、事件循环和图片加载通过 |
| PyInstaller | 6.22.3 | Qt 探针 exe 构建和执行通过 |
| FFmpeg / ffprobe | 9.0.2，Gyan essentials | 三种输出格式转换、解码与缩略图通过 |
| MCP SDK | 2.3.0 | 实际协商协议为 2026-07-28 |
| Qdrant / Python client | 1.19.2 / 1.19.1 | 实际服务、原生 BM25 与融合检索通过 |
| Ollama | 0.40.7 | 本地服务与 embedding 通过 |
| bge-m3 | `bge-m3:latest`，F16，1024 维 | 模型 digest：`9f9fde527ed75fe41f8782fd3d25524d72aa52cc4b3e1cafbfb38c473f6f561e` |
| 独立 reranker | `BAAI/bge-reranker-v2-m3` | 固定 revision：`953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` |
| Torch | 2.14.1+cpu | CPU 重排；Ollama 使用自己的 GPU 运行库 |
| Transformers / sentence-transformers | 5.20.2 / 6.1.0 | 本地加载及重排推理通过 |
| MySQL / Python connector | 8.0.46 / 26.7.0 | 独立实例认证和权限检查通过 |
| pypdf / python-docx | 6.21.1 / 1.2.0 | PDF/DOCX 依赖可用 |
| pytest / pytest-qt / pytest-asyncio | 9.1.1 / 4.5.0 / 1.4.0 | 测试工具可用 |
| Ruff | 0.17.1 | 环境探针检查通过 |

本轮还核实已有 Git、Visual C++ 构建工具和 C++ 运行库，无需重复安装。当前 NVIDIA 实测是 RTX 3060 Laptop GPU，6 GiB 显存；Ollama 已识别 CUDA 并在模型加载期间报告显存使用。不能把 CPU 版 Torch 的 `cuda_available=False` 当成显卡不可用。

## 3. 实际验证及证据

| 检查 | 结果与范围 | 证据 |
|---|---|---|
| Python 依赖 | `pip check` 无依赖冲突；版本冻结完成 | `reports/pip-packages.json`、`reports/python-inventory.json` |
| Qt | 控件信号、事件循环、中文文本和缩略图读取通过 | `reports/environment-junit.xml` |
| 文档依赖 | DOCX 中文写入再读取、PDF 内存读写通过；不是业务文件解析器验收 | 同上 |
| 视频处理 | 生成 2 秒测试源，转换 MP4/MKV/WebM，ffprobe 检查流与时长，完整解码通过；路径含中文和空格 | 同上 |
| MCP | 一个真实 stdio 服务进程，100 个并发请求、5 组显式标记返回一致；取消请求后仍可调用 | `reports/mcp-smoke.json` |
| MySQL | 只读账号能查询，DELETE/CREATE 被 1142 拒绝；写入账号事务回滚通过 | `reports/mysql-smoke.json` |
| Embedding | bge-m3 实际输出 1024 维、有限且归一化的向量 | `reports/rag-smoke.json` |
| 混合检索 | 本地服务执行 dense + 原生多语言 BM25 + RRF；重复 upsert 后仍只有 3 条；测试 collection 已移除 | 同上 |
| 独立重排 | CPU、4 线程对 3 条中英文编码相关样本评分，相关内容排首位 | 同上 |
| Qt 打包 | 生成独立目录 exe，启动并完成控件信号自检；另行检查 Windows 平台插件可加载 | `reports/packaging-smoke.json`、`reports/packaging-windows-smoke.json` |
| 服务生命周期 | 重复启动复用已有实例；停止、重启和数据库持久化检查通过 | `start-services.ps1`、`stop-services.ps1`、`reports/services.json` |
| DeepSeek 连通性 | 未带凭据访问 `/models` 返回 401；没有发起模型或搜索请求 | `reports/deepseek-connectivity.json` |

性能记录只反映本机的小样本：最初 4 条 embedding 请求含首次加载约 57.02 秒；后续独立短文本请求约 4.61 秒，紧接着的已加载请求约 0.036 秒。reranker 加载约 6.46 秒，3 对短文本推理约 0.964 秒。这些不是吞吐量、并发容量或产品延迟承诺。实现时需要处理首次加载等待，不能据此宣称性能验收通过。

MCP 探针验证的是 SDK 与传输兼容性，尚未实现 5 个真实 Agent 会话、工具队列、去重、幂等、审计或高并发业务验收。RAG 的 3 条样本只证明组件可组合使用，不能替代 Spec 中的检索质量评估集。

## 4. 启动、停止与复查

以下命令在 PowerShell 7.4+ 中执行，本次实际使用 7.6.5；没有验证 Windows PowerShell 5.1 兼容性。本机现有 PowerShell 可执行文件为：

`C:\Users\33072\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\powershell\pwsh.exe`

进入项目并加载当前终端环境：

```powershell
Set-Location 'D:\CodexWorkspace\bossjinzhoubishiti'
. .\environment\activate.ps1
```

启动三个本地服务，可重复执行：

```powershell
.\environment\start-services.ps1
```

| 服务 | 地址 | 项目用途 |
|---|---|---|
| Qdrant REST / gRPC | `127.0.0.1:6333` / `127.0.0.1:6334` | 本地向量与词法检索 |
| Ollama | `127.0.0.1:11434` | bge-m3 embedding，云功能关闭 |
| 项目 MySQL | `127.0.0.1:3307` | 数据库 `video_converter_env`，仅环境探针数据 |

MySQL 使用 `env_reader` / `env_writer` 分别验证查询和写入权限。密码由本机生成，以 Windows DPAPI 加密保存，同时限制私密目录权限，不写入文档、命令参数或版本库。这些凭据绑定当前 Windows 用户，不适合作为交付给评审的默认密码。

停止本项目启动的服务：

```powershell
.\environment\stop-services.ps1
```

脚本会核对可执行文件、PID 和启动时间，避免停止其他进程。MySQL 使用认证后的关闭命令；Qdrant 与 Ollama 停止对应的项目进程。原有 `MySQL80` 不在控制范围内。项目服务不会随 Windows 自动启动。

复查依赖、Qt、视频处理、文档依赖与 MCP：

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python -m pip check
python -m pytest .\environment\smoke\test_environment.py -q --basetemp .\environment\tmp\pytest --junitxml .\environment\reports\environment-junit.xml
python -m ruff check .\environment\smoke
.\environment\mysql-control.ps1 -Action check
```

复查完整本地 RAG 链路，需要三个服务已经启动：

```powershell
python .\environment\smoke\rag_probe.py
```

复查打包工具：

```powershell
.\environment\check-packaging.ps1
```

该脚本仅构建 Qt 环境探针；不会构建视频转换器。所有构建产物与日志在 `environment` 下。

## 5. 遇到的问题与解决办法

1. 命令行直连 GitHub 速度慢，Hugging Face 连接超时：读取 Windows 已有代理配置并仅用于当前进程后完成下载；不使用未核验的第三方二进制。
2. 第一次 MCP 检查假设裸 `dict` 注解会生成结构化输出，实际返回文本：探针改为 `dict[str, str]` 并显式启用结构化输出，重新检查通过。
3. 第一次 Qt 打包从其他工具的 Poppler 路径拾取了不兼容的 `icuuc.dll`：对构建进程隔离 PATH 后打包和 Windows 插件检查通过，没有删除其他工具的 DLL。
4. Ollama 启动时移除了尚为空的模型 manifest 目录：下载完成后重建目录再写入 manifest，模型已被服务识别并成功推理。
5. 服务生命周期检查发现 PowerShell 会将 ISO 时间反序列化为 DateTime：改为比较 UTC ticks。另发现 MySQL 在 Windows 下的监控进程与监听进程可能不同，改为核验并记录实际监听进程。项目 MySQL 增加独立的 loopback 管理账号匹配，认证关闭与重启已通过。调试中仅重启过项目新建的探针实例。

## 6. 下载来源与校验

- FFmpeg 使用 [FFmpeg 下载页](https://ffmpeg.org/download.html)列出的 [Gyan Windows builds](https://www.gyan.dev/ffmpeg/builds/)，下载 release essentials 9.0.2 ZIP，并核对发布方 SHA-256。
- Ollama 使用[官方 v0.40.7 Release](https://github.com/ollama/ollama/releases/tag/v0.40.7) 的 Windows amd64 ZIP，并核对发布资产 SHA-256。
- Qdrant 使用[官方 v1.19.2 Release](https://github.com/qdrant/qdrant/releases/tag/v1.19.2) 的 Windows MSVC ZIP，并核对发布资产 SHA-256。
- bge-m3 从 [Ollama 官方 registry manifest](https://registry.ollama.ai/v2/library/bge-m3/manifests/latest) 下载各 blob，逐个核对 manifest 中的 SHA-256；完整 manifest 已保存在本地。
- reranker 使用 [BAAI 官方模型仓库](https://huggingface.co/BAAI/bge-reranker-v2-m3)，固定 revision。7 个文件全部与该 revision 的元数据核对：LFS 文件使用 SHA-256，其余使用 Git blob SHA-1。
- CPU Torch 使用 [PyTorch 官方 CPU wheel 源](https://download.pytorch.org/whl/cpu)；其余 Python 包使用 PyPI。pip 安装报告包含具体下载地址和包哈希。
- [Qdrant 官方文本检索说明](https://qdrant.tech/documentation/search/text-search/full-text-search/)与本机实际请求共同确认原生 BM25/多语言分词可用；没有安装 `rank_bm25` 替代独立重排。

## 7. 尚未做的事情

- 未配置 DeepSeek API Key，未验证 `deepseek-v4-pro` 的认证、多轮工具调用、流式输出或网页搜索。按用户意见在需要联调时再使用评审自备 Key 或用户临时提供的 Key，不提前消耗一小时有效期。
- 未开始应用业务代码、UI 布局实现、业务数据库表、正式 MCP 工具或知识库内容建设。
- 未进行真实视频压力测试、5 个 Agent 会话并发验收、RAG 质量评估或完整应用打包验收。
- 当前 Qt 探针只在这台电脑运行过，尚未证明最终便携包在无开发环境的另一台 Windows 机器上可用。
- 未初始化 Git 仓库、创建 GitHub 仓库、提交代码或发布 Release；后续仍须按用户确认的阶段推进。
