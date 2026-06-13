# C/E 维数据拉取流程(会话内执行)

> `cdim_data.csv` 由 Claude 会话内用且慢 MCP 拉取(MCP 独立脚本调不了)。当前为样本(5 只),全池拉取按下述流程批量补。

## CSV 列

| 列 | 来源工具 | 字段 |
|---|---|---|
| brinson_ar | getFundBrinsonIndicator(LAST_3_YEAR) | ar 配置收益 |
| brinson_sr | 同上 | sr 选股收益 |
| brinson_er | 同上 | er 总超额 |
| conc_cr5 | getFundIndustryConcentration | data[0].cr5 前5行业集中度 |
| turnover_rate | getFundTurnoverRate | data[0].turnoverRate |

## 派生指标(cdim.py 自动算)

- selection_share = sr/er (er>0.02 时; C1 选股贡献占比)
- concentration = cr5 (C4, U型计分)
- turnover = turnover_rate (E2, 越低越好)

## 批量拉取流程(下次会话或定期)

1. 取目标基金代码(建议:上期评分主榜 + 候选池,约 300-600 只)
2. 对每只依次调三个工具(单只单调,无批量版),解析上述字段
3. 追加/更新到 cdim_data.csv(按 fund_code 去重,保留最新)
4. 提交 git

注:Brinson 用 LAST_3_YEAR;集中度/换手用默认最新报告期。每只3次调用,300只≈900次调用,建议分批跨会话或限定在主榜范围。
