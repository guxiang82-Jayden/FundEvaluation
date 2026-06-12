"""AKShare 数据适配层 (脚本独立运行的主数据源)
职责: 取数 + 整形为标准格式 + 本地缓存(parquet)
注: MCP(且慢/iFinD) 仅 Claude 会话可调用, 不进此层; 其数据用于会话内交叉校验
接口名以 AKShare 1.x 为准, 首次实跑时核对
"""
import os
from datetime import datetime

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
    return cached("fund_universe", fetch, max_age_days=7)


def active_equity_universe() -> pd.DataFrame:
    """主动权益组: 按东财类型映射项目口径(粗筛, 灵活配置仓位中枢在 L0 细筛)"""
    df = fund_universe()
    mask = df["fund_type"].str.contains("股票型|偏股混合|灵活配置", na=False, regex=True)
    mask &= ~df["fund_type"].str.contains("指数|QDII|FOF", na=False, regex=True)
    return df[mask].reset_index(drop=True)


# ---------- 净值 ----------
def fund_nav(fund_code: str) -> pd.Series:
    """单基金累计净值序列(复权). TODO: 核对 AKShare 字段(累计净值 vs 复权净值)"""
    def fetch():
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="累计净值走势")
        df = df.rename(columns={"净值日期": "date", "累计净值": "nav"})
        df["date"] = pd.to_datetime(df["date"])
        return df[["date", "nav"]]
    df = cached(f"nav_{fund_code}", fetch, max_age_days=1)
    return df.set_index("date")["nav"].astype(float).sort_index()


# ---------- 指数行情(基准合成用) ----------
def index_returns(code: str) -> pd.Series:
    """指数日收益. TODO: 债券指数/港股通指数来源待补"""
    def fetch():
        df = ak.stock_zh_index_daily(symbol=code)
        df["date"] = pd.to_datetime(df["date"])
        return df[["date", "close"]]
    df = cached(f"index_{code}", fetch, max_age_days=1)
    s = df.set_index("date")["close"].astype(float).sort_index()
    return s.pct_change().dropna()


def load_all_index_returns() -> dict:
    out = {}
    for code in set(config.BENCHMARK_INDEX_MAP.values()) | {config.DEFAULT_EQUITY_BENCHMARK}:
        if code.startswith(("sh", "sz")):
            try:
                out[code] = index_returns(code)
            except Exception as e:  # noqa: BLE001
                print(f"[warn] index {code} failed: {e}")
    return out


# ---------- 元数据(初筛用) ----------
def fund_meta(fund_code: str) -> dict:
    """单基金初筛元数据. 多源拼接, 任一源失败该字段记 None 并继续
    返回键与 screening.py 必需列对齐
    ⚠️ 接口名/字段名基于 AKShare 1.18 文档, 首次实跑时核对"""
    meta = {"fund_code": fund_code}

    # 1) 雪球基本信息: 成立时间/最新规模/基金经理
    try:
        info = ak.fund_individual_basic_info_xq(symbol=fund_code)
        kv = dict(zip(info["item"], info["value"]))
        setup = pd.to_datetime(kv.get("成立时间"), errors="coerce")
        if pd.notna(setup):
            meta["fund_age_years"] = (pd.Timestamp.now() - setup).days / 365.25
        scale_text = str(kv.get("最新规模", ""))
        meta["scale_yi"] = _parse_scale_yi(scale_text)
        meta["fund_name"] = kv.get("基金名称")
    except Exception as e:  # noqa: BLE001
        print(f"[warn] {fund_code} basic_info 失败: {e}")

    # 2) 经理任期: 东财基金经理变动一览
    try:
        mgr = ak.fund_announcement_personnel_em(symbol=fund_code)
        # TODO: 核对该接口字段; 备选 ak.fund_manager_em() 全量表按基金过滤
        meta["_manager_raw"] = mgr.to_dict("records")[:5]
    except Exception:
        try:
            allm = cached("manager_all", lambda: ak.fund_manager_em(), max_age_days=7)
            mine = allm[allm["现任基金"].astype(str).str.contains(fund_code, na=False)]
            if not mine.empty:
                meta["manager_names"] = mine["姓名"].tolist()
        except Exception as e:  # noqa: BLE001
            print(f"[warn] {fund_code} manager 失败: {e}")

    # 3) 持有人结构(年报/半年报口径)
    try:
        hold = ak.fund_individual_detail_hold_xq(symbol=fund_code)
        # 期望列: 机构持有比例/个人持有比例; 取最新一期
        if not hold.empty:
            latest = hold.iloc[-1]
            for col in hold.columns:
                if "机构" in str(col):
                    meta["inst_ratio"] = float(latest[col]) / 100.0
                    break
    except Exception as e:  # noqa: BLE001
        print(f"[warn] {fund_code} holders 失败: {e}")

    return meta


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


def build_meta_table(fund_codes: list[str]) -> pd.DataFrame:
    """批量元数据表(供 screening). 注意接口限频, 必要时加 sleep"""
    import time
    rows = []
    for i, code in enumerate(fund_codes):
        rows.append(fund_meta(code))
        time.sleep(0.3)  # 雪球/东财限频保护
        if (i + 1) % 50 == 0:
            print(f"  meta {i+1}/{len(fund_codes)}")
    df = pd.DataFrame(rows)
    # screening 需要但本层暂无法提供的列, 补默认值(规则自动跳过)
    for col, default in [("tenure_years", None), ("manager_changed_recent", None),
                          ("style_switches_2y", None), ("equity_low_quarters", None),
                          ("negative_record", None)]:
        if col not in df:
            df[col] = default
    if "fund_age_years" in df:
        df["fund_age_for_style"] = df["fund_age_years"]
    return df
