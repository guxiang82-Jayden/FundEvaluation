# 子任务 39:产品线扩展批1 — 指数(权益被动) + ETF(单列)评价卡(给本机 Codex)

> 遵循 COLLABORATION.md:只本地 commit 不 push;完成回写"✅ 已完成"。
> 设计依据:`38_框架_全产品线扩展...v0.1.md` §3(已 Jayden 拍板:复用引擎、ETF 单列)。本机有 akshare。
> **复用现有基础设施**:`scoring.score_all`(评分引擎)、`scoring_bond_index`/`build_index_navs`(工具型卡 + 跟踪误差/映射/TE gate 范式)、`investability_warn`(可投性前置)、`classify` 模式。

## 范围与原则
- 工具型范式:评"跟得准 / 便宜 / 好交易 / 指数有代表性"。**ETF 单列,不与场外指数合并。**
- 沿用固收 BOND_INDEX 的**诚实纪律**:权威映射不靠 NL 猜;**TE 物理 gate**(被动指数 TE 应 <≈2%,>5% 判错→回查/留空);取不到留 provisional;数据缺失优雅降级。

## 任务一:通用化评分模块 `scripts/scoring_index.py`
新建(借 `scoring_bond_index` 结构),两套模块级 INDICATORS(权重为 v0 先验,注释待校准),共用 `scoring.score_all`:

### 指数(权益被动·场外)INDEX_EQUITY_INDICATORS(5槽重映射)
- A 跟踪有效性 0.40:`tracking_error`(−1,最重)、`info_ratio`(+1,≈0=纯被动)
- B 成本 0.25:`total_fee`(−1)
- C 流动性/规模 0.20:`scale_adj`(规模 U型/对数钝化,同 scoring_bond_index)
- D 指数代表性 0.10:`index_mainstream`(主流宽基沪深300/中证500/1000/创业板/科创50=高,窄基/主题=中)
- E 运作 0.05:`fund_age_years`、`scale_stability`

### ETF(场内)ETF_INDICATORS
- A 跟踪有效性 0.35:`tracking_error` + `tracking_deviation`(跟踪偏离度)
- B 成本 0.15:`total_fee`
- C **场内流动性 0.25**:`amount_avg`(日均成交额,+1)、`turnover_amt`(换手,+1)、`bid_ask_spread`(价差,−1,若有)
- D **折溢价 0.15**:`premium_discount_abs`(折溢价率绝对值,−1)、`premium_discount_std`(折溢价稳定性,−1)
- E 规模/运作 0.10:`scale_adj`(**<2亿退市风险**)、`fund_age_years`
- `split` / `score_index_*`:按子组(指数:标的指数族;ETF:标的指数族)组内分位,<5 defer;tag `scorecard="INDEX"` / `"ETF"`。

## 任务二:分类与 universe
- 识别并单列三类(本批只评前两类,指增留批2):
  - **ETF**:fund_type/简称含 "ETF"/"交易型"(含 ETF 联接需另判,联接归场外指数或单列,**先单列 ETF,联接暂作场外指数**)。
  - **指数(场外被动)**:`指数型-股票`/`被动指数` 且非 ETF 且**非增强**(名称不含"增强")。
  - 指增(名称含"增强"/strategy_tag 量化指增)→ **本批跳过,标记留批2**。

## 任务三:数据
1. **基金↔标的指数映射** `data/index_map_equity.csv`(fund_code,index_code,index_name,index_mainstream):按名称/业绩基准解析标的(沪深300/中证500/1000/创业板/科创50/红利/行业…),建权威关键词表;解析不到留空(provisional)。
2. **指数收益**:akshare 权益指数(沪深300=`000300`/中证500=`000905`/中证1000=`000852`/创业板指等)→ 日收益 → 算 `tracking_error`/`info_ratio`(复用 build_index_navs 的 _tracking_stats 思路)。
3. **ETF 场内**:akshare ETF 日行情(成交额/换手/收盘)+ IOPV/净值 → `premium_discount`(折溢价率)、`amount_avg`。规模<2亿 → `investability_warn=True`(沿用前置)。
4. **TE gate**:指数 TE>5%、ETF TE>8% 判错回查/留空;产出 `data/index_equity_te_check.md`(覆盖、TE 分布、撤回清单)。

## 任务四:接入与输出
- 新建 `run_monthly_index.py`(或并入 run_monthly):跑 指数 + ETF 两 track,组内分位评分,输出 Excel 多 sheet(`指数榜`/`ETF榜`/各自待评)。<2亿 ETF / 映射缺失 → 观察/ provisional。
- 轻量测试 `test_scoring_index.py`(合成数据:低 TE/低折溢价/适度规模得高分;缺 TE 降级 provisional;ETF<2亿预警;子组<5 defer)。

## 验收
- 抽样合理:沪深300 ETF 的 TE 应极低(<1%)、折溢价 <0.5%、成交活跃;窄基/低流动 ETF 应被 C/D 维拉低或 <2亿预警。
- TE gate 生效,撤回清单有据;映射不到留 provisional 不报错。
- 不改 `scoring.score_all`/`config` 既有权重;新权重写模块内、标 v0 先验。

## 交付
- 本地 commit `[codex] feat(扩展批1): 指数+ETF 工具型评价卡 scoring_index + 映射/场内数据 + TE gate`(不 push),回写"✅ 已完成"。
- 回报附:指数/ETF 各覆盖只数、TE 分布、折溢价分布、抽样(沪深300ETF 等)、<2亿预警只数。

## 边界
- ✅ 新建 scoring_index.py + 映射/指数收益/ETF场内取数 + run_monthly_index + 测试;复用 score_all 引擎
- ❌ 不改 scoring.score_all/既有 config 权重;不 NL 猜映射;不造假 TE;ETF 不与场外指数合并;指增/量化不在本批;不 push
- 参考:`38_框架...v0.1` §3、`scoring_bond_index.py`/`build_index_navs.py`(工具型范式 + TE gate)、`data/index_code_ref.csv`(映射诚实范式)、`screening.mark_investability_bond`(可投性前置思路)
