# 子任务:固收+ 记分卡模块(给本机 Codex)

> 遵循 COLLABORATION.md:**只本地 commit,不 push**;完成后回写"✅ 已完成"并报"待统一推送"。
> **隔离原则**:只新建 `scripts/scoring_bond_plus.py` + `scripts/test_scoring_bond_plus.py`。
> **不改**任何现有 .py(尤其 config.py / scoring.py / metrics_bond.py / run_monthly_bond.py)。

## 背景
v0.4 固收线纯债线已串通(分类→初筛→Campisi/净值指标→评分,见 16/17 号交接)。
本任务实现**固收+ 记分卡**(框架 `10_固收线框架v0.4.md` 第4节):与纯债的差异是
**先按权益中枢分组,再组内比较;风险维(目标回撤达标)最重**。

主线已为你**备好配置和评分引擎**,你直接调用即可(不要改它们):
- `config.BOND_PLUS_DIM_WEIGHTS` / `config.BOND_PLUS_INDICATORS`(A25/B40/C20/D10/E5)
- `config.BOND_PLUS_EQUITY_BANDS = {"保守":(0,0.10),"稳健":(0.10,0.20),"积极":(0.20,1.0)}`
- `config.BOND_PLUS_TARGET_DD = -0.03`(目标回撤阈值)
- `scoring.score_all(df, dim_weights=..., indicators=..., veto_dim="B_risk", primary_dim="A_return")` 已参数化,直接传 BOND_PLUS 配置即可复用整套分位/覆盖率/否决/池逻辑。
- 可复用 `metrics.py`(回撤/卡玛/索提诺等)与 `metrics_bond.py`(compute_bond_metrics:campisi_alpha/monthly_positive_ratio 等)。
- 债底 C 维(credit_sink/duration_dev)与 convertible_ratio 由 `cdim_bond.load_cdim_bond` 提供(已落地),你的模块**不用重拉**,假定这些列可能已在 df 中(缺则该指标自动按剩余权重归一)。

## 你的任务:新建 `scripts/scoring_bond_plus.py`

### 1. 权益中枢分组
```python
def equity_center_band(equity_position: float) -> str:
    """按 config.BOND_PLUS_EQUITY_BANDS 把权益仓位映射到 保守/稳健/积极;缺失返回 '未分组'。"""
```
- 输入 equity_position(0~1,来自 akshare 资产配置 / data_akshare.fund_meta 的 equity_position 字段)
- 固收+ 评分在**同一权益档内**做分位(类比纯债的 effective_group)

### 2. 固收+ 特有指标(净值法,无需持仓;数据源用 akshare 或已有净值)
实现两个 config.BOND_PLUS_INDICATORS 里标 ★ 的指标:
```python
def target_dd_pass(nav: pd.Series, target: float = None) -> float:
    """目标回撤达标率: 滚动(如60日)最大回撤不破 target(默认 config.BOND_PLUS_TARGET_DD)的时间占比。
    越高越好(dir 1)。"""

def equity_contrib_ratio(nav: pd.Series, equity_index_ret: pd.Series) -> float:
    """股债贡献分解(净值回归近似): 用基金周/日收益对权益指数(如沪深300)回归,
    equity_contrib = beta * 指数累计收益; 返回 equity_contrib / 总收益 的占比(U型: 适度)。
    无指数数据则返回 NaN(该指标自动跳过)。"""
```
- 其余 BOND_PLUS 指标(ann_return/campisi_alpha/monthly_positive_ratio/max_drawdown/calmar/recovery_days/convertible_ratio/credit_sink/duration_dev/manager_experience/management_load/total_fee/inst_ratio)**已可由 metrics_bond + cdim_bond + meta 提供**,你的 build 函数把它们组装进 df 即可,不要重复造轮子。

### 3. 组装 + 评分主函数
```python
def score_bond_plus(df: pd.DataFrame) -> pd.DataFrame:
    """输入: 含固收+ 基金的指标宽表(已含 equity_position 及上述指标列)。
    步骤: 按 equity_center_band 分组 -> 每组(>=5只)调用
      scoring.score_all(g, dim_weights=config.BOND_PLUS_DIM_WEIGHTS,
                        indicators=config.BOND_PLUS_INDICATORS,
                        veto_dim='B_risk', primary_dim='A_return')
    -> 合并返回(带 equity_band 列)。"""
```

### 4. 自测 `if __name__ == "__main__":` + 单测 `test_scoring_bond_plus.py`
- 合成 ~30 只固收+(跨三档权益中枢)净值 + 指标,跑 score_bond_plus
- 断言:综合分 ∈ [0,100];同档内分位独立;目标回撤达标率高的基金 B 维更高;
  target_dd_pass/equity_contrib_ratio 计算正确(用构造数据验证:无回撤净值达标率=1.0)
- 合成数据测试**不依赖网络**(equity_index_ret 也用合成序列)

## 验收标准
- `scoring_bond_plus.py` 独立可跑;`test_scoring_bond_plus.py` 全部断言通过
- 不改任何现有 .py;只用 config.BOND_PLUS_* + scoring.score_all + metrics/metrics_bond
- 权益中枢分组正确;target_dd_pass / equity_contrib_ratio 算法正确且有单测
- 风格与 scoring/screening 一致(阈值集中、缺列防御、注释清晰)

## 交付方式(COLLABORATION.md)
- 写好两个文件 + 本地可选 `git commit -m "[codex] feat: 固收+记分卡 scoring_bond_plus"`(**不 push**)
- 完成后本文件末尾追加:`✅ 已完成 YYYY-MM-DD, 三档分组N只, 测试通过`,并报 Jayden"待统一推送"

## 边界
- ✅ 只新建 scoring_bond_plus.py + test_scoring_bond_plus.py
- ❌ 不改 config/scoring/metrics_bond/run_monthly_bond/cdim_bond 等任何现有文件,不 push
- 参考:`10_固收线框架v0.4.md` 第4节 + 现有 scoring.py / metrics_bond.py 风格
- akshare 在本机可用(沙箱不可);权益指数可用 ak 取沪深300,或测试用合成序列

✅ 已完成 2026-06-14(Codex):新增 scoring_bond_plus.py + test_scoring_bond_plus.py,三档共30只合成样本测试通过,未改主线文件。主线已对接(run_monthly_bond 分流自动切 BOND_PLUS)。待统一推送。
