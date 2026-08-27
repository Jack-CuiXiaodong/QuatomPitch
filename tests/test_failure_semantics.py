"""失败语义契约测试。

钉死一条规则：**空结果只允许表示「数据确实不存在」，取数故障必须留痕。**

这是本项目反复踩坑的根源。Form 4 内部人交易长期显示为 0，不是因为公司没有
内部人交易，而是取回的是 HTML 不是 XML，异常被就地吞掉后返回空列表——两者
在报告里长得一模一样。同类问题还有：yfinance 偶发整片返回空导致估值表全是
「—」、FilingSummary 取不到导致三大报表整节消失。
"""
import pytest

from quatompitch.datasources.issues import IssueLog


# ---------------------------------------------------------------------------
# IssueLog
# ---------------------------------------------------------------------------

def test_issue_log_is_falsy_and_silent_when_clean():
    log = IssueLog("测试源")
    assert not log
    assert log.as_warning() is None


def test_issue_log_reports_source_and_reason():
    log = IssueLog("测试源")
    log.record("取 A 失败", ValueError("boom"))
    assert log
    w = log.as_warning()
    assert "测试源" in w and "取 A 失败" in w and "ValueError" in w and "boom" in w


def test_issue_log_folds_repeated_failures():
    """限流时会一连串失败，全列出来会淹没报告。"""
    log = IssueLog("测试源")
    for i in range(10):
        log.record(f"取 {i} 失败", "timeout")
    w = log.as_warning(limit=3)
    assert "另有 7 处同类失败" in w


# ---------------------------------------------------------------------------
# 数据源：故障必须上报，不能伪装成「没数据」
# ---------------------------------------------------------------------------

def test_yfinance_source_reports_failure_instead_of_silent_empty(monkeypatch):
    """yfinance 整片挂掉时必须给出 warning，而不是安静地返回空财报。"""
    import quatompitch.datasources.yfinance_source as mod

    class _BoomTicker:
        def __init__(self, *a, **kw):
            pass

        @property
        def info(self):
            raise RuntimeError("network down")

        def __getattr__(self, name):
            raise RuntimeError("network down")

    monkeypatch.setattr(mod.yf, "Ticker", _BoomTicker)

    out = mod.YFinanceSource().fetch("TEST")
    assert out["annual_financials"] == []
    assert out.get("warning"), "整片失败却没有任何告警——正是要防的情况"
    assert "yfinance" in out["warning"]


def test_news_source_silent_when_rss_fallback_succeeds(monkeypatch):
    """主路失败但兜底成功，不该打扰用户。"""
    import quatompitch.datasources.yahoo_news as mod

    class _BoomTicker:
        def __init__(self, *a, **kw):
            pass

        @property
        def news(self):
            raise RuntimeError("api gone")

    monkeypatch.setattr(mod.yf, "Ticker", _BoomTicker)
    monkeypatch.setattr(
        mod.feedparser, "parse",
        lambda url: type("F", (), {"entries": [
            {"title": "T", "link": "http://x", "published": "2026-01-01"}
        ]})(),
    )

    out = mod.YahooNewsSource().fetch("TEST")
    assert len(out["news"]) == 1
    assert not out.get("warning"), "兜底成功就不该报警"


def test_news_source_reports_when_both_paths_fail(monkeypatch):
    import quatompitch.datasources.yahoo_news as mod

    class _BoomTicker:
        def __init__(self, *a, **kw):
            pass

        @property
        def news(self):
            raise RuntimeError("api gone")

    def _boom_parse(url):
        raise RuntimeError("rss gone")

    monkeypatch.setattr(mod.yf, "Ticker", _BoomTicker)
    monkeypatch.setattr(mod.feedparser, "parse", _boom_parse)

    out = mod.YahooNewsSource().fetch("TEST")
    assert out["news"] == []
    assert out.get("warning")


# ---------------------------------------------------------------------------
# 报告：真故障要在顶部警示，配置提示不要
# ---------------------------------------------------------------------------

def test_report_separates_config_notice_from_real_failure():
    from quatompitch.models import ResearchReport

    r = ResearchReport(
        ticker="T", generated_at="2026-01-01 00:00:00",
        warnings=["未配置 FRED_API_KEY，跳过宏观模块", "docs 采集不完整：超时"],
    )
    blocking = r.blocking_warnings
    assert len(blocking) == 1
    assert "docs" in blocking[0]


def test_report_top_banner_only_on_real_failure():
    from quatompitch.models import ResearchReport
    from quatompitch.report.generator import render_markdown

    clean = ResearchReport(ticker="T", generated_at="2026-01-01 00:00:00",
                           warnings=["未配置 FRED_API_KEY，跳过宏观模块"])
    assert "本次采集存在异常" not in render_markdown(clean)

    broken = ResearchReport(ticker="T", generated_at="2026-01-01 00:00:00",
                            warnings=["xbrl 采集失败：ReadTimeout"])
    assert "本次采集存在异常" in render_markdown(broken)
