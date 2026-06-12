"""RBSA 基于收益的风格分析 (Sharpe 1992)
约束回归: 基金收益 ~ Σ w_i * 风格指数收益, s.t. w_i>=0, Σw_i=1
用途: C2 风格稳定性评分、N7 风格漂移检测
依赖 scipy (SLSQP); 用户机器: pip install scipy
"""
import numpy as np
import pandas as pd

try:
    from scipy.optimize import minimize
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

# 默认风格基(4风格: 大盘价值/大盘成长/小盘价值/小盘成长), 行情代码为巨潮风格指数
# TODO: 首跑核对代码与数据源(AKShare stock_zh_index_daily 是否覆盖)
DEFAULT_STYLE_BASIS = {
    "large_value": "sz399373",   # 巨潮大盘价值
    "large_growth": "sz399372",  # 巨潮大盘成长
    "small_value": "sz399377",   # 巨潮小盘价值
    "small_growth": "sz399376",  # 巨潮小盘成长
}


def _project_simplex(v: np.ndarray) -> np.ndarray:
    """欧氏投影到概率单纯形 {w>=0, sum(w)=1} (Duchi et al. 2008)"""
    u = np.sort(v)[::-1]
    css = np.cumsum(u)
    rho = np.nonzero(u * np.arange(1, len(v) + 1) > (css - 1))[0][-1]
    theta = (css[rho] - 1) / (rho + 1.0)
    return np.maximum(v - theta, 0)


def _solve_weights(y: np.ndarray, X: np.ndarray) -> np.ndarray:
    """min ||y - Xw||^2  s.t. w>=0, sum(w)=1"""
    k = X.shape[1]
    if HAS_SCIPY:
        w0 = np.full(k, 1.0 / k)
        res = minimize(
            lambda w: np.sum((y - X @ w) ** 2),
            w0,
            method="SLSQP",
            bounds=[(0, 1)] * k,
            constraints={"type": "eq", "fun": lambda w: w.sum() - 1},
        )
        return res.x
    # numpy-only: 加速投影梯度(FISTA), 步长 1/L, L=2*λmax(X'X)
    XtX = X.T @ X
    Xty = X.T @ y
    L = 2 * np.linalg.eigvalsh(XtX).max()
    if L <= 0:
        return np.full(k, 1.0 / k)
    w = np.full(k, 1.0 / k)
    z, t = w.copy(), 1.0
    for _ in range(2000):
        grad = 2 * (XtX @ z - Xty)
        w_new = _project_simplex(z - grad / L)
        t_new = (1 + np.sqrt(1 + 4 * t * t)) / 2
        z = w_new + ((t - 1) / t_new) * (w_new - w)
        if np.abs(w_new - w).max() < 1e-8:
            w = w_new
            break
        w, t = w_new, t_new
    return w


def rbsa(fund_ret: pd.Series, style_rets: pd.DataFrame) -> dict:
    """单次 RBSA. 返回 {weights: Series, r2: float}"""
    df = pd.concat([fund_ret.rename("y"), style_rets], axis=1, join="inner").dropna()
    if len(df) < 40:
        return {"weights": None, "r2": np.nan}
    y = df["y"].values
    X = df.drop(columns="y").values
    w = _solve_weights(y, X)
    resid = y - X @ w
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - np.sum(resid ** 2) / ss_tot if ss_tot > 0 else np.nan
    return {"weights": pd.Series(w, index=df.columns.drop("y")), "r2": float(r2)}


def rolling_rbsa(fund_ret: pd.Series, style_rets: pd.DataFrame,
                 window_days: int = 120, step_days: int = 21) -> pd.DataFrame:
    """滚动 RBSA. 返回 DataFrame(index=窗口末日, columns=风格权重)"""
    fund_ret = fund_ret.sort_index().dropna()
    rows = {}
    idx = fund_ret.index
    for end_pos in range(window_days, len(idx), step_days):
        win_idx = idx[end_pos - window_days:end_pos]
        r = rbsa(fund_ret.loc[win_idx], style_rets)
        if r["weights"] is not None:
            rows[idx[end_pos - 1]] = r["weights"]
    return pd.DataFrame(rows).T


def style_label(weights: pd.Series, extreme_threshold: float = 0.6) -> str:
    """风格标签: 某一风格权重>阈值 -> 该风格; 否则 balanced
    输入权重 index 须为 DEFAULT_STYLE_BASIS 的 key"""
    if weights is None or weights.empty:
        return "unknown"
    top = weights.idxmax()
    return top if weights[top] >= extreme_threshold else "balanced"


def style_stability(rolling_weights: pd.DataFrame) -> dict:
    """C2 风格稳定性: 权重序列波动越小越稳定
    返回 {stability: 0-1 (高=稳), switches_2y: 近2年标签切换次数}"""
    if rolling_weights.empty:
        return {"stability": np.nan, "switches_2y": np.nan}
    # 稳定度 = 1 - 平均(各风格权重的滚动标准差)*2 (clip 到 0-1)
    vol = rolling_weights.std().mean()
    stability = float(np.clip(1 - 2 * vol, 0, 1))
    # 标签切换计数(近2年)
    cutoff = rolling_weights.index.max() - pd.Timedelta(days=730)
    recent = rolling_weights[rolling_weights.index >= cutoff]
    labels = [style_label(recent.loc[i]) for i in recent.index]
    switches = sum(1 for a, b in zip(labels, labels[1:]) if a != b)
    return {"stability": stability, "switches_2y": int(switches)}
