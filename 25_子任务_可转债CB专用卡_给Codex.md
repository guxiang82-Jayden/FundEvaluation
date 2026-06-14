# 子任务:可转债(CB)专用记分卡(给本机 Codex / 可选 mac)

> 遵循 COLLABORATION.md:只本地 commit 不 push;完成回写"✅ 已完成"。
> **隔离原则**:只新建 `scripts/scoring_bond_cb.py` + `scripts/test_scoring_bond_cb.py`。
> **不改** scoring.py/config.py/run_monthly_bond.py/metrics*.py(只读引用)。主线后续负责一行接入。
> ⚠️ 方法学为 v0 先验, 待 Jayden 过目 + 回测校准, 文件内注释标清"先验/待校准"。

## 背景
真跑质检(报告 `scripts/data/bond_run_report.md`)确认:可转债基金权益属性强(净值 Campisi R²≈0.03),
不能与纯债同卡。当前 run_monthly_bond 把 CB track 单列"待专用卡"暂不评分。本任务补这张卡。

## 设计(v0 先验, 同 4-Track 口径; CB 在**可转债组内**分位)
可转债基金本质偏权益,**不展示可解释为"择券alpha"的净值残差**。评价维度建议:
- **A 收益质量(权重 0.30)**:ann_return(0.5)、monthly_positive_ratio(0.5)  ← 绝对收益体验
- **B 风险控制(权重 0.40, 最重)**:max_drawdown(0.35)、calmar(0.30)、sortino(0.20)、recovery_days(-,0.15)
- **C 风格/弹性(权重 0.20)**:equity_beta(对中证转债或沪深300的净值回归beta, U型: 适度弹性)、convertible_ratio(来自 cdim_bond, U型)
- **D 经理(0.05)**:manager_experience、management_load
- **E 运作(0.05)**:total_fee
> 权重为先验, 注明"待 backtest RankIC 校准"。

## 你的任务
1. 新建 `scripts/scoring_bond_cb.py`:
   - 定义 `CB_DIM_WEIGHTS` / `CB_INDICATORS`(上面口径, 模块级常量, **不写进 config.py**)。
   - `equity_beta(nav, equity_index_ret)`:净值日收益对权益指数 OLS 的 beta(复用思路同 scoring_bond_plus.equity_contrib_ratio)。
   - `build_cb_metrics(df, navs, equity_index_ret)`:补 equity_beta 列(convertible_ratio 若 df 已有则保留)。
   - `score_cb(df)`:在"可转债基金"组内调用 `scoring.score_all(df, dim_weights=CB_DIM_WEIGHTS, indicators=CB_INDICATORS, veto_dim="B_risk", primary_dim="A_return")`,tag `scorecard="CB"`;<5 只 defer。
2. `scripts/test_scoring_bond_cb.py`:合成净值+权益指数,验证 equity_beta 计算、score_cb 组内分位、低回撤高分、缺指标自动归一。不依赖网络。

## 验收
- 独立可跑;test 全过;不改任何现有 .py。
- 注释标清方法学为 v0 先验、待校准;equity_beta 缺指数时返回 NaN(自动跳过)。

## 交付
- 本地 commit `[codex] feat(v0.4): 可转债CB专用记分卡 scoring_bond_cb`(不 push),回写"✅ 已完成"。
- 主线(Claude)收到后做一行接入:run_monthly_bond 的 CB track 由 defer 改为 `score_cb(...)`。

## 边界
- ✅ 只新建 scoring_bond_cb.py + 测试;CB 配置写在模块内
- ❌ 不改 config/scoring/run_monthly_bond;不 push;不直接接入流水线(主线负责)
- 参考:`10_固收线框架v0.4` + `scoring_bond_plus.py`(equity 回归/分档风格) + 真跑报告第8节

---
✅ 已由主线(Claude)直接建好 scripts/scoring_bond_cb.py + test_scoring_bond_cb.py(v0先验, 8只合成测试通过, equity_beta还原准确)。**未接入** run_monthly_bond(CB track 仍 defer),待 Jayden 过目方法学/权重后,主线一行接入(CB track 由 defer 改 score_cb)。无需再派 Codex。
