# 推送前检查脚本 —— 看清"谁改了什么"再决定推不推
# 用法: .\check.ps1
# 不做任何修改, 只读, 安全

$ErrorActionPreference = "SilentlyContinue"
Set-Location $PSScriptRoot

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host " 推送前检查 (只读, 不改任何东西)" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

# 1. 本地未提交的改动(工作区 + 暂存区)
Write-Host "`n[1] 本地未提交的改动:" -ForegroundColor Yellow
$changes = git status --short
if ($changes) {
    git status --short
    Write-Host "  -> 有以上文件改动待提交" -ForegroundColor Gray
} else {
    Write-Host "  (无, 工作区干净)" -ForegroundColor Green
}

# 2. 本地领先/落后远端多少
Write-Host "`n[2] 与远端(NAS)的差距:" -ForegroundColor Yellow
git fetch origin main 2>$null
$ahead = (git rev-list --count origin/main..HEAD 2>$null)
$behind = (git rev-list --count HEAD..origin/main 2>$null)
Write-Host "  本地领先远端: $ahead 个提交 (需要 push)"
Write-Host "  远端领先本地: $behind 个提交 (需要 pull, 可能是Codex推的)"

# 3. 远端有而本地没有的提交(别人推的)
if ([int]$behind -gt 0) {
    Write-Host "`n[3] 远端新提交(可能是其他agent):" -ForegroundColor Yellow
    git log --oneline HEAD..origin/main 2>$null
}

# 4. 最近5条提交历史
Write-Host "`n[4] 最近提交历史:" -ForegroundColor Yellow
git log --oneline -5

Write-Host "`n==================================================" -ForegroundColor Cyan
Write-Host " 把以上输出贴给 Claude, 它会告诉你下一步怎么做" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
