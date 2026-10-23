<#
.SYNOPSIS
  Build the Windows installers (Inno Setup): VozAta (desktop app + engine) and, since phase 57,
  VozAta Worker (worker app + engine) for the GPU PC.

.EXAMPLE
  pwsh packaging/build.ps1 -Version 1.0.0            # from the repository root
  pwsh packaging/build.ps1 -Version 1.0.0 -CpuOnly   # without the ~1 GB of CUDA DLLs

  Needs: the engine environment with the `cuda`, `translation` and `package` extras
  (pip install -e "engine[cuda,translation,package]"), the .NET 10 SDK and, for the installer
  itself, Inno Setup (`iscc` on PATH); without it the script stops after preparing build/.
  Speaker identification is not bundled: the installed PC downloads it (phase 56).
#>
param(
    [string] $Version = "0.0.0",
    [switch] $CpuOnly,
    [string] $Out = "build",
    [string] $Python = "python"
)
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$out = [IO.Path]::GetFullPath([IO.Path]::Combine($root, $Out))  # -Out may be absolute (a scratch folder)

Write-Host "== Engine (PyInstaller)"
$env:CPU_ONLY = if ($CpuOnly) { "1" } else { "0" }
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
if (Test-Path (Join-Path $out "dist/vozata-engine/_internal/torch")) { throw "torch got into the build" }

Write-Host "== Speaker runtime tools (phase 56: uv.exe and the engine source, for speakers install)"
$speakers = Join-Path $out "dist/vozata-engine/speakers"
New-Item -ItemType Directory -Force $speakers | Out-Null
$uv = & $Python -c "import uv; print(uv.find_uv_bin())"
if ($LASTEXITCODE -ne 0) { throw "uv is not installed (the package extra)" }
Copy-Item $uv (Join-Path $speakers "uv.exe") -Force
& $Python (Join-Path $root "packaging/make_source_zip.py") (Join-Path $root "engine/src") (Join-Path $speakers "vozata.zip")
if ($LASTEXITCODE -ne 0) { throw "make_source_zip.py failed" }
& $engine speakers status --json
if ($LASTEXITCODE -ne 0) { throw "vozata-engine.exe speakers status failed" }

# each app in its own folder, for its own installer (phase 57); a stale build must not leak in
foreach ($folder in "ui", "worker-ui") {
    $path = Join-Path $out $folder
    if (Test-Path $path) { Remove-Item -Recurse -Force $path }
}

Write-Host "== Desktop app (self-contained)"
dotnet publish (Join-Path $root "ui/src/VozAta.Desktop") -c Release -r win-x64 --self-contained `
    -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true "-p:Version=$Version" `
    -o (Join-Path $out "ui")
if ($LASTEXITCODE -ne 0) { throw "dotnet publish failed" }
Copy-Item (Join-Path $root "ui/src/VozAta.Desktop/appsettings.Installed.json") (Join-Path $out "ui/appsettings.json") -Force

Write-Host "== Worker app (self-contained; its installer puts the engine next to it, engine\vozata-engine.exe)"
dotnet publish (Join-Path $root "ui/src/VozAta.Worker") -c Release -r win-x64 --self-contained `
    -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true "-p:Version=$Version" `
    -o (Join-Path $out "worker-ui")
if ($LASTEXITCODE -ne 0) { throw "dotnet publish of VozAta.Worker failed" }

Write-Host "== First-run .env"
& $Python (Join-Path $root "packaging/make_installed_env.py") (Join-Path $root "engine/.env.example") (Join-Path $out "installed.env")
if ($LASTEXITCODE -ne 0) { throw "make_installed_env.py failed" }

$iscc = (Get-Command iscc -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    $candidates = @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6/ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs/Inno Setup 7/ISCC.exe"),  # a per-user install
        (Join-Path $env:LOCALAPPDATA "Programs/Inno Setup 6/ISCC.exe")
    )
    $iscc = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $iscc) {
    Write-Warning "Inno Setup (iscc) not found: build/ is ready, the installer was not created."
    exit 0
}
foreach ($script in "installer.iss", "installer-worker.iss") {
    Write-Host "== Installer (Inno Setup): $script"
    & $iscc /Qp "/DAppVersion=$Version" "/DBuildDir=$out" (Join-Path $root "packaging/$script")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed: $script" }
}
Get-ChildItem (Join-Path $out "installer") | ForEach-Object { Write-Host ("{0} ({1:N0} MB)" -f $_.FullName, ($_.Length / 1MB)) }
