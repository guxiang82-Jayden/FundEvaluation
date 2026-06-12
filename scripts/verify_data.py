"""AKShare 数据接口本机验证脚本
用途: 逐项体检评估框架所需接口, 输出字段名+样例+PASS/FAIL
运行: .venv 激活后 python verify_data.py
把完整输出贴回给 Claude, 据此修正 data_akshare.py 的字段映射
"""
import sys
import traceback

import pandas as pd

pd.set_option("display.max_columns", 20)
pd.set_option("display.width", 200)

try:
    import akshare as ak
    print(f"akshare {ak.__version__} | pandas {pd.__version__} | python {sys.version.split()[0]}")
except ImportError:
    sys.exit("akshare 未安装")

RESULTS = []


def check(name, fn):
    print(f"\n{'='*60}\n[{name}]")
    try:
        out = fn()
        print("PASS")
        RESULTS.append((name, "PASS", out))
    except Exception as e:  # noqa: BLE001
        print(f"FAIL: {type(e).__name__}: {e}")
        traceback.print_exc(limit=1)
        RESULTS.append((name, "FAIL", str(e)))


def show(df, n=3):
    print(f"shape={df.shape}")
    print(f"columns={list(df.columns)}")
    print(df.head(n).to_string())
    return f"{df.shape}"


# 1. 全量基金列表(东财)
check("fund_name_em 全量基金列表", lambda: show(ak.fund_name_em()))

# 2. 开放式基金实时行情列表(天天基金, 含类型)
check("fund_open_fund_daily_em 开放式基金列表", lambda: show(ak.fund_open_fund_daily_em()))

# 3. 单基金净值(天天) - 用 005827
check("fund_open_fund_info_em 累计净值走势", lambda: show(
    ak.fund_open_fund_info_em(symbol="005827", indicator="累计净值走势")))

check("fund_open_fund_info_em 单位净值走势", lambda: show(
    ak.fund_open_fund_info_em(symbol="005827", indicator="单位净值走势")))

# 4. 雪球基本信息(成立日/规模/经理)
check("fund_individual_basic_info_xq 基本信息", lambda: show(
    ak.fund_individual_basic_info_xq(symbol="005827"), n=15))

# 5. 基金经理(东财全量)
check("fund_manager_em 基金经理全量", lambda: show(ak.fund_manager_em()))

# 6. 持有人结构
def _hold():
    try:
        return show(ak.fund_individual_detail_hold_xq(symbol="005827", date="20241231"))
    except TypeError:
        return show(ak.fund_individual_detail_hold_xq(symbol="005827"))
check("fund_individual_detail_hold_xq 持有人结构", _hold)

# 7. 基金规模
check("fund_scale_open_sina 开放式基金规模", lambda: show(
    ak.fund_scale_open_sina(symbol="股票型基金")))

# 8. 季报持仓
check("fund_portfolio_hold_em 持仓", lambda: show(
    ak.fund_portfolio_hold_em(symbol="005827", date="2026")))

# 9. 指数行情(基准合成): 中证800
check("stock_zh_index_daily 中证800", lambda: show(
    ak.stock_zh_index_daily(symbol="sh000906")))

# 10. 巨潮风格指数(RBSA 风格基)
check("stock_zh_index_daily 巨潮大盘成长 sz399372", lambda: show(
    ak.stock_zh_index_daily(symbol="sz399372")))

# 11. 债券指数(基准合成, 探测可用性)
def _bond_index():
    try:
        return show(ak.bond_new_composite_index_cbond(indicator="财富", period="总值"))
    except Exception:
        return show(ak.bond_composite_index_cbond(indicator="财富", period="总值"))
check("中债综合指数", _bond_index)

# 12. 基金费率/交易规则
check("fund_fee_em 费率", lambda: show(ak.fund_fee_em(symbol="005827", indicator="申购费率")))

# 13. 业绩基准文本(基本概况)
def _overview():
    df = ak.fund_individual_basic_info_xq(symbol="163406")
    kv = dict(zip(df.iloc[:, 0], df.iloc[:, 1]))
    print({k: str(v)[:60] for k, v in kv.items()})
    return "ok"
check("163406 基本信息字典(看是否含业绩基准)", _overview)

# 汇总
print(f"\n{'='*60}\n汇总:")
for name, status, _ in RESULTS:
    print(f"  {'✅' if status=='PASS' else '❌'} {name}")
n_fail = sum(1 for _, s, _ in RESULTS if s == "FAIL")
print(f"\n{len(RESULTS)-n_fail}/{len(RESULTS)} 通过。请把以上完整输出贴回给 Claude。")
