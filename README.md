# QuatomPitch

美股辅助交易系统 —— 命令行输入股票代码，自动采集财务数据与重大信息（高管增减持、SEC 报送等），生成结构化 Markdown 研究报告，可直接输入 AI 大模型做对话式深度分析。

## 特性

- **一条命令出报告**：`quatompitch analyze AAPL`，约 30 秒完成采集 + 生成。
- **多源免费数据**：
  - **SEC EDGAR** — 10-K/10-Q/8-K 报送、Form 4 内部人交易（高管增持/减持）
  - **yfinance** — 实时行情、市值、三大报表
  - **FRED** — 宏观指标（可选，需免费 key）
  - **Yahoo Finance News** — 市场舆情
- **财务数据 + 估值指标**：P/E、ROE、EV/EBITDA、P/B、P/S、PEG、利润率等（作为数据呈现，不做筛选打分）。
- **本地 SQLite 存储**：自动缓存与历史回溯。
- **AI 友好输出**：结构化 Markdown，喂给大模型即可深度分析。

## 安装

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # Windows: copy .env.example .env
```

编辑 `.env`，**务必**填写 `SEC_USER_AGENT`（SEC 强制要求，格式：`应用名 你的邮箱`）。
`FRED_API_KEY` 可选，留空则跳过宏观模块。

## 使用

```bash
# 分析单只股票，生成 reports/AAPL_YYYY-MM-DD.md
python -m quatompitch.cli analyze AAPL

# 生成并把报告全文打印到终端
python -m quatompitch.cli analyze AAPL --open

# 查看历史报告
python -m quatompitch.cli reports --ticker AAPL

# 若已 pip install -e .，可直接用命令
quatompitch analyze AAPL
```

## 项目结构

```
quatompitch/
├── cli.py              命令行入口
├── pipeline.py         采集→计算→存储→报告 编排
├── config.py           配置（.env）
├── datasources/        数据源适配器（yfinance / SEC / FRED / news）
├── models/             领域模型
├── analysis/           估值指标计算
├── storage/            SQLite 存储层
└── report/             Markdown 报告模板与生成
```

详见 `docs/architecture.md`。

## 扩展新数据源

实现 `datasources/base.py` 的 `DataSource.fetch(ticker) -> dict`，在 `pipeline.py` 的 `sources` 中注册即可，无需改动其它模块。可据此接入 finnhub、Alpha Vantage 等。

## 免责声明

本工具仅供研究参考，不构成投资建议。数据可能存在延迟或口径差异，请以官方披露为准。
