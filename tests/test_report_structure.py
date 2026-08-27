"""报告 Markdown 结构测试。

`trim_blocks=True` 会吃掉块标签后的换行，这个坑已经踩过三次：
新闻 10 条挤成 1 行、速览末行紧跟 `---` 变成 setext 标题、表格前少空行导致
整块被当成段落。症状都不是报错，而是**渲染出来不对**，光看源码看不出来。

这里直接渲染一份带各类内容的报告，用规则扫描产物。
"""
from quatompitch.models import (
    Company, FinancialPeriod, InsiderTrade, NewsItem, Quote,
    ResearchReport, StatementTable,
)
from quatompitch.report.generator import render_markdown


def _sample_report() -> ResearchReport:
    """构造一份把所有条件分支都点亮的报告。"""
    period = FinancialPeriod(
        period_type="FY", fiscal_date="2025-12-31", source="sec-xbrl",
        filed_date="2026-02-27", accession_no="0001-25-000001", form_type="10-K",
        revenue=1000.0, cost_of_revenue=400.0, gross_profit=600.0,
        rnd_expense=200.0, sga_expense=100.0, operating_income=300.0,
        pretax_income=300.0, income_tax_expense=60.0, net_income=240.0,
        eps_diluted=2.4, total_assets=2000.0, total_liabilities=1200.0,
        total_equity=800.0, cash_and_equivalents=500.0,
        operating_cash_flow=350.0, capital_expenditure=50.0, free_cash_flow=300.0,
    )
    prior = period.model_copy(update={
        "fiscal_date": "2024-12-31", "revenue": 800.0, "net_income": 180.0,
    })
    quarter = period.model_copy(update={
        "period_type": "FQ", "fiscal_date": "2026-06-30", "fiscal_period": "Q2",
        "revenue": 300.0, "net_income": 70.0,
    })
    table = StatementTable(
        ticker="TEST", title="示例报表", category="primary",
        units="USD ($) $ in Thousands", period_label="12 Months Ended",
        columns=["Dec. 31, 2025", "Dec. 31, 2024"],
        rows=[["Revenue", "1,000", "800"], ["Segment · Revenue", "600", "500"]],
        source_form="10-K", filing_date="2026-02-27", url="http://example/R1.htm",
    )
    return ResearchReport(
        ticker="TEST", generated_at="2026-08-28 10:00:00",
        company=Company(ticker="TEST", name="Test Inc."),
        quote=Quote(ticker="TEST", price=100.0, market_cap=1e9, currency="USD"),
        annual_financials=[period, prior], quarterly_financials=[quarter],
        xbrl_annual=[period, prior], xbrl_quarterly=[quarter],
        primary_statements=[table],
        statement_tables=[table.model_copy(update={"category": "note"})],
        insider_trades=[
            InsiderTrade(ticker="TEST", insider_name="A", acquired_disposed="A",
                         transaction_code="P", shares=100.0, price=10.0),
            InsiderTrade(ticker="TEST", insider_name="B", acquired_disposed="D",
                         transaction_code="S", shares=50.0, price=11.0,
                         is_derivative=True, security_title="RSU"),
        ],
        news=[NewsItem(ticker="TEST", title="标题", publisher="P",
                       published_at="2026-08-01", url="http://x",
                       summary="摘要")],
        warnings=["未配置 FRED_API_KEY，跳过宏观模块"],
    )


def _scan(md: str) -> list[str]:
    """扫描渲染结果里的 Markdown 结构隐患。"""
    problems = []
    lines = md.split("\n")
    in_fence = False
    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        prev = lines[i - 1] if i else ""
        # GFM 表格不能打断段落：表格首行之前必须是空行或另一行表格
        if line.startswith("|") and prev.strip() and not prev.startswith("|"):
            problems.append(f"第{i+1}行 表格前缺空行：{prev[:40]!r}")
        # 文字行紧跟 --- 会被解析成 setext 标题
        if line.strip() == "---" and prev.strip() and not prev.startswith("|"):
            problems.append(f"第{i+1}行 --- 紧跟文字（会变标题）：{prev[:40]!r}")
    return problems


def test_rendered_markdown_has_no_structure_hazards():
    problems = _scan(render_markdown(_sample_report()))
    assert not problems, "渲染结果存在结构问题：\n" + "\n".join(problems)


def test_table_columns_are_consistent_within_each_table():
    """列数不一致会让整张表错位，下游模型读到的数就对错行了。"""
    md = render_markdown(_sample_report())
    lines, in_fence, block = md.split("\n"), False, []
    def _check(rows):
        if not rows:
            return
        widths = {r.count("|") for r in rows}
        assert len(widths) == 1, f"同一张表列数不一致 {widths}: {rows[0][:60]!r}"
    for line in lines:
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and line.startswith("|"):
            block.append(line)
        else:
            _check(block)
            block = []
    _check(block)


def test_news_items_render_one_per_line():
    """曾因 trim_blocks 把 10 条新闻挤成一行。"""
    md = render_markdown(_sample_report())
    news_lines = [l for l in md.split("\n") if l.startswith("- [标题]")]
    assert len(news_lines) == 1


def test_overview_block_present_and_labelled_as_index():
    md = render_markdown(_sample_report())
    assert "## 关键数据速览" in md
    assert "这是索引，不是结论" in md
    # 速览必须出现在正文之前
    assert md.index("## 关键数据速览") < md.index("、公司概况")
