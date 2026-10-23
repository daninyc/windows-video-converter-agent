# 从源码准备环境

普通使用者优先使用基础便携包和 AI 组件包，见 `ACCEPTANCE.md`。下面面向新克隆的开发者，不依赖本机未提交的 `environment/activate.ps1`；这套空白环境重建说明尚未在另一台干净机器执行，不能作为 T15 通过证据。

要求 Windows x64、CPython 3.13（项目声明 `>=3.13,<3.14`）及可访问固定依赖下载源。当前实测构建使用 Conda Python 3.13.9，普通 Python 发行版的重新构建未实测。把项目解压 / 克隆到 D 盘，例如 `D:\CodexWorkspace\bossjinzhoubishiti`，不要复制旧机器的 venv、数据库、密文凭据。

在项目根目录 PowerShell 执行。下面的 `python` 应先由开发者指向已安装的 CPython 3.13：

```powershell
$projectRoot = (Get-Location).Path
if (-not $projectRoot.StartsWith('D:\', [StringComparison]::OrdinalIgnoreCase)) { throw '请先进入 D 盘项目目录' }
New-Item -ItemType Directory -Force environment, environment/cache/pip, artifacts/tmp | Out-Null
$env:PIP_CACHE_DIR = Join-Path $projectRoot 'environment/cache/pip'
$env:TEMP = Join-Path $projectRoot 'artifacts/tmp'
$env:TMP = $env:TEMP
$env:HF_HOME = Join-Path $projectRoot 'environment/cache/huggingface'
$env:TORCH_HOME = Join-Path $projectRoot 'environment/cache/torch'
$env:XDG_CACHE_HOME = Join-Path $projectRoot 'environment/cache'
python -m venv environment/venv
$taskPython = Join-Path $projectRoot 'environment/venv/Scripts/python.exe'
& $taskPython -m pip install -r requirements-dev.lock
& $taskPython -m pip install --no-deps --no-build-isolation -e .
& $taskPython -m pip check
& $taskPython -m media_converter.devtools prepare --components core --data-dir data
& $taskPython -m media_converter.devtools fixtures --profile smoke --root artifacts/fixtures --data-dir data
& $taskPython -m media_converter --data-dir data
```

锁文件为版本固定快照，普通 wheel 没有完整 `--require-hashes` 集；不得给安装命令虚加该参数后宣称可复现。CPU Torch 使用锁文件中实际下载的直接 URL 和 SHA-256，不切换成 CUDA 或浮动版本。如果固定版本下载不可用，保留错误并调查，不能静默升级。

需要本地 AI 时，从 GUI 选择“私有组件”，或先关闭 GUI 后执行：

```powershell
& $taskPython -m media_converter.devtools prepare --components ai --mode private --data-dir data --output artifacts/reports/prepare-source.json
& $taskPython -m media_converter --data-dir data
```

CLI 私有检查结束会关闭所属服务；GUI 在同数据目录恢复私有准备后再使用。本流程不要求预先装 MySQL / Docker，不重置系统 root，也不索取在线 API。原生组件、模型的固定来源 / 摘要见 `src/media_converter/services/components.json`，首次下载可能较大，以向导空间计划为准。

后续测试命令与 README 一致，把 `python` 替换为 `& $taskPython`。只跑本地测试，不传 `--live-api`。Xiph 样本与素材授权、固定摘要见 `XIPH_TEST.md`，缺少时该可选测试跳过；不要把私人视频或已初始化数据目录加入 Git。

在最终源码上构建：

```powershell
& $taskPython -m media_converter.devtools build-windows --data-dir data --output dist
& $taskPython -m media_converter.devtools smoke-package --package dist/MediaConverter-Windows-x64.zip --without-dev-path --output artifacts/reports/package-smoke.json
```

构建时源码变动会拒绝产物；重新构建后才能引用它的哈希。公开发布还需 `TEST_REPORT.md` / `THIRD_PARTY.md` 中的人工、独立机、真实 API 和许可门槛，不以本页命令代替实际运行记录。
