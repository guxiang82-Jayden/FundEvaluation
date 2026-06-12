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

⚠️ **全量/过夜跑前必做**:关闭系统睡眠,否则中断(2026-06-12 实测教训):

```powershell
powercfg /change standby-timeout-ac 0   # 接通电源永不睡眠, 跑完可改回
```

中断不致命:净值/元数据有当日缓存,重跑快进;但仍建议一次跑完。

## 当前状态(2026-06-12)

**已完成并实测**:fund_meta(规模/成立/基准文本/仓位,雪球+东财源)、逐基金基准解析合成(22 指数映射,解析率约 50-60%)、份额合并、RBSA 风格分析(rbsa.py)、回测引擎(backtest.py,合成数据验证)、500 只真实样本两轮跑通、评分可信度标识(provisional/覆盖率/候选池)。

**已知未完成(按优先级)**:

1. 经理任期与变更(N4/N5)无数据源 —— AKShare 两接口均无单基金任职起始日,候选:fund_manager_change_em / 天天单基金页;会话内可用且慢 MCP 补
2. A2(同类分位持续性)、C 维(归因/风格/ReturnGap)、D/E 维数据管道未接 —— 当前综合分实为 A+B,已强制标记 provisional
3. 持有人结构(N6)、合并规模(N1 现用主份额规模)、近4季仓位中枢(N9 现用单期)
4. 累计净值未做分红再投资复权(高分红基金收益略低估)
5. 回测接真实历史数据(防前视) —— 引擎已就绪
6. 同类组细分(普通股票/偏股/灵活 + 策略标签)与自建分位
