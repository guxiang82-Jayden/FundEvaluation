"""data_akshare 取数适配测试(合成, 无网络)。"""
import pandas as pd

import data_akshare as da
import screening_bond


class _DummyAk:
    @staticmethod
    def fund_open_fund_info_em(symbol, indicator):
        if indicator == "单位净值走势":
            return pd.DataFrame({
                "净值日期": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]),
                "单位净值": [1.00, 0.95, 0.96],
                "日增长率": [0.0, -5.0, 1.05],
            })
        if indicator == "分红送配详情":
            return pd.DataFrame({
                "除息日": ["2025-01-02"],
                "每份分红": ["每份派现金0.0500元"],
            })
        raise AssertionError(indicator)

    @staticmethod
    def fund_fee_em(symbol, indicator):
        assert indicator == "运作费用"
        return pd.DataFrame([[
            "管理费率", "1.20%（每年）",
            "托管费率", "0.20%（每年）",
            "销售服务费率", "---",
        ]])

    @staticmethod
    def fund_purchase_em():
        return pd.DataFrame({
            "基金代码": ["212", "000134", "000001"],
            "基金简称": ["国泰估值优势混合", "信澳信用债A", "样本基金"],
            "申购状态": ["暂停申购", "暂停个人买入", "开放申购"],
            "赎回状态": ["暂停赎回", "开放赎回", "开放赎回"],
            "下一开放日": ["2026-07-01", "", ""],
        })

    @staticmethod
    def stock_zh_index_hist_csindex(symbol, start_date="20040101", end_date="20991231"):
        assert symbol == "931059"
        return pd.DataFrame({
            "日期": pd.date_range("2026-01-01", periods=4),
            "收盘": [100.0, 100.1, 100.3, 100.6],
        })

    @staticmethod
    def bond_index_general_cbond(index_category, indicator="财富", period="总值"):
        assert index_category == "国开行债券总指数"
        assert indicator == "财富"
        assert period == "1-3年"
        return pd.DataFrame({
            "date": pd.date_range("2026-01-01", periods=4),
            "value": [200.0, 200.2, 200.5, 200.9],
        })


def _patch_common():
    old = {
        "ak": da.ak,
        "cached": da.cached,
        "fund_meta": da.fund_meta,
        "fund_fee_table": da.fund_fee_table,
    }
    da.ak = _DummyAk()
    da.cached = lambda _name, fetch_fn, max_age_days=1: fetch_fn()
    da.fund_meta = lambda code, verbose=False: {
        "fund_code": str(code).zfill(6),
        "fund_name": "定期开放样本" if str(code).zfill(6) == "000212" else "普通样本",
        "scale_yi": 20,
        "fund_age_years": 5,
    }
    da.fund_fee_table = lambda codes: pd.DataFrame({
        "fund_code": [str(code).zfill(6) for code in codes],
        "management_fee": 0.012,
        "custodian_fee": 0.002,
        "sales_service_fee": None,
        "total_fee": 0.014,
    })
    return old


def _restore(old):
    da.ak = old["ak"]
    da.cached = old["cached"]
    da.fund_meta = old["fund_meta"]
    da.fund_fee_table = old["fund_fee_table"]


def test_fund_purchase_status_normalize():
    print("== fund_purchase_status 标准化 ==")
    old = _patch_common()
    try:
        out = da.fund_purchase_status()
    finally:
        _restore(old)
    row = out.set_index("fund_code").loc["000212"]
    assert row["subscribe_status"] == "暂停申购"
    assert row["redeem_status"] == "暂停赎回"
    assert "next_open_date" in out.columns
    print("  code zfill / status columns / next_open_date OK")


def test_build_meta_table_merge_and_warn_hit():
    print("== build_meta_table 合并申赎状态 + 可投性命中 ==")
    old = _patch_common()
    try:
        meta = da.build_meta_table(["000212", "000134", "000001"])
    finally:
        _restore(old)
    assert {"subscribe_status", "redeem_status", "fund_status_text"}.issubset(meta.columns)
    flagged = screening_bond.mark_investability_bond(meta).set_index("fund_code")
    assert bool(flagged.loc["000212", "investability_warn"]) is True
    assert bool(flagged.loc["000134", "investability_warn"]) is True
    assert bool(flagged.loc["000001", "investability_warn"]) is False
    assert "定期开放" in flagged.loc["000212", "fund_status_text"]
    print("  000212/000134 paused status hits investability_warn OK")


def test_build_meta_table_purchase_failure_degrades():
    print("== fund_purchase_status 失败降级 ==")
    old = _patch_common()
    da.fund_purchase_status = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        meta = da.build_meta_table(["000001"])
    finally:
        del da.fund_purchase_status
        import importlib
        importlib.reload(da)
    assert {"subscribe_status", "redeem_status", "fund_status_text"}.issubset(meta.columns)
    assert meta["fund_status_text"].fillna("").eq("").all()
    print("  source failure fills empty columns and does not interrupt OK")


def test_csi_index_returns():
    print("== CSI index_returns 标准化 ==")
    old = _patch_common()
    try:
        ret = da.index_returns("931059.CSI")
    finally:
        _restore(old)
    assert len(ret) == 3
    assert ret.index.is_monotonic_increasing
    assert ret.iloc[-1] > 0
    print("  CSI code routes to csindex close series OK")


def test_cbond_index_returns():
    print("== CBOND index_returns 标准化 ==")
    old = _patch_common()
    try:
        ret = da.index_returns("CBOND_国开行债券总指数_1-3年")
    finally:
        _restore(old)
    assert len(ret) == 3
    assert ret.iloc[-1] > 0
    print("  CBOND source key routes to ChinaBond category/period OK")


def test_reinvested_nav_and_no_dividend():
    print("== 分红再投资复权净值 ==")
    unit = pd.Series(
        [1.00, 0.95, 0.96],
        index=pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"]),
    )
    dividends = pd.DataFrame({
        "date": pd.to_datetime(["2025-01-02"]),
        "dividend": [0.05],
    })
    adjusted = da._reinvest_dividends(unit, dividends)
    unchanged = da._reinvest_dividends(unit, pd.DataFrame())
    assert adjusted.iloc[-1] > unit.iloc[-1]
    assert abs(adjusted.iloc[1] / adjusted.iloc[0] - 1) < 1e-12
    pd.testing.assert_series_equal(unchanged, unit)
    print("  除息日收益连续; 无分红序列不变 OK")


def test_fund_nav_defaults_to_adjusted():
    print("== fund_nav 默认复权口径 ==")
    old = _patch_common()
    try:
        nav = da.fund_nav("000001")
    finally:
        _restore(old)
    assert nav.iloc[-1] > 0.96
    assert abs(nav.iloc[1] / nav.iloc[0] - 1) < 1e-12
    print("  生产入口默认返回分红再投资净值 OK")


def test_operating_fee_parse_and_meta_merge():
    print("== E1 运作费率解析与元数据合并 ==")
    raw = _DummyAk.fund_fee_em("000001", "运作费用")
    fees = da._parse_operating_fee(raw)
    assert fees["管理费率"] == 0.012
    assert fees["托管费率"] == 0.002
    old = _patch_common()
    try:
        meta = da.build_meta_table(["000001"])
    finally:
        _restore(old)
    assert meta.loc[0, "total_fee"] == 0.014
    print("  管理费+托管费+销售服务费 -> total_fee OK")


if __name__ == "__main__":
    test_fund_purchase_status_normalize()
    test_build_meta_table_merge_and_warn_hit()
    test_build_meta_table_purchase_failure_degrades()
    test_csi_index_returns()
    test_cbond_index_returns()
    test_reinvested_nav_and_no_dividend()
    test_fund_nav_defaults_to_adjusted()
    test_operating_fee_parse_and_meta_merge()
    print("\ndata_akshare tests passed")
