# 基金评估项目一键运行入口(仓库根目录执行)
# 用法:
#   .\run.ps1 score            # 月度评分(全量)
#   .\run.ps1 score 500        # 月度评分(限500只)
#   .\run.ps1 test             # 引擎+模块自检(合成数据)
#   .\run.ps1 verify           # AKShare 接口体检
#   .\run.ps1 sync "提交说明"   # git add+commit+push 双端同步
#   .\run.ps1 sync             # 同上, 自动生成提交说明

param(
    [Parameter(Position = 0)] [string]$Cmd = "help",
    [Parameter(Position = 1)] [string]$Arg = ""
)

$Root = $PSScriptRoot
$Scripts = Join-Path $Root "scripts"
$Venv = Join-Path $Scripts ".venv\Scripts\Activate.ps1"

function Use-Venv {
    if (Test-Path $Venv) { & $Venv } else { Write-Host "未找到 .venv, 先在 scripts 下建虚拟环境" -ForegroundColor Red; exit 1 }
    Set-Location $Scripts
}

switch ($Cmd) {
    "score" {
        Use-Venv
        if ($Arg) { python run_monthly.py --limit $Arg } else { python run_monthly.py }
        Set-Location $Root
    }
    "test" {
        Use-Venv
        python test_engine.py
        python test_modules.py
        Set-Location $Root
    }
    "verify" {
        Use-Venv
        python verify_data.py
        Set-Location $Root
    }
    "sync" {
        Set-Location $Root
        git add .
        $msg = if ($Arg) { $Arg } else { "update: " + (Get-Date -Format "yyyy-MM-dd HH:mm") }
        git commit -m $msg
        git push
    }
    default {
        Write-Host @"
基金评估项目命令:
  .\run.ps1 score [N]     月度评分(可选限N只)
  .\run.ps1 test          引擎自检
  .\run.ps1 verify        数据接口体检
  .\run.ps1 sync ["说明"]  提交并双端推送
"@
    }
}
