# 基金评估项目(FundEvaluation)

公募基金定量评价体系,**主动权益 + 固收**双线。流程:同类分类 → 负面初筛 → **五维评分**(A收益 / B风控 / C来源 / D经理 / E运作)→ 工具型跟踪误差 → 可投性过滤 → L3 深研 → 滚动复盘。
核心原则:**过去≠未来**,评分服务于未来选择,证据不足不硬调权(见 `research/基金评估-核心原则_过去与未来.md`)。

> 统领文档:`07_路线图v1.0.md` · 评估框架:`01_评估框架v0.1.md` · 协作约定:`COLLABORATION.md`
> 协作分工:主线(Claude)写自包含任务包 → 本机(Codex)用 akshare 取数实现 → Jayden 统一 commit/push。

## Python 环境

- **Python 3.13.2** —— 实际安装 `C:\Python313`;兼容路径 `D:\python` → `C:\Python313`(迁移后旧 venv 仍可用)。
- 项目虚拟环境:`scripts\.venv`(关键依赖:akshare、pandas、numpy、scipy、openpyxl)。
- 数据源:**akshare**(本机:东财/新浪/中债官网/中证官网)+ **会话内 MCP**(且慢 qieman / iFinD / Gangtise,仅 Claude 会话内可用,独立脚本调不了 → C 维等数据先用 MCP 拉好存 `scripts/data/*.csv` 再被脚本读取)。

### 恢复环境

```powershell
cd D:\03_AI_Projects_and_Vault\Fund_Evaluation\scripts
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r ..\requirements-lock.txt
```

### 常用命令(均用项目 venv 的 python)

```powershell
cd D:\03_AI_Projects_and_Vault\Fund_Evaluation\scripts
.\.venv\Scripts\python.exe run_monthly.py          # 主动权益月度跑批
.\.venv\Scripts\python.exe run_monthly_bond.py     # 债基月度跑批(4-Track + 工具型)
.\.venv\Scripts\python.exe run_backtest.py --limit 800   # 回测校准(组内口径)
.\.venv\Scripts\python.exe test_engine.py          # 评分引擎测试
```
PowerShell 不支持 `&&`,多条命令用 `;` 分隔或分行。控制台报 GBK 编码问题时,测试已全部改用 ASCII 状态符,无需 `PYTHONIOENCODING`。

## 入库 / 不入库(见 `.gitignore`)

- **入库**:源代码 + 测试、`requirements-lock.txt`、`.env.example`、研究文档(`research/`、各 `*_交接/子任务_*.md`)、路线图、`scripts/data/*.csv`(C维/映射等可复用数据)。
- **不入库**:`.venv` / `.env` / API Key·Token / `__pycache__` / `scripts/cache` / `scripts/output` / `*.parquet` / 大型临时数据。

## 环境备份(换机/升级前在本机执行)

```powershell
cd D:\03_AI_Projects_and_Vault\Fund_Evaluation
.\scripts\.venv\Scripts\python.exe -m pip freeze > requirements-lock.txt
.\scripts\.venv\Scripts\python.exe --version > python-version.txt
git status -sb
```
