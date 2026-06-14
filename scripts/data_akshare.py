"""AKShare 数据适配层 (脚本独立运行的主数据源)
职责: 取数 + 整形为标准格式 + 本地缓存(parquet)
注: MCP(且慢/iFinD) 仅 Claude 会话可调用, 不进此层; 其数据用于会话内交叉校验
接口名以 AKShare 1.x 为准, 已于 2026-06-12 实测核对
"""
import os
from datetime import datetime

import numpy as np
import pandas as pd

import config

try:
    import akshare as ak
except ImportError:
    ak = None  # 允许在无 akshare 环境下 import 本模块(如沙箱测试评分引擎)


def _cache_path(name: str) -> str:
    os.makedirs(config.CACHE_DIR, exist_ok=True)
    return os.path.join(config.CACHE_DIR, f"{name}.parquet")


def cached(name: str, fetch_fn, max_age_days: int = 1) -> pd.DataFrame:
    path = _cache_path(name)
    if os.path.exists(path):
        age = (datetime.now().timestamp() - os.path.getmtime(path)) / 86400
        if age < max_age_days:
            return pd.read_parquet(path)
    df = fetch_fn()
    df.to_parquet(path)
    return df


# ---------- 全量基金列表与分类 ----------
def fund_universe() -> pd.DataFrame:
    """全市场开放式基金列表+类型. 列: fund_code, fund_name, fund_type"""
    def fetch():
        df = ak.fund_name_em()  # 东财全量: 基金代码/简称/类型
        df = df.rename(columns={"基金代码": "fund_code", "基金简称": "fund_name", "基金类型": "fund_type"})
        return df[["fund_code", "fund_name", "fund_type"]]
    df = cached("fund_universe", fetch, max_age_days=7)
    # 防御: 代码统一为6位字符串(防止任何环节被转成 int 丢前导零)
    df["fund_code"] = df["fund_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    return df


def active_equity_universe() -> pd.DataFrame:
    """主动权益组: 按东财类型映射项目口径(粗筛, 灵活配置仓位中枢在 L0 细筛)
    实测类型字符串(2026-06): '混合型-偏股' '混合型-灵活' '股票型' '债券型-混合二级' 等"""
    df = fund_universe()
    mask = df["fund_type"].str.contains("混合型-偏股|混合型-灵活|股票型", na=False, regex=True)
    mask &= ~df["fund_type"].str.contains("指数|QDII|FOF|债券|货币|理财|联接", na=False, regex=True)
    # 后端收费份额剔除(简称含"后端"); 91开头为转型/场内特殊代码, 无公开数据
    mask &= ~df["fund_name"].str.contains("后端", na=False)
    mask &= ~df["fund_code"].str.startswith("91")
    out = df[mask].reset_index(drop=True)
    return merge_share_classes(out)


def merge_share_classes(df: pd.DataFrame) -> pd.DataFrame:
    """多份额合并: 同名基金(去掉尾缀份额字母)只保留主份额
    优先级: 名称以A结尾 > 无字母尾缀 > 代码最小. 例: 稳健回报A/C -> 保留A"""
    import re
    base = df["fund_name"].str.replace(r"[A-Z]+$", "", regex=True)

    def priority(name):
        if re.search(r"A$", name):
            return 0
        if not re.search(r"[A-Z]$", name):
            return 1
        return 2

    tmp = df.assign(_base=base, _prio=df["fund_name"].map(priority))
    tmp = tmp.sort_values(["_base", "_prio", "fund_code"])
    merged = tmp.drop_duplicates("_base", keep="first").drop(columns=["_base", "_prio"])
    print(f"  份额合并: {len(df)} -> {len(merged)}")
    # 恢复按代码排序, 保证 limit 抽样可复现
    return merged.sort_values("fund_code").reset_index(drop=True)


# ---------- 净值 ----------
def fund_nav(fund_code: str) -> pd.Series:
    """单基金累计净值序列(已实测: 列名 净值日期/累计净值)
    ⚠️ 已知近似: 累计净值为分红简单加回, 非分红再投资复权; 对高分红基金收益略低估
    TODO v0.2: 用 单位净值+分红送配详情 自建复权净值"""
    def fetch():
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="累计净值走势")
        if df.empty or "净值日期" not in df.columns:
            raise ValueError("无净值数据(新发/特殊基金)")
        df = df.rename(columns={"净值日期": "date", "累计净值": "nav"})
        df["date"] = pd.to_datetime(df["date"])
        return df[["date", "nav"]]
    df = cached(f"nav_{fund_code}", fetch, max_age_days=1)
    s = df.set_index("date")["nav"].astype(float).sort_index()
    # 个别基金存在重复净值日期(实测 001158), 保留最后一条
    return s[~s.index.duplicated(keep="last")]


# ---------- 指数行情(基准合成用) ----------
def index_returns(code: str) -> pd.Series:
    """指数日收益. 股票指数(sh/sz前缀)走新浪; 中债指数(CBA前缀)走中债综合指数
    港股通综指暂无源, 基准含其成分时按剩余权重归一(benchmark.resolve_components 已处理)"""
    def fetch():
        if code.startswith("CBA"):
            try:
                df = ak.bond_new_composite_index_cbond(indicator="财富", period="总值")
            except Exception:
                df = ak.bond_composite_index_cbond(indicator="财富", period="总值")
            df = df.rename(columns={"value": "close"})
        else:
            df = ak.stock_zh_index_daily(symbol=code)
        df["date"] = pd.to_datetime(df["date"])
        return df[["date", "close"]]
    df = cached(f"index_{code}", fetch, max_age_days=1)
    s = df.set_index("date")["close"].astype(float).sort_index()
    return s.pct_change().dropna()


def load_all_index_returns_v2() -> dict:
    """股票指数 + 中债指数(实测可用) + RBSA 风格基(巨潮)"""
    import rbsa as _rbsa
    out = {}
    codes = {c for c in config.BENCHMARK_INDEX_MAP.values() if c.startswith(("sh", "sz", "CBA"))}
    codes |= {config.DEFAULT_EQUITY_BENCHMARK}
    codes |= set(_rbsa.DEFAULT_STYLE_BASIS.values())
    for code in sorted(codes):
        try:
            out[code] = index_returns(code)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] index {code} failed: {e}")
    return out


def load_all_index_returns() -> dict:
    """(兼容旧入口)"""
    out = {}
    for code in set(config.BENCHMARK_INDEX_MAP.values()) | {config.DEFAULT_EQUITY_BENCHMARK}:
        if code.startswith(("sh", "sz")):
            try:
                out[code] = index_returns(code)
            except Exception as e:  # noqa: BLE001
                print(f"[warn] index {code} failed: {e}")
    return out


# ---------- 元数据(初筛用) ----------
WARN_COUNTS = {}  # 字段缺失计数(汇总打印, 避免逐行刷屏)


def _warn(fund_code: str, field: str):
    WARN_COUNTS.setdefault(field, []).append(fund_code)


def fund_meta(fund_code: str, verbose: bool = False) -> dict:
    """单基金初筛元数据. 多源拼接, 任一源失败该字段记 None 并继续(计入 WARN_COUNTS)
    返回键与 screening.py 必需列对齐"""
    meta = {"fund_code": fund_code}

    # 1) 雪球基本信息(实测可用): 成立时间/最新规模/经理名单/业绩比较基准 ★
    try:
        info = ak.fund_individual_basic_info_xq(symbol=fund_code)
        kv = dict(zip(info["item"], info["value"]))
        setup = pd.to_datetime(kv.get("成立时间"), errors="coerce")
        if pd.notna(setup):
            meta["fund_age_years"] = (pd.Timestamp.now() - setup).days / 365.25
        meta["scale_yi"] = _parse_scale_yi(str(kv.get("最新规模", "")))
        meta["fund_name"] = kv.get("基金名称")
        meta["benchmark_text"] = kv.get("业绩比较基准")  # 供 benchmark.py 逐基金解析
        meta["fund_company"] = kv.get("基金公司")
    except Exception as e:  # noqa: BLE001
        _warn(fund_code, "basic_info")
        if verbose:
            print(f"[warn] {fund_code} basic_info 失败: {e}")

    # 2) 经理(实测: fund_manager_em 有'现任基金代码'列, 但无单基金任职起始日)
    # ⚠️ N4/N5 所需"任期"两个源均拿不到, 待补: 候选 ak.fund_manager_change_em /
    #    天天基金单基金经理页; 会话内可用且慢 MCP periodYears 交叉补充
    try:
        allm = cached("manager_all", lambda: ak.fund_manager_em(), max_age_days=7)
        mine = allm[allm["现任基金代码"].astype(str) == fund_code]
        if not mine.empty:
            names = mine["姓名"].tolist()
            meta["manager_names"] = names
            meta["manager_career_days"] = mine["累计从业时间"].max()  # 总从业(D1)
            # D2 管理半径: 主经理(从业最久者)的在管总规模 + 在管产品数
            lead = mine.loc[mine["累计从业时间"].idxmax(), "姓名"]
            lead_rows = allm[allm["姓名"] == lead]
            meta["manager_total_aum"] = pd.to_numeric(
                lead_rows["现任基金资产总规模"], errors="coerce").max()  # 亿(东财口径)
            meta["manager_fund_count"] = lead_rows["现任基金代码"].nunique()
    except Exception as e:  # noqa: BLE001
        _warn(fund_code, "manager")
        if verbose:
            print(f"[warn] {fund_code} manager 失败: {e}")

    # 3) 资产配置(实测: fund_individual_detail_hold_xq 返回 资产类型/仓位占比)
    #    用于 N9 仓位规则与灵活配置型的权益中枢判断; 持有人结构(N6)另找源
    try:
        hold = ak.fund_individual_detail_hold_xq(symbol=fund_code)
        kv = dict(zip(hold.iloc[:, 0], hold.iloc[:, 1]))
        if "股票" in kv:
            meta["equity_position"] = float(kv["股票"]) / 100.0
    except Exception as e:  # noqa: BLE001
        _warn(fund_code, "资产配置")
        if verbose:
            print(f"[warn] {fund_code} 资产配置 失败: {e}")

    # 4) 费率(E1): 同花顺源 fund_info_ths 含 管理费/托管费
    #    ⚠️ 字段名待本机实测核对(沙箱无 akshare 网络); 失败则 E1 留空降级
    #    ⚠️ 性能: 每只额外一次网络调用, 全量会增耗时; 费率少变, 可改为一次性批量缓存(类 cdim)
    #    若实测拖慢明显, 注释掉本段, 改用单独的 fee 缓存 CSV
    try:
        info = ak.fund_info_ths(symbol=fund_code)
        kv = dict(zip(info.iloc[:, 0], info.iloc[:, 1])) if info.shape[1] >= 2 else {}
        mgmt = _parse_pct(kv.get("管理费"))
        cust = _parse_pct(kv.get("托管费"))
        if mgmt is not None or cust is not None:
            meta["total_fee"] = (mgmt or 0) + (cust or 0)
    except Exception as e:  # noqa: BLE001
        _warn(fund_code, "费率")
        if verbose:
            print(f"[warn] {fund_code} 费率 失败: {e}")

    return meta


def _parse_pct(text) -> float | None:
    """'0.50%' -> 0.005; None/'' -> None"""
    if text is None:
        return None
    import re
    m = re.search(r"([\d.]+)\s*%", str(text))
    return float(m.group(1)) / 100 if m else None


def _parse_scale_yi(text: str) -> float | None:
    """'267.93亿' / '5000万' -> 亿元"""
    import re
    m = re.search(r"([\d.]+)\s*(亿|万)?", text)
    if not m:
        return None
    v = float(m.group(1))
    unit = m.group(2)
    if unit == "万":
        return v / 10000
    return v


def build_meta_table(fund_codes: list) -> pd.DataFrame:
    """批量元数据表(供 screening). 注意接口限频, 必要时加 sleep"""
    import time
    rows = []
    for i, code in enumerate(fund_codes):
        rows.append(fund_meta(code))
        time.sleep(0.3)  # 雪球/东财限频保护
        if (i + 1) % 50 == 0:
            print(f"  meta {i+1}/{len(fund_codes)}")
    if WARN_COUNTS:
        summary = {k: len(v) for k, v in WARN_COUNTS.items()}
        print(f"  元数据字段缺失汇总(多为新发/特殊基金, 已降级): {summary}")
        WARN_COUNTS.clear()
    df = pd.DataFrame(rows)
    # screening 需要但本层暂无法提供的列, 补默认值(规则自动跳过)
    for col, default in [("tenure_years", None), ("manager_changed_recent", None),
                          ("style_switches_2y", None), ("equity_low_quarters", None),
                          ("negative_record", None)]:
        if col not in df:
            df[col] = default
    if "fund_age_years" in df:
        df["fund_age_for_style"] = df["fund_age_years"]

    # D 维派生(供 scoring): 经验年限(7年封顶) + 管理半径
    if "manager_career_days" in df:
        df["manager_experience"] = (pd.to_numeric(df["manager_career_days"], errors="coerce")
                                    / 365.25).clip(upper=7)
    if "manager_total_aum" in df:
        # 管理半径: 在管规模 × √产品数(一拖多稀释); 越大越差(scoring direction=-1)
        cnt = pd.to_numeric(df.get("manager_fund_count", 1), errors="coerce").fillna(1)
        df["management_load"] = pd.to_numeric(df["manager_total_aum"], errors="coerce") * np.sqrt(cnt)
    return df
