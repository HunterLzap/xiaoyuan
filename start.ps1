param([int]$Port = 8000, [switch]$Devices, [int]$DevicePort = 8003)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$assistantPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $assistantPython)) {
    throw '请先执行 README 中的虚拟环境创建和依赖安装命令。'
}
Write-Host "API 配置页面：http://127.0.0.1:$Port/settings"
if ($Devices) {
    Write-Host "设备页面：http://127.0.0.1:$Port/devices"
    & $assistantPython -m backend.run_devices --admin-port $Port --device-port $DevicePort
    exit $LASTEXITCODE
}
& $assistantPython -m uvicorn backend.app.main:app --host 127.0.0.1 --port $Port --no-proxy-headers --log-level info
exit $LASTEXITCODE
