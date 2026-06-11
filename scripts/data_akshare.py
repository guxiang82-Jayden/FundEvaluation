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
    """规模/成立日/经理任期等. TODO: 拼接 ak.fund_individual_basic_info_xq /
    fund_manager_em / 持有人结构接口; 字段名首跑核对"""
    raise NotImplementedError("v0.1: 待首次实跑时实现并核对字段")
