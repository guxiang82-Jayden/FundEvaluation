"""L1 负面初筛
输入: 基金元数据 DataFrame (一行一基金), 输出: 带剔除标记与原因的 DataFrame
必需列(适配层负责提供, 缺列则对应规则跳过并记 warning):
  fund_code, fund_name, scale_yi(合并规模/亿), fund_age_years, tenure_years,
  manager_changed_recent(bool), inst_ratio, style_switches_2y, fund_age_for_style(年),
  equity_low_quarters(连续<50%仓位的季度数), negative_record(bool)
"""
import pandas as pd

import config

S = config.SCREENING


def is_theme_whitelisted(fund_name: str) -> bool:
    if not isinstance(fund_name, str):
        return False
    return any(kw.lower() in fund_name.lower() for kw in config.THEME_WHITELIST)
    # TODO: v0.2 升级为 名称+招募书文本+持仓 三重匹配


def apply_screening(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    reasons = {i: [] for i in df.index}

    def flag(mask, code):
        for i in df.index[mask.fillna(False)]:
            reasons[i].append(code)

    theme = df["fund_name"].map(is_theme_whitelisted) if "fund_name" in df else pd.Series(False, index=df.index)
    df["theme_whitelisted"] = theme

    if "scale_yi" in df:
        flag(df["scale_yi"] < S["N1_min_scale"], "N1_规模过小")
        flag(df["scale_yi"] > S["N2_max_scale"], "N2_规模过大")
    if "fund_age_years" in df:
        flag((df["fund_age_years"] < S["N3_min_fund_age_years"]) & (~theme), "N3_成立太短")
    if "tenure_years" in df:
        flag((df["tenure_years"] < S["N4_min_tenure_years"]) & (~theme), "N4_任期太短")
    if "manager_changed_recent" in df:
        flag(df["manager_changed_recent"] == True, "N5_经理近期变更")  # noqa: E712
    if "inst_ratio" in df:
        flag(df["inst_ratio"] > S["N6_max_inst_ratio"], "N6_机构定制盘")
    if "style_switches_2y" in df and "fund_age_for_style" in df:
        # N7 不豁免: 成立>=2年即适用
        flag((df["fund_age_for_style"] >= 2) & (df["style_switches_2y"] > S["N7_max_style_switches"]),
             "N7_风格漂移")
    if "negative_record" in df:
        flag(df["negative_record"] == True, "N8_负面记录")  # noqa: E712
    if "equity_low_quarters" in df:
        flag(df["equity_low_quarters"] >= S["N9_min_equity_quarters"], "N9_仓位异常")

    df["screen_reasons"] = [";".join(reasons[i]) for i in df.index]
    df["screened_out"] = df["screen_reasons"] != ""
    # 通道划分
    df["channel"] = "standard"
    df.loc[df["screened_out"], "channel"] = "excluded"
    # 主题豁免且年限不足 -> 观察通道(不入标准记分卡)
    if "fund_age_years" in df:
        obs = theme & (df["fund_age_years"] < 3) & (~df["screened_out"])
        df.loc[obs, "channel"] = "theme_observation"
    return df
