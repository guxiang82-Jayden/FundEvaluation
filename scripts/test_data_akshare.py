"""data_akshare 取数适配测试(合成, 无网络)。"""
import pandas as pd

import data_akshare as da
import screening_bond


class _DummyAk:
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


def _patch_common():
    old = {
        "ak": da.ak,
        "cached": da.cached,
        "fund_meta": da.fund_meta,
    }
    da.ak = _DummyAk()
    da.cached = lambda _name, fetch_fn, max_age_days=1: fetch_fn()
    da.fund_meta = lambda code, verbose=False: {
        "fund_code": str(code).zfill(6),
        "fund_name": "定期开放样本" if str(code).zfill(6) == "000212" else "普通样本",
        "scale_yi": 20,
        "fund_age_years": 5,
    }
    return old


def _restore(old):
    da.ak = old["ak"]
    da.cached = old["cached"]
    da.fund_meta = old["fund_meta"]


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


if __name__ == "__main__":
    test_fund_purchase_status_normalize()
    test_build_meta_table_merge_and_warn_hit()
    test_build_meta_table_purchase_failure_degrades()
    test_csi_index_returns()
    print("\ndata_akshare tests passed")
