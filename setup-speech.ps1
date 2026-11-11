param(
    [ValidateSet('kokoro','melo')][string[]]$Models = @('kokoro'),
    [switch]$SkipDownload
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
# Keep installers, caches, temporary downloads, and the venv in this project.
$speechCache = Join-Path $PSScriptRoot '.cache\speech'
New-Item -ItemType Directory -Force -Path (Join-Path $speechCache 'tmp') | Out-Null
$env:TEMP = Join-Path $speechCache 'tmp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $speechCache 'pip'
$env:HF_HOME = Join-Path $speechCache 'huggingface'
$env:TORCH_HOME = Join-Path $speechCache 'torch'
$env:XDG_CACHE_HOME = $speechCache
$speechPython = Join-Path $PSScriptRoot '.venv-speech\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $speechPython)) {
    $bootstrapPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $bootstrapPython)) { $bootstrapPython = 'python' }
    & $bootstrapPython -m venv (Join-Path $PSScriptRoot '.venv-speech')
    if ($LASTEXITCODE -ne 0) { throw 'Speech virtual environment creation failed' }
}
& $speechPython -m pip install -r (Join-Path $PSScriptRoot 'requirements-speech.txt')
if ($LASTEXITCODE -ne 0) { throw 'Speech dependency installation failed' }
if (-not $SkipDownload) {
    foreach ($modelName in $Models) {
        & $speechPython (Join-Path $PSScriptRoot 'scripts\speech.py') download --model $modelName
        if ($LASTEXITCODE -ne 0) { throw "Model preparation failed: $modelName" }
    }
}
Write-Output "Speech environment ready: $speechPython"
