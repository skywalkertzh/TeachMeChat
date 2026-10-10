param(
    [string]$Python = '',
    [switch]$Install,
    [switch]$Diagnostics,
    [switch]$Tests,
    [switch]$ReleaseCheck,
    [switch]$Cli,
    [switch]$Demo,
    [string]$ConfigDir = ''
)
$ErrorActionPreference = 'Stop'
$project = $PSScriptRoot
$runtime = Join-Path $project '.teachmechat-runtime'
if (-not [IO.Path]::IsPathRooted($runtime) -or $runtime.StartsWith('\\') -or $runtime.StartsWith('//')) { throw 'TeachMeChat runtime must be a local absolute path (network paths are not supported).' }
$dirs = @{
    TEMP='tmp'; TMP='tmp'; TMPDIR='tmp'; PIP_CACHE_DIR='cache\pip';
    XDG_CACHE_HOME='cache'; HF_HOME='cache\huggingface'; HF_HUB_CACHE='cache\huggingface\hub';
    HUGGINGFACE_HUB_CACHE='cache\huggingface\hub'; TORCH_HOME='cache\torch';
    TRANSFORMERS_CACHE='cache\huggingface\transformers'; NUMBA_CACHE_DIR='cache\numba';
    MPLCONFIGDIR='cache\matplotlib'; CUDA_CACHE_PATH='cache\cuda';
    TRITON_CACHE_DIR='cache\triton'; PYTHONPYCACHEPREFIX='cache\pycache'
}
foreach ($entry in $dirs.GetEnumerator()) {
    $path = Join-Path $runtime $entry.Value
    New-Item -ItemType Directory -Force -Path $path | Out-Null
    [Environment]::SetEnvironmentVariable($entry.Key, $path, 'Process')
}
$env:TEACHMECHAT_HOME = $runtime
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:DO_NOT_TRACK = '1'
$env:PYTHONUTF8 = '1'
$venvPython = Join-Path $runtime 'venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    if (-not $Install) { throw 'Environment not installed. Run this script with -Install first.' }
    if (-not $Python -and $env:TEACHMECHAT_PYTHON) { $Python = $env:TEACHMECHAT_PYTHON }
    if (-not $Python) {
        foreach ($candidate in @('python.exe', 'py.exe')) {
            $found = Get-Command $candidate -ErrorAction SilentlyContinue
            if ($found) { $Python = $found.Source; break }
        }
    }
    if (-not $Python -or -not (Test-Path -LiteralPath $Python)) { throw 'Provide -Python with an existing Python 3.10+ executable (e.g. -Python C:\Python310\python.exe) or set TEACHMECHAT_PYTHON.' }
    & $Python -B -c "import sys; assert sys.version_info >= (3,10), 'Python 3.10+ required'"
    if ($LASTEXITCODE -ne 0) { throw 'Unsupported Python.' }
    & $Python -B -m venv (Join-Path $runtime 'venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the local virtual environment.' }
}
Push-Location $project
try {
    if ($Install) {
        $requirements = Join-Path $project 'teachmechat\requirements-lock.txt'
        if (-not (Test-Path $requirements)) { $requirements = Join-Path $project 'teachmechat\requirements.txt' }
        & $venvPython -B -m pip install --no-compile -r $requirements
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; no application was started.' }
        Write-Host 'Installed. No models were downloaded. Start without -Install to run.'
    } elseif ($ReleaseCheck) {
        & $venvPython -B -m teachmechat --release-check
    } elseif ($Tests) {
        & $venvPython -B -m teachmechat --test
    } elseif ($Diagnostics) {
        & $venvPython -B -m teachmechat --diagnostics
    } else {
        $appArgs = @('-B', '-m', 'teachmechat')
        if ($Cli) { $appArgs += '--cli' }
        if ($Demo) { $appArgs += '--demo' }
        if ($ConfigDir) { $appArgs += @('--config-dir', $ConfigDir) }
        & $venvPython @appArgs
    }
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}
exit $code
