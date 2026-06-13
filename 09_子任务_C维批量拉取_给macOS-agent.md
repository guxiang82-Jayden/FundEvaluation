# 子任务:批量拉取主榜 C/E 维数据(给 macOS agent)

> 隔离原则:本任务**只生产数据**(追加到 `scripts/data/cdim_data.csv`),**不修改任何 .py 文件**,与主线开发互不冲突。完成后单独 commit 这一个 CSV。
>
> **进度更新 2026-06-13**:主线会话内已拉取 **25 只**(主榜综合分靠前),cdim_data.csv 已含 25 行。macOS 环境配好后,从主榜剩余基金继续往后拉(去重已有 25 只),目标扩到 200-300 只。代码列表见 /tmp/cdim_todo.json 的口径(可投主榜规模≥2亿,约 1985 只)。

## 背景

主动权益评分体系 v0.3 正在补全 C/E 维。`cdim.py` 已就绪,会读取 `scripts/data/cdim_data.csv` 把 C/E 维指标合并进评分,让基金从 provisional 升为 formal。目前 CSV 只有 5 只样本,需扩到全主榜(约 200-300 只)。

## 你的任务

为「可投主榜」的基金,用**且慢 MCP**(会话内可调)拉取三项数据,追加到 CSV。

### Step 1:取目标基金代码

读取最新存档的「可投主榜」sheet:
`D:\03_AI_Projects_and_Vault\Fund_Evaluation\archive\score_active_equity_2026-06-13.xlsx`
(注:你在 macOS,路径按你挂载的实际路径换算;文件在仓库 `archive/` 下)

取 `fund_code` 列(6位字符串,注意前导零)。优先按 `composite_score` 降序取前 200-300 只。**排除已在 cdim_data.csv 里的 5 只**(000979/001194/000411/001076/000390)。

### Step 2:逐只拉三个且慢 MCP 工具

对每个 fund_code:

1. `getFundBrinsonIndicator(fundCode, timePeriod="LAST_3_YEAR")` → 取 `ar`, `sr`, `er`
2. `getFundIndustryConcentration(fundCode)` → 取 `data[0].cr5`
3. `getFundTurnoverRate(fundCode)` → 取 `data[0].turnoverRate`

任一调用失败/无数据 → 该列留空,继续下一只(不要中断)。

### Step 3:追加到 CSV

文件:`scripts/data/cdim_data.csv`,**表头保持不变**:
```
fund_code,brinson_ar,brinson_sr,brinson_er,conc_cr5,turnover_rate
```
- 追加新行,**不要删除已有 5 行**
- fund_code 保持 6 位文本(前导零)
- 按 fund_code 去重(若重复保留最新)

### Step 4:校验并提交

```powershell
# 校验:能被 pandas 读、无重复、列数对
python -c "import pandas as pd; d=pd.read_csv('scripts/data/cdim_data.csv',dtype={'fund_code':str}); print(len(d),'行',d['fund_code'].duplicated().sum(),'重复')"
```
然后**只提交这一个文件**:
```powershell
cd <仓库根>
git add scripts/data/cdim_data.csv
git commit -m "data: 批量补充主榜C/E维数据(N只)"
git push
```

## 注意事项

- **只动 cdim_data.csv,不碰任何 .py**(主线在改 scoring/run_monthly,避免冲突)
- 且慢 MCP 无明确额度限制,但单只3次调用,300只≈900次,**可分批**(拉一批存一批,中断也不丢)
- 派生指标(selection_share 等)由 cdim.py 自动算,你**不用**算,只存原始 5 列
- er 可能为负或接近0(选股占比公式里 cdim.py 会处理),原样存即可
- 拉完在本文件末尾追加一行「已完成 N 只,日期」即可

## 验收

CSV 行数从 5 增至 200+,无重复,pandas 可读;git 单文件提交成功。主线 agent 下次跑 `run_monthly` 时会自动看到覆盖率提升、formal 基金增多。
