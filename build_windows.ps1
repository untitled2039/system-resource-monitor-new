param(
    [string]$Python = "python",
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$pythonVersion = & $Python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($pythonVersion -ne "3.12") {
    throw "Use 64-bit Python 3.12 for this build. Detected Python $pythonVersion."
}

& $Python -m PyInstaller --version *> $null
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is required. Install the build dependencies with: python -m pip install -r requirements-build.txt"
}

if (Test-Path (Join-Path $root "dist")) {
    Remove-Item -LiteralPath (Join-Path $root "dist") -Recurse -Force
}

& $Python -m PyInstaller --noconfirm --clean --windowed --onedir `
    --distpath (Join-Path $root "dist\app") `
    --name SystemResourceMonitor `
    --collect-all customtkinter --collect-all matplotlib --collect-all mpl_toolkits `
    --hidden-import=plyer.platforms.win.notification `
    --hidden-import=pystray._win32 `
    main.py
if ($LASTEXITCODE -ne 0) { throw "Application build failed." }

& $Python -m PyInstaller --noconfirm --clean --console --onedir `
    --distpath (Join-Path $root "dist\agent") `
    --name SystemResourceMonitorAgent `
    bluetooth_agent.py
if ($LASTEXITCODE -ne 0) { throw "Monitor agent build failed." }

$installer = Get-Command ISCC.exe -ErrorAction SilentlyContinue
if (-not $installer) {
    $defaultIscc = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
    if (-not (Test-Path -LiteralPath $defaultIscc)) {
        $defaultIscc = Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"
    }
    if (Test-Path -LiteralPath $defaultIscc) {
        $installer = @{ Source = $defaultIscc }
    }
}
if (-not $SkipInstaller -and $installer) {
    New-Item -ItemType Directory -Force -Path (Join-Path $root "release") | Out-Null
    & $installer.Source (Join-Path $root "installer\SystemResourceMonitor.iss")
    if ($LASTEXITCODE -ne 0) { throw "Installer build failed." }
} elseif (-not $SkipInstaller) {
    Write-Warning "Inno Setup was not found. EXEs are in dist; install Inno Setup and rerun this script to create the setup installer."
}

Write-Host "Build output: $root\dist"
