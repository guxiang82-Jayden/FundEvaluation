# 子任务:BOND_INDEX 工具型记分卡(给本机 Codex)

> 遵循 COLLABORATION.md:只本地 commit 不 push;完成回写"✅ 已完成"。
> **隔离原则**:只新建 `scripts/scoring_bond_index.py` + `scripts/test_scoring_bond_index.py`。
> **不改** scoring.py / config.py / run_monthly_bond.py / metrics*.py(只读引用)。主线后续负责一行接入。
> ⚠️ 方法学为 v0 先验,文件内注释标清"先验/待校准";维度权重待 Jayden 过目。

## 背景
4-Track 中 BOND_INDEX(指数型-固收 + QDII.*债)目前**单列"工具型待评"、不评分**(见 run_monthly_bond.py:`BOND_INDEX_TYPE_RE`、write_score_workbook 的 `defer_sheets["BOND_INDEX"]="工具型待评"`)。
工具型不评 alpha,评的是:**是否便宜、跟得准、好交易、指数有代表性**。本任务补这张卡(对照 scoring_bond_cb.py 的隔离写法)。

## 设计(v0 先验)

### 组内口径
- 在 BOND_INDEX track 内分位,但**必须再分两子组分别评分**(异质,不可混排):
  - `指数固收`(境内被动债指)
  - `QDII债`(含汇率/海外信用,口径不同)
- 各子组 >=5 只才评分,不足 defer(沿用 MIN_GROUP=5)。子组判定可用 fund_type 含 "QDII" 与否。

### 维度(复用 scoring.score_all 的 5 个标准槽位键,语义重映射,**模块内常量**)
> 复用 A_return/B_risk/C_attribution/D_manager/E_operation 这 5 个键,是为了**不改 scoring.py**;
> 在模块 docstring + 注释里写清"工具型语义重映射",避免误读。

| 槽位键 | 工具型语义 | 权重(先验) | 指标(方向) |
|---|---|---|---|
| A_return | **跟踪有效性** | 0.35 | `tracking_error`(-1,最重)、`info_ratio_track`(+1,可选);**无指数映射时本维降级**(见数据相位) |
| B_risk | **成本** | 0.30 | `total_fee`(综合费率,-1);可加 `bid_ask_proxy`(场内价差代理,-1,若有) |
| C_attribution | **流动性/规模** | 0.20 | `scale_yi`(+1 但边际递减,建议 log 压缩或分档:<2亿 退市风险扣分、>50亿 不再加分)、`turnover_amt_proxy`(+1,可选) |
| D_manager | **指数代表性** | 0.10 | `index_mainstream`(+1,主流宽基/政金债=高,小众/策略指数=低;来自指数映射表先验打分) |
| E_operation | **运作稳定性** | 0.05 | `fund_age_years`(+1)、`scale_stability`(+1,可选) |

- `primary_dim="A_return"`(跟踪有效性为首要);`veto_dim=None`(工具型不因高费率/小规模直接否决,只扣分。若 score_all 必须传 veto_dim,传 None 或新增可选参数前先确认其行为,**不得改 score_all 签名**——用 None)。
- 缺指标自动按剩余权重归一(score_all 既有行为),以支持数据相位降级。

### ⚠️ 数据相位拆分(务必照做,别硬造数)
**跟踪误差与指数代表性需要"基金↔标的指数"映射,目前仓库没有。** 故分两相落地:

- **Phase A(本任务,先交付)**:用**已有数据**评分——`total_fee`(E维数据/且慢 BatchGetFundTradeRules)、`scale_yi`(universe)、`fund_age_years`。
  跟踪误差 / 指数代表性**暂缺 → A 维、D 维按 score_all 归一逻辑自动降级**,score_label 标 provisional。
  即 Phase A 实际只跑成本(B)+流动性规模(C)+运作(E),先让工具型有"省钱好用"维度的排序。
- **Phase B(后续,单独数据任务)**:建 `data/index_map_bond.csv`(fund_code → 标的指数代码/名称 + 主流度先验分),拉指数净值算 `tracking_error`,补齐 A/D 维。本任务**只预留列与接口**,不负责造映射。

## 你的任务(Phase A)
1. 新建 `scripts/scoring_bond_index.py`:
   - 模块常量 `INDEX_DIM_WEIGHTS` / `INDEX_INDICATORS`(上表,**不写进 config.py**)。
   - `split_index_subgroup(df)`:按 fund_type 是否含 "QDII" 打 `index_subgroup ∈ {指数固收, QDII债}`。
   - `scale_score_prep` 思路:scale 的边际递减(log 或分档)可在 INDICATORS 用方向 0(U/钝化)或在 build 里预处理出 `scale_adj` 列再喂 score_all。择一,注释说明。
   - `build_index_metrics(df, navs=None, index_ret_map=None)`:预留 `tracking_error` 计算接口(给定 index_ret_map 时算 nav 日收益对标的指数的跟踪误差=超额收益年化标准差;否则该列 NaN)。Phase A 调用时不传 index_ret_map,留 NaN。
   - `score_index(df)`:按 `index_subgroup` 组内分位(<5 defer),调用 `scoring.score_all(gdf, dim_weights=INDEX_DIM_WEIGHTS, indicators=INDEX_INDICATORS, veto_dim=None, primary_dim="A_return")`,tag `scorecard="BOND_INDEX"`。
2. `scripts/test_scoring_bond_index.py`(不依赖网络):
   - 合成两子组(指数固收/QDII债)各 >=5 只,验证:子组拆分正确、组内分位、低费率/适度规模得高分、缺 tracking_error 时自动降级且 score_label=provisional、子组<5 时 defer。
   - 给定合成 index_ret_map 时 tracking_error 能算出且方向正确(跟踪误差小→A维高)。

## 验收
- 独立可跑;test 全过;不改任何现有 .py、不改 score_all 签名。
- 注释标清:工具型语义重映射、v0 先验权重待校准、Phase A/B 数据相位。
- tracking_error/index 代表性缺数据时**优雅降级**(不报错、自动归一、标 provisional)。

## 交付
- 本地 commit `[codex] feat(v0.4): BOND_INDEX 工具型记分卡 scoring_bond_index(Phase A)`(不 push),回写"✅ 已完成"。
- 主线(Claude)收到后:① run_monthly_bond 的 BOND_INDEX track 由 defer 改为 `score_index(...)`;② _SHEET_MAP 增 `BOND_INDEX→"工具型榜"`;③ 排期 Phase B 数据任务。

## 边界
- ✅ 只新建 scoring_bond_index.py + 测试;配置写模块内;Phase A 只用现成数据
- ❌ 不改 config/scoring/run_monthly_bond;不 push;不接入流水线(主线负责);不硬造指数映射数据
- 参考:`scoring_bond_cb.py`(隔离写法 + score_all 复用)、`10_固收线框架v0.4`、用户口径"跟踪误差/费率/规模/流动性/指数代表性,先排除同业存单"

---

✅ 已完成 2026-06-16

- 新增 `scripts/scoring_bond_index.py` 与 `scripts/test_scoring_bond_index.py`。
- Phase A 支持 `total_fee`、`scale_yi -> scale_adj`、`fund_age_years` 评分；缺 `tracking_error/index_mainstream` 时自动降级为 `provisional`。
- 已预留 Phase B `navs + index_ret_map` 跟踪误差接口；未硬造指数映射数据。
- 子组按 `指数固收/QDII债` 分开评分，子组少于 5 只 defer。
- 离线测试通过：分组、降级、低费率/规模、defer、tracking_error 方向均验证。
