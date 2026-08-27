"""数据源解析层测试——用真实 SEC 响应做 fixture，不联网。

这一层此前零测试覆盖，而它恰恰是全项目最容易出错、也最难发现错误的地方：
解析出的数字格式完好、量级合理，错了也没人看得出来。本轮修过的每一个解析
缺陷都在这里钉死，避免重构时悄悄回归。

fixture 全部是真实报送响应（tests/fixtures/），不是手写的示例——手写的
示例只能验证我对格式的假设，验证不了 SEC 实际返回什么。
"""
from pathlib import Path

import pytest
import xml.etree.ElementTree as ET

from quatompitch.datasources.sec_docs import SecDocsSource, _clean_cell, _html_to_text
from quatompitch.datasources.sec_edgar import SecEdgarSource, _parse_form4_xml

FIXTURES = Path(__file__).parent / "fixtures"


def _fx(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _rows_by_label(table: dict, keyword: str) -> list[list[str]]:
    return [r for r in table["rows"] if keyword.lower() in r[0].lower()]


# ---------------------------------------------------------------------------
# Form 4 内部人交易
# ---------------------------------------------------------------------------

def test_form4_parses_common_stock_transactions():
    trades = _parse_form4_xml(_fx("form4_aapl.xml"), "AAPL", "http://x")
    assert trades, "AAPL 这份 Form 4 应解析出交易"
    common = [t for t in trades if not t.is_derivative]
    assert common
    t = common[0]
    assert t.insider_name and t.transaction_date and t.transaction_code
    assert t.shares and t.shares > 0


def test_form4_parses_derivative_only_filing():
    """SHOP 这份报送**没有 nonDerivativeTable**，只读普通股表会整份漏掉。

    这正是内部人交易长期显示为 0 的原因。
    """
    trades = _parse_form4_xml(
        _fx("form4_shop_derivative_only.xml"), "SHOP", "http://x"
    )
    assert trades, "只有衍生品表的报送也必须解析出交易"
    assert all(t.is_derivative for t in trades)
    assert any(t.security_title for t in trades), "衍生品应带证券名称"
    assert any(t.exercise_price is not None for t in trades), "衍生品应带行权价"


def test_form4_parse_failure_raises_not_returns_empty():
    """拿到的不是 XML 属于取数故障，必须抛异常。

    静默返回空列表会让「取错了地址」伪装成「这家公司没有内部人交易」——
    最初的 bug 就是这么藏住的：SEC 的 primaryDocument 带 XSLT 渲染前缀，
    该地址返回 HTML，ParseError 被就地吞掉。
    """
    # 真实的 XSLT 渲染页长这样：HTML 4.01 DTD + 未闭合的 meta/br，不是合法 XML
    rendered_html = (
        '<!DOCTYPE html PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" '
        '"http://www.w3.org/TR/html4/loose.dtd">\n'
        "<html><head><meta http-equiv=Content-Type content='text/html'>"
        "</head><body><table><tr><td>1. Name of Reporting Person<br>"
        "</td></tr></table></body></html>"
    )
    with pytest.raises(ET.ParseError):
        _parse_form4_xml(rendered_html, "X", "http://x")


def test_form4_url_strips_xslt_render_prefix():
    """primaryDocument 形如 xslF345X06/form4.xml，该地址返回的是 HTML。"""
    src = SecEdgarSource()
    url = src._find_form4_xml(None, "320193", "000114036126033928",
                              "xslF345X06/form4.xml")
    assert url.endswith("/form4.xml")
    assert "xslF345X06" not in url


# ---------------------------------------------------------------------------
# R 文件表格解析
# ---------------------------------------------------------------------------

def test_r_table_flattens_group_labels_into_row_labels():
    """分组名单独占一行时，要拍进行标签，让每行能独立读懂。"""
    t = SecDocsSource._parse_r_table(_fx("r_duol_revenue.htm"))
    assert t and t["columns"]
    labels = [r[0] for r in t["rows"]]
    assert any(lab.startswith("Subscription · ") for lab in labels)
    assert any(lab.startswith("Advertising · ") for lab in labels)


def test_r_table_keeps_legitimately_repeated_group():
    """DUOL 的 "Other" 作为分组合法地出现两次，不能当轴标签噪音跳过。

    跳过的话分组名会停留在上一个，164,147 会被错标成 Subscription，
    订阅收入凭空翻倍。
    """
    t = SecDocsSource._parse_r_table(_fx("r_duol_revenue.htm"))
    labels = [r[0] for r in t["rows"]]
    other_rows = [lab for lab in labels if lab.startswith("Other · ")]
    assert len(other_rows) == 2, f"应有两行 Other，实际 {other_rows}"
    # 且订阅只能有一行，不能把 Other 的金额也算进订阅
    subs = [r for r in t["rows"] if r[0].startswith("Subscription · ")]
    assert len(subs) == 1


def test_r_table_skips_repeating_axis_label():
    """NVDA 在每个真实分组前重复一次轴标签，会把分组名冲掉。"""
    t = SecDocsSource._parse_r_table(_fx("r_nvda_region.htm"))
    labels = [r[0] for r in t["rows"]]
    assert any(lab.startswith("United States · ") for lab in labels), labels[:6]
    # 轴标签不应成为分组前缀
    assert not any(lab.startswith("Revenues and Long-Lived Assets · ") for lab in labels)


def test_r_table_never_emits_pipe_in_cells():
    """SEC 把 XBRL 多维成员渲染成 `Level 1 | Cash Equivalents`。

    竖线是 Markdown 列分隔符，原样输出会当场撑破整张表。
    """
    raw = _fx("r_duol_fairvalue_pipes.htm")
    assert "|" in raw, "这份 fixture 的原文应含竖线，否则测不到东西"
    t = SecDocsSource._parse_r_table(raw)
    for row in t["rows"]:
        for cell in row:
            assert "|" not in cell, f"单元格仍含竖线: {cell!r}"
    assert any(" · " in r[0] for r in t["rows"]), "竖线应被换成 ·"


def test_r_table_labels_columns_with_period_span():
    """10-Q 利润表有单季与累计两组列，日期重复，必须靠 colspan 区分。

    不区分的话，2.98 亿的单季营收和 5.90 亿的半年营收会被当成同一期。
    """
    t = SecDocsSource._parse_r_table(_fx("r_duol_10q_income_colspan.htm"))
    cols = t["columns"]
    assert len(cols) == len(set(cols)), f"列名必须唯一，实际 {cols}"
    assert any("3 Months" in c for c in cols), cols
    assert any("6 Months" in c for c in cols), cols


def test_r_table_balance_sheet_columns_not_double_labelled():
    """时点表表头本身就是日期，不应再套一层「（日期）」。"""
    t = SecDocsSource._parse_r_table(_fx("r_duol_revenue.htm"))
    for c in t["columns"]:
        assert c.count("（") <= 1, f"列名重复标注: {c!r}"


def test_r_table_rows_are_rectangular():
    """每行列数必须与表头一致，否则渲染出的 Markdown 表格会错位。"""
    for name in ("r_duol_revenue.htm", "r_nvda_region.htm",
                 "r_duol_10q_income_colspan.htm", "r_duol_fairvalue_pipes.htm"):
        t = SecDocsSource._parse_r_table(_fx(name))
        width = len(t["columns"]) + 1
        for row in t["rows"]:
            assert len(row) == width, f"{name}: 行宽 {len(row)} != {width}: {row[:2]}"


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------

def test_clean_cell_replaces_pipe_with_middot():
    assert _clean_cell("Level 1 | Cash Equivalents") == "Level 1 · Cash Equivalents"
    assert _clean_cell("  a\n b  ") == "a b"


def test_html_to_text_strips_inline_xbrl_metadata():
    """inline XBRL 的隐藏节点塞满机器标签，会淹没 8-K 这类短文档的正文。"""
    html = """
    <html><body>
      <ix:header><ix:hidden><span>us-gaap:CommonStockMember</span></ix:hidden></ix:header>
      <div style="display:none">0000320193</div>
      <p>Item 2.02 Results of Operations.</p>
    </body></html>
    """
    text = _html_to_text(html)
    assert "Item 2.02" in text
    assert "CommonStockMember" not in text
    assert "0000320193" not in text
