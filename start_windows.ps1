$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RootDir

$PythonBin = if ($env:PYTHON_BIN) { $env:PYTHON_BIN } else { "python" }

try {
  & $PythonBin --version | Out-Null
} catch {
  Write-Host "未找到 Python。请先安装 Python 3.11+，或设置 PYTHON_BIN 指向 python.exe。"
  exit 1
}

if (-not (Test-Path ".venv")) {
  & $PythonBin -m venv .venv
}

$VenvPython = Join-Path $RootDir ".venv\Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip setuptools wheel
& $VenvPython -m pip install -r requirements.txt

if (-not (Test-Path "app_ui\node_modules")) {
  npm --prefix app_ui install
}

npm --prefix app_ui run build

$HostName = if ($env:HOST_NAME) { $env:HOST_NAME } else { "0.0.0.0" }
$Port = if ($env:PORT) { $env:PORT } else { "8010" }

Write-Host "启动 CosyVoice API Only: http://127.0.0.1:$Port"
& $VenvPython -m uvicorn api_server:app --host $HostName --port $Port
