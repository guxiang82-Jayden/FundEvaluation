"""L0 同类组细分模块 (v0.2 预备, 暂未接入主流程 —— 等用户确认后在 run_monthly 启用)
输入: universe df(fund_code, fund_name, fund_type) + 可选 equity_position(Series, index=fund_code)
输出: subgroup(评分同类组), strategy_tags(第二轴标签), classify_confidence
设计依据: research/基金评估-公募基金分类与评价指标映射.md 第三节(资产主干 × 策略标签正交)
离线测试: 2026-06-13 合成数据断言通过(见交接文档)
"""
import re

import pandas as pd

# 行业主题关键词 -> 主题名(命中后同类组单列为 行业主题:X, 评分基准应换行业指数)
INDUSTRY_KEYWORDS = {
    "医药|医疗|健康|生物|创新药": "医药",
    "消费|食品|饮料|白酒|酒": "消费",
    "科技|互联网|信息|TMT|电子": "科技",
    "半导体|芯片|集成电路": "半导体",
    "人工智能|AI|智能(?!制造)": "AI",
    "新能源|光伏|电池|风电|碳中和": "新能源",
    "军工|国防|航空航天|卫星": "军工航天",
    "金融|银行|证券|地产": "金融地产",
    "制造|高端装备|智能制造|先进制造": "高端制造",
    "资源|有色|周期|能源|煤炭|钢铁": "资源周期",
    "农业|养殖": "农业",
    "环保|低碳|ESG": "环保ESG",
    "机器人|具身": "机器人",
}

# 策略标签(正交第二轴, 不改变同类组; 量化中性/指增已在主动权益组之外)
STRATEGY_PATTERNS = {
    "量化": r"量化|大数据|多因子",
    "沪港深": r"沪港深|港股通|恒生|香港",
    "红利": r"红利|股息",
    "打新": r"打新",
    "定增": r"定增",
}


def classify(df: pd.DataFrame, equity_position: pd.Series = None) -> pd.DataFrame:
    """返回 df + subgroup / strategy_tags / classify_confidence 列"""
    out = df.copy()
    name = out["fund_name"].fillna("")
    ftype = out["fund_type"].fillna("")

    # 1) 资产主干子组
    sub = pd.Series("unknown", index=out.index)
    sub[ftype.str.contains("股票型")] = "普通股票型"
    sub[ftype.str.contains("混合型-偏股")] = "偏股混合型"
    sub[ftype.str.contains("混合型-灵活|混合型-平衡")] = "灵活配置型"
    conf = pd.Series("high", index=out.index)
    conf[sub == "unknown"] = "low"

    # 灵活配置型: 权益仓位<60% 出组复核; 无仓位数据降置信度
    # TODO v0.2: 改用近4季仓位中枢(当前仅最新单期, 已知近似)
    if equity_position is not None:
        ep = out["fund_code"].map(equity_position)
        low_ep = (sub == "灵活配置型") & (ep < 0.60)
        sub[low_ep] = "偏债倾向(出组复核)"
        conf[low_ep] = "low"
        conf[(sub == "灵活配置型") & ep.isna()] = "medium"
    else:
        conf[sub == "灵活配置型"] = "medium"

    # 保留资产主干(行业主题组样本<10只时回退到主干组评分)
    backbone = sub.copy()

    # 2) 行业主题(首个命中关键词生效)
    theme = pd.Series("", index=out.index)
    for pat, label in INDUSTRY_KEYWORDS.items():
        hit = name.str.contains(pat, regex=True) & (theme == "")
        theme[hit] = label
    is_theme = theme != ""
    sub[is_theme] = "行业主题:" + theme[is_theme]
    out["backbone"] = backbone

    # 3) 策略标签(可多标签, "+"连接)
    def _tags(n: str) -> str:
        hits = [label for label, pat in STRATEGY_PATTERNS.items() if re.search(pat, n)]
        return "+".join(hits)

    out["subgroup"] = sub
    out["strategy_tags"] = name.map(_tags)
    out["classify_confidence"] = conf
    return out


def subgroup_stats(out: pd.DataFrame) -> pd.DataFrame:
    """各同类组数量统计. 评分前检查: 组内<10只不单独评级(并入相近组), 参考银河规则"""
    return out.groupby("subgroup").size().sort_values(ascending=False).rename("count").to_frame()
