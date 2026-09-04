# 打包奥黛塔助手为 Windows 可执行程序（onedir，资源外置）
# 用法: pwsh -File build_exe.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "== [1/3] PyInstaller 构建 =="
python -m PyInstaller --noconfirm --clean --windowed --name genshin_gui `
  --icon assets/helper_icon.ico `
  --collect-all dxcam --collect-all vosk --collect-all sounddevice `
  --hidden-import fx_server gui.py

Write-Host "== [2/3] 拼装发布目录 dist/genshin_gui =="
$dist = Join-Path (Get-Location) "dist\genshin_gui"
Copy-Item config.json $dist -Force
Copy-Item assets $dist -Recurse -Force
Copy-Item models $dist -Recurse -Force
Copy-Item output $dist -Recurse -Force

Write-Host "== [3/3] 完成: $dist\genshin_gui.exe =="
Get-ChildItem $dist | Select-Object Name, Length | Format-Table -AutoSize
