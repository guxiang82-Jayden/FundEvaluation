"""业绩基准解析与合成
输入: 基准字符串, 如 "沪深300指数收益率×45%+中证港股通综合指数收益率×35%+中债总指数收益率×20%"
输出: [(指数名, 权重)], 以及合成的基准日收益序列
"""
import re

import pandas as pd

import config

# 兼容 ×/*/x, %/百分数
_PART = re.compile(r"([^+×*x]+?)(?:收益率)?\s*[×*x]\s*([\d.]+)%?")


def parse_benchmark(text: str) -> list[tuple[str, float]]:
    """解析复合基准字符串 -> [(name, weight)], weight 已归一为小数"""
    if not text:
        return []
    text = text.replace("(", "(").replace(")", ")").strip()
    parts = []
    for seg in text.split("+"):
        m = _PART.search(seg)
        if not m:
            continue
        name = m.group(1).strip()
        w = float(m.group(2))
        if w > 1:
            w /= 100.0
        parts.append((name, w))
    return parts


def resolve_components(parts: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """指数名 -> 行情代码; 解析不出的成分丢弃并归一化剩余权重"""
    resolved = []
    for name, w in parts:
        code = None
        for key, v in config.BENCHMARK_INDEX_MAP.items():
            if key in name or name in key:
                code = v
                break
        if code:
            resolved.append((code, w))
    total = sum(w for _, w in resolved)
    if total <= 0:
        return []
    return [(c, w / total) for c, w in resolved]


def synthesize(index_returns: dict[str, pd.Series], components: list[tuple[str, float]]) -> pd.Series:
    """按权重合成基准日收益. index_returns: code -> 日收益序列"""
    series = []
    weights = []
    for code, w in components:
        if code in index_returns:
            series.append(index_returns[code].rename(code))
            weights.append(w)
    if not series:
        return pd.Series(dtype=float)
    df = pd.concat(series, axis=1, join="inner").dropna()
    total = sum(weights)
    return sum(df[c] * (w / total) for (c, w) in zip(df.columns, weights))


def get_benchmark_returns(benchmark_text: str, index_returns: dict[str, pd.Series]) -> tuple[pd.Series, str]:
    """主入口. 返回 (基准日收益, 说明). 解析失败回退默认基准"""
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
