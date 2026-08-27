"""报告生成：把 ResearchReport 渲染为结构化 Markdown。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..analysis import build_overview
from ..config import settings
from ..models import ResearchReport

TEMPLATE_DIR = Path(__file__).parent / "templates"


def _fmt_money(v: Optional[float], currency: str = "$") -> str:
    """人类可读的金额：$1.23B / $45.6M / $789.0K。"""
    if v is None:
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    sign = "-" if v < 0 else ""
    a = abs(v)
    if a >= 1e12:
        return f"{sign}{currency}{a/1e12:.2f}T"
    if a >= 1e9:
        return f"{sign}{currency}{a/1e9:.2f}B"
    if a >= 1e6:
        return f"{sign}{currency}{a/1e6:.2f}M"
    if a >= 1e3:
        return f"{sign}{currency}{a/1e3:.2f}K"
    return f"{sign}{currency}{a:,.2f}"


def _fmt_num(v: Optional[float], decimals: int = 2) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):,.{decimals}f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_pct(v: Optional[float], decimals: int = 2) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.{decimals}f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_shares(v: Optional[float]) -> str:
    if v is None:
        return "—"
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "—"
    a = abs(v)
    sign = "-" if v < 0 else ""
    if a >= 1e6:
        return f"{sign}{a/1e6:.2f}M"
    if a >= 1e3:
        return f"{sign}{a/1e3:.1f}K"
    return f"{sign}{a:,.0f}"


def _fmt_cell(v) -> str:
    """表格单元格兜底：任何内容都不该撑破 Markdown 的列结构。

    竖线是列分隔符、换行会直接结束这一行，两者出现在单元格里都会让整张表错位。
    数据源已做过一轮清洗，这里是最后一道防线（公司名、证券名称都可能带竖线）。
    """
    if v is None:
        return "—"
    s = str(v).replace("\r", " ").replace("\n", " ")
    return s.replace("|", "\\|").strip()


def _build_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(enabled_extensions=(), default=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["money"] = _fmt_money
    env.filters["num"] = _fmt_num
    env.filters["pct"] = _fmt_pct
    env.filters["shares"] = _fmt_shares
    env.filters["cell"] = _fmt_cell
    return env


def render_markdown(report: ResearchReport) -> str:
    env = _build_env()
    tmpl = env.get_template("report.md.j2")
    # 速览是纯派生数据，用完即弃，不进 ResearchReport 也不落库
    return tmpl.render(r=report, ov=build_overview(report))


def write_report(report: ResearchReport) -> Path:
    md = render_markdown(report)
    out_dir = settings.report_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    day = report.generated_at.split(" ")[0].split("T")[0]
    path = out_dir / f"{report.ticker}_{day}.md"
    path.write_text(md, encoding="utf-8")
    return path
