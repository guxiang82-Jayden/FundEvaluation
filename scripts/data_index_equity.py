"""权益被动指数/ETF 数据适配：分类、权威关键词映射、场内指标。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

import data_akshare as da
import scoring_enhanced as se
import scoring_index as si

REPO_ROOT = Path(__file__).resolve().parents[1]
MAP_PATH = REPO_ROOT / "data" / "index_map_equity.csv"

# 明确指数名称 -> 可验证行情代码。未命中不做模糊猜测。
INDEX_KEYWORDS = [
    ("中证A500", "sh000510", "中证A500", 1.00),
    ("中证1000", "sh000852", "中证1000", 1.00),
    ("中证500", "sh000905", "中证500", 1.00),
    ("沪深300", "sh000300", "沪深300", 1.00),
    ("中证800", "sh000906", "中证800", 0.90),
    ("上证50", "sh000016", "上证50", 1.00),
    ("科创50", "sh000688", "科创50", 1.00),
    ("创业板50", "sz399673", "创业板50", 0.90),
    ("创业板", "sz399006", "创业板指", 1.00),
    ("深证100", "sz399330", "深证100", 0.90),
    ("国证2000", "sz399303", "国证2000", 0.80),
    ("中证2000", "932000.CSI", "中证2000", 0.80),
    ("中证红利", "sh000922", "中证红利", 0.80),
    ("上证红利", "sh000015", "上证红利", 0.80),
    ("深证红利", "sz399324", "深证红利", 0.80),
]

ENHANCED_PATTERN = r"增强|量化"
INDEX_VARIANT_PATTERN = (
    r"增强|量化|成长|价值|低波|红利低波|等权|ESG|质量|高股息|行业|主题|策略|安中"
)


def fund_list() -> pd.DataFrame:
    return da.fund_universe()


def etf_spot() -> pd.DataFrame:
    def fetch():
        raw = da.ak.fund_etf_spot_em()
        return raw.rename(columns={
            "代码": "fund_code",
            "名称": "fund_name_spot",
            "成交额": "amount",
            "换手率": "turnover_amt_spot",
            "IOPV实时估值": "iopv",
            "基金折价率": "discount_rate_spot",
            "买一": "bid1",
            "卖一": "ask1",
            "总市值": "market_cap",
        })
    out = da.cached("equity_etf_spot", fetch, max_age_days=1)
    out["fund_code"] = out["fund_code"].astype(str).str.replace(
        r"\.0$", "", regex=True).str.zfill(6)
    return out


def classify_universe() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    funds = fund_list().copy()
    funds["fund_code"] = funds["fund_code"].astype(str).str.zfill(6)
    spot = etf_spot()
    etf_codes = set(spot["fund_code"])
    names = funds["fund_name"].fillna("").astype(str)
    types = funds["fund_type"].fillna("").astype(str)
    enhanced = names.str.contains(ENHANCED_PATTERN, regex=True)

    etf = funds[
        funds["fund_code"].isin(etf_codes)
        & types.eq("指数型-股票")
        & ~enhanced
    ].copy()
    etf["track"] = "ETF"

    off = funds[
        types.eq("指数型-股票")
        & ~funds["fund_code"].isin(etf_codes)
        & ~enhanced
    ].copy()
    off["track"] = "INDEX"
    off = da.merge_share_classes(off)

    enhanced_df = funds[types.eq("指数型-股票") & enhanced].copy()
    enhanced_df["track"] = "ENHANCED"
    enhanced_df = da.merge_share_classes(enhanced_df)
    return off.reset_index(drop=True), etf.reset_index(drop=True), enhanced_df


def parse_index_name(name: str, *, enhanced: bool = False) -> dict:
    text = str(name)
    if enhanced:
        text = pd.Series([text]).str.replace(ENHANCED_PATTERN, "", regex=True).iloc[0]
    # 宽基名称后带风格/策略修饰时不是同一个指数，未建权威映射前留空。
    if pd.Series([text]).str.contains(INDEX_VARIANT_PATTERN, regex=True).iloc[0]:
        return {
            "index_code": pd.NA,
            "index_name": pd.NA,
            "index_family": "映射缺失",
            "index_mainstream": np.nan,
            "map_rule": pd.NA,
        }
    for keyword, code, index_name, mainstream in INDEX_KEYWORDS:
        if keyword in text:
            return {
                "index_code": code,
                "index_name": index_name,
                "index_family": index_name,
                "index_mainstream": mainstream,
                "map_rule": f"name:{keyword}",
            }
    return {
        "index_code": pd.NA,
        "index_name": pd.NA,
        "index_family": "映射缺失",
        "index_mainstream": np.nan,
        "map_rule": pd.NA,
    }


def build_index_map(
    off: pd.DataFrame,
    etf: pd.DataFrame,
    enhanced: pd.DataFrame | None = None,
    path: str | Path = MAP_PATH,
) -> pd.DataFrame:
    frames = [off, etf]
    if enhanced is not None:
        frames.append(enhanced)
    base = pd.concat(frames, ignore_index=True, sort=False)
    rows = []
    for row in base.itertuples(index=False):
        parsed = parse_index_name(
            row.fund_name, enhanced=str(row.track) == "ENHANCED")
        rows.append({
            "fund_code": row.fund_code,
            "fund_name": row.fund_name,
            "track": row.track,
            **parsed,
        })
    out = pd.DataFrame(rows).drop_duplicates("fund_code", keep="first")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, encoding="utf-8-sig")
    return out


def load_index_map(path: str | Path = MAP_PATH) -> pd.DataFrame:
    if not Path(path).exists():
        return pd.DataFrame()
    out = pd.read_csv(path, dtype={"fund_code": str, "index_code": str})
    out["fund_code"] = out["fund_code"].str.zfill(6)
    return out


def merge_map(df: pd.DataFrame, mapping: pd.DataFrame) -> pd.DataFrame:
    return df.merge(
        mapping[["fund_code", "index_code", "index_name", "index_family",
                 "index_mainstream", "map_rule"]],
        on="fund_code",
        how="left",
    )


def build_index_returns(mapping: pd.DataFrame) -> dict[str, pd.Series]:
    out = {}
    for code in sorted(set(mapping["index_code"].dropna().astype(str))):
        try:
            out[code] = da.index_returns(code)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] equity index {code} failed: {exc}")
    return out


def _etf_history(code: str) -> pd.DataFrame:
    def fetch():
        raw = da.ak.fund_etf_hist_em(
            symbol=code, period="daily",
            start_date="20000101",
            end_date=datetime.now().strftime("%Y%m%d"),
            adjust="",
        )
        return raw.rename(columns={
            "日期": "date", "收盘": "close", "成交额": "amount",
            "换手率": "turnover_amt",
        })
    out = da.cached(f"equity_etf_hist_{code}", fetch, max_age_days=1)
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    for col in ("close", "amount", "turnover_amt"):
        out[col] = pd.to_numeric(out.get(col), errors="coerce")
    return out.dropna(subset=["date", "close"]).sort_values("date")


def _etf_nav(code: str) -> pd.Series:
    def fetch():
        raw = da.ak.fund_etf_fund_info_em(
            fund=code, start_date="20000101",
            end_date=datetime.now().strftime("%Y%m%d"))
        return raw.rename(columns={"净值日期": "date", "单位净值": "nav"})[
            ["date", "nav"]]
    out = da.cached(f"equity_etf_nav_{code}", fetch, max_age_days=1)
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["nav"] = pd.to_numeric(out["nav"], errors="coerce")
    return out.dropna().drop_duplicates("date", keep="last").set_index("date")["nav"].sort_index()


def _etf_tracking_nav(code: str) -> pd.Series:
    """用官方日增长率构造连续净值，规避份额折算造成的单位净值跳变。"""
    def fetch():
        raw = da.ak.fund_etf_fund_info_em(
            fund=code, start_date="20000101",
            end_date=datetime.now().strftime("%Y%m%d"))
        return raw.rename(columns={
            "净值日期": "date", "日增长率": "daily_growth",
        })[["date", "daily_growth"]]

    out = da.cached(f"equity_etf_growth_v1_{code}", fetch, max_age_days=1)
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    growth = pd.to_numeric(out["daily_growth"], errors="coerce") / 100
    clean = pd.DataFrame({"date": out["date"], "growth": growth}).dropna()
    clean = clean.drop_duplicates("date", keep="last").sort_values("date")
    return (1 + clean.set_index("date")["growth"]).cumprod()


def _bid_ask_spread(row: pd.Series) -> float:
    bid = pd.to_numeric(row.get("bid1"), errors="coerce")
    ask = pd.to_numeric(row.get("ask1"), errors="coerce")
    mid = (bid + ask) / 2
    return float((ask - bid) / mid) if pd.notna(mid) and mid > 0 and ask >= bid else np.nan


def build_etf_metrics(
    df: pd.DataFrame,
    spot: pd.DataFrame,
    index_returns: dict[str, pd.Series],
) -> pd.DataFrame:
    spot_idx = spot.drop_duplicates("fund_code").set_index("fund_code")
    rows = []
    for i, fund in enumerate(df.itertuples(index=False), start=1):
        code = str(fund.fund_code)
        row = fund._asdict()
        try:
            hist = _etf_history(code)
            nav = _etf_nav(code)
            tracking_nav = _etf_tracking_nav(code)
            idx_ret = index_returns.get(str(row.get("index_code")))
            stats = (
                si.tracking_stats(tracking_nav, idx_ret)
                if idx_ret is not None else {
                    "tracking_error": np.nan, "info_ratio": np.nan,
                    "tracking_deviation": np.nan, "tracking_days": 0,
                })
            aligned = pd.concat(
                [hist.set_index("date")["close"], nav],
                axis=1, join="inner").dropna()
            premium = aligned["close"] / aligned["nav"] - 1
            recent = hist.tail(60)
            row.update(stats)
            row.update({
                "amount_avg": recent["amount"].mean(),
                "turnover_amt": recent["turnover_amt"].mean(),
                "premium_discount_abs": premium.abs().tail(120).mean(),
                "premium_discount_std": premium.tail(120).std(),
                "fund_age_years": (
                    (pd.Timestamp.now() - hist["date"].min()).days / 365.25
                    if not hist.empty else np.nan),
            })
            if code in spot_idx.index:
                live = spot_idx.loc[code]
                row["scale_yi"] = pd.to_numeric(
                    live.get("market_cap"), errors="coerce") / 1e8
                row["bid_ask_spread"] = _bid_ask_spread(live)
        except Exception as exc:  # noqa: BLE001
            row["data_error"] = str(exc)
        rows.append(row)
        if i % 20 == 0:
            print(f"  ETF metrics {i}/{len(df)}")
    return pd.DataFrame(rows)


def build_offexchange_metrics(
    df: pd.DataFrame,
    index_returns: dict[str, pd.Series],
) -> pd.DataFrame:
    codes = df["fund_code"].tolist()
    meta = da.build_meta_table(codes)
    merged = df.merge(meta.drop(columns=["fund_name"], errors="ignore"),
                      on="fund_code", how="left")
    rows = []
    for i, row in merged.iterrows():
        result = row.to_dict()
        try:
            nav = da.fund_nav(row["fund_code"])
            idx_ret = index_returns.get(str(row.get("index_code")))
            if idx_ret is not None:
                result.update(si.tracking_stats(nav, idx_ret))
        except Exception as exc:  # noqa: BLE001
            result["data_error"] = str(exc)
        rows.append(result)
        if (i + 1) % 20 == 0:
            print(f"  INDEX metrics {i+1}/{len(merged)}")
    return pd.DataFrame(rows)


def build_enhanced_metrics(
    df: pd.DataFrame,
    index_returns: dict[str, pd.Series],
) -> pd.DataFrame:
    """构造指增超额指标；标的指数缺失时保留空值并诚实降级。"""
    codes = df["fund_code"].astype(str).tolist()
    meta = da.build_meta_table(codes)
    merged = df.merge(
        meta.drop(columns=["fund_name"], errors="ignore"),
        on="fund_code", how="left")

    cdim_path = Path(__file__).resolve().parent / "data" / "cdim_data.csv"
    if cdim_path.exists():
        cdim = pd.read_csv(cdim_path, dtype={"fund_code": str})
        cdim["fund_code"] = cdim["fund_code"].str.zfill(6)
        style_cols = [
            c for c in (
                "fund_code", "style_stability", "rbsa_r2", "turnover_rate")
            if c in cdim.columns]
        style_data = cdim[style_cols].drop_duplicates(
            "fund_code", keep="last").rename(columns={"turnover_rate": "turnover"})
        merged = merged.merge(
            style_data,
            on="fund_code", how="left")

    rows = []
    for i, row in merged.iterrows():
        result = row.to_dict()
        idx_ret = index_returns.get(str(row.get("index_code")))
        if idx_ret is None:
            result["metric_status"] = "mapping_missing"
        else:
            try:
                nav = da.fund_nav(str(row["fund_code"]))
                result.update(se.excess_metrics(nav, idx_ret))
                result["metric_status"] = "ok"
            except Exception as exc:  # noqa: BLE001
                result["metric_status"] = "metrics_failed"
                result["data_error"] = str(exc)
        rows.append(result)
        if (i + 1) % 20 == 0:
            print(f"  ENHANCED metrics {i+1}/{len(merged)}")
    return pd.DataFrame(rows)
