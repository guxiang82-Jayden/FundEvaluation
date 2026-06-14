# 子任务:修复个别基金净值 reindex 报错(给本机 Codex)

> **隔离原则**:本任务需改 `scripts/data_akshare.py` 的 **`fund_nav` 函数内部**(单点修复),以及可选新增一个排查脚本。**只动 fund_nav 这一个函数,不碰其他函数和其他文件。**
>
> ⚠️ 时序:主线 agent 也可能动 data_akshare.py 的其他部分。你提交前务必 `git pull --rebase`;若 fund_nav 处有冲突,以"保留重复日期去重逻辑 + 不破坏现有列名"为原则手动解决。

## 背景

全量跑批时,极少数基金(已知:`003984`、`009092`、`009126`、`001158`、`481013`)报错:
```
[warn] XXXXXX metrics failed: cannot reindex on an axis with duplicate labels
```
原因:东财净值接口 `ak.fund_open_fund_info_em(symbol=code, indicator="累计净值走势")` 对这些基金返回了**重复的净值日期**,导致后续 reindex/对齐失败。

`fund_nav` 当前已有一行去重(`s[~s.index.duplicated(keep="last")]`),但这几只仍报错——说明去重没覆盖到全部情况(可能是日期格式不一、或 NaN 索引、或排序问题)。

## 你的任务

### 1. 先复现+定位
写一个临时排查脚本(可放 `scripts/_debug_reindex.py`,排查完可删或保留),对这 5 个代码逐一:
```python
import akshare as ak
df = ak.fund_open_fund_info_em(symbol="003984", indicator="累计净值走势")
# 看: 是否有重复日期? 日期列类型? 是否有NaN? 重复的是完全相同还是同日不同值?
print(df.shape, df["净值日期"].duplicated().sum(), df["净值日期"].dtype)
print(df[df["净值日期"].duplicated(keep=False)])
```
搞清楚到底是什么导致去重没生效。

### 2. 修复 fund_nav
在 `scripts/data_akshare.py` 的 `fund_nav` 函数里加固(只改这个函数):
- 确保日期解析后**先排序再去重**
- 去除 NaN 索引/NaN 值
- 去重用 `keep="last"`(保留最新值)
- 加固后这 5 只都能正常返回净值序列,不再报 reindex 错

参考当前实现(大致):
```python
def fund_nav(fund_code):
    def fetch():
        df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="累计净值走势")
        if df.empty or "净值日期" not in df.columns:
            raise ValueError("无净值数据(新发/特殊基金)")
        df = df.rename(columns={"净值日期": "date", "累计净值": "nav"})
        df["date"] = pd.to_datetime(df["date"])
        return df[["date", "nav"]]
    df = cached(f"nav_{fund_code}", fetch, max_age_days=1)
    s = df.set_index("date")["nav"].astype(float).sort_index()
    return s[~s.index.duplicated(keep="last")]
```
你需要让它对 5 个问题基金都稳健(可能要在 fetch 里就 dropna+去重,或处理日期解析异常)。

### 3. 验证
- 5 个基金 `fund_nav("003984")` 等都能返回非空、无重复索引的 Series
- 跑一下 `python test_engine.py` 确认没破坏现有测试(应仍全过)
- 把验证输出贴在 commit message 或 `scripts/data/reindex_fix_verify.txt`

## 验收标准
- 5 个问题基金 fund_nav 不再报错,返回干净 Series(索引无重复、无 NaN、已排序)
- test_engine.py 仍全部通过
- 只改了 data_akshare.py 的 fund_nav 函数(+ 可选 debug 脚本)

## 提交方式
```bash
git pull --rebase
git add scripts/data_akshare.py scripts/data/reindex_fix_verify.txt   # 不加 debug 脚本可不提交它
git commit -m "[codex] fix: fund_nav 加固去重, 修复5只基金reindex报错"
git push
```
- commit 带 `[codex]` 前缀;push 前 `git pull --rebase`
- 完成后本文件末尾追加:`✅ 已完成 YYYY-MM-DD, 5只验证通过, test_engine全过`

## 边界
- ✅ 只改 data_akshare.py 的 fund_nav 函数
- ❌ 不动其他函数、不动其他 .py、不 `git add .`
- 缓存注意:这5只可能已有坏缓存,排查时先删 `scripts/cache/nav_003984.parquet` 等再测

✅ 已完成 2026-06-14, 5只验证通过, test_engine全过
