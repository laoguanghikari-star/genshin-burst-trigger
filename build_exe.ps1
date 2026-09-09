# Build Odette Assistant as a Windows executable (PyInstaller onedir, external resources)
# Usage: pwsh -ExecutionPolicy Bypass -File build_exe.ps1
# NOTE: keep this file ASCII-only - Windows PowerShell 5.1 reads BOM-less .ps1 as ANSI/GBK
#       and would garble any non-ASCII text into a parse error.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot   # this script lives in the repo root; do NOT go up one level

foreach ($p in @("gui.py", "config.json", "assets", "models", "assets\helper_icon.ico")) {
  if (-not (Test-Path $p)) { throw "missing required file: $p (run this script from the repo root)" }
}

Write-Host "== [1/3] PyInstaller build =="
python -m PyInstaller --noconfirm --clean --windowed --name genshin_gui `
  --icon assets/helper_icon.ico `
  --collect-all dxcam --collect-all vosk --collect-all sounddevice `
  --hidden-import fx_server gui.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit $LASTEXITCODE)" }

Write-Host "== [2/3] Assemble release dir dist/genshin_gui =="
$dist = Join-Path $PSScriptRoot "dist\genshin_gui"
if (-not (Test-Path $dist)) { throw "build output dir not found: $dist" }
Copy-Item config.json $dist -Force
Copy-Item assets $dist -Recurse -Force
Copy-Item models $dist -Recurse -Force
if (Test-Path output) {
  Copy-Item output $dist -Recurse -Force
} else {
  New-Item -ItemType Directory -Path (Join-Path $dist "output") -Force | Out-Null
}

Write-Host "== [3/3] Done: $dist\genshin_gui.exe =="
Get-ChildItem $dist | Select-Object Name, Length | Format-Table -AutoSize
Write-Host "Self-check: & '$dist\genshin_gui.exe' --selftest   (result: output/selftest_result.txt)"
