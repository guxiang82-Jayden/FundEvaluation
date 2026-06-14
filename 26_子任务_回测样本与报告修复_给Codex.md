# 子任务:让回测可信(样本构造 + 报告修复)给本机 Codex

> 遵循 COLLABORATION.md:本地 commit 不 push;完成回写"✅ 已完成"。
> **隔离边界**:只改 `scripts/run_backtest.py` 与 `scripts/backtest.py`(均为回测专用,主线不依赖);可扩 `scripts/test_backtest.py`。
> **不改** scoring.py / config.py / metrics*.py / run_monthly*.py。

## 背景(关键)
首轮真跑 `run_backtest.py --limit 300` 只得到**36 只有效基金**,RankIC 均值 -0.149——但 n=36 标准误≈0.17,**统计上与 0 无法区分,不能用于校准权重**。
根因推测:回测最早 asof=2019-12-31 需 3 年窗口(基金须 2016 年前成立),而当前按 universe 顺序取前 300 只、**未按成立年限筛**,多数较新基金在早期 asof 被 valid_3y/inception 过滤掉。也可能混有净值抓取失败。**先诊断再修。**

## 任务

### 1. 诊断:失败原因分桶(先做, 写进报告)
在 `run_backtest.py` 加载阶段统计并打印/写报告:
- 请求数 / 净值抓取成功数 / 抓取失败数(HTML异常等)/ 成立太短被过滤数 / 最终有效数
- 让我们确知"小样本"主因是 **短历史** 还是 **抓取失败**。

### 2. 样本构造改造(核心)
- **成立年限预筛**:进回测池前,用成立日(复用 `_load_inception_dates` / 雪球 basic_info)只保留 `成立日 ≤ 最早asof − min_history_years` 的基金,**再** limit。
- 新增 CLI:`--asof-start`(默认 2019)、`--asof-end`(默认 2024)、`--min-history-years`(默认 3)、`--limit` 默认提到 1500(预筛后合格的才进回测)。
- 目标:有效样本/期 上到**数百只**(而非 36),RankIC 才有统计意义。
- (可选)净值抓取失败重试 1–2 次 + 退避;HTML异常计入失败桶不算"无净值"。

### 3. 报告修复(backtest.py / run_backtest.py)
- `calibration_suggest`:当有 IC 数据但 `total_pos_ic==0`(各维 IC 全≤0)时,note 不应是"无IC数据",改为 **"各维IC≤0,暂不调权(非缺数据)"**;真正缺数据(NaN)才显示"无IC数据"。区分这两种。
- `run_backtest.py` 报告第3节"**窗口胜负小结**"当前为空:补上 5y vs 3y 的结论(对同一指标比较 mean_ic 与正IC率,汇总哪种窗口更具预测力的一句话)。

### 4. 测试(扩 test_backtest.py, 合成数据)
- calibration note 区分:构造"全维 IC≤0"与"维度 IC 缺失"两种 summary,断言 note 文案不同。
- (可选)成立年限预筛函数单测:给定 inception_dates,断言只保留够老的基金。

## 验收
- `run_backtest.py` 打印失败原因分桶;预筛+大limit 后有效样本显著上升(本机实测写进报告)。
- 报告 note 区分正确;第3节窗口小结非空。
- test_backtest.py 全过;不改主线文件。
- ⚠️ **不要**据这版结果改 config 权重——样本可信后由 Jayden 评审再定。

## 交付
- 本地 commit `[codex] fix(v1.0): 回测样本构造(成立预筛+诊断分桶)+ 报告修复`(不 push),回写"✅ 已完成 + 新有效样本数 + 失败分桶结论"。

## 边界
- ✅ 只改 run_backtest.py / backtest.py / test_backtest.py
- ❌ 不改 scoring/config/metrics/run_monthly*;不 push;不改权重
- 参考:`data/backtest_calibration_report.md`(首轮)+ 路线图 07 第五节
