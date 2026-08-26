# QuatomPitch 架构设计文档

> 美股辅助交易系统 · 重建版架构设计
> 版本 v1.0 · 2026-08-26

---

## 1. 设计目标

- **单命令闭环**：命令行输入股票代码，30 秒内完成「采集 → 计算 → 存储 → 生成报告」。
- **多源免费数据**：SEC EDGAR、yfinance、FRED、Yahoo Finance News，全部免费接口，预留 finnhub / Alpha Vantage 扩展位。
- **AI 友好输出**：结构化 Markdown 报告，可直接喂给大模型做对话式深度分析。
- **可扩展、可维护**：数据源、指标、报告模板三者解耦，新增一个数据源或一个估值指标不影响其它模块。
- **本地存储**：SQLite 单文件数据库，零配置、便于缓存与历史回溯。

---

## 2. 技术选型

| 层次 | 选型 | 理由 |
|------|------|------|
| 语言 | Python 3.11 | 与原系统一致，金融库生态完善 |
| CLI 框架 | `typer` + `rich` | 命令声明式、终端输出美观（表格/进度条） |
| HTTP | `httpx`（同步+异步） | SEC / FRED / RSS 并发采集提速 |
| 数据处理 | `pandas` | 财报表格、时间序列处理 |
| 数据库 | SQLite + `SQLAlchemy` ORM | 本地单文件、表结构清晰、便于扩展迁移 |
| 行情/财报 | `yfinance` | 免 key，实时价、市值、三大报表 |
| SEC | 直连 EDGAR REST + XBRL API | 免 key，10-K / XBRL facts / Form 4 |
| 宏观 | `fredapi` | 免费 key，宏观指标序列 |
| 舆情 | `yfinance.news` + `feedparser`(RSS 兜底) | 免 key，市场新闻 |
| 模板 | `Jinja2` | Markdown 报告模板化 |
| 配置 | `pydantic-settings` + `.env` | API key / User-Agent 集中管理 |
| 测试 | `pytest` | 指标计算单元测试 |

---

## 3. 目录结构

```
QuatomPitch/
├── README.md
├── pyproject.toml            # 依赖与打包元数据
├── requirements.txt          # 依赖清单（pip 安装）
├── .env.example              # 环境变量样例（FRED_API_KEY / SEC_USER_AGENT）
├── .gitignore                # 忽略 data/、reports/、.env、__pycache__
├── quatompitch/
│   ├── __init__.py
│   ├── cli.py                # 命令行入口（typer）
│   ├── pipeline.py           # 核心编排：采集→计算→存储→报告
│   ├── config.py             # pydantic-settings 读取环境变量
│   ├── datasources/          # 数据源适配器（每个源一个文件）
│   │   ├── base.py           #   抽象基类 DataSource（统一接口）
│   │   ├── yfinance_source.py
│   │   ├── sec_edgar.py      #   公司事实库 / 10-K / XBRL / Form 4
│   │   ├── fred_source.py
│   │   └── yahoo_news.py
│   ├── models/               # 领域模型（pydantic dataclass）
│   │   ├── company.py        #   公司基本信息
│   │   ├── financials.py     #   财务快照
│   │   ├── insider.py        #   内部人交易
│   │   └── report.py         #   报告聚合对象
│   ├── analysis/             # 指标计算与筛选
│   │   ├── valuation.py      #   P/E、ROE、EV/EBITDA、P/B、P/S、PEG
│   │   ├── screening.py      #   低估值筛选规则引擎
│   │   └── insider.py        #   高管增持信号分析
│   ├── storage/              # 数据库层
│   │   ├── db.py             #   engine / session / 建表
│   │   ├── schema.py         #   SQLAlchemy 表模型
│   │   └── repository.py     #   读写封装 + 当日缓存判断
│   └── report/
│       ├── generator.py      #   聚合数据 → 渲染 Markdown
│       └── templates/
│           └── report.md.j2
├── data/                     # SQLite 数据库文件（git 忽略）
│   └── quatompitch.db
├── reports/                  # 生成的 Markdown 报告（git 忽略）
├── tests/
│   ├── test_valuation.py
│   ├── test_screening.py
│   └── test_datasources.py
└── docs/
    └── architecture.md       # 本文档
```

---

## 4. 数据流

```
        ┌─────────────┐
用户 →  │  cli.py     │  quatompitch analyze AAPL
        └──────┬──────┘
               ↓
        ┌─────────────┐   ①查当日缓存（命中则跳过采集）
        │ pipeline.py │──────────────────────────────┐
        └──────┬──────┘                               │
               ↓ ②并发采集                            │
   ┌───────────┼───────────┬───────────┐              │
   ↓           ↓           ↓           ↓              │
yfinance    SEC EDGAR    FRED     Yahoo News          │
（价/财报） （10-K/XBRL  （宏观）  （舆情）            │
             /Form4）                                 │
   └───────────┴───────────┴───────────┘              │
               ↓ ③归一化为 models                     │
        ┌─────────────┐                               │
        │  storage    │ ←─────────────────────────────┘
        │ (SQLite 存储 + 缓存)
        └──────┬──────┘
               ↓ ④指标计算 + 筛选打标
        ┌─────────────┐
        │  analysis   │  估值指标 / 低估值标签 / 增持信号
        └──────┬──────┘
               ↓ ⑤渲染
        ┌─────────────┐
        │  report     │  Jinja2 → Markdown
        └──────┬──────┘
               ↓
     reports/AAPL_2026-08-26.md  +  终端摘要
```

**缓存策略**：同一 ticker 同一交易日重复分析时，行情/财报直接读 SQLite，不再打网络，保证 30 秒内出结果并降低接口压力。

---

## 5. 数据库表设计（SQLite）

| 表 | 关键字段 | 说明 |
|----|----------|------|
| `companies` | cik, ticker(PK), name, sector, industry, exchange, updated_at | 公司主表 |
| `prices` | id, ticker, date, open, high, low, close, volume, market_cap | 日行情 |
| `financials` | id, ticker, period_type(FY/FQ), fiscal_date, revenue, net_income, ebitda, gross_profit, total_equity, total_debt, cash, shares_out, eps, source | 财报快照 |
| `valuations` | id, ticker, as_of_date, pe, forward_pe, roe, ev_ebitda, pb, ps, peg, flags(JSON) | 估值指标计算结果 |
| `filings` | id, cik, ticker, form_type, filing_date, accession_no, url, summary | SEC 报送索引（10-K/10-Q/8-K） |
| `insider_trades` | id, ticker, insider_name, title, txn_date, txn_code(P/S), shares, price, value, filing_url | Form 4 内部人交易 |
| `macro_indicators` | id, series_id, date, value | FRED 宏观序列（如 DGS10、CPIAUCSL） |
| `news` | id, ticker, published_at, title, publisher, url, sentiment | 舆情新闻 |
| `reports` | id, ticker, generated_at, path, summary | 报告归档索引 |

主键统一自增 `id`，`ticker + date/fiscal_date` 建唯一索引防重复入库。

---

## 6. 核心估值指标（analysis/valuation.py）

| 指标 | 公式 | 数据来源 |
|------|------|----------|
| P/E（市盈率） | 股价 ÷ 每股收益(TTM) | yfinance |
| Forward P/E | 股价 ÷ 预期 EPS | yfinance |
| ROE | 净利润 ÷ 股东权益 | 财报 |
| EV/EBITDA | (市值 + 总负债 − 现金) ÷ EBITDA | 市值 + 财报 |
| P/B（市净率） | 股价 ÷ 每股净资产 | 财报 |
| P/S（市销率） | 市值 ÷ 营收 | 财报 |
| PEG | P/E ÷ 盈利增速 | 计算 |

**低估值筛选规则**（screening.py，阈值可配置化）：
- P/E 低于行业中位数或 < 15
- EV/EBITDA < 10
- ROE > 15%
- P/B < 3
- 近 90 天存在高管净增持 → 额外加分

规则以「规则表 + 权重打分」形式实现，输出候选标签写入 `valuations.flags`。

---

## 7. 数据源与接口说明

| 数据源 | 是否需 key | 获取内容 | 注意事项 |
|--------|-----------|----------|----------|
| yfinance | 否 | 实时价、市值、三大报表、基础新闻 | 非官方接口，需容错重试 |
| SEC EDGAR | 否 | 公司 facts(XBRL)、10-K、Form 4 | **必须带 User-Agent**（SEC 强制），限速 10 req/s |
| FRED | 免费 key | 宏观指标（利率、CPI 等） | 需注册 API key |
| Yahoo Finance News | 否 | 市场舆情 | 用 yfinance.news，RSS 兜底 |
| **finnhub**（扩展） | 免费 key | 更多基本面/内部人数据 | 预留适配器位 |
| **Alpha Vantage**（扩展） | 免费 key | 备用财报源 | 预留适配器位 |

所有数据源实现同一 `DataSource` 抽象接口（`fetch(ticker) -> dict`），新增源只需实现该接口并在 pipeline 注册。

---

## 8. 依赖清单（requirements.txt）

```
yfinance
httpx
pandas
sqlalchemy
fredapi
feedparser
jinja2
typer
rich
pydantic
pydantic-settings
python-dotenv
pytest          # 开发/测试
```

---

## 9. 命令行接口设计

```bash
# 分析单只股票，生成报告
quatompitch analyze AAPL

# 批量筛选低估值候选
quatompitch screen --tickers AAPL,MSFT,GOOGL --rule low-valuation

# 仅刷新某源缓存
quatompitch refresh AAPL --source sec

# 查看历史报告
quatompitch reports --ticker AAPL
```

---

## 10. 开发路线图（分阶段交付）

| 阶段 | 内容 | 产出 |
|------|------|------|
| **P0 脚手架** | 目录、`pyproject`、config、DB schema、git 初始化 | 可运行空壳 + 建库 |
| **P1 最小闭环** | yfinance 采集 → 估值计算 → Markdown 报告 | `analyze TICKER` 跑通 |
| **P2 SEC** | EDGAR 10-K / XBRL facts / filings 索引 | 财报数据入库 |
| **P3 宏观+舆情** | FRED 指标 + Yahoo News | 报告含宏观与新闻 |
| **P4 内部人** | Form 4 解析 + 高管增持信号 | 增持分析入报告 |
| **P5 筛选器** | 批量 screen 低估值候选 | `screen` 命令 |
| **P6 加固** | 单元测试、缓存优化、finnhub 扩展 | 稳定版 |

每个阶段独立可运行、可提交、可 push，方便你在电脑上用 Claude Code 接力迭代。

---

## 11. Cowork ↔ Claude Code 同步方式

1. 你在桌面 app **Add folder** 连接一个本地文件夹（如 `~/projects/QuatomPitch`）。
2. 我把代码写入该文件夹并 `git init` + 首次 commit。
3. 你在电脑上 `git remote add` 你的 GitHub 仓库并 `git push`（用你本地已登录的 git，我不接触你的 token）。
4. 新电脑/后续用 Claude Code 打开同一文件夹，通过 `git pull` / `git push` 与本处保持同步，共用一份 git 历史。

---

## 12. 待你确认的关键点

1. **项目文件夹名与路径**：默认 `QuatomPitch`，位置由你 Add folder 时决定。
2. **数据库**：SQLite 是否符合预期（原系统"本地数据库"），还是要换 PostgreSQL？
3. **CLI 框架**：`typer` 是否可接受，或坚持原来的 argparse。
4. **FRED API key**：宏观模块需要，你是否已有 key（没有可先跳过 P3 宏观）。
5. **路线图起点**：确认后我从 P0 脚手架开始写入你连接的文件夹。
```
