"""build_index_navs 映射与指数收益加载测试(合成, 无网络)。"""
import tempfile

import pandas as pd

import build_index_navs as binavs


def test_load_merge_and_fetch():
    print("== BOND_INDEX 映射读取/合并/收益加载 ==")
    csv = "fund_code,index_code,index_name,index_mainstream\n1,CBA00101,中债综合,0.9\n2,,QDII留空,0.4\n"
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv)
        path = f.name
    mapping = binavs.load_index_map(path)
    assert list(mapping["fund_code"]) == ["000001", "000002"]
    base = pd.DataFrame({
        "fund_code": ["000001", "000002", "000003"],
        "index_code": [pd.NA, "KEEP", pd.NA],
    })
    merged = binavs.merge_index_map(base, mapping)
    rows = merged.set_index("fund_code")
    assert rows.loc["000001", "index_code"] == "CBA00101"
    assert rows.loc["000002", "index_code"] == "KEEP"
    old = binavs.da.index_returns
    binavs.da.index_returns = lambda code: pd.Series([0.01, 0.02], index=pd.date_range("2026-01-01", periods=2))
    try:
        ret_map = binavs.build_index_ret_map(mapping)
    finally:
        binavs.da.index_returns = old
    assert list(ret_map) == ["CBA00101"]
    print("  csv normalize / preserve existing columns / skip empty mapping OK")


if __name__ == "__main__":
    test_load_merge_and_fetch()
    print("\nbuild_index_navs tests passed")
