"""核心编排：采集 → 计算 → 存储 → 生成报告。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from .analysis import compute_valuation
from .datasources import (
    FredSource,
    SecEdgarSource,
    YahooNewsSource,
    YFinanceSource,
)
from .models import ResearchReport
from .report.generator import write_report
from .storage import repository as repo
from .storage.db import init_db


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def analyze(ticker: str, progress=None) -> tuple[ResearchReport, Path]:
    """对单只股票执行完整分析，返回 (报告对象, 输出文件路径)。"""
    ticker = ticker.strip().upper()
    init_db()

    report = ResearchReport(ticker=ticker, generated_at=_now())

    sources = {
        "yfinance": YFinanceSource(),
        "sec": SecEdgarSource(),
        "news": YahooNewsSource(),
        "fred": FredSource(),
    }

    def _log(msg: str) -> None:
        if progress:
            progress(msg)

    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(src.fetch, ticker): name
                   for name, src in sources.items()}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                results[name] = fut.result()
                _log(f"✓ {name} 采集完成")
            except Exception as e:  # 单源失败不影响整体
                results[name] = {}
                report.warnings.append(f"{name} 采集失败：{e}")
                _log(f"✗ {name} 采集失败：{e}")

    # --- 归一化组装 ---
    yf = results.get("yfinance", {})
    report.company = yf.get("company")
    report.quote = yf.get("quote")
    report.annual_financials = yf.get("annual_financials", []) or []
    report.quarterly_financials = yf.get("quarterly_financials", []) or []
    info_metrics = yf.get("info_metrics", {})

    sec = results.get("sec", {})
    report.filings = sec.get("filings", []) or []
    report.insider_trades = sec.get("insider_trades", []) or []
    if sec.get("warning"):
        report.warnings.append(sec["warning"])
    # 回填 CIK 到 company
    if report.company and sec.get("cik"):
        report.company.cik = sec["cik"]

    news = results.get("news", {})
    report.news = news.get("news", []) or []

    fred = results.get("fred", {})
    report.macro = fred.get("macro", []) or []
    if fred.get("skipped"):
        report.warnings.append(fred["skipped"])

    # --- 估值指标 ---
    report.valuation = compute_valuation(
        ticker, report.quote, report.annual_financials, info_metrics
    )

    # --- 排序：财报按报告期倒序，内部人交易按日期倒序 ---
    report.annual_financials.sort(key=lambda p: p.fiscal_date, reverse=True)
    report.quarterly_financials.sort(key=lambda p: p.fiscal_date, reverse=True)
    report.quarterly_financials = report.quarterly_financials[:8]
    report.insider_trades.sort(
        key=lambda t: t.transaction_date or "", reverse=True
    )

    # --- 持久化 ---
    try:
        if report.company:
            repo.save_company(report.company)
        if report.annual_financials or report.quarterly_financials:
            repo.save_financials(
                ticker, report.annual_financials + report.quarterly_financials
            )
        if report.valuation:
            repo.save_valuation(report.valuation)
        if report.insider_trades:
            repo.save_insider_trades(ticker, report.insider_trades)
        if report.filings:
            repo.save_filings(ticker, report.filings)
    except Exception as e:
        report.warnings.append(f"数据库写入告警：{e}")

    # --- 生成报告 ---
    path = write_report(report)
    summary = _summary_line(report)
    try:
        repo.record_report(report, str(path), summary)
    except Exception:
        pass

    return report, path


def _summary_line(report: ResearchReport) -> str:
    q = report.quote
    v = report.valuation
    parts = []
    if q and q.price:
        parts.append(f"价 {q.price}")
    if q and q.market_cap:
        parts.append(f"市值 {q.market_cap/1e9:.1f}B")
    if v and v.pe_trailing:
        parts.append(f"PE {v.pe_trailing:.1f}")
    if report.insider_trades:
        parts.append(f"内部人交易 {len(report.insider_trades)} 笔")
    return " · ".join(parts)
