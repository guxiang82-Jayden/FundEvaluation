"""债基 Campisi 净值归因端到端试跑(v0.4)
串起 data_bond(中债因子) + campisi(五因子回归) + AKShare 债基净值
用法:
  python run_bond_campisi.py 000186 100018 003547   # 指定债基代码
  python run_bond_campisi.py                          # 用内置样本

输出: 每只债基的 R²、年化alpha、置信度、各因子beta;批量时存 output/bond_campisi_<date>.csv
注: 纯债 R²>0.7 alpha可信; 含权(二级债基/固收+) R²<0.5 标低置信度须辅持仓
"""
import sys
from datetime import date

import pandas as pd

import campisi
import data_bond

# 内置样本: 几类债基(纯债/信用债/二级债)
SAMPLE_BONDS = ["000186", "100018", "003547", "270048", "001021"]


def fund_nav_daily(fund_code: str) -> pd.Series:
    """债基日累计净值(复用 data_bond 内部取数, 与主线 data_akshare 一致口径)"""
    return data_bond._fund_nav(fund_code)


def analyze_one(fund_code: str, factors: pd.DataFrame) -> dict:
    try:
        nav = fund_nav_daily(fund_code)
        wk = campisi.nav_to_weekly(nav)
        r = campisi.campisi_regress(wk, factors)
        r["fund_code"] = fund_code
        return r
    except Exception as e:  # noqa: BLE001
        return {"fund_code": fund_code, "error": str(e)[:60],
                "r2": None, "alpha_ann": None, "confidence": "error"}


def main():
    codes = sys.argv[1:] or SAMPLE_BONDS
    print(f"== 取中债因子 ==")
    idx_ret = data_bond.bond_index_weekly_returns()
    factors = campisi.build_factors(idx_ret)
    print(f"可用因子: {list(factors.columns)} | 周数据 {len(factors)}")

    print(f"\n== Campisi 归因 {len(codes)} 只债基 ==")
    rows = []
    for code in codes:
        r = analyze_one(code, factors)
        rows.append(r)
        if r.get("error"):
            print(f"  {code}: 失败 {r['error']}")
        else:
            betas = " ".join(f"{k}={v:+.2f}" for k, v in r["betas"].items())
            print(f"  {code}: R²={r['r2']:.3f} ({r['confidence']}) "
                  f"alpha年化={r['alpha_ann']:+.2%} | {betas}")

    # 汇总表
    df = pd.DataFrame([{k: v for k, v in r.items() if k != "betas"} for r in rows])
    import os
    os.makedirs("output", exist_ok=True)
    out = os.path.join("output", f"bond_campisi_{date.today().isoformat()}.csv")
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\n输出: {out}")
    # 简单质检
    ok = df["confidence"].isin(["high", "medium"]).sum() if "confidence" in df else 0
    print(f"可信归因(R²≥0.5): {ok}/{len(df)} | 纯债alpha可信(high): {(df['confidence']=='high').sum() if 'confidence' in df else 0}")


if __name__ == "__main__":
    main()
