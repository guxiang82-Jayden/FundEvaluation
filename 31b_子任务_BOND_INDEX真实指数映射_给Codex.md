# 子任务 31b:BOND_INDEX 真实标的指数映射(修 31 一刀切占位)(给本机 Codex)

> 遵循 COLLABORATION.md:只本地 commit 不 push;完成回写"✅ 已完成"。
> 修复 31 的数据缺陷:`data/index_map_bond.csv` 把全部 24 只**一刀切映射到 CBA00101 中债综合财富指数、mainstream 全 0.90**,导致 tracking_error 失真(实测 0.11~0.21=年化11-21%,真跟踪型应 <2%)。**代码无需改,只重建映射数据 + 加校验。**

## 核心问题
指数固收基金各自跟踪**不同**标的(国开 1-3 年 / 政金债 / 同业存单 AAA / 特定久期段 / 海外债…),不能都对中债综合。错配指数算出的"跟踪误差"是噪声,会让工具型榜的 A 维(跟踪有效性)/D 维(代表性)排序失真。

## 你的任务(本机 akshare,不调且慢 MCP)
1. **逐只确定真实标的指数**,来源优先级:
   - (a) **基金名称**解析(指数固收命名通常含标的,如"XX中债7-10年国开行债券指数A"→ 7-10年国开)。
   - (b) 业绩基准文本(若 akshare 可取,如 `fund_individual_basic_info_xq`/东财基金档案的"业绩比较基准"),正则提取指数名。
   - 二者皆无法确定 → **index_code 留空**(下游自动 provisional)。**严禁再填默认中债综合。**
2. **建指数关键词→代码参考表**(模块内常量或 `data/index_code_ref.csv`),至少覆盖常见债指:
   - 中债综合财富 CBA00101;中债-国开行债券总;中债-政策性金融债;中债 1-3年/3-5年/7-10年 国开;中证同业存单AAA;中债信用债总;中证短融;(QDII海外债标的若 akshare 无净值则留空)。
   - 每个指数给 **index_mainstream 先验**:宽基综合/国开总/政金债总=0.9;细分久期段=0.6;同业存单=0.8;海外/小众策略=0.3~0.4。**分级、不要全 0.9**。
3. **重建 `data/index_map_bond.csv`**(fund_code,index_code,index_name,index_mainstream),只对能确定的填,其余留空。
4. **重算并自检 tracking_error**(复用 `build_index_navs` + `scoring_bond_index`):
   - **验收硬指标**:映射正确后,指数固收(境内被动)的 TE 应**显著下降到 <≈3%**;若仍 >5%,说明该只映射仍错配 → 回查或留空。
   - QDII债 因汇率/海外,TE 偏高可接受,但**单列说明**,不与境内混排判定。

## 验收
- `index_map_bond.csv` 不再有"全部同一指数 + 全 0.90"的情况;index_mainstream 分级合理。
- 重算后境内指数固收 TE 中位数 <≈3%(报告 TE 分布:min/中位/max + 仍>5%的清单)。
- 解析不到的基金 index_code 留空、保持 provisional,不报错。

## 交付
- 本地 commit `[codex] fix(v0.4): BOND_INDEX 真实标的指数映射(替换一刀切默认)+ TE自检`(不 push),回写"✅ 已完成"。
- 回报附:映射覆盖只数、TE 分布(min/中位/max)、仍 >5% 的清单及原因。

## 边界
- ✅ 重建 index_map_bond.csv + 关键词参考表 + TE 自检;按名称/基准解析
- ❌ 不改 scoring_bond_index.py 评分逻辑/build_index_navs 接口;不调且慢 MCP;不 push;不再用默认中债综合兜底
- 参考:31 已有的 `build_index_navs.py` / `scoring_bond_index.py`;TE 的物理意义(真跟踪应 <2-3%)是本次正确性的硬约束

✅ 已完成 2026-06-17

Codex 回写:
- 已重建 `data/index_map_bond.csv`: 当前 BOND_INDEX universe 756 行, 不再使用一刀切 `CBA00101` 兜底。
- 新增 `data/index_code_ref.csv`: 记录关键词 -> 标的指数族/主流度/收益源状态。
- 有 `index_code` 的基金 1 只: `016859 中加中债-新综合债券指数发起`, `CBA00101`, TE=0.009401。
- TE 分布: min=0.009401, median=0.009401, max=0.009401, >5% 清单=无。
- 755 只保持 provisional: 已解析 `index_name/index_mainstream`, 但当前取数层无法按真实细分指数取收益, 因此 `index_code` 留空, 避免再次产生假 TE。
- 详见 `data/index_map_bond_te_check.md`。
