# 评估脚本 v0.1

对应设计文档:`01_评估框架v0.1.md` | 数据源结论:`02_数据源试跑记录.md`

## Python 环境

- Python 3.13.2
- 实际安装位置：`C:\Python313`
- 当前兼容路径：`D:\python` → `C:\Python313`
- 项目虚拟环境：`scripts\.venv`
- 依赖锁：根目录 `requirements-lock.txt`
- 版本记录：根目录 `python-version.txt`

恢复环境（在项目根目录运行）：

```powershell
C:\Python313\python.exe -m venv scripts\.venv
.\scripts\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\scripts\.venv\Scripts\python.exe -m pip check
```

`.venv`、`.env`、API Key、Token、缓存和大型临时数据不提交 Git。

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

## 固收线架构(v0.4,2026-06-14 建成,测试全绿)

```
classify_bond.py      L0 债基/固收+分类(AKShare 类型映射 + 可转债按名识别)
screening_bond.py     L1 债基负面初筛(独立于权益线, 缺列跳过对应规则)
metrics_bond.py       债基指标层(净值风控 + Campisi 净值法 alpha + 持续性, 数据源无关)
campisi.py            净值法 Campisi 五因子归因(久期中性正交, 残差=alpha)
data_bond.py          AKShare 中债财富指数取数层(Campisi 因子, 用户机)
cdim_bond.py          C 维债基数据合并层(且慢 MCP 拉取存 CSV → data/cdim_bond_data.csv)
scoring_bond_plus.py  固收+评分(按权益中枢分档, 组内分位)
scoring_bond_cb.py    可转债专用记分卡(v0 先验, 组内≥5 评分, 待 RankIC 校准)
run_monthly_bond.py   债基月度跑批主入口(L0→L1→指标→4-Track 评分→Excel)
                      4-Track: 纯债 / 一级债 / 固收+ / 可转债CB(+ 指数固收/QDII工具型单列观察)
```

## v1.0 闭环工具(2026-06-14 建成, 测试全绿)

```
review.py             滚动复盘机制(复盘四问: 命中率/误杀漏放/RankIC/可比性break → 季度报告)
backtest.py           回测引擎(T期评分→T+1组内超额; 分维度/分窗口 RankIC; 严格防前视)
run_backtest.py       回测驱动(权益线滚动 RankIC + 权重校准报告; 样本受限待扩)
```

**设计要点**:MCP(且慢/iFinD)只有 Claude 会话能调用,不进脚本依赖;脚本主干 AKShare 可独立调度,MCP 数据用于会话内交叉校验与深研。引擎吃 DataFrame,换数据源不动核心逻辑。

## 测试清单(12 套, 2026-06-15 复跑全绿, 合成/离线无网络)

| 测试文件 | 覆盖范围 |
|---|---|
| test_engine.py | 权益线指标计算 + 初筛/评分流水线(v0.1 主自检) |
| test_modules.py | rbsa.py 风格分析 / backtest.py 引擎 |
| test_classify_bond.py | 债基 L0 分类器 |
| test_screening_bond.py | 债基 L1 初筛模块 |
| test_bond_pipeline.py | 债基固收线端到端: 分类→指标→初筛→score_all(BOND) |
| test_cdim_bond.py | C 维加载层 + 生效(用真实 cdim_bond_data.csv) |
| test_campisi.py | campisi.py 净值五因子归因 |
| test_scoring_bond_plus.py | 固收+ 记分卡 |
| test_scoring_bond_cb.py | 可转债 CB 专用记分卡 |
| test_bond_tracks.py | 4-Track 路由 + 评分 + Excel 分表 |
| test_review.py | review.py 双线复盘四问机制 |
| test_backtest.py | 分维度/分窗口 RankIC 多期聚合 |

运行(在 scripts/ 下): `python test_<名>.py`,各自独立、无网络依赖。

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
