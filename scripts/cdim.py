"""C/E 维数据合并层(数据由 Claude 会话内用且慢 MCP 批量拉取后存 CSV)
MCP 仅会话内可用, 独立脚本调不了 -> 与 manager_tenure 同模式

CSV: data/cdim_data.csv, 列:
  fund_code, brinson_ar, brinson_sr, brinson_er, conc_cr5, turnover_rate
  (来源: getFundBrinsonIndicator / getFundIndustryConcentration / getFundTurnoverRate)

派生指标(供 scoring):
  selection_share = sr/er  (C1 选股贡献占比; er<=0 时置 NaN 不参评)
  concentration   = cr5    (C4 集中度, U型计分由 scoring 处理)
  turnover        = turnover_rate (E2, 越低越好, 量化标签豁免-待v0.4)
"""
import os

import numpy as np
import pandas as pd

CDIM_CSV = os.path.join("data", "cdim_data.csv")


def load_cdim(meta_df: pd.DataFrame) -> pd.DataFrame:
    """把 C/E 维派生指标 merge 进 meta/df. 无 CSV 或未命中则留空(评分自动降级)"""
    if not os.path.exists(CDIM_CSV):
        return meta_df
    c = pd.read_csv(CDIM_CSV, dtype={"fund_code": str})
    c["fund_code"] = c["fund_code"].str.zfill(6)

    # 派生指标
    er = c["brinson_er"]
    c["selection_share"] = np.where(er > 0.02, c["brinson_sr"] / er, np.nan)
    # 选股占比理论上 0~1, 极端值裁剪(配置/选股可互为负)
    c["selection_share"] = c["selection_share"].clip(-1, 2)
    c["concentration"] = c["conc_cr5"]
    c["turnover"] = c["turnover_rate"]

    keep = ["fund_code", "selection_share", "concentration", "turnover"]
    out = meta_df.merge(c[keep], on="fund_code", how="left")
    hit = c["fund_code"].isin(meta_df["fund_code"]).sum()
    print(f"  C/E维补充(且慢源): 命中 {hit} 只 -> C1选股/C4集中/E2换手 生效")
    return out
