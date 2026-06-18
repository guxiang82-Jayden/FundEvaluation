"""C/E 维数据合并层(数据由 Claude 会话内用且慢 MCP 批量拉取后存 CSV)
MCP 仅会话内可用, 独立脚本调不了 -> 与 manager_tenure 同模式

CSV: data/cdim_data.csv, 列:
  fund_code, brinson_ar, brinson_sr, brinson_er, conc_cr5, turnover_rate,
  style_stability, style_switches_2y, rbsa_r2,
  style_large_value/style_large_growth/style_small_value/style_small_growth
  (来源: getFundBrinsonIndicator / getFundIndustryConcentration / getFundTurnoverRate)

派生指标(供 scoring):
  selection_share = sr/er  (C1 选股贡献占比; er<=0 时置 NaN 不参评)
  style_stability          (C2 RBSA滚动权重稳定度, 0-1)
  style_switches_2y        (N7 近2年风格标签切换次数)
  concentration   = cr5    (C4 集中度, U型计分由 scoring 处理)
  turnover        = turnover_rate (E2, 越低越好, 量化标签豁免-待v0.4)
"""
import os

import numpy as np
import pandas as pd

CDIM_CSV = os.path.join("data", "cdim_data.csv")
RBSA_MIN_R2 = 0.20


def _numeric_column(df: pd.DataFrame, name: str) -> pd.Series:
    if name not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=float)
    return pd.to_numeric(df[name], errors="coerce")


def load_cdim(meta_df: pd.DataFrame) -> pd.DataFrame:
    """把 C/E 维派生指标 merge 进 meta/df. 无 CSV 或未命中则留空(评分自动降级)"""
    if not os.path.exists(CDIM_CSV):
        return meta_df
    c = pd.read_csv(CDIM_CSV, dtype={"fund_code": str})
    c["fund_code"] = c["fund_code"].str.zfill(6)

    # 派生指标
    er = _numeric_column(c, "brinson_er")
    sr = _numeric_column(c, "brinson_sr")
    c["selection_share"] = np.where(er > 0.02, sr / er, np.nan)
    # 选股占比理论上 0~1, 极端值裁剪(配置/选股可互为负)
    c["selection_share"] = c["selection_share"].clip(-1, 2)
    c["concentration"] = _numeric_column(c, "conc_cr5")
    c["turnover"] = _numeric_column(c, "turnover_rate")

    optional = [
        "style_stability", "style_switches_2y", "rbsa_r2",
        "style_large_value", "style_large_growth",
        "style_small_value", "style_small_growth",
    ]
    if "rbsa_r2" in c.columns:
        reliable = pd.to_numeric(c["rbsa_r2"], errors="coerce") >= RBSA_MIN_R2
        for col in ("style_stability", "style_switches_2y"):
            if col in c.columns:
                c.loc[~reliable, col] = np.nan
    keep = ["fund_code", "selection_share", "concentration", "turnover"]
    keep += [col for col in optional if col in c.columns]
    # data_akshare 会为部分筛选字段预放空占位列；真实 C 维数据应覆盖占位，
    # 避免 merge 后生成 style_switches_2y_x/_y 导致 N7 看不到字段。
    replace_cols = [col for col in keep if col != "fund_code" and col in meta_df.columns]
    out = meta_df.drop(columns=replace_cols).merge(c[keep], on="fund_code", how="left")
    hit = c["fund_code"].isin(meta_df["fund_code"]).sum()
    style_hit = (out["style_stability"].notna().sum()
                 if "style_stability" in out.columns else 0)
    print(f"  C/E维补充: 命中 {hit} 只 -> C1/C4/E2; "
          f"RBSA风格命中 {style_hit} 只 -> C2/N7 生效")
    return out
