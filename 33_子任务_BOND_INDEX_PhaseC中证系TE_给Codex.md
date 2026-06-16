# 子任务 33:BOND_INDEX Phase C — 中证系标的接 akshare 解锁 TE(给本机 Codex)

> 遵循 COLLABORATION.md:只本地 commit 不 push;完成回写"✅ 已完成"。
> 承 31/31b:工具型卡 A 维(跟踪有效性)目前仅 1/756 有 TE,因 `data_akshare.index_returns` 只能取中债综合。本任务先解锁**中证系**3 族(代码可信、东财大概率可取),让同业存单/综合债/短融类工具型升 formal。

## 背景与边界
- 主线会话内已用 iFinD 核出 3 个**可信中证代码**(见 `data/index_code_phasec_csi.csv`):
  - 同业存单AAA `931059.CSI`、中证综合债 `H11009.CSI`、中证短融 `H11014.CSI`。
- ⚠️ **中债系(国开/政金/农发/国债各久期段,CBAxxxxx)本轮不做** —— iFinD NL 匹配实测不可靠(会返回错误指数),需官方中债指数代码字典核对,留作后续。**不要凭名称猜 CBA 代码。**

## 你的任务(本机 akshare)
1. **验证并扩展取数**:确认 `data_akshare.index_returns()` 能否按中证代码(`931059`/`H11009`/`H11014`,或东财格式如 `931059.CSI`)取日度收盘 → 日收益。
   - 若现有接口只支持中债/旧格式,扩展之(东财中证指数接口,如 `ak.index_zh_a_hist` / `stock_zh_index_daily_em` 之类,按代码取);失败则该族跳过并报告。
2. **回填 `index_map_bond.csv`**:对 BOND_INDEX universe 中名称/基准匹配"同业存单(AAA)/中证综合债/中证短融"的基金,填对应中证 `index_code` + `index_name` + `index_mainstream`(用 csi 参考表的值)。匹配不确定的**留空**(保持 provisional,勿乱填)。
3. **重算 TE 并 gate 校验**(复用 `build_index_navs` + `scoring_bond_index`):
   - **硬指标**:被动跟踪型 TE 应很低 —— 同业存单 **<≈0.5%**、综合债/短融 **<≈2%**。若某族 TE 仍偏高(>3%),说明代码或匹配错,**回查或留空**,不要让假 TE 进榜。
4. 跑通后报告:这 3 族各覆盖多少只、TE 分布(min/中位/max)、升 formal 的只数。

## 验收
- 至少同业存单AAA 一族成功:相关工具型基金拿到合理低 TE(<0.5%)、A 维生效、`score_label` 升 formal。
- 中证代码取不到时优雅降级(留空 provisional、不报错、不中断主流程)。
- 不动中债系、不猜 CBA 代码;不改 `scoring_bond_index.py` 评分逻辑。

## 交付
- 本地 commit `[codex] feat(v0.4): BOND_INDEX Phase C 中证系(同业存单/综合债/短融)接akshare解锁TE`(不 push),回写"✅ 已完成"。
- 回报附:3 族覆盖只数、TE 分布、akshare 取中证代码是否需扩展(及如何扩展)。

## 边界
- ✅ 验证/扩展 akshare 取中证指数 + 回填 index_map 中证系 + 重算TE + gate 校验
- ❌ 不碰中债系 CBA 代码(待官方字典);不猜代码;不改评分逻辑;不 push
- 参考:`data/index_code_phasec_csi.csv`、`build_index_navs.py`、`scoring_bond_index.py`、`data/index_map_bond_te_check.md`(31b 的 TE 自检范式)
