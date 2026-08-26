"""估值计算单元测试。"""
from quatompitch.models import FinancialPeriod, Quote
from quatompitch.analysis import compute_valuation


def test_roe_and_ev_ebitda_self_computed():
    quote = Quote(ticker="TEST", price=100.0, market_cap=1_000_000_000.0)
    annual = [
        FinancialPeriod(
            period_type="FY",
            fiscal_date="2024-12-31",
            revenue=500_000_000.0,
            ebitda=200_000_000.0,
            net_income=150_000_000.0,
            total_equity=750_000_000.0,
            total_debt=100_000_000.0,
            cash_and_equivalents=50_000_000.0,
            shares_outstanding=10_000_000.0,
        )
    ]
    v = compute_valuation("TEST", quote, annual, info_metrics={})

    # ROE = 150M / 750M = 20%
    assert round(v.roe, 2) == 20.0
    # EV = 1000M + 100M - 50M = 1050M；EV/EBITDA = 1050/200 = 5.25
    assert round(v.ev_ebitda, 2) == 5.25
    # P/S = 1000M / 500M = 2.0
    assert round(v.ps, 2) == 2.0
    # book/share = 750M/10M = 75；P/B = 100/75 = 1.33
    assert round(v.pb, 2) == 1.33


def test_fallback_to_info_metrics_when_no_financials():
    quote = Quote(ticker="TEST", price=100.0, market_cap=None)
    v = compute_valuation(
        "TEST", quote, [],
        info_metrics={"trailingPE": 15.0, "returnOnEquity": 0.18, "priceToBook": 3.0},
    )
    assert v.pe_trailing == 15.0
    assert round(v.roe, 2) == 18.0  # 0.18 -> 18%
    assert v.pb == 3.0
