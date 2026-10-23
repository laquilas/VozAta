<#
.SYNOPSIS
  Build the Windows installer: packaged engine + self-contained desktop app + Inno Setup.

.EXAMPLE
  pwsh packaging/build.ps1 -Version 1.0.0            # from the repository root
  pwsh packaging/build.ps1 -Version 1.0.0 -CpuOnly   # without the ~1 GB of CUDA DLLs

  Needs: the engine environment with the `cuda` and `package` extras
  (pip install -e "engine[cuda,package]"), the .NET 10 SDK and, for the installer itself, Inno
  Setup 6 (`iscc` on PATH); without it the script stops after preparing build/.
#>
param(
    [string] $Version = "0.0.0",
    [switch] $CpuOnly,
    [string] $Out = "build",
    [string] $Python = "python"
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$out = [IO.Path]::GetFullPath((Join-Path $root $Out))

Write-Host "== Engine (PyInstaller)"
$env:CPU_ONLY = if ($CpuOnly) { "1" } else { "0" }
& $Python -m PyInstaller (Join-Path $root "packaging/engine.spec") --noconfirm `
    --distpath (Join-Path $out "dist") --workpath (Join-Path $out "work")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

Write-Host "== Engine smoke test"
$engine = Join-Path $out "dist/vozata-engine/vozata-engine.exe"
& $engine --version
if ($LASTEXITCODE -ne 0) { throw "vozata-engine.exe --version failed" }
# phase 44: the same bundle runs the worker on a GPU PC of the network
& $engine worker --check
if ($LASTEXITCODE -ne 0) { throw "vozata-engine.exe worker --check failed" }

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
& $iscc.Source /Qp "/DAppVersion=$Version" "/DBuildDir=$out" (Join-Path $root "packaging/installer.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Get-ChildItem (Join-Path $out "installer") | ForEach-Object { Write-Host ("{0} ({1:N0} MB)" -f $_.FullName, ($_.Length / 1MB)) }
