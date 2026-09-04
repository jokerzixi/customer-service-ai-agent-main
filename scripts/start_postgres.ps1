# 启动本仓库本地 Postgres（conda 环境内置）
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$PgBin = "D:\Anaconda\envs\multi-agent-env\Library\bin"
$PgData = Join-Path $Root ".pgdata"
$env:Path = "$PgBin;" + $env:Path

if (-not (Test-Path (Join-Path $PgData "PG_VERSION"))) {
    Write-Host "未找到数据目录，请先按 README 初始化，或重新运行安装步骤。"
    exit 1
}

$status = & pg_ctl -D $PgData status 2>&1 | Out-String
if ($status -match "server is running") {
    Write-Host "Postgres 已在运行"
} else {
    & pg_ctl -D $PgData -l (Join-Path $PgData "logfile.log") start
    Write-Host "Postgres 已启动"
}
