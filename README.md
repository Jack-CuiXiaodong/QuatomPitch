# QuatomPitch

QuatomPitch turns a US stock ticker into a single, structured Markdown report — pulled
live from SEC EDGAR and market data sources — designed to be handed straight to an LLM
for deep, conversational analysis. This project is for **educational and research**
purposes.

```bash
qp AAPL
# -> reports/AAPL_2026-08-28.md  (50K-150K tokens of primary-source data)
```

Note: the tool does not screen stocks, score candidates, or produce buy/sell
recommendations. It collects and structures data — the analysis happens in your
conversation with the LLM afterward.

## Disclaimer

This project is for **educational and research purposes only**.

- Not intended for real trading or investment
- No investment advice or guarantees provided
- Valuation metrics (P/E, ROE, EV/EBITDA, etc.) are presented as data only — never
  used for screening or ranking
- Creator assumes no liability for financial losses
- Consult a financial advisor for investment decisions
- Data may be delayed or diverge from official filings; always defer to the source

By using this software, you agree to use it solely for learning purposes.

## What's in a report

| Section | Content |
|---|---|
| Key metrics snapshot | Latest FY/FQ figures, YoY, margins — an index, not a conclusion |
| Reading notes | Source priority, what `—` means, timing pitfalls — written for the LLM that consumes the file |
| Primary financial statements | As-filed statements rendered by SEC, in the company's own line labels — including custom XBRL tags |
| SEC XBRL financials | Normalized data, 6 fiscal years + 10 quarters, traceable to each filing |
| Consistency checks | Accounting identities verified on the spot, so mapping errors surface themselves |
| Segment / product / geographic revenue | Pulled from filing footnotes |
| Insider trades | Form 4 detail, common stock and derivatives in separate tables |
| Filing text excerpts | Business, risk factors, MD&A, 8-K events + EX-99 press releases |
| Market news | Headlines with summaries |

## Design principles

**Source priority, and what wins when they disagree.**
`As-filed statements` → `SEC XBRL (normalized)` → `yfinance (third-party)`. The first
uses the company's own labels and never drops a line item — including ones filed under
custom XBRL extensions. Chasing every custom tag by hand is whack-a-mole; there are 500+
us-gaap concepts and each company picks its own.

**An empty result must mean "this data doesn't exist" — never "the fetch failed."**
A silently swallowed exception makes a real failure indistinguishable from a company
having no data. This project's insider-trade count sat at zero for a while because of
exactly that: the parser fetched a rendered HTML page instead of raw XML, the parse
error was caught, and an empty list looked identical to "no insider activity."

**A wrong number is worse than a missing one.**
A blank cell is visibly `—`; a mislabeled value looks like a perfectly reasonable
number. So the report cross-checks accounting identities on the spot (gross profit =
revenue − COGS, assets = liabilities + equity, an operating-income residual) and
reports the delta when they don't reconcile.

**Derived values carry their formula.**
Free cash flow, ROE, EV/EBITDA and friends are computed by this tool, not filed by the
company — conventions vary and custom XBRL tags aren't available via the standard API.
Column names and a "basis" column spell out exactly what was divided by what.

## Install

Requires Python 3.10+.

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# macOS/Linux: .venv/bin/pip install -r requirements.txt

cp .env.example .env     # Windows: copy .env.example .env
```

### Environment variables

Edit `.env`:

- `SEC_USER_AGENT` — **required**. SEC rejects unidentified traffic. Format:
  `"YourApp your-email@example.com"`.
- `FRED_API_KEY` — optional, free at [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html).
  Leave blank to skip the macro section.

## How to Run

On Windows, use `qp.bat` at the repo root — it calls the venv's Python directly, so you
never need to activate the virtualenv:

```bash
qp AAPL                # generate a report
qp AAPL --refresh      # bypass the cache and re-fetch
qp AAPL --open         # generate and print the full report
qp reports -t AAPL     # list past reports for a ticker
qp cache               # inspect the response cache; --clear to empty it
qp test                # run the test suite
```

On other platforms, call the module directly:

```bash
python -m quatompitch.cli analyze AAPL
```

## Development

```bash
git clone https://github.com/Jack-CuiXiaodong/QuatomPitch.git
cd QuatomPitch
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt
.venv/Scripts/python.exe -m pytest tests/ -q
```

36 tests, all offline. Parser tests replay **real SEC responses** stored in
`tests/fixtures/` — a hand-written sample only proves what you assumed SEC returns, not
what it actually does.

### Adding a data source

Implement `DataSource.fetch(ticker) -> dict` in `datasources/base.py` and register it in
`pipeline.py`'s `sources` dict — no other module changes needed. Any new SEC source must
reuse `SecClient`; it owns the process-wide rate limiter, and a second client bypassing
it will get the whole project rate-limited by SEC.

See [docs/architecture.md](docs/architecture.md) for the full design, and
[CLAUDE.md](CLAUDE.md) for the working conventions this codebase follows.

## How to Contribute

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

**Important**: please keep pull requests small and focused — it makes them much easier
to review and merge.

## Feature Requests

Open an [issue](https://github.com/Jack-CuiXiaodong/QuatomPitch/issues) tagged
`enhancement`.

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.
