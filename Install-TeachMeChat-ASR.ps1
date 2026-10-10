param(
    [ValidateSet('Cpu', 'ExistingTorch')]
    [string]$Backend = 'Cpu',
    [switch]$DownloadTurbo
)
$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
$runtime = Join-Path $project '.teachmechat-runtime'
$python = Join-Path $runtime 'venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Run Start-TeachMeChat.ps1 -Install first.' }
if (-not [IO.Path]::IsPathRooted($runtime) -or $runtime.StartsWith('\\') -or $runtime.StartsWith('//')) { throw 'Runtime must be a local absolute path (network paths are not supported).' }
$dirs = @{ TEMP='tmp'; TMP='tmp'; TMPDIR='tmp'; PIP_CACHE_DIR='cache\pip'; XDG_CACHE_HOME='cache'; HF_HOME='cache\huggingface'; TORCH_HOME='cache\torch'; NUMBA_CACHE_DIR='cache\numba'; CUDA_CACHE_PATH='cache\cuda' }
foreach ($entry in $dirs.GetEnumerator()) {
    $path = Join-Path $runtime $entry.Value
    New-Item -ItemType Directory -Force -Path $path | Out-Null
    [Environment]::SetEnvironmentVariable($entry.Key, $path, 'Process')
}
$env:TEACHMECHAT_HOME = $runtime
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
Write-Host 'Optional ASR install: downloads PyTorch/Whisper into the local project runtime. Several GB of free space may be needed.'
Push-Location $project
try {
    if ($Backend -eq 'Cpu') {
        & $python -B -m pip install --no-compile 'torch>=2.6' --index-url https://download.pytorch.org/whl/cpu
        if ($LASTEXITCODE -ne 0) { throw 'CPU PyTorch installation failed.' }
    } else {
        & $python -B -c "import torch; print(torch.__version__)"
        if ($LASTEXITCODE -ne 0) { throw 'Install a compatible PyTorch into the local project venv first.' }
    }
    & $python -B -m pip install --no-compile openai-whisper
    if ($LASTEXITCODE -ne 0) { throw 'Whisper installation failed.' }
    if ($DownloadTurbo) {
        & $python -B -m teachmechat.download_model
        if ($LASTEXITCODE -ne 0) { throw 'Model download failed.' }
    }
} finally { Pop-Location }
