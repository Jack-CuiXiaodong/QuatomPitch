"""命令行入口（typer）。"""
from __future__ import annotations

import sys

import typer
from rich.console import Console
from rich.table import Table

from . import pipeline
from .storage import repository as repo

# Windows 中文环境（GBK 代码页）下，一旦 stdout/stderr 被重定向或管道接走，
# 输出里的 ✓ 等字符会抛 UnicodeEncodeError，直接打断整个采集流程。统一切到 UTF-8。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # 非 TextIOWrapper（如测试替身）时跳过
        pass

app = typer.Typer(
    add_completion=False,
    help="QuatomPitch —— 美股财务数据与重大信息采集，生成结构化 Markdown 研究报告。",
)
console = Console()


@app.command()
def analyze(
    ticker: str = typer.Argument(..., help="股票代码，如 AAPL"),
    open_file: bool = typer.Option(False, "--open", help="生成后打印报告全文到终端"),
):
    """采集并生成单只股票的研究报告。"""
    console.print(f"[bold cyan]分析 {ticker.upper()}[/] …")

    with console.status("采集数据中…", spinner="dots"):
        report, path = pipeline.analyze(
            ticker, progress=lambda m: console.log(m)
        )

    # 终端摘要
    t = Table(title=f"{report.ticker} 摘要", show_header=False)
    if report.quote:
        t.add_row("现价", str(report.quote.price))
        t.add_row("市值", f"{(report.quote.market_cap or 0)/1e9:.2f}B")
    if report.valuation:
        t.add_row("P/E (TTM)", str(report.valuation.pe_trailing))
        t.add_row("ROE", f"{report.valuation.roe:.2f}%" if report.valuation.roe else "—")
    t.add_row("年度财报期数", str(len(report.annual_financials)))
    t.add_row("XBRL 年度/季度", f"{len(report.xbrl_annual)} / {len(report.xbrl_quarterly)}")
    t.add_row("三大报表原文", str(len(report.primary_statements)))
    t.add_row("分部收入表", str(len(report.statement_tables)))
    t.add_row("内部人交易笔数", str(len(report.insider_trades)))
    t.add_row("SEC 报送", str(len(report.filings)))
    doc_chars = sum(d.total_chars for d in report.filing_documents)
    t.add_row(
        "报送正文",
        f"{len(report.filing_documents)} 份 / {doc_chars:,} 字符",
    )
    t.add_row("新闻", str(len(report.news)))
    console.print(t)

    console.print(f"[bold green]✓ 报告已生成：[/] {path}")
    if report.warnings:
        console.print("[yellow]告警：[/]")
        for w in report.warnings:
            console.print(f"  - {w}")

    if open_file:
        console.rule("报告全文")
        console.print(path.read_text(encoding="utf-8"))


@app.command()
def reports(
    ticker: str = typer.Option(None, "--ticker", "-t", help="按代码筛选"),
    limit: int = typer.Option(20, "--limit", "-n"),
):
    """查看历史报告记录。"""
    rows = repo.list_reports(ticker, limit)
    if not rows:
        console.print("[dim]暂无报告记录。[/]")
        return
    t = Table(title="历史报告")
    t.add_column("代码")
    t.add_column("生成时间")
    t.add_column("摘要")
    t.add_column("路径")
    for r in rows:
        t.add_row(r["ticker"], r["generated_at"], r["summary"] or "", r["path"])
    console.print(t)


if __name__ == "__main__":
    app()
