"""基金评估框架 v0.1 配置
对应文档: 01_评估框架v0.1.md
所有阈值与权重为先验值, 以回测校准为准 (见文档第6节)
"""

# ---------- 路径 ----------
CACHE_DIR = "cache"
OUTPUT_DIR = "output"

# ---------- L0 同类组定义 (Wind/东财二级分类 -> 项目口径) ----------
ACTIVE_EQUITY_TYPES = {"普通股票型", "偏股混合型", "灵活配置型"}
EQUITY_POSITION_FLOOR = 0.60   # 灵活配置纳入主动权益组的权益中枢下限

# ---------- L1 负面初筛阈值 ----------
SCREENING = {
    "N1_min_scale": 0.5,          # 合并规模下限(亿), 贴近清盘线
    "N2_max_scale": 300.0,        # 规模上限(亿), 待回测校准
    "N3_min_fund_age_years": 1.0, # 成立年限下限 (主题白名单豁免)
    "N4_min_tenure_years": 1.0,   # 现任经理任期下限 (主题白名单豁免)
    "N5_recent_change_months": 6, # 经理变更观察窗口(月)
    "N6_max_inst_ratio": 0.90,    # 机构持有占比上限
    "N7_max_style_switches": 2,   # 近2年风格切换次数上限(成立>=2年适用, 不豁免)
    "N9_min_equity_quarters": 4,  # 连续低仓位季度数
    "N9_equity_floor": 0.50,
}

# 主题白名单 (N3/N4 豁免; 季度复核; 详见 04_主题白名单.md, 2026-06-11 版)
THEME_WHITELIST = [
    # AI/算力
    "人工智能", "AI", "智能", "数字经济", "算力", "云计算",
    # 半导体
    "半导体", "芯片", "集成电路",
    # 机器人/具身智能
    "机器人", "具身智能", "智能制造", "高端装备",
    # 创新药
    "创新药", "生物医药", "医药健康",
    # 航天/军工/低空
    "航空航天", "卫星", "空天", "低空经济", "通用航空", "无人机",
    # 未来产业
    "量子", "6G", "脑机接口", "生物制造", "合成生物",
    # 新能源
    "核能核电", "氢能", "核聚变",
]

# ---------- L2 记分卡 ----------
# 窗口合成权重
WINDOW_WEIGHTS = {"5y": 0.6, "3y": 0.4}   # 无5y数据时只用3y并标记 low_confidence

# 维度权重
DIM_WEIGHTS = {
    "A_return": 0.30,
    "B_risk": 0.25,
    "C_attribution": 0.20,
    "D_manager": 0.15,
    "E_operation": 0.10,
}

# 维度内指标权重 (指标键 -> (权重, 方向: 1=越大越好, -1=越小越好, 0=U型))
INDICATORS = {
    "A_return": {
        "excess_return_ann": (0.40, 1),    # A1 年化超额(对基准)
        "rank_persistence": (0.30, 1),     # A2 滚动1年同类分位中位数
        "monthly_win_rate": (0.15, 1),     # A3 月度超额胜率
        "tenure_excess_ann": (0.15, 1),    # A4 任期年化超额
    },
    "B_risk": {
        "max_drawdown": (0.30, 1),         # B1 (取负后越大越好, 统一在计算层处理为高=好)
        "calmar": (0.30, 1),               # B2
        "sortino": (0.25, 1),              # B3
        "recovery_days": (0.15, -1),       # B4 修复天数越短越好
    },
    "C_attribution": {
        "selection_share": (0.35, 1),      # C1 选股贡献占比
        "style_stability": (0.30, 1),      # C2
        "return_gap": (0.20, 1),           # C3
        "concentration": (0.15, 0),        # C4 U型: 适度集中为佳
    },
    "D_manager": {
        "manager_experience": (0.30, 1),   # D1 经验年限(7年封顶)
        "management_load": (0.30, -1),     # D2 管理半径(规模+产品数, 越大越差)
        "scale_growth": (0.25, -1),        # D3 规模暴增惩罚
        "company_platform": (0.15, 1),     # D4
    },
    "E_operation": {
        "total_fee": (0.50, -1),           # E1
        "turnover": (0.30, -1),            # E2 (量化标签豁免)
        "holder_balance": (0.20, 1),       # E3
    },
}

# ---------- L2 记分卡 · 债基(v0.4 固收线, 对应 10_固收线框架v0.4 第3节) ----------
# 维度权重(纯债口径): 风险控制最重, 收益质量低于权益线(纯债收益差异小)
BOND_DIM_WEIGHTS = {
    "A_return": 0.25,        # 收益质量
    "B_risk": 0.35,          # 风险控制(债基最重)
    "C_attribution": 0.25,   # 收益来源与信用
    "D_manager": 0.10,       # 经理与平台
    "E_operation": 0.05,     # 运作费用
}

# 债基维度内指标(键 -> (权重, 方向: 1=越大越好, -1=越小越好, 0=U型))
# 设计铁律: 票息不计能力分(只作标签); A1 净值法alpha 经五因子回归剔除beta后的残差
# C 维(择券/信用/久期/杠杆)需且慢持仓数据, v0.4-1 暂缺 -> 该维按剩余权重归一/标 provisional
BOND_INDICATORS = {
    "A_return": {
        "campisi_alpha": (0.45, 1),            # A1 净值法 alpha(五因子残差年化)
        "ann_return": (0.30, 1),               # A3 同类超额(组内分位即等价同类超额)
        "cpr_persistence": (0.25, 1),          # A2 NAFMII 胜率持续性(CPR)
    },
    "B_risk": {
        "calmar": (0.30, 1),                   # B2 卡玛(核心)
        "max_drawdown": (0.25, 1),             # B1 最大回撤(取负后高=好, 计算层处理)
        "recovery_days": (0.15, -1),           # B1 修复天数越短越好
        "sortino": (0.15, 1),                  # B3 下行风险
        "monthly_positive_ratio": (0.15, 1),   # B5 月度正收益占比(绝对收益体验)
    },
    "C_attribution": {                          # C 维: 待且慢债基持仓工具接入
        "selection_share_bond": (0.35, 1),     # C1 Campisi 择券占超额比
        "credit_sink": (0.30, 0),              # C2 信用下沉度(U型: 适度为佳)
        "duration_dev": (0.20, 0),             # C3 久期偏离(U型)
        "leverage_contrib": (0.15, 1),         # C4 杠杆套息贡献
    },
    "D_manager": {
        "manager_experience": (0.50, 1),       # D1 固收经验年限
        "management_load": (0.50, -1),         # D2 管理半径(在管规模, 越大越差)
    },
    "E_operation": {
        "total_fee": (0.60, -1),               # E1 综合费率(债基费率敏感)
        "inst_ratio": (0.40, -1),              # E2 机构占比(大额申赎风险)
    },
}

# 短板规则
SHORTBOARD_PCTL = 20      # 任一维度分位<20 -> 降档标记
VETO_DIM = "B_risk"       # 风险维度一票否决
VETO_PCTL = 10

# 评分可信度: 维度权重覆盖率低于此值 -> 综合分标记 provisional, 重点池仅为"候选"
FORMAL_MIN_WEIGHT_COVERAGE = 0.75
PRIMARY_DIM = "A_return"   # 主维(收益): 整维缺失则否决排名(防风险维独撑虚高)
MICRO_SCALE_YI = 2.0       # 可投性下限(亿): 规模<此值或缺失 -> 容量/限购风险, 不进正式重点池

# 评分预处理
WINSORIZE = (0.01, 0.99)

# ---------- L3 深研触发 ----------
FOCUS_POOL_TOP_PCT = 0.20   # 综合分同类前20%

# ---------- 数据 ----------
TRADING_DAYS_PER_YEAR = 244   # A股年化天数
RISK_FREE_ANNUAL = 0.015      # 无风险利率(暂用), TODO: 改为动态取数

# 业绩基准解析: 指数名称 -> 行情代码 (AKShare/东财口径, 逐步补充)
BENCHMARK_INDEX_MAP = {
    "沪深300指数": "sh000300",
    "中证500指数": "sh000905",
    "中证800指数": "sh000906",
    "中证1000指数": "sh000852",
    "中证全指": "sh000985",
    "上证指数": "sh000001",
    "上证综合指数": "sh000001",
    "深证成份指数": "sz399001",
    "深证成指": "sz399001",
    "创业板指数": "sz399006",
    "科创50": "sh000688",
    "中证国债指数": "sh000012",   # 代理: 上证国债指数(中证国债H11006无免费日行情源)
    "上证国债指数": "sh000012",
    "国债指数": "sh000012",
    "上证A股指数": "sh000002",
    "中证红利": "sh000922",
    "中证医药卫生": "sh000933",
    "中证内地消费主题": "sh000942",
    "中证新能源指数": "sz399808",
    "中证港股通综合指数": "HKD_PORTFOLIO",   # 暂无源, 解析时按剩余权重归一
    "恒生指数": "HSI",                        # 暂无源
    # 债券类: 统一代理到中债综合财富总值(全债/综合债/全价等写法差异为已知近似)
    "中债总指数": "CBA00101",
    "中债综合": "CBA00101",
    "中债总财富指数": "CBA00101",
    "中证全债": "CBA00101",
    "中证综合债": "CBA00101",
    "中国债券总": "CBA00101",
    # 存款利率类: 暂无源(权重通常≤20%, 触发剔除归一)
    "存款利率": "RF_DEPOSIT",
    "存款基准利率": "RF_DEPOSIT",
}
DEFAULT_EQUITY_BENCHMARK = "sh000906"  # 基准缺失/无法解析时回退: 中证800
