# 子任务:可转债(CB)v0 权重审核与校准(给本机 Codex)

> 遵循 COLLABORATION.md:只本地 commit 不 push;完成回写"✅ 已完成"。
> **隔离原则**:产出**研究备忘 + 校准脚本**,**不直接改 `scoring_bond_cb.py`**(权重改动等 Jayden 拍板,主线接入)。
> 本机有 akshare → 可拉可转债基金真实净值做 CB 专用 mini-RankIC。

## 背景
`scripts/scoring_bond_cb.py` 已落地,v0 先验权重:
- A_return 0.30(ann_return 0.5 / monthly_positive_ratio 0.5)
- **B_risk 0.40**(max_drawdown 0.35 / calmar 0.30 / sortino 0.20 / recovery_days 0.15)
- C_attribution 0.20(equity_beta 0.5 U型 / convertible_ratio 0.5 U型)
- D_manager 0.05、E_operation 0.05

注释已标"v0 先验,待 backtest RankIC 校准"。本任务做这次审核 + 给证据化的 v1 建议。
> 方法学原则参照 `research/基金评估-核心原则_过去与未来`:**过去≠未来,权重要由证据校准,而非拍脑袋;证据不足时维持先验并说明**。

## 你的任务(三段,缺数据则降级并标注)

### 1. 文献对标(定性)
复核仓库已入库研报对"可转债基金/含权益债基"评价的维度倾向:
- `research/` 下华宝五因子、华宝调研六维、NAFMII 四维、转债相关研报(如有)。
- 产出一段对标:**这些方法对 CB 的风控权重(回撤/卡玛)、弹性(转债仓位/股性)是否支持 B=0.40 最重、C=0.20 的设定?** 有无指标遗漏(如转股溢价率、债底保护、正股质量)?

### 2. 权重敏感性 / 稳健性(可无网络)
写 `scripts/cb_weight_sensitivity.py`:
- 对一组 CB 样本(优先真实,见第3段;无则合成 >=15 只),在 v0 权重基础上对 A/B/C 三维做 ±10%/±20% 扰动(D/E 固定),
- 计算扰动前后 **Top榜 Spearman 排名相关**与 **Top5 重合率**,
- 结论:当前排名对哪一维权重最敏感?v0 是否"脆弱"(小扰动就翻盘)?

### 3. CB 专用 mini-RankIC 回测(本机 akshare,核心证据)
写 `scripts/backtest_cb.py`(参照 `scripts/backtest.py` 的防前视 + 组内分位思路,但**CB 单组**):
- universe:可转债基金(复用 run_monthly_bond 的 CB 判定:名称含"可转债" / bond_subgroup="可转债基金")。
- 在 2020–2024 年末若干 asof 点:用当时净值算 CB 指标 → CB 组内分位综合分(用 CB_DIM_WEIGHTS)→ 对比前瞻 12 个月**CB 组内**超额收益,算各维 RankIC + ic_std + t 值(沿用 backtest.py 的 SE≈ic_std/√n)。
- **重点回答**:B(风控)、A(收益)、C(弹性 equity_beta/转债仓位)三维,哪个对未来 CB 表现更有预测力?B=0.40 最重是否被证据支持?equity_beta 的 U 型假设(适度弹性最优)成不成立?
- 复用主线刚加的 `backtest.calibration_suggest`(显著性护栏:|t|<1 维持原权重),避免噪声归一。

## 产出
- `research/基金评估-CB权重审核_v0校准.md`:三段结论 + 数据表(各维 mean_ic/ic_std/t)+ 敏感性结果 + **v1 建议权重(若证据充分;不足则明确"维持 v0 + 待更多期")**,带方法学说明,结尾"结论不构成投资建议"。
- 脚本:`scripts/cb_weight_sensitivity.py`、`scripts/backtest_cb.py`(+ 各自简单自测)。
- **不改** `scoring_bond_cb.py`(建议落在备忘里,主线据此接入)。

## 验收
- 脚本可独立跑(回测段依赖 akshare,沙箱不可跑属正常,本机跑);
- 备忘给出**证据强度自评**(IC 是否显著、样本期数、是否仅净值维度)——不得把不显著 IC 包装成"建议大改权重";
- 与主线一致的统计口径(显著性护栏、组内分位、防前视)。

## 边界
- ✅ 新建审核备忘 + 两个脚本;CB 单组回测;诚实标注证据强度
- ❌ 不改 scoring_bond_cb.py / config / scoring;不 push;不把噪声当信号
- 参考:`scoring_bond_cb.py`、`scripts/backtest.py`(防前视/calibration_suggest 护栏)、`research/基金评估-核心原则_过去与未来`、华宝/NAFMII 研报
