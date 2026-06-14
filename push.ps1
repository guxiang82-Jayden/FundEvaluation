# 一键安全推送 —— 收拢所有 agent 的改动并同步到 NAS+GitHub
# 用法: .\push.ps1 "本次说明"
# 自动: 先拉远端(防冲突) -> 收集所有改动 -> 提交 -> 推送两端

param([Parameter(Mandatory=$true)][string]$Message)
Set-Location $PSScriptRoot

Write-Host "[1/4] 先拉远端(拿其他agent已推的)..." -ForegroundColor Yellow
git pull --rebase origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host "`n!! pull --rebase 出错(可能有冲突)。停止。" -ForegroundColor Red
    Write-Host "   请把上面的报错贴给 Claude 处理, 不要继续操作。" -ForegroundColor Red
    exit 1
}

Write-Host "`n[2/4] 收集所有改动..." -ForegroundColor Yellow
git add .
$staged = git diff --cached --stat
if (-not $staged) {
    Write-Host "  (没有新改动需要提交, 已是最新)" -ForegroundColor Green
    # 仍尝试推送本地领先的提交
    git push
    exit 0
}
git diff --cached --stat

Write-Host "`n[3/4] 提交..." -ForegroundColor Yellow
git commit -m $Message

Write-Host "`n[4/4] 推送到 NAS + GitHub..." -ForegroundColor Yellow
git push
if ($LASTEXITCODE -ne 0) {
    Write-Host "`n!! push 出错(可能是Gitea凭据过期或网络)。" -ForegroundColor Red
    Write-Host "   提交已在本地保存, 不会丢。把报错贴给 Claude。" -ForegroundColor Red
    exit 1
}

Write-Host "`n✅ 完成! 所有改动已同步到 NAS 和 GitHub。" -ForegroundColor Green
