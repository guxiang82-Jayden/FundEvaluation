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
def _clean_nav_frame(df: pd.DataFrame) -> pd.DataFrame:
    df = df[["date", "nav"]].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
    return (df.dropna(subset=["date", "nav"])
            .sort_values("date", kind="stable")
            .drop_duplicates("date", keep="last"))


def fund_nav_unit(fund_code: str) -> pd.Series:
    """单基金单位净值序列(未复权), 供复权构造与口径核验。"""
    def fetch():
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")
        if df.empty or not {"净值日期", "单位净值"}.issubset(df.columns):
            raise ValueError("无净值数据(新发/特殊基金)")
        return _clean_nav_frame(
            df.rename(columns={"净值日期": "date", "单位净值": "nav"}))
    df = _clean_nav_frame(cached(f"nav_unit_{fund_code}", fetch, max_age_days=1))
    return df.set_index("date")["nav"]


def _parse_dividend_per_share(value) -> float | None:
    """解析 '每份派现金0.1230元' 等东财分红文本。"""
    if value is None or pd.isna(value):
        return None
    import re
    match = re.search(r"现金\s*([\d.]+)\s*元", str(value))
    if not match:
        match = re.search(r"([\d.]+)", str(value))
    return float(match.group(1)) if match else None


def fund_dividends(fund_code: str) -> pd.DataFrame:
    """每份现金分红表, 列 date/dividend; 无分红时返回空表。"""
    def fetch():
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="分红送配详情")
        if df.empty:
            return pd.DataFrame(columns=["date", "dividend"])
        date_col = _pick_column(df.columns, ["除息日", "权益登记日", "分红发放日"])
        value_col = _pick_column(df.columns, ["每份分红", "分红"])
        if date_col is None or value_col is None:
            raise ValueError("分红送配详情缺少除息日/每份分红列")
        out = pd.DataFrame({
            "date": pd.to_datetime(df[date_col], errors="coerce"),
            "dividend": df[value_col].map(_parse_dividend_per_share),
        }).dropna()
        out = out[out["dividend"] > 0]
        return out.groupby("date", as_index=False)["dividend"].sum()

    df = cached(f"dividend_{fund_code}", fetch, max_age_days=30)
    if df.empty:
        return pd.DataFrame(columns=["date", "dividend"])
    out = df[["date", "dividend"]].copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out["dividend"] = pd.to_numeric(out["dividend"], errors="coerce")
    return out.dropna().sort_values("date")


def _reinvest_dividends(unit_nav: pd.Series, dividends: pd.DataFrame) -> pd.Series:
    """按除息日单位净值将现金分红再投资, 返回前复权净值。"""
    nav = pd.to_numeric(unit_nav, errors="coerce").dropna().sort_index()
    nav = nav[~nav.index.duplicated(keep="last")]
    if nav.empty or dividends is None or dividends.empty:
        return nav

    div_by_nav_date = pd.Series(0.0, index=nav.index)
    for row in dividends.itertuples(index=False):
        pos = nav.index.searchsorted(pd.Timestamp(row.date), side="left")
        if pos < len(nav):
            div_by_nav_date.iloc[pos] += float(row.dividend)

    factor_step = 1.0 + div_by_nav_date.div(nav).fillna(0.0)
    adjusted = nav * factor_step.cumprod()
    adjusted.name = "nav"
    return adjusted


def fund_nav_adjusted(fund_code: str) -> pd.Series:
    """分红再投资复权净值; 分红源失败时优雅降级为单位净值。"""
    unit = fund_nav_unit(fund_code)
    try:
        dividends = fund_dividends(fund_code)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] {fund_code} dividend failed, use unit NAV: {e}")
        dividends = pd.DataFrame(columns=["date", "dividend"])
    return _reinvest_dividends(unit, dividends)


def fund_nav(fund_code: str) -> pd.Series:
    """单基金分红再投资复权净值(生产统一口径)。"""
    return fund_nav_adjusted(fund_code)


# ---------- 指数行情(基准合成用) ----------
def _normalize_csi_code(code: str) -> str | None:
    raw = str(code).strip()
    upper = raw.upper()
    if upper.endswith(".CSI"):
        upper = upper[:-4]
    if upper.startswith("CSI"):
        upper = upper[3:]
    if upper.startswith("H") or (upper.isdigit() and len(upper) == 6):
        return upper
    return None


def _parse_cbond_code(code: str) -> tuple[str, str] | None:
    raw = str(code).strip()
    if not raw.startswith("CBOND_"):
        return None
    body = raw[len("CBOND_"):]
    if "_" not in body:
        return None
    category, period = body.rsplit("_", 1)
    if category and period:
        return category, period
    return None


def index_returns(code: str) -> pd.Series:
    """指数日收益.

    股票指数(sh/sz前缀)走新浪; 中债指数(CBA前缀)走中债综合指数;
    中证系(931059.CSI/H11009.CSI/H11014.CSI 等)走中证官网历史行情;
    中债细分源键(CBOND_指数族_期限段)走中债官网指数族接口。
    港股通综指暂无源, 基准含其成分时按剩余权重归一(benchmark.resolve_components 已处理)"""
    code = str(code).strip()

    def fetch():
        cbond = _parse_cbond_code(code)
        if cbond:
            category, period = cbond
            df = ak.bond_index_general_cbond(
                index_category=category, indicator="财富", period=period)
            df = df.rename(columns={"value": "close"})
        elif code.startswith("CBA"):
            try:
                df = ak.bond_new_composite_index_cbond(indicator="财富", period="总值")
            except Exception:
                df = ak.bond_composite_index_cbond(indicator="财富", period="总值")
            df = df.rename(columns={"value": "close"})
        elif _normalize_csi_code(code):
            df = ak.stock_zh_index_hist_csindex(
                symbol=_normalize_csi_code(code),
                start_date="20040101",
                end_date=datetime.now().strftime("%Y%m%d"),
            )
            df = df.rename(columns={"日期": "date", "收盘": "close"})
        else:
            df = ak.stock_zh_index_daily(symbol=code)
        df["date"] = pd.to_datetime(df["date"])
        return df[["date", "close"]]
    df = cached(f"index_{code}", fetch, max_age_days=1)
    s = df.set_index("date")["close"].astype(float).sort_index()
    return s.pct_change().dropna()


def _pick_column(columns, candidates):
    for c in candidates:
        if c in columns:
            return c
    return None


def fund_purchase_status() -> pd.DataFrame:
    """全市场基金申赎状态表(一次拉取, 按基金代码缓存).

    输出列与 screening_bond.mark_investability_bond 对齐:
    fund_code / subscribe_status / redeem_status / next_open_date。
    """
    def fetch():
        df = ak.fund_purchase_em()
        code_col = _pick_column(df.columns, ["基金代码", "基金编码", "代码"])
        if code_col is None:
            raise ValueError("fund_purchase_em 缺少基金代码列")
        sub_col = _pick_column(df.columns, ["申购状态", "购买状态", "认购状态"])
        red_col = _pick_column(df.columns, ["赎回状态", "卖出状态"])
        open_col = _pick_column(df.columns, ["下一开放日", "下一个开放日", "开放日"])

        out = pd.DataFrame()
        out["fund_code"] = df[code_col].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
        out["subscribe_status"] = df[sub_col].astype(str).str.strip() if sub_col else ""
        out["redeem_status"] = df[red_col].astype(str).str.strip() if red_col else ""
        if open_col:
            out["next_open_date"] = pd.to_datetime(df[open_col], errors="coerce")
        else:
            out["next_open_date"] = pd.NaT
        return out.drop_duplicates("fund_code", keep="first")

    return cached("fund_purchase_status", fetch, max_age_days=1)


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


def style_index_returns(csv_path: str = os.path.join("data", "style_index_returns.csv")) -> pd.DataFrame:
    """四风格指数日收益表; AKShare 不可用时尝试读取主线提供的 CSV。"""
    import rbsa as _rbsa

    series = {}
    errors = []
    for style, code in _rbsa.DEFAULT_STYLE_BASIS.items():
        try:
            series[style] = index_returns(code).rename(style)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{style}/{code}: {e}")
    if len(series) == len(_rbsa.DEFAULT_STYLE_BASIS):
        return pd.concat(series.values(), axis=1, join="inner").dropna().sort_index()

    if os.path.exists(csv_path):
        fallback = pd.read_csv(csv_path)
        date_col = _pick_column(fallback.columns, ["date", "日期"])
        required = list(_rbsa.DEFAULT_STYLE_BASIS)
        if date_col and set(required).issubset(fallback.columns):
            fallback[date_col] = pd.to_datetime(fallback[date_col], errors="coerce")
            return (fallback.set_index(date_col)[required]
                    .apply(pd.to_numeric, errors="coerce")
                    .dropna()
                    .sort_index())
    raise RuntimeError("风格指数收益不完整且无可用 CSV fallback: " + "; ".join(errors))


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


def _parse_operating_fee(df: pd.DataFrame) -> dict:
    """解析 fund_fee_em('运作费用') 的横向键值表。"""
    values = {}
    if df is None or df.empty:
        return values
    flat = df.astype(object).where(pd.notna(df), None).to_numpy().ravel().tolist()
    for i in range(0, len(flat) - 1, 2):
        key = str(flat[i]).strip() if flat[i] is not None else ""
        if "费率" in key:
            values[key] = _parse_pct(flat[i + 1])
    return values


def fund_fee_table(fund_codes: list) -> pd.DataFrame:
    """批量构建长期缓存的年运作费率表, 避免 fund_meta 逐只重复取数。"""
    codes = pd.Series(fund_codes, dtype=str).str.replace(
        r"\.0$", "", regex=True).str.zfill(6).drop_duplicates().tolist()
    path = _cache_path("fund_operating_fees")
    columns = ["fund_code", "management_fee", "custodian_fee",
               "sales_service_fee", "total_fee"]
    if os.path.exists(path):
        try:
            old = pd.read_parquet(path)
        except Exception:  # noqa: BLE001
            old = pd.DataFrame(columns=columns)
    else:
        old = pd.DataFrame(columns=columns)
    if "fund_code" not in old:
        old = pd.DataFrame(columns=columns)
    old["fund_code"] = old["fund_code"].astype(str).str.zfill(6)
    missing = [code for code in codes if code not in set(old["fund_code"])]

    rows = []
    failed = 0
    for i, code in enumerate(missing):
        try:
            fees = _parse_operating_fee(ak.fund_fee_em(
                symbol=code, indicator="运作费用"))
            mgmt = fees.get("管理费率")
            cust = fees.get("托管费率")
            sales = fees.get("销售服务费率")
            valid = [x for x in (mgmt, cust, sales) if x is not None]
            rows.append({
                "fund_code": code,
                "management_fee": mgmt,
                "custodian_fee": cust,
                "sales_service_fee": sales,
                "total_fee": sum(valid) if valid else None,
            })
        except Exception:  # noqa: BLE001
            failed += 1
        if (i + 1) % 50 == 0:
            print(f"  fee {i+1}/{len(missing)}")
    if failed:
        print(f"  [warn] fee fetch failed: {failed}/{len(missing)} (will retry next run)")

    if rows:
        old = pd.concat([old, pd.DataFrame(rows)], ignore_index=True)
        old = old.drop_duplicates("fund_code", keep="last")
    for col in ("management_fee", "custodian_fee", "sales_service_fee", "total_fee"):
        old[col] = pd.to_numeric(old[col], errors="coerce")
    if rows:
        old.to_parquet(path, index=False)
    return old[old["fund_code"].isin(codes)].reindex(columns=columns)


def _merge_purchase_status(df: pd.DataFrame) -> pd.DataFrame:
    """Merge subscribe/redeem status; source failure must not break monthly run."""
    out = df.copy()
    for col in ("subscribe_status", "redeem_status", "fund_status_text"):
        if col not in out.columns:
            out[col] = ""
    try:
        status = fund_purchase_status()
        keep = [c for c in ["fund_code", "subscribe_status", "redeem_status", "next_open_date"]
                if c in status.columns]
        out = out.drop(columns=[c for c in keep if c != "fund_code" and c in out.columns],
                       errors="ignore")
        out = out.merge(status[keep], on="fund_code", how="left")
    except Exception as e:  # noqa: BLE001
        print(f"[warn] fund_purchase_status failed, investability status degraded: {e}")

    for col in ("subscribe_status", "redeem_status"):
        if col not in out.columns:
            out[col] = ""
        out[col] = out[col].fillna("").astype(str)
    text = out["subscribe_status"] + " " + out["redeem_status"]
    name_text = out.get("fund_name", pd.Series("", index=out.index)).fillna("").astype(str)
    type_text = out.get("fund_type", pd.Series("", index=out.index)).fillna("").astype(str)
    is_regular_open = (name_text + " " + type_text).str.contains("定期开放|定开", regex=True)
    out["fund_status_text"] = np.where(is_regular_open, text + " 定期开放", text)
    out["fund_status_text"] = pd.Series(out["fund_status_text"], index=out.index).fillna("").astype(str).str.strip()
    return out


def build_meta_table(fund_codes: list) -> pd.DataFrame:
    """批量元数据表(供 screening). 注意接口限频, 必要时加 sleep"""
    import time
    try:
        fee_table = fund_fee_table(fund_codes)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] fund_fee_table failed, E1 degraded: {e}")
        fee_table = pd.DataFrame(columns=["fund_code", "total_fee"])
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
    if not fee_table.empty:
        fee_cols = [c for c in fee_table.columns if c == "fund_code" or c not in df.columns]
        df = df.merge(fee_table[fee_cols], on="fund_code", how="left")
    coverage = df.get("total_fee", pd.Series(np.nan, index=df.index)).notna().mean()
    fee_values = pd.to_numeric(df.get("total_fee", pd.Series(dtype=float)), errors="coerce")
    valid_fee = fee_values.dropna()
    if len(df):
        if valid_fee.empty:
            print("  E1 total_fee覆盖率: 0.0%")
        else:
            print(f"  E1 total_fee覆盖率: {coverage:.1%} | "
                  f"p25/中位/p75: {valid_fee.quantile(.25):.2%}/"
                  f"{valid_fee.median():.2%}/{valid_fee.quantile(.75):.2%} | "
                  f"异常(<=0或>3%): {((valid_fee <= 0) | (valid_fee > .03)).sum()}")
    return _merge_purchase_status(df)
