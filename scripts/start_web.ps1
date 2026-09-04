# 使用 conda 环境启动 Flask Web（需 Postgres + Redis + langgraph 已就绪）
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Py = "D:\Anaconda\envs\multi-agent-env\python.exe"
$env:Path = "D:\Anaconda\envs\multi-agent-env;D:\Anaconda\envs\multi-agent-env\Scripts;" + $env:Path
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
Set-Location $Root
& $Py scripts\init_db.py
& $Py web_app.py
