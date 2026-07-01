# 多 Agent 协作约定(Codex 统一版本管理)

> 本项目由多个 agent 共享同一本地工作目录协作(Claude 主线 / Codex / mac agent / 未来其他)。
> **核心规则:Codex 负责提交边界审核、版本管理及双端推送。其他 agent 只写文件,不执行 git 操作。**
> 2026-07-01 起生效。

## 一、角色与权限

| 角色 | 写文件 | git commit | git push |
|---|---|---|---|
| **Jayden(用户)** | ✅ | 可要求 Codex 提交 | 可要求 Codex 推送 |
| Claude(主线) | ✅ | ❌(本就不跑git) | ❌ |
| **Codex(本机)** | ✅ | ✅ **统一管理** | ✅ **双端推送者** |
| mac agent | ✅ | ❌ | ❌ |

## 二、Codex 双端同步流程

```powershell
cd D:\03_AI_Projects_and_Vault\Fund_Evaluation
git fetch origin
git fetch github
# 审核工作区与两端分支，确认提交边界；必要时先 rebase 并手动处理冲突
git push origin main
git push github main
```

推送前必须确认两个远端分支均可安全快进；不得用强制推送覆盖任一端历史。

## 三、Agent 的交付方式

**Claude / mac agent**完成任务后:

- ✅ 写好文件
- ❌ 不执行 `git add` / `commit` / `pull` / `push`
- ✅ 回报改动文件、测试结果及已知风险
- ✅ 由 Codex 审核改动范围、运行必要测试、分批提交并同步两端

Codex 自己完成的任务同样先审核、测试，再按任务边界提交和双推。

## 四、文件隔离原则(仍然重要)

即使单一推送者,仍按"分文件隔离"派活,避免逻辑覆盖:

- 优先派**新建文件**的任务(data_bond.py / classify_bond.py 等)
- 必须改现有文件时,**限定到单个函数**,并在任务包标注"只改 X 函数"
- 同一文件**不同时**派给两方
- 主线高频改动区(scoring.py / run_monthly.py / config.py)尽量只由 Claude 主线动

## 五、任务包标准格式

每个子任务一个 `NN_子任务_<名>_给<agent>.md`,放根目录,含:
目标 / 隔离边界(碰哪些文件·不碰哪些) / 步骤 / 验收标准 / **交付方式(本地commit不push,回写进度)** / 边界清单。

## 六、版本管理原则

- 不使用 `git add .` 无差别收拢；按任务文件清单精确暂存。
- 不覆盖或回滚来源不明的工作区改动。
- 每次推送前检查 `origin/main`、`github/main` 与本地 `main` 的祖先关系。
- 两端同步成功后回报提交号；任一端失败时明确报告，不把单端成功表述为同步完成。
- 不使用 `--force` / `--force-with-lease`，除非 Jayden 明确授权并已完成风险说明。

## 七、历史说明

2026-06-14 至 2026-06-30 采用 Jayden 单一推送者模型。
自 2026-07-01 起改为 Codex 统一版本管理并同步 `origin`(本地 Git 服务)与 `github`。
