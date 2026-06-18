# 子任务 36:权益线补全(二)— C2 风格稳定性 + N7 风格漂移 + 编码清理(给本机 Codex)

> 遵循 COLLABORATION.md:只本地 commit 不 push;完成回写"✅ 已完成"。
> 本机有 akshare + scipy。`rbsa.py` 已完整就绪,本任务=喂数据 + 接入 cdim,不重写算法。

## 背景
`config.INDICATORS["C_attribution"]["style_stability"]`(C2,权重0.30)与 `SCREENING["N7_max_style_switches"]`(风格漂移筛)槽位都在,但**没数据喂 → C2 生产降级、N7 不生效**。`rbsa.py` 已实现:
- `rolling_rbsa(fund_ret, style_rets, window=120, step=21)` → 滚动风格权重
- `style_stability(rolling_weights)` → `{stability: 0-1(高=稳), switches_2y: 近2年标签切换次数}`
- 默认风格基 `DEFAULT_STYLE_BASIS`:巨潮大盘价值/成长、小盘价值/成长(sz399373/399372/399377/399376),注释有 `TODO 首跑核对数据源`。

## Step 0(先做):确认风格指数收益源
确认 akshare 能否取这 4 个巨潮风格指数的历史日行情(如 `ak.stock_zh_index_daily(symbol="sz399372")` 或等价接口)→ 转日收益。
- **能取**:直接用。
- **取不到/覆盖差**:**回报告知,主线(Claude)会话内用 iFinD 拉这 4 个风格指数收益存 CSV 给你**(同 BOND_INDEX 中证系的协作模式)。也可评估中证风格指数(成长/价值)作备选,但**先报现状、不要随意换基**。

## 你的任务
1. 新增取数:`style_index_returns()` → 返回 4 风格指数的日收益 DataFrame(对齐日期)。akshare 不行则留接口、读主线提供的 CSV(如 `data/style_index_returns.csv`)。
2. 批量计算:对主动权益 universe 每只,用**复权净值**(已是任务35的口径)日收益跑 `rolling_rbsa` → `style_stability`,得到:
   - `style_stability`(0-1)→ C2
   - `style_switches_2y`(整数)→ N7 风格漂移筛
   - 可选 `rbsa_r2`(拟合优度,低 R² 说明风格基不解释该基金,C2 置信度低)
   - 存入 `data/cdim_data.csv` 新增列(同 brinson/turnover 模式)。**整批算、缓存,别重复跑。**
3. 接入加载层:
   - `cdim.py`:把 `style_stability` 派生为 C2 输入列;`style_switches_2y` 供 screening。docstring 补列说明。
   - 确认 `screening_*`(权益)读 `style_switches_2y` 触发 N7(`>SCREENING["N7_max_style_switches"]` 标记/降级);若字段名不一致,对齐之。
   - **不改 scoring/config 权重**,只补数据通路。缺数据自动降级。
4. **编码清理(顺手)**:把 `scripts/test_*.py` 里的 `✓`✗ 等非 ASCII 符号换成 ASCII(如 `[OK]`/`[FAIL]`),消除 Windows GBK 控制台的 `UnicodeEncodeError`(35 已暴露此坑),让测试不依赖 `PYTHONIOENCODING`。

## 验收
- `style_stability ∈ [0,1]`;抽 3-5 只验证合理:风格鲜明的基金(如某小盘成长)对应风格权重高、R² 较高;风格漂移大的基金 stability 低、switches_2y 高。
- C2 进入评分输入(覆盖率报告),N7 能基于真实 switches 触发。
- 风格基取不到时优雅降级(C2 留空、不报错、不中断主流程)。
- 测试去除非 ASCII 后,**不设** `PYTHONIOENCODING` 也能跑通。

## 交付
- 本地 commit `[codex] feat(v0.3): C2风格稳定性(RBSA)+N7漂移接入 + 测试编码清理`(不 push),回写"✅ 已完成"。
- 回报附:风格源结论(akshare 能否取)、C2 覆盖率、3-5 只抽样的风格权重/stability/R²、switches 触发 N7 的只数。

## 边界
- ✅ 用现成 rbsa.py;补风格指数取数 + 批算 + 接 cdim/screening + 测试编码清理
- ❌ 不重写 rbsa 算法;不改 scoring/config 权重;不逐只慢调网络;不 push;C3 ReturnGap 不在本包
- 参考:`rbsa.py`(现成接口)、`cdim.py`(C/E维并入模式)、`config.INDICATORS C2` + `SCREENING N7`、任务35复权净值口径

✅ 已完成 2026-06-18

## 实跑结论

- 四个巨潮风格指数 AKShare 均可用：`sz399373/399372/399377/399376`，
  共同收益区间 `2010-01-08` 至 `2026-06-17`，3990 个交易日。
- 新增 `build_style_cdim.py`，复用任务35复权净值，支持检查点落盘与断点续跑。
- 全主动权益池 4926 只完成原始 RBSA 4568 只，覆盖率 92.7%；
  18 只取数失败，306 只历史不足，另有少量仅一个滚动窗口、稳定度不可计算。
- 加入透明置信门槛：`rbsa_r2 < 0.20` 时保留原始结果供审计，但 C2/N7 自动降级。
  经门槛后 C2 有效 4175/4926，覆盖率 84.8%；393 只因低 R² 降级。
- 可靠样本分布：stability 中位 0.658，R² 中位 0.645，近2年切换次数中位 3。
- 代表样本：
  - 广发小盘成长混合A：small_growth 1.00，stability 0.599，R² 0.783。
  - 工银中小盘混合：small_growth 1.00，stability 0.739，R² 0.795。
  - 国泰海通科创板量化选股A：small_growth 1.00，stability 0.946，R² 0.829。
  - 宝盈优势产业混合A：stability 0.399，switches 4，R² 0.552。
- 修复了真实接线问题：`build_meta_table` 的空 `style_switches_2y` 占位列此前会在
  merge 后产生 `_x/_y`，现由真实 RBSA 字段覆盖，N7 已在生产链路生效。
- `run_monthly.py --limit 50` 真跑：C2 有效 39/50，评分权重覆盖率均值 94%；
  N7 触发 19 只，剔除原因汇总 `N7_风格漂移:19`。

## 风险提示

- 全量可靠样本中 `switches_2y > 2` 有 2270 只，超过半数；首批50只有19只触发。
  当前 `0.6` 单标签阈值容易在 `balanced ↔ 单一风格` 附近抖动。
- 建议主线在正式投资使用前，将 N7 暂作观察标记，后续增加标签滞回/连续两窗口确认，
  或按同类组校准切换次数阈值；本任务按现有 config 接通，不擅自改权重与 RBSA 算法。
- 所有 `scripts/test_*.py` 的状态符号已改为 ASCII，默认 Windows 控制台无需
  `PYTHONIOENCODING` 即可运行。
- 全测试集未再出现 GBK/UnicodeEncodeError。两项非本任务数据态/资源态问题：
  `test_cdim_bond.py` 当前真实债基 C 维命中 105 只，未达到测试硬阈值；
  `test_review.py` 业务断言通过，但 Windows 临时 xlsx 文件句柄占用导致清理失败。
  均未越界修改。

待统一推送。
