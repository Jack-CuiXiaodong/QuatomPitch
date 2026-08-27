"""自洽性校验单元测试。

重点覆盖「营业利润残差」——它是用来兜住科目映射错误的那道网。真实案例：
Adobe 把销售营销与管理费用拆开申报，工具却只取到管理费用，漏掉 64.9 亿，
输出的是一个量级完全合理的数字，只有靠残差才能发现。
"""
from quatompitch.analysis import run_checks
from quatompitch.models import FinancialPeriod
from quatompitch.models.quality import DIFF, OK, SKIP


def _period(**kw) -> FinancialPeriod:
    base = dict(
        period_type="FY", fiscal_date="2025-12-31", source="sec-xbrl",
        revenue=1000.0, cost_of_revenue=400.0, gross_profit=600.0,
        rnd_expense=200.0, sga_expense=100.0,
        operating_income=300.0,
        pretax_income=300.0, income_tax_expense=60.0, net_income=240.0,
        total_assets=2000.0, total_liabilities=1200.0, total_equity=800.0,
    )
    base.update(kw)
    return FinancialPeriod(**base)


def _by_name(checks, keyword):
    return [c for c in checks if keyword in c.name]


def test_clean_period_passes_all_identities():
    checks = run_checks([_period()])
    assert checks, "应产生校验记录"
    assert all(c.status == OK for c in checks), [
        (c.name, c.status, c.diff) for c in checks if c.status != OK
    ]


def test_detects_broken_gross_profit():
    # 毛利应为 600，申报成 500
    checks = run_checks([_period(gross_profit=500.0)])
    gp = _by_name(checks, "毛利")[0]
    assert gp.status == DIFF
    assert gp.diff == -100.0


def test_detects_unclassified_operating_expense():
    """模拟 Adobe：漏采一笔大额营业费用，营业利润残差应报差异。"""
    # 毛利 600 − 已归类费用(研发 200) = 400，而申报营业利润 300，
    # 说明还有 100（占营收 10%）的费用没被采集到。
    checks = run_checks([_period(sga_expense=None)])
    residual = _by_name(checks, "营业利润残差")[0]
    assert residual.status == DIFF
    assert residual.diff_pct > 3.0


def test_small_residual_is_tolerated():
    """摊销等未单独归类的小额科目不应报警。"""
    # 残差 10，占营收 1%
    checks = run_checks([_period(operating_income=290.0)])
    residual = _by_name(checks, "营业利润残差")[0]
    assert residual.status == OK


def test_split_and_combined_sga_are_not_double_counted():
    """销管费拆开申报时按两项相加，不应与合并口径重复计入。"""
    split = _period(sga_expense=None, selling_marketing_expense=70.0,
                    general_admin_expense=30.0)
    residual = _by_name(run_checks([split]), "营业利润残差")[0]
    assert residual.status == OK, residual.diff


def test_missing_fields_are_skipped_not_failed():
    checks = run_checks([_period(pretax_income=None, income_tax_expense=None)])
    ni = _by_name(checks, "净利润")[0]
    assert ni.status == SKIP


def test_cross_source_flags_divergent_yfinance_value():
    xbrl = [_period()]
    yf = [FinancialPeriod(period_type="FY", fiscal_date="2025-12-31",
                          source="yfinance", revenue=900.0)]
    checks = run_checks(xbrl, yf)
    rev = [c for c in checks if c.scope == "跨源比对" and "营收" in c.name]
    assert rev and rev[0].status == DIFF
