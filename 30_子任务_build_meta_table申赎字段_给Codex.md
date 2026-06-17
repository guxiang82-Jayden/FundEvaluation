# 子任务:build_meta_table 补申赎状态字段(可投性数据落地)(给本机 Codex)

> 遵循 COLLABORATION.md:只本地 commit 不 push;完成回写"✅ 已完成"。
> 本机有 akshare → 拉申购/赎回状态整表。**最小侵入**:只动 `data_akshare.py` 取数层 + 测试。

## 背景
主线已落地"可投性前置"逻辑(`screening_bond.mark_investability_bond` + `scoring.score_all` OR 透传 `investability_warn`),
但**数据缺位**:`build_meta_table` 目前不提供申赎状态,功能 dormant。固收 L3 暴露:纯债 Top1(000212)定开停申赎、Top2(000134)暂停个人买入,**高分却买不了**。本任务把申赎状态接进来,让可投性预警在生产生效。

## 数据源
`akshare.fund_purchase_em()` 返回全市场申赎状态整表(列约为:基金代码/基金简称/基金类型/最新规模/手续费/**申购状态**/**赎回状态**/下一开放日)。**一次拉全表**,按 fund_code merge,**不要逐只调**(整表即可,避免限频)。

## 你的任务(只动 data_akshare.py)
1. 新增 `fund_purchase_status() -> pd.DataFrame`(带 `_cache` 缓存,同现有 parquet 缓存模式):
   - `ak.fund_purchase_em()`,重命名 → `fund_code`(zfill6)/`subscribe_status`(申购状态)/`redeem_status`(赎回状态)/`next_open_date`(下一开放日, 若有)。
   - 去重 fund_code。
2. 在 `build_meta_table` 末尾(`return df` 前)merge:
   - `df = df.merge(fund_purchase_status()[["fund_code","subscribe_status","redeem_status"]], on="fund_code", how="left")`。
   - 派生 `fund_status_text`:把 `subscribe_status`+`redeem_status`+(fund_type/name 含"定期开放/定开"→"定期开放")拼成一个文本列(供 `mark_investability_bond` 的关键词匹配)。
   - 缺列/拉取失败时 try/except 降级:warn 一行、补空列,**不可中断主流程**。
3. 列命名务必与主线 `screening_bond.mark_investability_bond` 一致:它识别 `subscribe_status / redeem_status / purchase_status / fund_status_text / can_subscribe` 任一。

## 验收
- `build_meta_table` 输出含 `subscribe_status/redeem_status/fund_status_text` 列。
- 对 000212(应"定期开放/暂停申赎")、000134(应"暂停"个人买入相关)实测:`mark_investability_bond` 后 `investability_warn=True`。
- akshare 拉取失败时优雅降级(空列),`run_monthly_bond` 仍能跑完(只是预警数=0)。
- 新增/扩展 `test_data_akshare.py` 或在 `test_bond_tracks.py` 加一条:给定含"暂停申购"的合成 meta,merge 后 warn 命中。

## 交付
- 本地 commit `[codex] feat(v0.4): build_meta_table 接申赎状态 -> 可投性预警生产生效`(不 push),回写"✅ 已完成"。
- 回报里附:000212/000134 实测的 subscribe_status/redeem_status 原始值,供主线核对关键词覆盖。

## 边界
- ✅ 只动 data_akshare.py(取数)+ 测试;整表拉取
- ❌ 不改 scoring/screening_bond/run_monthly_bond(主线已就绪,列对齐即可);不 push;不逐只调接口

✅ 已完成 2026-06-17

Codex 回写:
- `fund_purchase_em` 实测 26752 行, 已标准化为 `fund_code/subscribe_status/redeem_status/next_open_date` 并接入 `build_meta_table`。
- 000212: `subscribe_status=暂停申购`, `redeem_status=暂停赎回`, `next_open_date=2026-08-12`, `investability_warn=True`。
- 000134: `subscribe_status=暂停申购`, `redeem_status=开放赎回`, `investability_warn=True`。
- 已验证取数失败时补空列并不中断主流程。
