<#
.SYNOPSIS
  Update / Reinstall / downgrade / Remove test of the installer (phase 67), silent.

  Needs two builds of the same installer: -Older (e.g. 0.3.1) and -Setup (e.g. 0.3.2). Build them
  as test builds so nothing of this PC is touched: their settings and runtime folders point at
  -Data (iscc /DSpeakersWorkDir=<Data>\settings /DRuntimesDir=<Data>\runtimes ...). The product
  must not be installed on this PC: the test installs and removes it.

.EXAMPLE
  pwsh packaging/maintenance-test.ps1 -Older build\old\VozAta-Setup-0.3.1.exe `
      -Setup build\new\VozAta-Setup-0.3.2.exe -Data $env:TEMP\vozata-maintenance
#>
param(
    [Parameter(Mandatory)] [string] $Older,
    [Parameter(Mandatory)] [string] $Setup,
    [Parameter(Mandatory)] [string] $Data,
    [string] $AppId = "{6E0B9F4A-2C5D-4E8B-9A1F-3D7C5B2E8A61}",
    [string] $Dir = (Join-Path ($env:RUNNER_TEMP ?? $env:TEMP) "VozAta-maintenance-app")
)
$ErrorActionPreference = "Stop"
$key = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\${AppId}_is1"
$settings = Join-Path $Data "settings"
$runtimes = Join-Path $Data "runtimes"
$marker = Join-Path $settings "meeting-marker.txt"
$quiet = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/TASKS=", "/DIR=`"$Dir`"")

function Check([bool] $condition, [string] $what) {
    if (-not $condition) { throw "FAILED: $what" }
    Write-Host "ok: $what"
}

function Run([string] $file, [string[]] $arguments) {
    (Start-Process $file -ArgumentList $arguments -Wait -PassThru).ExitCode
}

function Installed() {
    if (Test-Path $key) { (Get-ItemProperty $key).DisplayVersion } else { $null }
}

function Uninstall([string[]] $switches) {
    $uninstaller = (Get-ItemProperty $key).UninstallString.Trim('"')
    $code = Run $uninstaller (@("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") + $switches)
    foreach ($i in 1..60) { if (-not (Test-Path $key)) { break }; Start-Sleep 1 }  # it goes on in a copy
    Start-Sleep 2
    $code
}

Check (-not (Test-Path $key)) "the product is not installed before the test"
New-Item -ItemType Directory -Force $settings, (Join-Path $runtimes "speakers") | Out-Null
Set-Content $marker "a meeting"
Set-Content (Join-Path $runtimes "speakers\ready.json") "{}"

Check ((Run $Older $quiet) -eq 0) "install the older version"
$older = Installed
Check ((Run $Setup $quiet) -eq 0) "update over it"
$current = Installed
Check ($current -ne $older) "the version changed ($older -> $current)"
Check (Test-Path $marker) "the update kept the data"

Check ((Run $Setup $quiet) -eq 0) "reinstall the same version"
Check ((Installed) -eq $current) "still $current"
Check (Test-Path $marker) "the reinstall kept the data"

Check ((Run $Older $quiet) -ne 0) "a silent downgrade is refused"
Check ((Installed) -eq $current) "still $current after the refused downgrade"
Check ((Run $Older ($quiet + "/ALLOWDOWNGRADE")) -eq 0) "a downgrade with /ALLOWDOWNGRADE"
Check ((Installed) -eq $older) "now $older"
Check ((Run $Setup $quiet) -eq 0) "update again"

Check ((Uninstall @()) -eq 0) "silent uninstall"
Check (-not (Test-Path $key)) "unregistered"
Check (Test-Path $marker) "a silent uninstall keeps the data"

Check ((Run $Setup $quiet) -eq 0) "install again"
Check ((Uninstall @("/KEEPDATA")) -eq 0) "uninstall with /KEEPDATA"
Check (Test-Path $marker) "/KEEPDATA keeps the data"

Check ((Run $Setup $quiet) -eq 0) "install again"
Check ((Uninstall @("/DELETEDATA")) -eq 0) "uninstall with /DELETEDATA"
Check (-not (Test-Path $settings)) "/DELETEDATA deletes the settings folder"
Check (-not (Test-Path (Join-Path $runtimes "speakers"))) "the downloaded runtimes are gone"
Check (-not (Test-Path "$Dir\VozAta.Desktop.exe")) "the program is gone"
Write-Host "maintenance test passed"
