# 子任务 34:BOND_INDEX 中债系标的字典 + 解锁 TE(给本机 Codex)

> 遵循 COLLABORATION.md:只本地 commit 不 push;完成回写"✅ 已完成"。
> 承 31b/33:中证系(同业存单/综合债/短融)已用权威代码 + TE gate 解锁 110 只。本任务攻**中债系**(国开/政金/农发/进出口行/国债各久期段,CBAxxxxx),把工具型 A 维进一步铺开。

## 关键教训(必须遵守)
- ❌ **不要用 iFinD index_data 的 NL 模糊匹配猜代码**(31b/Phase C 实测:把"中证全债"返回成"内地消费"股票指数、把"7-10年国开"返回成"国债及政金")。
- ✅ 代码必须来自**权威源**:中债估值中心官网指数代码表 / 中证指数公司 / 可核对的 iFinD SDK 精确查询。
- ✅ **TE gate 是正确性的最终裁判**:被动跟踪的久期段债指 TE 应低(短段 <~1%、长段 <~3%);若 >5% 必是代码或匹配错 → 回查或留空,绝不让假 TE 进榜(同 33 的纪律)。

## Step 0(先做,决定可行性):确认中债指数净值源
当前 `data_akshare.index_returns` 对 `CBA*` **只能取中债综合/新综合**,取不到久期段(国开1-3/3-5/7-10、政金、国债段)。先确认本机能否取到这些久期段指数的**历史日净值**:
- 候选:iFinD 本机 SDK(若已装)/ 中债官网导出 / akshare 其它接口 / Wind 等。
- **若本机无任何可靠源 → 如实报告"中债久期段无净值源,本族暂挂",不要强行造数。** 这是合格的结论。

## Step 1(若有源):建字典 + 回填
1. 新建 `data/index_code_cbond_ref.csv`:`keyword,index_code,index_name,index_mainstream,return_source,verified`,逐条权威核对。覆盖:国开行(1-3/3-5/7-10/总)、政策性金融债(久期段/总)、农发行、进出口行、国债(久期段/总)。mainstream 分级(总指数0.9 / 久期段0.6)。
2. 逐只解析 BOND_INDEX 中债系基金的**真实业绩基准/名称** → 匹配期限段与族 → 回填 `index_map_bond.csv` 的 `index_code`;不确定的**留空保持 provisional**。
3. 扩展 `index_returns` 支持选定的中债源取净值(若需)。

## Step 2:重算 TE + gate
- 复用 `build_index_navs` + `scoring_bond_index`,重算中债系 TE。
- gate:久期段 TE 偏高于综合属正常,但仍应 <~3%;>5% 回查/留空。
- 产出 `data/index_map_bond_cbond_te_check.md`:覆盖只数、各族 TE 分布(min/中位/max)、>3% 清单及处置。

## 验收
- 有源则:中债系新增若干只拿到合理低 TE、升 formal;字典权威可核;gate 通过。
- 无源则:如实报告并把中债系标注"待净值源",不造假 TE(此结论同样验收通过)。
- 优雅降级、不报错、不改 `scoring_bond_index.py` 评分逻辑;QDII 海外债单列、不与境内同口径混排。

## 交付
- 本地 commit `[codex] feat(v0.4): BOND_INDEX 中债系字典 + TE(或:中债久期段无净值源结论)`(不 push),回写"✅ 已完成"。
- 回报附:Step 0 的净值源结论、字典覆盖、TE 分布。

## 边界
- ✅ Step0 探源 → 有源则建权威字典+回填+TE gate;无源则如实挂起
- ❌ 不 NL 猜代码;不造假 TE;不碰中证系(已完成);不改评分逻辑;不 push
- 参考:`data/index_code_ref.csv`、`data/index_map_bond_phasec_te_check.md`(33 范式)、`build_index_navs.py`
