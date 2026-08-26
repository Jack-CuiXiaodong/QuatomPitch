"""SEC XBRL companyfacts 数据源：官方结构化财务数据。

相比 yfinance 的优势：口径是公司自己报给 SEC 的原始 XBRL 事实，可溯源到具体
报送（accession），科目也更全（研发费、销管费、所得税、分项现金流等）。

接口：https://data.sec.gov/api/xbrl/companyfacts/CIK{10位}.json
免 API key，但同样受 SEC User-Agent 与限速约束（复用 SecClient）。
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from ..models import FinancialPeriod
from .base import DataSource
from .sec_edgar import SecClient, resolve_cik

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"

# 领域字段 → us-gaap 概念候选（按优先级，取第一个有值的）。
# 不同公司用的标签不一样，所以每项都给多个候选。
CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": (
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
    ),
    "cost_of_revenue": ("CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfSales"),
    "gross_profit": ("GrossProfit",),
    "rnd_expense": ("ResearchAndDevelopmentExpense",),
    "sga_expense": (
        "SellingGeneralAndAdministrativeExpense",
        "GeneralAndAdministrativeExpense",
    ),
    "operating_expenses": ("OperatingExpenses", "CostsAndExpenses"),
    "operating_income": ("OperatingIncomeLoss",),
    "pretax_income": (
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ),
    "income_tax_expense": ("IncomeTaxExpenseBenefit",),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "eps_basic": ("EarningsPerShareBasic",),
    "eps_diluted": ("EarningsPerShareDiluted",),
    "shares_diluted_wtd": ("WeightedAverageNumberOfDilutedSharesOutstanding",),
    # 时点科目（instant）
    "total_assets": ("Assets",),
    "current_assets": ("AssetsCurrent",),
    "inventory": ("InventoryNet",),
    "receivables": ("AccountsReceivableNetCurrent",),
    "total_liabilities": ("Liabilities",),
    "current_liabilities": ("LiabilitiesCurrent",),
    "total_equity": (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ),
    "long_term_debt": ("LongTermDebtNoncurrent", "LongTermDebt"),
    "cash_and_equivalents": (
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ),
    "short_term_investments": ("ShortTermInvestments", "MarketableSecuritiesCurrent"),
    "shares_outstanding": ("CommonStockSharesOutstanding", "CommonStockSharesIssued"),
    # 合同负债 / 递延收入：订阅制公司的收入确认与收款存在时间差，
    # 只看已确认收入会漏掉订单端的先行信号
    "deferred_revenue": (
        "ContractWithCustomerLiabilityCurrent",
        "DeferredRevenueCurrent",
        "ContractWithCustomerLiability",
    ),
    # 现金流（duration）
    "operating_cash_flow": (
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ),
    "investing_cash_flow": ("NetCashProvidedByUsedInInvestingActivities",),
    "financing_cash_flow": ("NetCashProvidedByUsedInFinancingActivities",),
    "capital_expenditure": (
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
    ),
    # 软件/无形资产的资本化支出。软件公司常把它算进资本开支，漏掉会高估自由现金流。
    # 注意：不少公司（如 DUOL）用的是自定义扩展标签，companyfacts 接口不暴露，
    # 那种情况下这里取不到值，free_cash_flow 会相应偏高——列名已写明公式。
    "capitalized_software": (
        "PaymentsForSoftware",
        "PaymentsForCapitalizedComputerSoftwareCosts",
        "PaymentsToDevelopSoftware",
        "PaymentsToAcquireIntangibleAssets",
    ),
    # 股权激励：非现金费用，但真实摊薄股东权益，估值建模必看
    "share_based_compensation": (
        "ShareBasedCompensation",
        "AllocatedShareBasedCompensationExpense",
    ),
    "dividends_paid": ("PaymentsOfDividendsCommonStock", "PaymentsOfDividends"),
    "share_repurchase": (
        "PaymentsForRepurchaseOfCommonStock",
        "TreasuryStockValueAcquiredCostMethod",
    ),
}

# 时点科目：只有 end 没有 start，按报告期末日期对齐
_INSTANT_FIELDS = {
    "total_assets", "current_assets", "inventory", "receivables",
    "total_liabilities", "current_liabilities", "total_equity",
    "long_term_debt", "cash_and_equivalents", "short_term_investments",
    "shares_outstanding", "deferred_revenue",
}

# 每股类科目单位不是 USD 而是 USD/shares，股数是 shares
_UNIT_HINTS = {
    "eps_basic": "USD/shares",
    "eps_diluted": "USD/shares",
    "shares_diluted_wtd": "shares",
    "shares_outstanding": "shares",
}


def _days(start: str, end: str) -> int:
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except (TypeError, ValueError):
        return -1


def _pick_unit(concept: dict, field: str) -> list[dict]:
    """从 XBRL 概念里挑出合适单位的事实列表。"""
    units = concept.get("units", {})
    hint = _UNIT_HINTS.get(field)
    if hint and hint in units:
        return units[hint]
    for key in ("USD", "shares", "USD/shares", "pure"):
        if key in units:
            return units[key]
    return next(iter(units.values()), []) if units else []


class SecXbrlSource(DataSource):
    """把 companyfacts 归集成按报告期对齐的 FinancialPeriod 列表。"""

    name = "xbrl"

    def __init__(self, max_annual: int = 6, max_quarterly: int = 10) -> None:
        self.max_annual = max_annual
        self.max_quarterly = max_quarterly

    def fetch(self, ticker: str) -> dict[str, Any]:
        client = SecClient()
        try:
            cik = resolve_cik(client, ticker)
            if not cik:
                return {"xbrl_annual": [], "xbrl_quarterly": [],
                        "warning": f"XBRL 未找到 {ticker} 的 CIK"}

            facts = client.get_json(COMPANYFACTS_URL.format(cik10=cik))
            gaap = facts.get("facts", {}).get("us-gaap", {})
            if not gaap:
                return {"xbrl_annual": [], "xbrl_quarterly": [],
                        "warning": f"{ticker} 的 XBRL companyfacts 为空"}

            annual = self._build(gaap, ticker, annual=True)[: self.max_annual]
            quarterly = self._build(gaap, ticker, annual=False)[: self.max_quarterly]
            return {"xbrl_annual": annual, "xbrl_quarterly": quarterly}
        finally:
            client.close()

    # ------------------------------------------------------------------
    def _build(self, gaap: dict, ticker: str, annual: bool) -> list[FinancialPeriod]:
        """按报告期末日期归集事实，组装成 FinancialPeriod。"""
        # buckets[end_date] = {字段: 值}，另附该期的溯源信息
        buckets: dict[str, dict[str, Any]] = {}

        for field, candidates in CONCEPTS.items():
            is_instant = field in _INSTANT_FIELDS
            # 必须遍历**全部**候选标签而不是命中即止：同一科目在不同年份可能换标签
            # （例如 AAPL 的分红 2017 年前用 PaymentsOfDividendsCommonStock，之后
            # 改用 PaymentsOfDividends），命中即止会把近年的值整片丢掉。
            # rank 小 = 优先级高；同 rank 时取 filed 更晚的（重述后的值）。
            for rank, concept_name in enumerate(candidates):
                concept = gaap.get(concept_name)
                if not concept:
                    continue
                for fact in _pick_unit(concept, field):
                    end = fact.get("end")
                    if not end:
                        continue
                    if not self._matches_period(fact, is_instant, annual):
                        continue
                    b = buckets.setdefault(end, {})
                    filed = fact.get("filed", "")
                    prev = b.get(f"__meta__{field}")
                    if prev is not None:
                        prev_rank, prev_filed = prev
                        if rank > prev_rank:
                            continue  # 已被更优先的标签填过
                        if rank == prev_rank and filed <= prev_filed:
                            continue  # 同标签下保留最新报送
                    b[field] = fact.get("val")
                    b[f"__meta__{field}"] = (rank, filed)
                    # 溯源信息取 filed **最早**的那条：那是该期首次作为当期披露的报送。
                    # 若取最晚的，后续季报重述比较列时会把自己的 fp（如 Q3）
                    # 盖到更早的期上，季度标签就全错位了。
                    if filed and filed < b.get("__filed__", "9999"):
                        b["__filed__"] = filed
                        b["__form__"] = fact.get("form")
                        b["__accn__"] = fact.get("accn")
                        b["__fp__"] = fact.get("fp")

        periods: list[FinancialPeriod] = []
        for end, vals in buckets.items():
            clean = {k: v for k, v in vals.items() if not k.startswith("__")}
            # 丢掉「只有时点科目」的孤点期：10-Q 里会带上一财年末的资产负债表作为
            # 比较列，若保留会和年度表重复，且整行经营数据为空。
            if clean.get("revenue") is None and clean.get("net_income") is None:
                continue
            p = FinancialPeriod(
                period_type="FY" if annual else "FQ",
                fiscal_date=end,
                source="sec-xbrl",
                form_type=vals.get("__form__"),
                accession_no=vals.get("__accn__"),
                fiscal_period=vals.get("__fp__"),
                **clean,
            )
            # 自由现金流：XBRL 没有现成标签，只能自算。
            # 公式 = 经营现金流 − 购建固定资产 − 资本化软件/无形资产。
            # 报告列名写明了这个公式：公司自己披露的 FCF 口径可能不同（有的还要
            # 减内容成本、有的用自定义标签导致这里取不到），差异以 10-K 原文为准。
            if p.operating_cash_flow is not None and p.capital_expenditure is not None:
                p.free_cash_flow = (
                    p.operating_cash_flow
                    - abs(p.capital_expenditure)
                    - abs(p.capitalized_software or 0.0)
                )
            periods.append(p)

        periods.sort(key=lambda x: x.fiscal_date, reverse=True)
        return periods

    @staticmethod
    def _matches_period(fact: dict, is_instant: bool, annual: bool) -> bool:
        """判断一条 XBRL 事实是否属于目标周期（年报期 / 季报期）。"""
        form = (fact.get("form") or "").upper()
        fp = (fact.get("fp") or "").upper()

        if is_instant:
            # 时点科目按所属报送区分：年报取 10-K，季报取 10-Q
            if annual:
                return form.startswith("10-K") and fp == "FY"
            return form.startswith("10-Q")

        start, end = fact.get("start"), fact.get("end")
        if not start or not end:
            return False
        span = _days(start, end)
        if annual:
            # 完整财年约 350~380 天，且必须来自 10-K 的 FY 期
            return form.startswith("10-K") and fp == "FY" and 340 <= span <= 380
        # 单季约 84~98 天
        return form.startswith("10-Q") and 80 <= span <= 100
