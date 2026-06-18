# 子任务 37:权益线补全(三)— C3 ReturnGap(半年频近似)(给本机 Codex)

> 遵循 COLLABORATION.md:只本地 commit 不 push;完成回写"✅ 已完成"。
> 本机有 akshare。这是权益补全最重的一波(全持仓 + 个股收益),**务必缓存 + 限期数 + 断点续跑**(参考 35/36 的 checkpoint 模式)。

## 背景与方法
`config.INDICATORS["C_attribution"]["return_gap"]`(C3,权重0.20,方向+1)槽位在,但无数据 → 生产降级。
**ReturnGap(Kacperczyk-Sialm-Zheng)**:衡量"两次持仓披露之间,基金的交易/未观测操作是否创造价值"。
- 定义:`ReturnGap = 基金实际收益 − 按上期披露全持仓"不动持有"到本期的假想收益`。
- 正值=两次披露间的调仓/打新/择时等净贡献为正;持续正的 ReturnGap 是"隐性能力"的证据(对应深研模板"隐性能力"项)。

## 关键降级口径(必须遵守,诚实优先)
- **全持仓只有半年报/年报有**;季报仅 top10,不足以算全口径 ReturnGap。→ **C3 按半年频计算**,用最近 2-4 个半年报/年报期。
- 季报 top10 **不要**拿来冒充全持仓算(覆盖度不够会系统性失真);若某期只有 top10,该期**跳过或单独标注**,不混入。
- 港股通/QDII/停牌/退市个股拿不到收益的 → 该持仓权重缺失,按"可得持仓重新归一"或该期降级,并记录缺口比例;缺口过大(如可得权重<70%)该期作废。
- 有效期数 < 2 → C3 标低置信/降级(同 C2 的 rbsa_r2 门槛思路,留审计值但 C2/C3 评分降级)。

## 你的任务
1. 取数:
   - 全持仓:`ak.fund_portfolio_hold_em(symbol=code, date=报告期)`,筛半年报/年报期,得个股代码+占净值权重。
   - 个股收益:akshare 股票日线;**全市场涉及个股去重后一次性/批量拉取并缓存**,切勿每基金每股重复调。
2. 算 ReturnGap(半年频):每个半年报期 t,持仓权重不动持有到下期披露(约6个月),假想收益 `Σ w_i·r_i`;实际收益用**复权净值**(任务35口径);`gap_t = 实际 − 假想`;多期取均值 → `return_gap`。同时产出 `return_gap_n_periods`(有效期数)、`holdings_coverage`(可得持仓权重占比)。
3. 接入:`return_gap` 写入 `data/cdim_data.csv`(注意:cdim 实际读 `scripts/data/cdim_data.csv`);`cdim.py` 派生 C3(槽位已有);有效期数<2 或覆盖过低则降级。**不改 scoring/config 权重。**
4. 新增 `build_returngap_cdim.py`(可断点续跑 + 检查点)+ 轻量测试。

## 验收
- `return_gap` 分布合理(多数在 ±5% 半年 量级内,极端值排查并说明);覆盖率报告(多少只拿到 ≥2 个有效半年报期)。
- 港股/QDII/停牌缺收益时优雅降级(重新归一或跳过该期),不中断主流程。
- C3 进入评分输入;低置信(期数<2/覆盖<70%)样本自动降级,不污染榜单。
- `run_monthly.py --limit 30` 跑通,报告 C3 有效覆盖与权重覆盖率。

## 交付
- 本地 commit `[codex] feat(v0.3): C3 ReturnGap(半年频近似)接入(权益补全三)`(不 push),回写"✅ 已完成"。
- 回报附:全持仓可得只数、C3 有效覆盖率、return_gap 分布(min/中位/max)、3-5 只抽样(实际vs假想vs gap)、缺口过大被作废的期数统计。

## 边界
- ✅ 新建 build_returngap_cdim.py + 取数(全持仓/个股收益,缓存)+ 接 cdim 的 C3 + 测试
- ❌ 不改 scoring.py/config 权重;不拿季报top10冒充全持仓;不逐股重复调;不 push;C3 标"半年频近似/低频"
- 参考:`cdim.py`(C/E维并入,读 scripts/data/cdim_data.csv)、`config.INDICATORS C3`、`data_akshare.fund_nav`(复权)、`build_style_cdim.py`(35/36 的 checkpoint/断点续跑范式)
- 方法论:Kacperczyk-Sialm-Zheng (2008) Return Gap;本项目"隐性能力"维度
