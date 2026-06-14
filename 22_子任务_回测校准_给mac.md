# 子任务:回测校准权重(给远端 macOS 同事)

> 你在**远端 macOS**,不共享本机工作目录。流程:`git clone`/`pull` 远端仓库 → 在**新分支**开发 → 提交带 `[mac]` 前缀 → **push 到分支**(不要直接推 main)→ 通知 Jayden 评审合并。这样不与本机单一推送者冲突。
> **隔离原则**:主要在 `scripts/backtest.py`(现为骨架)+ 新增驱动脚本/测试。**不改** scoring.py / config.py / run_monthly*.py(只读引用)。

## 背景与目标
框架第6节 + 核心原则:评分权重当前是**先验值**,需用**历史证据校准**(v1.0 闭环三大件之一)。
现有 `scripts/backtest.py` 已有骨架:`forward_return` / `backtest_one_period`(整体 RankIC)/ `backtest_multi_period`。
**本任务把它升级为"能产出权重校准证据"的回测**,先做**主动权益线**(backtest.py 当前对接的就是 equity 的 scoring 默认配置;债基双 track 校准列为后续)。

## 你的任务

### 1. 真实数据驱动(新增 `scripts/run_backtest.py`)
- 用 akshare 取一批主动权益基金(可复用 `data_akshare.active_equity_universe` + `fund_nav`;为控时长可先取规模前 200~300 只)的**完整历史净值**与基准。
- 滚动评估点:2019-12-31 ~ 2024-12-31 每年末(共 6 个 asof),前瞻窗口 12 个月。
- **严格防前视**:评分只用 asof 之前的净值切片(backtest 已切片);**禁用 asof 时点尚未成立**的基金;持仓类指标(C/D/E)暂不纳入回测(只用净值可算的 A/B),并在报告里标注此限制。

### 2. 分维度 RankIC(改 `backtest.py`,这是核心)
- 现在只算综合分 RankIC。**新增:每个维度分 `score_A_return`/`score_B_risk`/...(以及各窗口 3y/5y)与前瞻收益的 RankIC**。
- **同类组内**做:在每个 subgroup 内算分位与 RankIC(跨组直接比会失真);前瞻收益用**相对同类中位的超额**而非绝对值。
- 汇总:各维度 RankIC 的多期均值 + 为正比例(稳定性)。

### 3. 长短窗口预测力专项(框架核心问题)
- 对比 **5y 窗口指标 vs 3y 窗口指标** 各自对前瞻收益的 RankIC,回答"长历史 vs 近期 谁更预测未来"。

### 4. 权重校准建议(输出)
- 由各维度 RankIC(贡献度)给出**建议维度权重**(如按正 RankIC 归一,或与现 `config.DIM_WEIGHTS` 对比给增减建议)。
- **不要直接改 config.py**;把建议写进报告 `scripts/data/backtest_calibration_report.md`,由主线评审后再落 config。

### 5. 测试 `scripts/test_backtest.py`
- 合成净值(部分基金前瞻确实更高)验证:`backtest_one_period` 返回结构、分维度 RankIC 计算正确、防前视切片不泄漏未来、成立<窗口的基金被排除。
- 不依赖网络(合成数据)。

## 验收标准
- `backtest.py` 产出**分维度 + 分窗口 RankIC**;`run_backtest.py` 能在本机/你的 mac 上用真实数据跑出 6 期滚动结果;`test_backtest.py` 全过。
- 报告 `backtest_calibration_report.md`:各维度/窗口 RankIC 均值与稳定性 + 权重校准建议 + 防前视与"仅A/B维"的限制说明。
- 不改 scoring.py/config.py/run_monthly*.py。

## 交付方式(远端)
```bash
git clone <远端仓库>            # 或在已有克隆里 git pull --rebase
git checkout -b mac/backtest-calib
# ... 开发 backtest.py / run_backtest.py / test_backtest.py / 报告 ...
git add scripts/backtest.py scripts/run_backtest.py scripts/test_backtest.py scripts/data/backtest_calibration_report.md
git commit -m "[mac] feat(v1.0): 分维度RankIC回测 + 权重校准证据"
git push -u origin mac/backtest-calib      # 推分支, 不推 main
```
- 完成后本文件末尾追加 `✅ 已完成 YYYY-MM-DD, 分支 mac/backtest-calib`,通知 Jayden 评审合并。

## 边界
- ✅ backtest.py + run_backtest.py + test_backtest.py + 报告;推**分支**
- ❌ 不改 scoring/config/run_monthly;❌ 不直接推 main;❌ 不直接改权重(只给建议)
- 参考:框架 `07_路线图v1.0.md` 第五节、`research/基金评估-核心原则_过去与未来.md`
