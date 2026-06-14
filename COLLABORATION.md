# 多 Agent 协作约定(git 单一推送者模型)

> 本项目由多个 agent 共享同一本地工作目录协作(Claude 主线 / Codex / mac agent / 未来其他)。
> **核心规则:Jayden(用户)是唯一 git 推送者。所有 agent 只写文件,不 push。**
> 定稿 2026-06-14。

## 一、角色与权限

| 角色 | 写文件 | git commit | git push |
|---|---|---|---|
| **Jayden(用户)** | ✅ | ✅ | ✅ **唯一推送者** |
| Claude(主线) | ✅ | ❌(本就不跑git) | ❌ |
| Codex(本机) | ✅ | ⚠️ 仅本地commit,见下 | ❌ **不再自己 push** |
| mac agent | ✅ | ⚠️ 同上 | ❌ |

## 二、推送流程(只有 Jayden 执行)

```powershell
cd D:\03_AI_Projects_and_Vault\Fund_Evaluation
git pull --rebase          # 拉远端(若有)
git add .                  # 收集所有 agent 的改动
git commit -m "说明"       # 或用 .\run.ps1 sync "说明"
git push
```

阶段性收拢提交即可(不必每个小改动都推)。建议时机:一个里程碑完成、或准备换机器/休息前。

## 三、Agent 的提交方式(改版)

**Codex / mac agent 新规则**:完成任务后

- ✅ 写好文件
- ✅ 可选:本地 `git add <自己的文件> && git commit -m "[codex] ..."`(**只 commit,不 push**)
- ❌ **不执行 git push**
- ✅ 在任务包末尾回写"✅ 已完成",并明确告诉 Jayden"已完成,待统一推送"

Jayden 看到回报后,统一 pull--rebase + add + push。

## 四、文件隔离原则(仍然重要)

即使单一推送者,仍按"分文件隔离"派活,避免逻辑覆盖:

- 优先派**新建文件**的任务(data_bond.py / classify_bond.py 等)
- 必须改现有文件时,**限定到单个函数**,并在任务包标注"只改 X 函数"
- 同一文件**不同时**派给两方
- 主线高频改动区(scoring.py / run_monthly.py / config.py)尽量只由 Claude 主线动

## 五、任务包标准格式

每个子任务一个 `NN_子任务_<名>_给<agent>.md`,放根目录,含:
目标 / 隔离边界(碰哪些文件·不碰哪些) / 步骤 / 验收标准 / **交付方式(本地commit不push,回写进度)** / 边界清单。

## 六、为什么这样

- push 命令实际由 Jayden 在终端执行 → 让其成为唯一闸口最自然
- 单一推送者 = 不可能并发 push 冲突,无需各 agent 反复 rebase
- 仍共享实时代码(Codex 的 data_bond.py,Claude 立刻能 import)→ 保留并行协作价值
- 比"各自分支"简单:无合并负担;比"Codex 专管 git"清晰:Jayden 是项目唯一裁判

## 七、历史说明

2026-06-14 前 Codex 自行 push 了 3 次(fa1286a/28e7796 等),均零冲突成功(得益于严格文件隔离)。此约定生效后改为单一推送者,降低长期混乱风险。
