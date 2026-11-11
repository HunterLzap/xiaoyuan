$ErrorActionPreference = 'Continue'
$env:IDF_TOOLS_PATH = 'E:\xiaodan\firmware\.espressif'
$env:TEMP = 'E:\xiaodan\firmware\.tmp'
$env:TMP = 'E:\xiaodan\firmware\.tmp'
$env:PIP_CACHE_DIR = 'E:\xiaodan\firmware\.cache\pip'
$env:IDF_GITHUB_ASSETS = 'dl.espressif.cn/github_assets'
$env:IDF_COMPONENT_CACHE_PATH = 'E:\xiaodan\firmware\.cache\component_manager'
$env:CCACHE_DIR = 'E:\xiaodan\firmware\.cache\ccache'
New-Item -ItemType Directory -Force -Path $env:TEMP, $env:PIP_CACHE_DIR, $env:IDF_COMPONENT_CACHE_PATH, $env:CCACHE_DIR | Out-Null

$idf = 'E:\xiaodan\firmware\esp-idf-v5.5.2'
$py  = 'E:\xiaodan\firmware\.espressif\python_env\idf5.5_py3.12_env\Scripts\python.exe'
$env:IDF_PATH = $idf

$curPath = $env:PATH
$exportLines = & $py "$idf\tools\idf_tools.py" export --format key-value 2>$null
foreach ($line in $exportLines) {
    if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
        $name = $matches[1]; $val = $matches[2] -replace '%PATH%', $curPath
        Set-Item -Path "env:$name" -Value $val
    }
}

$proj = 'E:\xiaodan\firmware\xiaozhi-esp32'
Set-Location $proj
$defaults = 'sdkconfig.defaults;sdkconfig.defaults.esp32s3;sdkconfig.defaults.atoms3r-tafei-mn5'

Write-Output "===== BUILD MN5 TRIAL ====="
& cmd.exe /d /c "E:\xiaodan\firmware\build-mn5.bat" 2>&1
Write-Output "mn5-build-exit=$LASTEXITCODE"
Write-Output "===== MN5 BUILD DONE ====="
