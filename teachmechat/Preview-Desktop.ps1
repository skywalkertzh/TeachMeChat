param([switch]$Settings,[switch]$Analysis,[switch]$Generating,[double]$Scale=1,[int]$Width=1360,[int]$Height=860)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$runtime=Join-Path $root '.teachmechat-runtime'
$env:TEMP=Join-Path $runtime 'tmp'
$env:TMP=$env:TEMP
$env:TMPDIR=$env:TEMP
$env:PYTHONDONTWRITEBYTECODE='1'
$env:PYTHONUTF8='1'
$env:QT_SCALE_FACTOR="$Scale"
$python=Join-Path $runtime 'venv\Scripts\python.exe'
$name=if ($Settings) {'settings'} elseif ($Analysis) {'analysis'} elseif ($Generating) {'generating'} else {"desktop-${Width}-${Scale}"}
$args=@('-B','-m','teachmechat.desktop.preview','--output',(Join-Path $runtime "previews\$name.png"),'--width',"$Width",'--height',"$Height")
if ($Settings) { $args+='--settings' }
if ($Analysis) { $args+='--analysis' }
if ($Generating) { $args+='--generating' }
Push-Location $root
try { & $python @args; if ($LASTEXITCODE -ne 0) { throw 'Preview failed.' } } finally { Pop-Location }
