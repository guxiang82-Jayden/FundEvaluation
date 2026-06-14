# 子任务:债基双 track 真跑 + 口径质检(给本机 Codex)

> 遵循 COLLABORATION.md:本地 commit 不 push;完成回写"✅ 已完成"并报"待统一推送"。
> **这是"跑批 + 观察报告"任务,不改主线代码**。若发现口径 bug,只**记录到报告**,交主线 agent 修(避免与主线并行改 run_monthly_bond.py 撞车)。

## 背景
v0.4 债基线纯债 + 固收+ 双记分卡已串通并上库(commit 741bcbb)。此前全是合成数据,需在本机用 akshare **真跑一遍**,暴露真实口径问题。

## 步骤
```bash
cd D:\03_AI_Projects_and_Vault\Fund_Evaluation
git pull --rebase                      # 取到 741bcbb 及之后
cd scripts ; .venv\Scripts\activate
python test_engine.py ; python test_bond_pipeline.py ; python test_cdim_bond.py ; python test_bond_tracks.py   # 应全过
python data_bond.py                    # 确认中债指数取数 + 纯债 R²>0.6
python run_monthly_bond.py --limit 60  # 双 track 真跑(调试, 不归档)
```

## 需要你观察并记录的(写进 `scripts/data/bond_run_report.md`)
1. **L0 分类分布**:`subgroup_stats` 各债基子组数量;有无大量"未分类"。
2. **双 track 样本量**:纯债 track / 固收+ track 各多少;固收+ 三档(保守/稳健/积极)各多少,**是否有档 <5 只被 defer**(framework 要求同档≥5 才评分)。
3. **覆盖率/可信度**:formal vs provisional 比例;`weight_coverage` 均值;命中 cdim_bond 的有几只(C2/C3/C4 生效)。
4. **Campisi 质量**:纯债 `campisi_r2` 分布(高/中/低置信占比),含权基金 R² 是否如预期偏低。
5. **equity_position 可得性**:固收+ track 里 equity_position 缺失率(缺则该只 defer 或走兜底)——这是固收+ 能否真正走 BOND_PLUS 的关键。
6. **口径疑点**(重点!逐条记录,不改代码):
   - 可转债基金当前归 BOND track(纯债记分卡),是否合理?(framework 说可转债权益属性强,或应单列)
   - `bond_universe` 用东财 `债券型|混合型-偏债` 正则,是否漏/误纳(如指数债基、同业存单、QDII债)?
   - 中债指数缺"中债转债"(data_bond 注释有 TODO),对含权基金 Campisi 的影响?
   - 小子组 <10 只回退"纯债综合"后,跨子组分位是否失真?
   - 任何 `[warn]` / `metrics failed` / `screen skipped` 的频次。
7. **榜单合理性**:打开输出 xlsx 的"纯债可投主榜""固收+榜",人工扫 Top10 是否符合直觉(大厂稳健纯债靠前、踩雷/高杠杆靠后)。

## 交付
- 写 `scripts/data/bond_run_report.md`(上述 7 点 + 关键数字 + 你的口径修正建议)
- 可附输出 xlsx 路径(不必提交 xlsx 本身,output/ 已 gitignore)
- 本地 `git add scripts/data/bond_run_report.md && git commit -m "[codex] docs: 债基真跑质检报告"`(**不 push**)
- 本文件末尾追加 `✅ 已完成 YYYY-MM-DD`,报 Jayden"待统一推送"

## 边界
- ❌ 不改任何 .py(发现 bug 只写报告);❌ 不 push
- ✅ 只新增 bond_run_report.md
- 跑批耗时长可先 `--limit 60`;若顺利可再 `python run_monthly_bond.py`(全量,会归档)
