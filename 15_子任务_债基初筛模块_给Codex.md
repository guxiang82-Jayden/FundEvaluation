# 子任务:债基 L1 负面初筛独立模块(给本机 Codex)

> 遵循 COLLABORATION.md:**只本地 commit,不 push**;完成后回报"待统一推送"。
> **隔离原则**:只新建 `scripts/screening_bond.py` + 测试。不改任何现有 .py(尤其不动 screening.py)。

## 背景

v0.4 固收线需要债基的 L1 负面初筛(类比主动权益 screening.py)。设计在 `10_固收线框架v0.4.md` 第2节已定,本任务实现为独立模块。

## 你的任务

新建 `scripts/screening_bond.py`,实现债基负面初筛(对应框架第2节 FN1-FN6):

| # | 规则 | 阈值(v0.4先验) | 说明 |
|---|---|---|---|
| FN1 | 规模过小 | 合并规模 < 0.5亿 | 清盘线,纯债更敏感 |
| FN2 | 成立太短 | < 1 年 | 净值五因子回归需≥1年周频 |
| FN3 | 经理变更 | 近6个月换将且无共管 | |
| FN4 | 杠杆超限 | 杠杆率 > 140% | 开放式上限,触线预警 |
| FN5 | 踩雷记录 | 持仓违约/净值异动 | 排雷(数据待接,先留接口) |
| FN6 | 机构定制盘 | 机构持有>95%且户数极少 | 大额申赎风险 |

### 函数签名(对齐 screening.py 风格)
```python
def apply_screening_bond(df: pd.DataFrame) -> pd.DataFrame:
    """输入债基元数据df, 输出带剔除标记与原因的df。
    必需列(缺列则该规则跳过并记warning):
      fund_code, fund_name, scale_yi, fund_age_years,
      manager_changed_recent, leverage_ratio, neg_alert, inst_ratio
    返回 df + screen_reasons / screened_out / channel 列"""
```

参考 `scripts/screening.py` 的实现风格(逐规则 flag、reasons 拼接、channel 划分),但**新建独立文件,不 import 或修改 screening.py**。

- 阈值集中在文件顶部常量(便于调参),对齐 config 风格
- 缺列的规则自动跳过(像主线 screening 那样防御),不报错
- channel: "standard"(通过) / "excluded"(剔除)

### 单元测试 `scripts/test_screening_bond.py`
合成债基样本(各触发一条规则 + 正常的),断言:
- 规模0.3亿→FN1剔除
- 成立0.5年→FN2剔除
- 杠杆1.6→FN4剔除
- 正常基金→channel=standard
- 缺列时该规则跳过不报错

## 验收标准
- screening_bond.py 独立可跑(可配合 classify_bond 造样本自测)
- test_screening_bond.py 全部断言通过
- 不修改任何现有 .py
- 阈值与 `10_固收线框架v0.4.md` 第2节一致

## 交付方式(新规则)
- 写好文件 + 本地可选 commit(`[codex]` 前缀),**不 push**
- 完成后本文件末尾追加:`✅ 已完成 YYYY-MM-DD, 测试通过`
- 向 Jayden 报告"已完成,待统一推送"

## 边界
- ✅ 只新建 screening_bond.py + test_screening_bond.py
- ❌ 不改 screening.py / 任何现有 .py / 不 push
- 参考:`10_固收线框架v0.4.md` 第2节 + 现有 `scripts/screening.py` 的代码风格

✅ 已完成 2026-06-14, 测试通过
