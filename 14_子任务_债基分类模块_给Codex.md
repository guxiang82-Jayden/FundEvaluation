# 子任务:债基 L0 分类独立模块(给本机 Codex)

> **隔离原则**:只新建 `scripts/classify_bond.py` 一个文件 + 测试。**不修改任何现有 .py**(尤其不动 classify.py / data_akshare.py / scoring.py)。零冲突。

## 背景

v0.4 固收线需要债基的 L0 同类组分类(类比主动权益的 classify.py)。设计已在 `10_固收线框架v0.4.md` 第1节定好,本任务把它实现为独立模块,供未来债基记分卡调用。

## 你的任务

新建 `scripts/classify_bond.py`,实现债基分类:

### 1. 资产主干分类(按东财 fund_type 字符串 + 名称)
东财债基类型字符串实测形如:`债券型-长债`、`债券型-中短债`、`债券型-混合一级`、`债券型-混合二级`、`债券型-可转债` 等(你可用 `ak.fund_name_em()` 取全量验证实际字符串)。

映射到项目口径子组:
- 短期纯债（中短债、短债）
- 中长期纯债（长债）
- 混合债券一级（混合一级、可投转债不可买股）
- 混合债券二级（混合二级，≤20%权益）
- 偏债混合 / 固收+（混合型-偏债 等）
- 可转债基金（单列）

### 2. 策略标签(正交第二轴,从名称提取)
- 利率债型 / 信用债型(名称含"信用")
- 信用下沉(待持仓数据,先留接口)
- 摊余成本法(名称含"摊余")
- 持有期(名称含"持有"/"定开")
- 同业存单(名称含"同业存单")

### 3. 函数签名(对齐 classify.py 风格)
```python
def classify_bond(df: pd.DataFrame) -> pd.DataFrame:
    """输入 df(含 fund_code, fund_name, fund_type),
    返回 df + bond_subgroup / bond_strategy_tags / classify_confidence"""
```
参考 `scripts/classify.py` 的实现风格(资产主干 + 策略标签 + 置信度三档),但**新建独立文件,不要 import 或修改 classify.py**。

### 4. 取全量债基测试
写 `if __name__ == "__main__":`,用 `ak.fund_name_em()` 取全市场,筛出债券型,跑 classify_bond,打印各子组数量分布(类似主线 run_monthly 的 "effective_group" 统计)。

### 5. 单元测试 `scripts/test_classify_bond.py`
合成几条债基样本(各类型 + 各策略名),断言分类正确(短债→短期纯债、混合二级→混合债券二级、含"摊余"→摊余标签等)。

## 验收标准
- `classify_bond.py` 独立可跑,全市场债基能分出合理子组分布(主要子组数量级合理,如中长期纯债应是大头)
- `test_classify_bond.py` 全部断言通过
- 不修改任何现有 .py 文件
- 分类口径与 `10_固收线框架v0.4.md` 第1节一致

## 提交方式
```bash
git pull --rebase
git add scripts/classify_bond.py scripts/test_classify_bond.py
git commit -m "[codex] feat: 债基L0分类模块 classify_bond.py"
git push
```
- commit 带 `[codex]` 前缀;push 前 `git pull --rebase`
- 完成后本文件末尾追加:`✅ 已完成 YYYY-MM-DD, 子组N个, 测试通过`

## 边界
- ✅ 只新建 classify_bond.py + test_classify_bond.py
- ❌ 不改 classify.py / 任何现有 .py / 不 `git add .`
- 东财债基类型字符串以你实测 `ak.fund_name_em()` 的结果为准,注释里写清实际字符串
- 参考文档:`10_固收线框架v0.4.md` 第1节(债基分类设计)

✅ 已完成 2026-06-14, 子组6个, 测试通过
