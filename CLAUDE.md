# CLAUDE.md — QuatomPitch 项目上下文

> 本文件供 Claude Code / Cowork 在任何电脑上快速理解本项目。改动项目约定时请同步更新本文件。

## 这是什么

QuatomPitch 是一套**美股辅助交易系统**。命令行输入股票代码，自动采集数据并生成**结构化 Markdown 研究报告**，报告可直接喂给 AI 大模型做对话式深度分析，辅助投资决策。

## 项目范围（重要，不要越界）

- 系统**只负责两件事**：① 采集详细准确的财务数据；② 采集重大信息（高管增持/减持等）。最终产出 MD 文件。
- **不做低估值筛选、不做候选打分、不做买卖建议**。这是明确决定，不要自作主张加回来。
- 估值指标（P/E、ROE、EV/EBITDA 等）**仅作为数据**呈现在报告里，不参与任何筛选判断。

## 快速开始

日常一律用根目录的 `qp.bat`。它直接调 `.venv` 里的 python，**不需要激活虚拟环境**：

```powershell
.\qp AAPL                # 生成报告 -> reports\AAPL_<日期>.md
.\qp AAPL --open         # 生成并在终端打印全文
.\qp reports -t AAPL     # 查看历史报告记录
.\qp test                # 跑单元测试
```

裸股票代码会自动补 `analyze`；`analyze` / `reports` 也可显式写。

> **不要去激活虚拟环境。** 本机 PowerShell 执行策略是 `Restricted`，
> `.venv\Scripts\activate`（.ps1）会被拒绝执行 —— 这正是 `qp.bat` 存在的原因。
> 要手工调用就写全路径：`.\.venv\Scripts\python.exe -m quatompitch.cli analyze AAPL`

### 换台机器从零搭环境

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt   # 测试用
copy .env.example .env    # 然后填 SEC_USER_AGENT
```

### 环境变量（.env）

| 变量 | 是否必填 | 说明 |
|------|----------|------|
| `SEC_USER_AGENT` | **必填** | SEC 强制要求，格式 `应用名 邮箱`。不填 SEC 返回 403。 |
| `FRED_API_KEY` | 可选 | 留空则自动跳过宏观模块，不影响主报告。免费注册：fred.stlouisfed.org |
| `QUATOMPITCH_DB_PATH` | 可选 | 默认 `data/quatompitch.db` |
| `QUATOMPITCH_REPORT_DIR` | 可选 | 默认 `reports` |

## 架构

```
quatompitch/
├── cli.py              typer 命令行入口（analyze / reports）
├── pipeline.py         核心编排：并发采集 → 计算 → 存储 → 生成报告
├── config.py           pydantic-settings 读 .env
├── datasources/        数据源适配器，统一 DataSource 接口
│   ├── base.py             抽象基类 DataSource.fetch(ticker) -> dict
│   ├── yfinance_source.py  行情、公司信息、三大报表
│   ├── sec_edgar.py        CIK 映射、10-K/10-Q/8-K 索引、Form 4 内部人交易
│   │                       （SecClient 在此定义：User-Agent + 全局限速）
│   ├── sec_xbrl.py         XBRL companyfacts：官方结构化财务，可溯源到报送
│   ├── sec_docs.py         报送正文抽取（业务/风险/MD&A/8-K+EX-99）与分部收入表
│   ├── fred_source.py      宏观指标（可选）
│   └── yahoo_news.py       舆情，yfinance.news + RSS 兜底
├── models/             pydantic 领域模型（Company/Quote/FinancialPeriod/InsiderTrade/…）
├── analysis/
│   └── valuation.py    估值指标计算（优先财报自算，缺失回退 yfinance 现成值）
├── storage/            SQLite + SQLAlchemy（schema / db / repository）
└── report/
    ├── generator.py    Jinja2 渲染 + 数值格式化 filter（money/num/pct/shares）
    └── templates/report.md.j2   报告模板
```

详细设计见 `docs/architecture.md`。

## 关键设计约定

1. **三层解耦**：数据源 / 指标计算 / 报告模板互不依赖。新增数据源只需实现 `DataSource.fetch()` 并在 `pipeline.py` 的 `sources` 字典注册，不改其它模块。
2. **单源失败不影响整体**：`pipeline.analyze()` 用线程池并发采集，任一数据源抛异常都被捕获、记入 `report.warnings`，报告照常生成。修改时保持这个容错性。
3. **SEC 限速与 User-Agent**：`SecClient` 内置节流（默认 8 req/s，SEC 上限约 10）和 User-Agent 头。**不要绕过**，否则会被 SEC 封。限速状态是**模块级全局**（`_RATE_LOCK` + `_LAST_REQUEST_AT`），因为 pipeline 会并发跑 sec / xbrl / docs 三个 SEC 数据源——若各自计时会叠加到 24 req/s 直接超限。新增 SEC 数据源必须复用 `SecClient`，不要自己发请求。
4. **估值指标回退策略**：`compute_valuation()` 优先用财报自算（ROE、EV/EBITDA、P/S、P/B），拿不到则回退 yfinance 的现成字段。
5. **数据库 UPSERT**：`repository.py` 用 SQLite `ON CONFLICT DO UPDATE`，重复分析同一股票不会产生脏数据。
6. **报告模板里的空值**：所有 Jinja2 filter 对 `None` 都渲染成 `—`，不要让模板抛异常。
7. **MD 是给大模型吃的，不是给人读的**：用户拿到 MD 直接投喂大模型做对话式分析。所以宁可长、不可缺——报送正文要带原文（大模型打不开链接），表格每行要能独立读懂（分组名拍进行标签，而不是单独占一行）。报告体量目前 50K～145K token 属正常。
   报告开头的**「读前须知」是这份文件的交接契约**：数据源优先级、`—` 的含义、
   哪些是自算派生值、时间窗口陷阱、两张内部人交易表不能相加、以及本文件不包含什么。
   口径说明散在各节引言里模型未必按顺序读，所以统一在此声明一遍。**新增会引起误读的
   口径时，除了改对应章节，也要同步更新这一节。** 它只占全文约 0.4%，很便宜。
8. **章节号自增**：模板顶部用 `CN` + `namespace(i=0)` 计数，加一节不必手工重编号（宏观模块是可选章节，硬编号必错）。
9. **财务数据的来源优先级**（报告章节顺序即按此排）：
   **① 三大报表原文（R 文件 as-filed）** → ② XBRL companyfacts（归一化） → ③ yfinance（第三方交叉验证）。
   R 文件是 SEC 按报送渲染的报表，用公司自己的行标签，**包含自定义扩展标签的行**；
   companyfacts 只暴露 us-gaap 标准标签，DUOL 的「资本化软件支出」这类在那里根本取不到。
   所以缺科目时先想「R 文件里有没有」，而不是继续往 `CONCEPTS` 里加候选标签——
   那是打地鼠，us-gaap 有 500 多个概念，各家挑哪个是它自己的事。
   定位主报表用 `FilingSummary.xml` 的 `MenuCategory == "Statements"`，不要靠名称正则猜。
10. **自洽性校验是防错数的网**（`analysis/consistency.py`）：会计恒等式是确定性的，
   报告里当场核一遍（毛利=营收−成本、净利=税前−所得税、总资产=负债+权益、营业利润残差）。
   **错数比缺数危险**——缺一格是「—」一眼可见，取错标签却会输出量级合理的数字。
   Adobe 漏采 64.9 亿销售营销费那次就是这样，靠残差才能发现。
   实测：营业利润残差恰好等于未归类费用之和（SHOP 2023 的 14.9 亿 = 物流减值 13.4 亿 + 交易损失 1.52 亿）。
   加新科目字段时记得同步更新 `_opex_sum()`，否则残差会假报警。
11. **派生指标必须写明公式与口径**：原始申报科目可以说「以 SEC 为准」，自算的派生值（自由现金流、ROE、EV/EBITDA…）不行——各家口径不同，且公司自定义 XBRL 标签 companyfacts 取不到。列名带公式、估值表带「口径」列，都是为了让下游模型知道分子分母来自哪个时间窗口。**宁可标注不确定，也不要给一个看起来权威的错数。**
12. **表格单元格不能含竖线**：SEC 会把 XBRL 多维成员渲染成 `Level 1 | Cash Equivalents`，竖线是 Markdown 列分隔符，原样输出会当场撑破整张表、后面所有行错位。数据层 `_clean_cell()` 换成 `·`，渲染层 `cell` filter 再兜底转义。

## 当前状态与已知问题

- **已用真实数据端到端验证**（2026-08-26，AAPL / MSFT / NVDA 三只均跑通）。当时修掉三个只在真实数据下才暴露的缺陷（commit f1cd59f）：
  - **SEC Form 4 内部人交易恒为 0**：`primaryDocument` 带 XSLT 渲染前缀（如 `xslF345X06/form4.xml`），该地址返回的是 HTML 不是 XML，`ET.fromstring` 必然失败，又被 `except ParseError` 静默吞掉。已剥掉前缀取原始 XML。
  - **stdout 被管道/重定向时整个流程中断**：中文 Windows 是 GBK 代码页，进度输出里的 `✓` 抛 UnicodeEncodeError，崩溃点在采集途中，报告根本写不出来。已在 CLI 启动时把 stdout/stderr 切到 UTF-8。
  - **新闻 10 条挤成 1 行**：`trim_blocks=True` 会吃掉块标签后的换行，而新闻那行以 `{% endif %}` 结尾。已改用 `{% endif +%}`。
- 运行环境：Python 3.12.10 + `.venv`。实测 pandas 3.0.5 / yfinance 1.6.0 / numpy 2.5.2 下 yfinance 字段映射正常，`_row()` 候选行名无需改动。
- 2026-08-26 补齐了「大模型原料」缺口：此前报告只有 5K token，10-K/10-Q 只给链接不给正文、无分部收入、季度财报只有 4 个字段。现已加 `sec_xbrl.py`（官方 XBRL 财务，6 年年度 + 10 季度全字段）、`sec_docs.py`（报送正文 + 分部/分产品/分地区收入表），并展开季度表、渲染新闻摘要。AAPL/MSFT/NVDA 实测 43K～94K token。
- `pytest` 在 `requirements-dev.txt` 里，需单独装（`qp test` 会用到）。
- 报送正文单章节默认截断在 40,000 字符（`sec_section_max_chars`，设 0 则不截断）。风险因素动辄十几万字，不截会把报告撑爆。
- 已知数据口径问题（暂未处理，非 bug）：
  - 年度财报最老一期常常整行为空 —— yfinance 一般只给 4 个完整财年，模板按约定渲染成 `—`。
  - 内部人「增持」汇总金额常显示 `$0.00` —— 增持多为 M 代码（期权行权），本身不带成交价。
- FRED 未配置 key，宏观模块默认跳过。

## 开发分工

- **Claude Code（本机）**：用真实数据跑通、调数据源接口 bug、日常迭代。数据源接口格式多变，必须用真实响应调试。
- **Cowork（云端）**：搭框架、加新数据源、重构、写文档、规划。云端出口白名单挡住了 sec.gov 和 Yahoo Finance，**无法在云端跑真实采集**，只能用合成数据验证逻辑。

## 后续路线图

- 用真实数据跑通并修复字段映射问题
- 扩展数据源：finnhub、Alpha Vantage（预留适配器位）
- 补充 SEC XBRL 财务数据（直接从 companyfacts 取，交叉验证 yfinance）
- 完善缓存策略（同一交易日重复分析直接读 SQLite）
- 补充测试覆盖（数据源解析层）
