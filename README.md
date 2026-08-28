# QuatomPitch

**把一只美股的公开资料，压成一份能直接喂给大模型的 Markdown。**

输入股票代码，自动从 SEC EDGAR 与行情源采集数据，产出一份 5～15 万 token 的
结构化研究报告。报告里带 10-K/10-Q/8-K 的**正文原文**（大模型打不开链接）、
三大报表的**申报原文**、分部收入、内部人交易明细，以及每个数字的来源与口径标注。

```bash
qp AAPL
# -> reports/AAPL_2026-08-28.md
```

## 这个工具做什么、不做什么

**做**：把数据采全、采准，并把每个数字的来源、口径、可信度标清楚。

**不做**：估值判断、选股筛选、打分排序、买卖建议。那是你拿着这份 MD 去和大模型
对话时该做的事。报告里的 P/E、ROE 等指标只作为**数据**呈现，不参与任何筛选。

## 报告里有什么

| 章节 | 内容 |
|------|------|
| 关键数据速览 | 最新财年/财季核心科目 + 同比、利润率、行情估值。**是索引不是结论** |
| 读前须知 | 写给消费这份文件的模型：数据源优先级、口径陷阱、`—` 的含义 |
| 三大报表原文 | 报送里 SEC 渲染的 as-filed 报表，**含公司自定义扩展标签的行** |
| SEC XBRL | 归一化财务数据，6 年年度 + 10 季度，可溯源到 accession |
| 数据自洽性校验 | 会计恒等式当场核对，让科目映射错误自己暴露 |
| 分部 · 分产品 · 分地区收入 | 从报表附注抽取（XBRL 接口拿不到带维度的数据） |
| 内部人交易 | Form 4 明细，普通股与衍生品分表 |
| 报送正文摘录 | 业务概述、风险因素、MD&A、8-K 事件与 EX-99 业绩新闻稿 |
| 市场舆情 | 标题 + 摘要 |

## 设计上的几个取舍

**数据源有优先级，冲突时以报送原文为准。**
`三大报表原文（as-filed）` → `XBRL companyfacts（归一化）` → `yfinance（第三方）`。
前者用公司自己的行标签、科目一行不少；后者可跨公司比较但只覆盖 us-gaap 标准标签。
靠往标签候选表里不断加名字去补缺口是打地鼠——us-gaap 有 500 多个概念，
各家挑哪个是它自己的事。

**空结果只能表示「数据确实不存在」。**
取数故障必须留痕，绝不静默返回空列表。否则「抓取失败」会伪装成「公司没披露」——
本项目的内部人交易曾长期显示为 0，就是因为取回的是 HTML 不是 XML，
解析异常被就地吞掉。

**错数比缺数危险。**
缺一格是 `—`，一眼可见；取错标签却会输出一个量级合理的数字，谁都看不出来。
所以报告里当场核会计恒等式（毛利=营收−成本、总资产=负债+权益、营业利润残差），
对不上就如实报差额。实测中残差往往精确等于某个未归类的一次性科目。

**派生值必须写明公式。**
自由现金流、ROE、EV/EBITDA 这些是本工具自算的，各家口径不同。
列名带公式、估值表带「口径」列，让下游模型知道分子分母来自哪个时间窗口。
宁可标注不确定，也不给一个看起来权威的错数。

## 安装

需要 Python 3.10+。

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# macOS/Linux: .venv/bin/pip install -r requirements.txt

cp .env.example .env     # Windows: copy .env.example .env
```

编辑 `.env` 填 `SEC_USER_AGENT`（SEC 强制要求，格式 `应用名 你的邮箱`，不填会被拒绝）。
`FRED_API_KEY` 可选，留空则跳过宏观模块。

## 使用

Windows 下用根目录的 `qp.bat`，直接调 `.venv` 里的 python，不需要激活虚拟环境：

```powershell
.\qp AAPL                # 生成报告
.\qp AAPL --refresh      # 忽略缓存强制重下（SEC 偶发 503 时用）
.\qp AAPL --open         # 生成并打印全文
.\qp reports -t AAPL     # 历史报告记录
.\qp cache               # 查看缓存占用；--clear 清空
.\qp test                # 跑测试
```

其它平台直接调模块：

```bash
python -m quatompitch.cli analyze AAPL
```

## 结构

```
quatompitch/
├── cli.py              命令行入口（analyze / reports / cache）
├── pipeline.py         并发采集 → 计算 → 校验 → 存储 → 生成
├── datasources/
│   ├── sec_edgar.py      CIK 映射、报送索引、Form 4（SecClient 全局限速在此）
│   ├── sec_xbrl.py       XBRL companyfacts
│   ├── sec_docs.py       报送正文、三大报表原文、分部收入表
│   ├── cache.py          响应磁盘缓存（/Archives/ 永久，其余按 TTL）
│   ├── issues.py         局部失败留痕
│   ├── yfinance_source.py / yahoo_news.py / fred_source.py
├── analysis/
│   ├── valuation.py      估值指标（带口径标注）
│   ├── consistency.py    会计恒等式校验
│   └── overview.py       关键数据速览
├── models/             pydantic 领域模型
├── storage/            SQLite + SQLAlchemy
└── report/             Jinja2 模板与渲染
```

详见 [docs/architecture.md](docs/architecture.md)，开发约定见 [CLAUDE.md](CLAUDE.md)。

## 测试

36 个测试，全部离线。解析层的 fixture 是**真实 SEC 响应**（`tests/fixtures/`）——
手写示例只能验证「我以为 SEC 返回什么」，验证不了它实际返回什么。

```bash
.\qp test
```

## 扩展数据源

实现 `datasources/base.py` 的 `DataSource.fetch(ticker) -> dict`，
在 `pipeline.py` 的 `sources` 字典注册即可，不改其它模块。
新增 SEC 数据源必须复用 `SecClient`——限速是进程级共享的，自己发请求会超限被封。

## 免责声明

本工具仅供研究参考，**不构成投资建议**。数据可能存在延迟或口径差异，请以官方披露为准。
报告中的估值指标为机械计算结果，未经人工复核。
