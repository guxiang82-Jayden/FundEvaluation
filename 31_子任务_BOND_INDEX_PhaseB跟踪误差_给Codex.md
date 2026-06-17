# 子任务:BOND_INDEX Phase B — 指数映射 + 真·跟踪误差(给本机 Codex)

> 遵循 COLLABORATION.md:只本地 commit 不 push;完成回写"✅ 已完成"。
> 本机有 akshare → 拉标的指数净值。主线 `scoring_bond_index.py` 已留好 Phase B 接口。

## 背景
`scoring_bond_index.py`(工具型卡)Phase A 已接入主线,但**跟踪误差(A维)/指数代表性(D维)缺数据**,工具型榜目前全 `provisional`。模块已预留:
- `build_index_metrics(df, navs, index_ret_map)`:传入 `index_ret_map` 即算 `tracking_error`/`info_ratio_track`(`_tracking_stats`)。
- `_lookup_index_return(row, index_ret_map)`:支持 `index_ret_map[fund_code]` 或 `row["index_code"]/["benchmark_code"]` → `index_ret_map[index_code]`。
- `INDEX_INDICATORS["D_manager"]["index_mainstream"]`:指数主流度先验分(+1)。
本任务补这两块数据,让工具型榜从 provisional 升 formal。

## 你的任务
1. **建映射表 `data/index_map_bond.csv`**,列:`fund_code, index_code, index_name, index_mainstream`。
   - 覆盖 universe 里 track==BOND_INDEX 的基金(指数固收 + QDII债)。
   - `index_code`:标的指数代码(从 `getFundBenchmarkInfo`/akshare 业绩基准解析,或人工填主要指数)。
   - `index_mainstream`:主流度先验分 [0,1] —— 宽基/政金债/国开/中证综合债等主流=0.8~1.0;细分策略/小众指数=0.3~0.5。**人工先验,注释标"待校准"**。
   - 拉不到标的指数的基金:留空行或 index_code 空,**下游自动降级**(tracking_error=NaN)。
2. **新增 `scripts/build_index_navs.py`**(或并入现有取数):按 `index_map_bond.csv` 的 index_code,用 `data_akshare.index_returns()` 拉指数日收益,产出 `index_ret_map = {index_code: ret_series}`;给 `run_monthly_bond` 调用。
3. **接入 run_monthly_bond**(最小改动,主线风格):
   - `score_index_track` 增加可选入参 `navs`/`index_ret_map`;有则 `scoring_bond_index.build_index_metrics(df, navs, index_ret_map)` 后再 `score_index`,使 tracking_error/index_mainstream 生效。
   - `index_mainstream` 列从 `index_map_bond.csv` merge 进 df。
4. 测试:合成 fund nav + index ret,验证 tracking_error 方向(跟踪误差小→A维高)、index_mainstream 高→D维高、映射缺失→降级 provisional 不报错。

## 验收
- 工具型榜上,有映射的基金 `score_label` 由 provisional → formal(A/D 维补齐);无映射的仍 provisional(降级)。
- `index_map_bond.csv` 注释/README 说明 index_mainstream 为人工先验待校准。
- akshare/指数拉取失败优雅降级,不中断主流程。

## 交付
- 本地 commit `[codex] feat(v0.4): BOND_INDEX Phase B 指数映射+跟踪误差`(不 push),回写"✅ 已完成"。
- 回报附:覆盖了多少只 BOND_INDEX、多少只成功算出 tracking_error、典型基金的 te 数值。

## 边界
- ✅ 新建 index_map_bond.csv + build_index_navs.py;最小改动 run_monthly_bond/score_index_track 接 Phase B 接口
- ❌ 不改 scoring_bond_index.py 的评分逻辑/权重(只喂数据);不改 scoring.py/config.py;不 push
- 参考:`scoring_bond_index.py`(build_index_metrics/_lookup_index_return/_tracking_stats)、`data_akshare.index_returns`

✅ 已完成 2026-06-17

Codex 回写:
- `data/index_map_bond.csv` 当前 26 行, 其中 24 行有 `index_code`; QDII债留空降级, 不用境内中债指数硬套。
- `build_index_navs.py` 已接入 `run_monthly_bond.score_index_track(navs, index_ret_map)`, 映射/指数失败会降级不中断。
- 轻量实测 `CBA00101` 可取收益; 抽样 3 只成功计算 tracking_error:
  - 006102: TE=0.155970
  - 007729: TE=0.110158
  - 008100: TE=0.208294
- `index_mainstream` 为人工先验, 待后续用真实映射与回测校准。
