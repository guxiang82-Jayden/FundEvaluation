# 子任务 40:产品线扩展批2 — 指数增强(指增)评价卡(给本机 Codex)

> 遵循 COLLABORATION.md:只本地 commit 不 push;完成回写"✅ 已完成"。
> 设计依据:`38_框架_全产品线扩展v0.1` §4(增强·主动Alpha范式)。本机有 akshare + scipy。
> **复用批1/既有基础设施**:`scoring.score_all`、批1 的 `data/index_map_equity.csv`(标的指数映射)+ 指数收益取数、`data_akshare.fund_nav`(复权)、`rbsa.py`/`build_style_cdim`(风格稳定)、`investability_warn`。

## 范式与核心问题
指增 = **增强·主动 Alpha** 范式:评"**对标的指数的超额是否持续、扣费后还剩多少**"。**不是**工具型(不追求 TE 越小越好——TE 太低反而像"伪增强")。

## 任务一:评分模块 `scripts/scoring_enhanced.py`
新建,复用 `scoring.score_all`;ENHANCED_DIM_WEIGHTS / ENHANCED_INDICATORS(v0 先验,注释待校准):
- **A 超额能力 0.40**(核心):`excess_return_ann`(对标的指数年化超额,+1,0.40)、`info_ratio`(信息比率=超额年化/跟踪误差,+1,0.35)、`excess_win_rate`(滚动超额胜率,+1,0.25)
- **B 超额风控 0.25**:`excess_max_drawdown`(超额序列最大回撤,取负后高=好,0.6)、`excess_calmar`(0.4)
- **C 风格/跟踪 0.15**:`style_stability`(RBSA,+1,0.6)、`tracking_error`(**U型/容忍带**:方向 0;过低=伪增强、过高=偏离,0.4)
- **D 经理 0.10**:`manager_experience` / `management_load`
- **E 运作 0.10**:`total_fee`(−1)、`turnover`(量化指增高换手,**低权重或豁免**)
- 同类组:**按标的指数族**(沪深300指增 / 中证500指增 / 中证1000指增 / 红利指增 / 全市场指增),组内分位,<5 defer;tag `scorecard="ENHANCED"`。

## 任务二:universe 与标的映射
- universe:名称含"增强"或 classify 的指增/量化指增标签的权益基金(批1 已把这些"留批2"标记)。
- 标的映射:**复用并扩展** `data/index_map_equity.csv` 的关键词解析,把指增基金也映射到标的指数(300指增→沪深300、500指增→中证500…);解析不到留空(provisional)。

## 任务三:超额指标计算(口径要统一,诚实标注)
- **超额收益**:`基金复权日收益 − 标的指数日收益`。⚠️ 标的用**价格指数**(批1 已取的 000300/000905/000852 等);基金复权含分红,故超额对价格指数会**略高估**(行业惯例近似)——**在报告/注释里标清此口径**,有全收益指数源则优先。
- `excess_return_ann`(超额年化)、`info_ratio`(超额年化/超额std年化=跟踪误差)、`excess_win_rate`(滚动60交易日超额>0 占比)、`excess_max_drawdown`/`excess_calmar`(超额累计序列)、`tracking_error`(超额std年化)。
- **容忍带预警**:`tracking_error < 1%` → 标 `pseudo_enhance_warn`(疑似伪增强/贴被动);`> 12%` → 标 `te_excess_warn`(偏离过大)。这两类**不剔除**,作观察标记(沿用软标记纪律)。

## 任务四:接入与输出
- 接入 `run_monthly_index.py`(批1 已建)新增 ENHANCED track,或并入;输出 `指增榜` sheet,按标的指数族组内分位;<2亿/映射缺失/低置信 → 观察/provisional。
- 轻量测试 `test_scoring_enhanced.py`(合成:高且稳超额→高分;伪增强 TE<1%→预警;缺标的映射→provisional;子组<5 defer)。

## 验收
- 抽样合理:知名 500/1000 指增(超额显著且稳)应高分、info_ratio 居前;TE<1% 的"伪增强"被标记;风格漂移大的 C 维低。
- 超额口径(价格指数近似)在报告与注释里写清;容忍带预警有据。
- 不改 `scoring.score_all`/既有 config 权重;新权重模块内、标 v0 先验。

## 交付
- 本地 commit `[codex] feat(扩展批2): 指增评价卡 scoring_enhanced(超额/信息比率/超额胜率/容忍带)`(不 push),回写"✅ 已完成"。
- 回报附:指增覆盖只数、各标的族分布、info_ratio/超额年化 分布、伪增强预警只数、3-5 只抽样(超额年化/IR/超额胜率/TE)。

## 边界
- ✅ 新建 scoring_enhanced.py + 扩展标的映射到指增 + 超额指标 + 接 run_monthly_index + 测试;复用 score_all/批1映射/RBSA
- ❌ 不改 score_all/既有 config 权重;不把 TE 当越小越好(指增非被动);超额口径要标注;不 push;量化(批3)/多资产(批4-6)不在本批
- 参考:`38_框架v0.1` §4、批1 `scoring_index.py`/`data/index_map_equity.csv`/指数收益取数、`rbsa.py`、`screening` 软标记范式

✅ 已完成 2026-06-28
