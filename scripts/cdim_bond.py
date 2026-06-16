"""C 维(债基)数据合并层 — 数据由会话内且慢 MCP 批量拉取后存 CSV(同 cdim.py 模式)。
MCP 仅会话内可用, 独立脚本调不了 -> 与 manager_tenure / cdim 同模式。

CSV: data/cdim_bond_data.csv, 列:
  fund_code, credit_ratio, convertible_ratio, leverage_ratio,
  dur_sensitive, cr5_bond, neg_alert, pick_effect(可选)
  (来源: 且慢 getBondAllocationByFundCode / getBondIndicator / getBondFundWithAlertRecord)

派生指标(供 scoring 的 config.BOND_INDICATORS C 维 + screening_bond):
  credit_sink      = credit_ratio    (C2 信用下沉, U型: 适度为佳;
                                       中债隐含评级分布源在本部署为空, 用信用债净资产占比代理)
  duration_dev     = dur_sensitive   (C3 久期偏离, U型: 距同类中枢近=稳健)
  leverage_contrib = leverage_ratio  (C4 杠杆套息, 越高套息贡献越大)
  pick_alpha_bond  = pick_effect     (C1b 持仓法 Campisi 券种选择效应; 与净值法 C1a 互补)
  (C1a selection_share_bond 由净值 Campisi 残差衍生, 不在本持仓层)
  leverage_ratio / neg_alert 直通 screening_bond(FN4 杠杆超限 / FN5 踩雷)
"""
import os

import pandas as pd

CDIM_BOND_CSV = os.path.join("data", "cdim_bond_data.csv")


def load_cdim_bond(df: pd.DataFrame) -> pd.DataFrame:
    """把 C 维派生指标 + 排雷/杠杆 merge 进 df。无 CSV 或未命中则留空(评分自动降级)。"""
    if not os.path.exists(CDIM_BOND_CSV):
        return df
    c = pd.read_csv(CDIM_BOND_CSV, dtype={"fund_code": str})
    c["fund_code"] = c["fund_code"].str.zfill(6)

    c["credit_sink"] = c["credit_ratio"]
    c["duration_dev"] = c["dur_sensitive"]
    c["leverage_contrib"] = c["leverage_ratio"]
    if "pick_effect" in c.columns:
        c["pick_alpha_bond"] = c["pick_effect"]

    keep = ["fund_code", "credit_sink", "duration_dev", "leverage_contrib",
            "pick_alpha_bond", "leverage_ratio", "neg_alert", "cr5_bond", "convertible_ratio"]
    keep = [k for k in keep if k in c.columns]
    out = df.merge(c[keep], on="fund_code", how="left")
    hit = c["fund_code"].isin(df["fund_code"]).sum()
    print(f"  C维补充(且慢债基源): 命中 {hit} 只 -> C2信用/C3久期/C4杠杆 + 排雷/杠杆筛 生效")
    return out
