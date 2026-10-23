<#
.SYNOPSIS
  Install test for the built installer (run by the Release workflow): silent per-user install,
  the desktop app starts the bundled engine, uninstall removes the program and keeps the data.

  With -Worker (phase 57): the VozAta Worker installer, which carries the worker app and the
  engine but not the desktop app; the packaged worker passes its installation check.

.EXAMPLE
  pwsh packaging/install-test.ps1 -Setup build/installer/VozAta-Setup-1.0.0.exe
  pwsh packaging/install-test.ps1 -Setup build/installer/VozAta-Worker-Setup-1.0.0.exe -Worker
#>
param(
    [Parameter(Mandatory)] [string] $Setup,
    [string] $Dir = (Join-Path ($env:RUNNER_TEMP ?? $env:TEMP) "VozAta-install"),
    [switch] $Worker
)
$ErrorActionPreference = "Stop"
function Check([bool] $condition, [string] $what) {
    if (-not $condition) { throw "FAILED: $what" }
    Write-Host "ok: $what"
}

if ($Worker) {
    $shortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "VozAta Worker.lnk"
    $install = Start-Process $Setup -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=`"$Dir`"" -Wait -PassThru
    Check ($install.ExitCode -eq 0) "silent install (exit code $($install.ExitCode))"
    Check (Test-Path "$Dir\VozAta.Worker.exe") "worker app installed"
    Check (Test-Path "$Dir\engine\vozata-engine.exe") "engine installed"
    Check (Test-Path "$Dir\engine\speakers\uv.exe") "the speaker runtime tools installed"
    Check (-not (Test-Path "$Dir\VozAta.Desktop.exe")) "no desktop app"
    Check (Test-Path $shortcut) "Start-menu shortcut"
    $check = & "$Dir\engine\vozata-engine.exe" worker --check --json | ConvertFrom-Json
    Check ($LASTEXITCODE -eq 0) "the packaged worker passes --check"
    Check (($check.tasks | Where-Object name -eq "speech").available) "the worker offers speech"
    # a stand-in speaker runtime: the uninstaller removes it when VozAta itself is not installed
    $runtime = Join-Path $env:LOCALAPPDATA "VozAta\speakers"
    Check (-not (Test-Path $runtime)) "no speaker runtime before the test (move a real one aside)"
    New-Item -ItemType Directory -Force $runtime | Out-Null
    Set-Content -Path (Join-Path $runtime "ready.json") -Value "{}"
    $uninstall = Start-Process "$Dir\unins000.exe" -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait -PassThru
    Start-Sleep 5  # the uninstaller finishes in a copy of itself
    Check ($uninstall.ExitCode -eq 0) "silent uninstall (exit code $($uninstall.ExitCode))"
    Check (-not (Test-Path "$Dir\VozAta.Worker.exe")) "worker app removed"
    Check (-not (Test-Path $shortcut)) "shortcut removed"
    Check (-not (Test-Path $runtime)) "the speaker runtime removed"
    Write-Host "worker install test passed"
    exit 0
}

$appData = Join-Path $env:APPDATA "VozAta"
$docs = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "VozAta"
$shortcut = Join-Path ([Environment]::GetFolderPath("Programs")) "VozAta.lnk"

$install = Start-Process $Setup -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DIR=`"$Dir`"" -Wait -PassThru
Check ($install.ExitCode -eq 0) "silent install (exit code $($install.ExitCode))"
Check (Test-Path "$Dir\VozAta.Desktop.exe") "desktop app installed"
Check (Test-Path "$Dir\engine\vozata-engine.exe") "engine installed"
Check (-not (Test-Path "$Dir\VozAta.Worker.exe")) "no worker app (its own installer, phase 57)"
# The in-app player (phase 37): LibVLC and its audio plugins next to the app, x64 only
Check (Test-Path "$Dir\libvlc\win-x64\libvlc.dll") "LibVLC installed"
Check (Test-Path "$Dir\libvlc\win-x64\plugins\audio_output\libmmdevice_plugin.dll") "LibVLC audio output plugin installed"
Check (Test-Path "$Dir\libvlc\win-x64\plugins\access\libhttp_plugin.dll") "LibVLC HTTP plugin installed"
Check (-not (Test-Path "$Dir\libvlc\win-x86")) "no 32-bit LibVLC"
Check ((Get-Content "$Dir\appsettings.json" -Raw) -match "vozata-engine.exe") "installed appsettings point to the bundled engine"
Check (Test-Path "$appData\.env") ".env created in %APPDATA%\VozAta"
Check ((Select-String -Path "$appData\.env" -Pattern '^OUTPUT_DIR=\$\{USERPROFILE\}/Documents/VozAta$') -ne $null) ".env keeps recordings in Documents"
Check (Test-Path $shortcut) "Start-menu shortcut"

$app = Start-Process "$Dir\VozAta.Desktop.exe" -WorkingDirectory $Dir -PassThru
$health = $null
foreach ($attempt in 1..90) {
    Start-Sleep 2
    try { $health = Invoke-RestMethod http://127.0.0.1:8765/health -TimeoutSec 10; break } catch { }
}
Check ($health -ne $null) "the engine answers /health after the app starts"
$engine = Get-CimInstance Win32_Process -Filter "Name='vozata-engine.exe'" | Select-Object -First 1
Check ($engine.ExecutablePath -eq "$Dir\engine\vozata-engine.exe") "the app started the bundled engine ($($engine.ExecutablePath))"
Check ($engine.ParentProcessId -eq $app.Id) "the engine is the app's child process"
$settings = Invoke-RestMethod http://127.0.0.1:8765/settings
$expected = ("$env:USERPROFILE/Documents/VozAta" -replace "\\", "/")
Check (($settings.values.OUTPUT_DIR -replace "\\", "/") -eq $expected) "the engine records into $expected"
Write-Host "engine $($health.version), GPU available: $($health.gpu.available), speech: $($health.stt.model) on $($health.stt.device)"

New-Item -ItemType Directory -Force $docs | Out-Null
Set-Content -Path (Join-Path $docs "keep-me.txt") -Value "a recording stand-in"
Stop-Process -Id $app.Id -Force
Stop-Process -Id $engine.ProcessId -Force -ErrorAction SilentlyContinue
Start-Sleep 3

$uninstall = Start-Process "$Dir\unins000.exe" -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait -PassThru
Start-Sleep 5  # the uninstaller finishes in a copy of itself
Check ($uninstall.ExitCode -eq 0) "silent uninstall (exit code $($uninstall.ExitCode))"
Check (-not (Test-Path "$Dir\VozAta.Desktop.exe")) "desktop app removed"
Check (-not (Test-Path "$Dir\engine\vozata-engine.exe")) "engine removed"
Check (-not (Test-Path $shortcut)) "shortcut removed"
Check (Test-Path "$appData\.env") ".env kept"
Check (Test-Path (Join-Path $docs "keep-me.txt")) "recordings kept"
Write-Host "install test passed"
