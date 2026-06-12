# 评估脚本 v0.1

对应设计文档:`01_评估框架v0.1.md` | 数据源结论:`02_数据源试跑记录.md`

## 架构

```
config.py        全部阈值/权重/同类口径/主题白名单 —— 调参只动这里
metrics.py       指标计算(净值序列 → 卡玛/索提诺/胜率/回撤修复等), 数据源无关
benchmark.py     业绩基准字符串解析 → 指数行情合成基准收益
screening.py     L1 负面初筛(N1-N9 + 主题豁免 + 观察通道分流)
scoring.py       L2 评分引擎(同类分位记分卡、窗口合成、短板/否决、重点池)
data_akshare.py  AKShare 适配层(独立运行的主数据源, 含 parquet 缓存)
run_monthly.py   月度跑批入口 → output/score_*.xlsx(评分/观察池/剔除三张表)
test_engine.py   合成数据测试(已通过 2026-06-11)
```

**设计要点**:MCP(且慢/iFinD)只有 Claude 会话能调用,不进脚本依赖;脚本主干 AKShare 可独立调度,MCP 数据用于会话内交叉校验与深研。引擎吃 DataFrame,换数据源不动核心逻辑。

## 运行

```bash
pip install akshare pandas pyarrow openpyxl scipy
python test_engine.py                 # 合成数据自检
python test_modules.py                # RBSA/回测模块自检
python run_monthly.py --limit 50      # 小样本试跑
python run_monthly.py                 # 全量(主动权益组)
```

scipy 可选:无 scipy 时 RBSA 自动退化为 numpy FISTA 实现(已测,结果一致)。

## v0.1 已知未完成(按优先级)

1. `data_akshare.fund_meta()` 未实现 —— 规模/任期/持有人等初筛元数据,需首跑核对 AKShare 字段
2. 逐基金基准解析未接入主流程(暂统一用中证800);债券/港股指数行情源待补
3. A2(同类分位持续性)、C 维(归因/风格/ReturnGap)、D/E 维数据管道未接
4. 回测验证模块(框架文档第 6 节)未建
