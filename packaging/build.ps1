<#
.SYNOPSIS
  Build the Windows installer: packaged engine + self-contained desktop app + Inno Setup.

.EXAMPLE
  pwsh packaging/build.ps1 -Version 1.0.0            # from the repository root
  pwsh packaging/build.ps1 -Version 1.0.0 -CpuOnly   # without the ~1 GB of CUDA DLLs
  pwsh packaging/build.ps1 -Version 1.0.0 -Speakers  # the speakers edition (+ pyannote / torch)

  Needs: the engine environment with the `cuda`, `translation` and `package` extras
  (pip install -e "engine[cuda,translation,package]"; `diarization` too for -Speakers), the .NET 10
  SDK and, for the installer itself, Inno Setup 6 (`iscc` on PATH); without it the script stops
  after preparing build/.
#>
param(
    [string] $Version = "0.0.0",
    [switch] $CpuOnly,
    [switch] $Speakers,
    [string] $Out = "build",
    [string] $Python = "python"
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$out = [IO.Path]::GetFullPath([IO.Path]::Combine($root, $Out))  # -Out may be absolute (a scratch folder)

Write-Host "== Engine (PyInstaller)"
$env:CPU_ONLY = if ($CpuOnly) { "1" } else { "0" }
$env:SPEAKERS = if ($Speakers) { "1" } else { "0" }  # phase 51: the speakers edition
& $Python -m PyInstaller (Join-Path $root "packaging/engine.spec") --noconfirm `
    --distpath (Join-Path $out "dist") --workpath (Join-Path $out "work")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host "== Engine smoke test"
$engine = Join-Path $out "dist/vozata-engine/vozata-engine.exe"
& $engine --version
if ($LASTEXITCODE -ne 0) { throw "vozata-engine.exe --version failed" }
# phase 44: the same bundle runs the worker on a GPU PC of the network; phase 51: with every task
$check = & $engine worker --check --json
if ($LASTEXITCODE -ne 0) { throw "vozata-engine.exe worker --check failed" }
Write-Host $check
$tasks = @{}
($check | ConvertFrom-Json).tasks | ForEach-Object { $tasks[$_.name] = $_ }
if (-not $tasks.translation.available) { throw "the packaged worker does not offer translation" }
if ($Speakers -and $tasks.speakers.reason -eq "missing_extra") {
    throw "the speakers edition does not bundle the diarization extra"
}
# the pyannote children run as `vozata-engine.exe -m <module>` (phase 51)
& $engine -m vozata --version
if ($LASTEXITCODE -ne 0) { throw "vozata-engine.exe -m <module> failed" }

Write-Host "== Desktop app (self-contained)"
dotnet publish (Join-Path $root "ui/src/VozAta.Desktop") -c Release -r win-x64 --self-contained `
    -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -o (Join-Path $out "ui")
if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed" }
Copy-Item (Join-Path $root "ui/src/VozAta.Desktop/appsettings.Installed.json") (Join-Path $out "ui/appsettings.json") -Force

Write-Host "== Worker app (self-contained, next to the desktop app: both use engine\vozata-engine.exe)"
dotnet publish (Join-Path $root "ui/src/VozAta.Worker") -c Release -r win-x64 --self-contained `
    -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -o (Join-Path $out "ui")
if ($LASTEXITCODE -ne 0) { throw "dotnet publish of VozAta.Worker failed" }

Write-Host "== First-run .env"
& $Python (Join-Path $root "packaging/make_installed_env.py") (Join-Path $root "engine/.env.example") (Join-Path $out "installed.env")
if ($LASTEXITCODE -ne 0) { throw "make_installed_env.py failed" }

$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $iscc) {
    $candidate = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6/ISCC.exe"
    if (Test-Path $candidate) { $iscc = Get-Item $candidate }
}
if (-not $iscc) {
    Write-Warning "Inno Setup (iscc) not found: build/ is ready, the installer was not created."
    exit 0
}
Write-Host "== Installer (Inno Setup)"
$edition = if ($Speakers) { "-speakers" } else { "" }
& $iscc.Source /Qp "/DAppVersion=$Version" "/DBuildDir=$out" "/DEdition=$edition" (Join-Path $root "packaging/installer.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Get-ChildItem (Join-Path $out "installer") | ForEach-Object { Write-Host ("{0} ({1:N0} MB)" -f $_.FullName, ($_.Length / 1MB)) }
