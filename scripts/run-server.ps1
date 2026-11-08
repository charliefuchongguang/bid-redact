$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$backend = Join-Path $root 'backend'
$Host.UI.RawUI.WindowTitle = '投标文件自动脱敏 - 服务运行中（关闭此窗口即停止）'
$env:APP_SUPERVISED = '1'

$exitCode = 0
while ($true) {
    Set-Location -LiteralPath $backend
    & $python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
    $exitCode = $LASTEXITCODE
    if ($exitCode -eq 75) {
        Write-Host ''
        Write-Host '检测到重启请求，正在重新启动服务...' -ForegroundColor Cyan
        Start-Sleep -Seconds 1
        continue
    }
    break
}

if ($exitCode -ne 0) {
    Write-Host ''
    Write-Host "服务已退出（exit $exitCode）。请查看上方错误信息。" -ForegroundColor Red
    Read-Host '按回车关闭'
}