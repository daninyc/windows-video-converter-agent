$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$targetFile = Join-Path $projectRoot 'artifacts/review-target.json'
if (-not (Test-Path -LiteralPath $targetFile)) {
    throw '验收入口尚未准备好，请先查看 docs/ACCEPTANCE.md。'
}
$target = Get-Content -LiteralPath $targetFile -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not (Test-Path -LiteralPath $target.executable)) {
    throw '验收程序不存在，请核对 review-target.json 和打包验收报告。'
}
Start-Process -FilePath $target.executable -ArgumentList @('--data-dir', ('"' + $target.data_dir + '"')) -WorkingDirectory $projectRoot -WindowStyle Normal
