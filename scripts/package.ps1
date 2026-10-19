# 用 PyInstaller 打 Windows x64 可运行目录
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $VenvPy) {
    $Py = $VenvPy
} else {
    $Py = "python"
}

Write-Host ">> python: $Py"
& $Py -m pip install -q -r (Join-Path $Root "requirements-build.txt")
if ($LASTEXITCODE -ne 0) { throw "pip install pyinstaller failed" }

$Spec = Join-Path $Root "scripts\wegram.spec"
& $Py -m PyInstaller --noconfirm --clean $Spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$Out = Join-Path $Root "dist\wegram"
if (-not (Test-Path (Join-Path $Out "wegram.exe"))) {
    throw "missing dist\wegram\wegram.exe"
}

Copy-Item (Join-Path $Root "config.example.yaml") (Join-Path $Out "config.example.yaml") -Force
foreach ($d in @("logs", "data")) {
    New-Item -ItemType Directory -Path (Join-Path $Out $d) -Force | Out-Null
}

Write-Host ">> package ready: $Out"
