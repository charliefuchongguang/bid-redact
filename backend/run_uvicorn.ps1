$root = Split-Path $PSScriptRoot -Parent
Set-Location $PSScriptRoot
$log = Join-Path $root "data\logs\uvicorn.out.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
& (Join-Path $root ".venv\Scripts\python.exe") -m uvicorn app.main:app --host 127.0.0.1 --port 8000 *>> $log