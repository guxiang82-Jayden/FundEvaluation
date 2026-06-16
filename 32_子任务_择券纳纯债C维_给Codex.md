# 子任务:择券效应纳入纯债 C 维(Campisi pickEffect)(Codex 代码 + 主线数据)

> 遵循 COLLABORATION.md:只本地 commit 不 push;完成回写"✅ 已完成"。
> ⚠️ **职责拆分**:数据拉取(且慢 getFundCampisiIndicator)是**会话内 MCP**,Codex 本机调不了 → 由主线(Claude)会话内批量拉、存 CSV(同 cdim_bond 模式);**Codex 负责代码接线 + 测试(读 CSV,data-gated)**。

## 背景(固收 L3 反馈)
纯债深研发现:三只纯债 Campisi **券种选择(pickEffect)效应全部为负**(−0.43/−0.64/−0.81),收益全由票息 carry 驱动 → 高分非选券能力。当前纯债 C 维 C1 用的是**净值法** `selection_share_bond`(Campisi 残差代理)。本任务把**持仓法** Campisi 的 `pickEffect` 作为补充的"择券能力"指标纳入纯债 C 维,显式区分"票息 beta vs 选券 alpha"。

## 口径建议(待 Jayden 拍板,先按此实现)
- **互补而非替换**:保留净值法 `selection_share_bond`(C1a),新增持仓法 `pick_alpha_bond`(C1b)。二者都指向择券,净值法周频可跑、持仓法半年频更直接。
- 纯债 C 维(当前 `selection_share 0.35 / credit_sink 0.30 / duration_dev 0.20 / leverage_contrib 0.15`)**先验**调整建议:`selection_share_bond 0.20 / pick_alpha_bond 0.20 / credit_sink 0.25 / duration_dev 0.20 / leverage_contrib 0.15`(择券两源各半)。**注释标"v0先验,待Jayden校准/回测"**。
- `pick_alpha_bond` 方向 +1(择券正贡献=好);数据缺失时 score_all 自动按剩余权重归一(dormant 不影响现状)。

## 主线(Claude 会话内)先行交付的数据
- `data/cdim_bond_data.csv` **增列 `pick_effect`**(且慢 getFundCampisiIndicator 的 pickEffect,纯债 universe 批量)。
  (Codex 无需等数据齐:列暂缺时你的代码须 data-gated 优雅降级。)

## 你的任务(Codex,只动加载层 + config + 测试)
1. `cdim_bond.py`:`load_cdim_bond` 支持 `pick_effect` 列 → 派生 C 维输入列 `pick_alpha_bond = pick_effect`(若 CSV 有该列;无则不产生该列,评分自动降级)。在模块 docstring 补该列说明。
2. `config.py`:`BOND_INDICATORS["C_attribution"]` 按上面口径建议增 `pick_alpha_bond`(+1)并调整内部权重(注释 v0 先验待校准)。**只改 BOND_INDICATORS,不动 BOND_DIM_WEIGHTS(C 维总权重 0.20 不变)**。
3. 测试:合成含/不含 `pick_effect` 两种 df,验证:有该列时 C 维纳入择券正贡献、择券为负的基金 C 维更低;无该列时优雅降级(覆盖率归一、不报错)、回归现有 test_bond_pipeline/test_engine 仍过。

## 验收
- 代码 data-gated:`pick_effect` 缺失时行为与现状一致(测试证明)。
- config 改动只在 BOND_INDICATORS C 维内部,C 维总权重 0.20 不变。
- 注释标清 v0 先验、口径待 Jayden 校准、净值法/持仓法互补关系。

## 交付
- 本地 commit `[codex] feat(v0.4): 纯债C维纳入持仓法择券(pick_alpha_bond, data-gated, v0先验)`(不 push),回写"✅ 已完成"。
- 主线随后会话内补 `pick_effect` 数据列并真跑验证;Jayden 最终拍 C 维内部权重。

## 边界
- ✅ 只改 cdim_bond.py(加载)+ config.py(BOND_INDICATORS C 维)+ 测试;data-gated
- ❌ 不改 scoring.py/metrics_bond.py;不动 C 维总权重;不调用且慢 MCP(数据由主线会话内提供);不 push
- 参考:`cdim_bond.py`(C 维派生模式)、`config.py` BOND_INDICATORS、`research/基金评估-CB权重审核_v0校准`(同款"维持先验+待校准"纪律)、固收 L3 总览

✅ 已完成 2026-06-17

Codex 回写:
- `cdim_bond.load_cdim_bond` 已支持可选 `pick_effect` -> `pick_alpha_bond`, 缺列时不产生该列并优雅降级。
- `BOND_INDICATORS["C_attribution"]` 已调整为: `selection_share_bond 0.20 / pick_alpha_bond 0.20 / credit_sink 0.25 / duration_dev 0.20 / leverage_contrib 0.15`; `BOND_DIM_WEIGHTS` 未改。
- 已补 `test_pick_effect_data_gated`: 验证负择券 C 维更低、无 `pick_effect` 时不报错。
- 已跑 `test_cdim_bond.py`、`test_bond_pipeline.py`、`test_engine.py` 通过。
