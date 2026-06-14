# 子任务:campisi 净值五因子的中债指数取数层(给本机 Codex)

> 协作约定见文末。**隔离原则**:只新建 `scripts/data_bond.py` 一个文件 + 可选缓存 CSV,**不修改任何现有 .py**。

## 背景

v0.4 固收线核心算法 `scripts/campisi.py` 已就绪(净值五因子回归,已测试通过)。它需要一个**取数层**提供 5 个因子所需的中债系列指数的**周收益序列**。本任务就是实现这个取数层。

`campisi.py` 的 `build_factors(index_weekly_ret)` 期望输入一个 dict:`{指数名: 周收益序列(pd.Series, index=DatetimeIndex)}`,需要的指数名(键必须精确匹配):

```
中债国债总财富
中债中短期
中债长期
中债企业债AAA
中债国开债
中债高收益企业债
中债转债
```

## 你的任务

新建 `scripts/data_bond.py`,实现:

1. **逐个调研 AKShare 接口**找到上述 7 个中债指数的日行情。候选接口(自己验证哪个对、字段名是什么):
   - `ak.bond_new_composite_index_cbond(indicator=..., period=...)`
   - `ak.bond_composite_index_cbond(...)`
   - `ak.bond_china_yield(...)`(收益率曲线,可能需要换算)
   - 中债官网指数在 AKShare 里的其他入口——**以你实测能跑通的为准**
   - 若某指数 AKShare 无直接源,记录在文件注释里标 TODO,**不要硬凑**

2. 实现函数:
   ```python
   def bond_index_weekly_returns() -> dict:
       """返回 {指数名: 周收益序列}, 键用上面7个精确名称。
       缺失的指数跳过(campisi.build_factors 会自动少构造对应因子)。"""
   ```
   - 日行情 → 周收益:`nav.resample("W-FRI").last().pct_change().dropna()`(与 campisi.nav_to_weekly 一致)
   - parquet 缓存(参考 data_akshare.py 的 cached() 模式,max_age_days=7)

3. **写一个自测 `if __name__ == "__main__":`**,打印每个指数取到的起止日期、行数,以及 campisi.build_factors 能构造出几个因子。

4. **端到端验证**:用某只真实纯债基金(如 `000032 易方达信用债` 或你选)的净值,跑通 `campisi.campisi_regress`,打印 R²、alpha、betas。预期纯债 R²>0.6。把验证输出贴在 commit message 或单独的 `scripts/data/bond_index_verify.txt`。

## 验收标准

- `scripts/data_bond.py` 能独立运行,`bond_index_weekly_returns()` 至少返回 4 个可用指数(level/credit 必须有,即国债总财富 + 企业债AAA + 国开债)
- 端到端:某纯债基金跑 campisi 得到合理 R²(>0.6)和 alpha
- 不修改任何现有 .py 文件
- 注释里写清每个指数用的确切 AKShare 接口名 + 字段名,缺失的标 TODO

## 提交方式(协作约定)

```bash
git pull --rebase                          # 先拉, 避免和主线撞车
git add scripts/data_bond.py scripts/data/bond_index_verify.txt
git commit -m "[codex] feat: campisi中债指数取数层 data_bond.py"
git push
```

- commit message **必须带 `[codex]` 前缀**
- **只提交你新建的文件**,不要 `git add .`(避免误带主线改动)
- push 前务必 `git pull --rebase`
- 完成后在本文件末尾追加一行:`✅ 已完成 YYYY-MM-DD,可用指数 N 个,纯债验证 R²=X.XX`

## 环境

- 工作目录:`D:\03_AI_Projects_and_Vault\Fund_Evaluation`
- venv 在 `scripts\.venv`,已装 akshare/pandas/pyarrow
- 网络:akshare 直连(若超时,中债指数可能需代理或换接口,记录在注释)

## 边界(重要)

- ❌ 不改 campisi.py / scoring.py / run_monthly.py / data_akshare.py 等任何现有文件
- ❌ 不 `git add .`,只加你的新文件
- ✅ 只新建 data_bond.py + 可选 verify.txt
- 有疑问或接口都不通时,把你试过的接口和报错写进 data_bond.py 注释,提交后让主线 agent 接力,不要卡住

✅ 已完成 2026-06-14,可用指数 6 个,纯债验证 R²=0.61
