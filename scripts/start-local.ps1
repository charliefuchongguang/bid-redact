$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
$frontend = Join-Path $root 'frontend'
$distIndex = Join-Path $frontend 'dist\index.html'
$envFile = Join-Path $root '.env'
$url = 'http://127.0.0.1:8000'

function Test-AppReady {
    try {
        $response = Invoke-WebRequest -Uri "$url/api/health" -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    } catch {
        return $false
    }
}

function Wait-AppReady {
    param([int]$Seconds = 90)
    for ($i = 0; $i -lt $Seconds; $i++) {
        if (Test-AppReady) { return $true }
        Start-Sleep -Seconds 1
    }
    return $false
}

if (Test-AppReady) {
    Write-Host '服务已经在运行，正在打开浏览器...'
    Start-Process $url
    exit 0
}

if (-not (Test-Path -LiteralPath $python)) {
    Write-Host ''
    Write-Host '未找到 Python 运行环境：.venv\Scripts\python.exe' -ForegroundColor Yellow
    Write-Host '请先双击项目根目录的「首次安装.bat」，或让管理员完成环境安装。'
    Write-Host ''
    Read-Host '按回车关闭'
    exit 1
}

if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath (Join-Path $root '.env.example') -Destination $envFile
    Write-Host '已生成 .env。首次使用请在 .env 中填写 MINERU_API_TOKEN，否则扫描件无法处理。' -ForegroundColor Yellow
}

$faceModel = Join-Path $root 'data\models\insightface\det_10g.onnx'
if (-not (Test-Path -LiteralPath $faceModel)) {
    Write-Host '未找到 InsightFace 人脸检测模型，身份证头像检测可能失败。请运行「首次安装.bat」补装模型。' -ForegroundColor Yellow
}

if (-not (Test-Path -LiteralPath $distIndex)) {
    Write-Host '未找到前端构建产物，正在构建前端...'
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
        Write-Host '未安装 Node.js/npm，无法构建前端。请先运行「首次安装.bat」。' -ForegroundColor Yellow
        Read-Host '按回车关闭'
        exit 1
    }
    Push-Location -LiteralPath $frontend
    try {
        npm install
        if ($LASTEXITCODE -ne 0) { throw 'npm install 失败' }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'npm run build 失败' }
    } finally {
        Pop-Location
    }
}

$runServer = Join-Path $root 'scripts\run-server.ps1'

Start-Process -FilePath 'powershell.exe' -ArgumentList @(
    '-NoProfile',
    '-NoExit',
    '-ExecutionPolicy', 'Bypass',
    '-File', $runServer
)

Write-Host '正在启动服务...'
if (Wait-AppReady) {
    Write-Host "服务已启动：$url"
    Start-Process $url
    Write-Host '浏览器已打开。关闭服务窗口即可停止服务。'
    Start-Sleep -Seconds 2
} else {
    Write-Host '服务启动超时，请查看服务窗口中的错误信息。' -ForegroundColor Red
    Read-Host '按回车关闭'
    exit 1
}