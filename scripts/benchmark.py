"""业绩基准解析与合成
输入: 基准字符串(实测格式多样: "指数×45%+..." / "65%×指数+..." / 全角＋ / *号)
输出: [(指数名, 权重)], 以及合成的基准日收益序列
安全规则: 已映射成分的原始权重之和 < MIN_MATCHED_WEIGHT 时回退默认基准,
          避免残缺基准失真(如股基基准只匹配到债券部分)
"""
import re

import pandas as pd

import config

MIN_MATCHED_WEIGHT = 0.5

# name×weight 与 weight×name 双向匹配
_NAME_W = re.compile(r"^(.+?)(?:收益率)?\s*×\s*([\d.]+)%?$")
_W_NAME = re.compile(r"^([\d.]+)%?\s*×\s*(.+?)(?:收益率)?$")


def _normalize(text: str) -> str:
    """全角/变体符号归一: ＋→+, *xX×→×, 全角括号/空格清理"""
    t = text.replace("＋", "+").replace("（", "(").replace("）", ")")
    t = re.sub(r"[*xX✕Ⅹ]", "×", t)
    return t.strip()


def parse_benchmark(text: str) -> list[tuple[str, float]]:
    """解析复合基准字符串 -> [(name, weight)], weight 为小数"""
    if not text or not isinstance(text, str):
        return []
    parts = []
    for seg in _normalize(text).split("+"):
        seg = seg.strip()
        if not seg:
            continue
        m = _NAME_W.match(seg)
        if m:
            name, w = m.group(1).strip(), float(m.group(2))
        else:
            m = _W_NAME.match(seg)
            if not m:
                continue
            w, name = float(m.group(1)), m.group(2).strip()
        if w > 1:
            w /= 100.0
        # 清理名称尾缀
        name = re.sub(r"(收益率|的收益率)$", "", name).strip()
        parts.append((name, w))
    return parts


def resolve_components(parts: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """指数名 -> 行情代码. 匹配权重之和 < MIN_MATCHED_WEIGHT 时返回 [](触发回退)"""
    resolved = []
    matched_w = 0.0
    for name, w in parts:
        code = None
        for key, v in config.BENCHMARK_INDEX_MAP.items():
            if key in name or name in key:
                code = v
                break
        if code:
            resolved.append((code, w))
            matched_w += w
    if matched_w < MIN_MATCHED_WEIGHT:
        return []
    total = sum(w for _, w in resolved)
    return [(c, w / total) for c, w in resolved]


def synthesize(index_returns: dict[str, pd.Series], components: list[tuple[str, float]]) -> pd.Series:
    """按权重合成基准日收益. 无行情数据的成分(如存款利率)剔除后再归一"""
    series = []
    weights = []
    for code, w in components:
        if code in index_returns:
            series.append(index_returns[code].rename(code))
            weights.append(w)
    if not series or sum(weights) < MIN_MATCHED_WEIGHT * 0.8:
        return pd.Series(dtype=float)
    df = pd.concat(series, axis=1, join="inner").dropna()
    total = sum(weights)
    return sum(df[c] * (w / total) for (c, w) in zip(df.columns, weights))


def get_benchmark_returns(benchmark_text: str, index_returns: dict[str, pd.Series]) -> tuple[pd.Series, str]:
    """主入口. 返回 (基准日收益, 说明). 解析失败/权重残缺均回退默认基准"""
    parts = parse_benchmark(benchmark_text)
    comps = resolve_components(parts)
    if comps:
        ret = synthesize(index_returns, comps)
        if not ret.empty:
            return ret, f"parsed:{comps}"
    fallback = config.DEFAULT_EQUITY_BENCHMARK
    if fallback in index_returns:
        return index_returns[fallback], f"fallback:{fallback}"
    return pd.Series(dtype=float), "unavailable"
