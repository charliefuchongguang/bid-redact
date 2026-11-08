$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root '.venv'
$python = Join-Path $venv 'Scripts\python.exe'
$envFile = Join-Path $root '.env'
$frontend = Join-Path $root 'frontend'
$model = Join-Path $root 'data\models\insightface\det_10g.onnx'

Write-Host '=== 投标文件自动脱敏 · 首次安装 ===' -ForegroundColor Cyan

if (-not (Test-Path -LiteralPath $python)) {
    $basePython = $null
    foreach ($candidate in @('py -3.12', 'py -3', 'python')) {
        try {
            $parts = $candidate.Split(' ')
            $command = Get-Command $parts[0] -ErrorAction Stop
            if ($parts.Length -gt 1) {
                & $command.Source $parts[1] --version *> $null
            } else {
                & $command.Source --version *> $null
            }
            if ($LASTEXITCODE -eq 0) { $basePython = $candidate; break }
        } catch {}
    }
    if (-not $basePython) {
        Write-Host '未找到 Python 3.12。请先安装 Python 3.12，并勾选 Add Python to PATH。' -ForegroundColor Red
        Read-Host '按回车关闭'
        exit 1
    }
    Write-Host "正在创建虚拟环境（$basePython）..."
    if ($basePython -eq 'py -3.12') { py -3.12 -m venv $venv } else { python -m venv $venv }
    if ($LASTEXITCODE -ne 0) { throw '创建虚拟环境失败' }
}

if (-not (Test-Path -LiteralPath $envFile)) {
    Copy-Item -LiteralPath (Join-Path $root '.env.example') -Destination $envFile
    Write-Host '已生成 .env。请填写 MINERU_API_TOKEN。' -ForegroundColor Yellow
}

Write-Host '正在安装后端依赖...'
& $python -m pip install --upgrade pip
& $python -m pip install -r (Join-Path $root 'requirements.txt')
& $python -m pip install --no-deps 'insightface==2.1'
& $python -m pip install -r (Join-Path $root 'requirements-face.txt')

if (-not (Test-Path -LiteralPath $model)) {
    Write-Host '未找到 InsightFace 人脸检测模型。' -ForegroundColor Yellow
    $answer = Read-Host '如已取得 InsightFace 预训练模型授权，输入 Y 下载模型；否则直接回车跳过'
    if ($answer -match '^[Yy]') {
        Push-Location -LiteralPath (Join-Path $root 'backend')
        try {
            & $python -m scripts.download_face_model --pack buffalo_l --accept-license
        } finally {
            Pop-Location
        }
    } else {
        Write-Host '已跳过模型下载。身份证头像检测将不可用。' -ForegroundColor Yellow
    }
}

if (Get-Command npm -ErrorAction SilentlyContinue) {
    Write-Host '正在构建前端...'
    Push-Location -LiteralPath $frontend
    try {
        npm install
        if ($LASTEXITCODE -ne 0) { throw 'npm install 失败' }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'npm run build 失败' }
    } finally {
        Pop-Location
    }
} else {
    Write-Host '未安装 Node.js/npm，跳过前端构建。请安装 Node.js 20+ 后重新运行本安装。' -ForegroundColor Yellow
}

Write-Host '正在初始化数据库...'
Push-Location -LiteralPath (Join-Path $root 'backend')
try {
    & $python -m app.db.init_db
} finally {
    Pop-Location
}

Write-Host ''
Write-Host '安装完成。以后双击「启动投标脱敏工具.bat」即可使用。' -ForegroundColor Green
Read-Host '按回车关闭'