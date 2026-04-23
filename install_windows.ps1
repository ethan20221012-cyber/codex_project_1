$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

if (!(Test-Path ".\requirements.txt")) {
    Write-Error "未找到 requirements.txt，请确认你在项目目录中运行 install_windows.ps1"
}

if (!(Test-Path ".\.venv")) {
    py -3 -m venv .venv
}

.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -r .\requirements.txt

Write-Host "依赖安装完成。"
Write-Host "启动 GUI: python .\meeting_gui.py"
