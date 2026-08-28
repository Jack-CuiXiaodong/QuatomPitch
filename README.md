# QuatomPitch

QuatomPitch turns a US stock ticker into a single, structured Markdown report —
pulled from SEC EDGAR and market data — meant to be handed straight to an LLM for
analysis. This project is for **educational and research** purposes.

```bash
qp AAPL
# -> reports/AAPL_<date>.md
```

The report includes as-filed financial statements, normalized SEC XBRL data, insider
trades (Form 4), segment revenue, and excerpts from the actual 10-K/10-Q/8-K text —
everything an LLM needs to reason about the company, in one file.

Note: the tool does not screen stocks, score candidates, or produce buy/sell
recommendations. It only collects and structures data.

## Disclaimer

This project is for **educational and research purposes only**.

- Not intended for real trading or investment
- No investment advice or guarantees provided
- Valuation metrics (P/E, ROE, EV/EBITDA, etc.) are shown as data only — never used
  for screening or ranking
- Creator assumes no liability for financial losses
- Consult a financial advisor for investment decisions

By using this software, you agree to use it solely for learning purposes.

## How to Install

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

On other platforms:

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

36 tests, all offline — the parser tests replay real SEC responses stored in
`tests/fixtures/`.

New data sources implement `DataSource.fetch(ticker) -> dict` in `datasources/base.py`
and register in `pipeline.py`'s `sources` dict. See
[docs/architecture.md](docs/architecture.md) and [CLAUDE.md](CLAUDE.md) for the full
design and working conventions.

## How to Contribute

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

**Important**: please keep pull requests small and focused.

## Feature Requests

Open an [issue](https://github.com/Jack-CuiXiaodong/QuatomPitch/issues) tagged
`enhancement`.

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.
