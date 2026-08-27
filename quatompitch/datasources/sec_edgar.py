"""SEC EDGAR 数据源：CIK 映射、报送索引（10-K/10-Q/8-K）、Form 4 内部人交易。

免 API key，但所有请求必须带 User-Agent（SEC 强制），并遵守限速（约 10 req/s）。
"""
from __future__ import annotations

import json
import threading
import time
import xml.etree.ElementTree as ET
from typing import Any, Optional

import httpx

from ..config import settings
from ..models import Filing, InsiderTrade
from .base import DataSource
from .cache import CACHE
from .issues import IssueLog

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
ARCHIVE_BASE = "https://www.sec.gov/Archives/edgar/data"

# 关注的报送类型
INDEX_FORMS = {"10-K", "10-Q", "8-K", "20-F", "40-F"}

# 限速状态必须是**进程级**的：pipeline 会并发跑多个 SEC 数据源，
# 每个实例各自限速的话叠加起来会突破 SEC 约 10 req/s 的上限而被封禁。
_RATE_LOCK = threading.Lock()
_LAST_REQUEST_AT = 0.0

_TICKER_CACHE: dict[str, str] = {}
_TICKER_CACHE_LOCK = threading.Lock()


class SecClient:
    """带 User-Agent 与限速的 SEC HTTP 客户端。"""

    def __init__(self) -> None:
        self._client = httpx.Client(
            headers={
                "User-Agent": settings.sec_user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
            timeout=settings.http_timeout,
            follow_redirects=True,
        )
        self._min_interval = 1.0 / max(settings.sec_rate_limit_per_sec, 1.0)

    def _throttle(self) -> None:
        """全进程共享的令牌间隔，保证所有 SEC 数据源合计不超限。"""
        global _LAST_REQUEST_AT
        with _RATE_LOCK:
            elapsed = time.monotonic() - _LAST_REQUEST_AT
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            _LAST_REQUEST_AT = time.monotonic()

    def get_json(self, url: str) -> Any:
        # 走 get_text 以复用同一条缓存路径，不要各缓存各的
        return json.loads(self.get_text(url))

    def get_text(self, url: str) -> str:
        cached = CACHE.get(url)
        if cached is not None:
            return cached  # 命中缓存不消耗限速配额
        self._throttle()
        r = self._client.get(url)
        r.raise_for_status()
        CACHE.put(url, r.text)  # 只缓存成功响应，失败照常抛
        return r.text

    def close(self) -> None:
        self._client.close()


def resolve_cik(client: SecClient, ticker: str) -> Optional[str]:
    """ticker → 10 位零填充 CIK。

    映射表约 1 MB，多个 SEC 数据源并发时用锁保证只拉一次。
    """
    ticker = ticker.upper()
    with _TICKER_CACHE_LOCK:
        if not _TICKER_CACHE:
            data = client.get_json(SEC_TICKERS_URL)
            for row in data.values():
                _TICKER_CACHE[str(row["ticker"]).upper()] = str(row["cik_str"])
        cik = _TICKER_CACHE.get(ticker)
    return cik.zfill(10) if cik else None


def _text(el: Optional[ET.Element], path: str) -> Optional[str]:
    if el is None:
        return None
    found = el.find(path)
    return found.text.strip() if found is not None and found.text else None


def _float(el: Optional[ET.Element], path: str) -> Optional[float]:
    v = _text(el, path)
    if v is None:
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _parse_form4_xml(xml_text: str, ticker: str, filing_url: str) -> list[InsiderTrade]:
    """解析 Form 4 XML，抽取普通股与衍生品交易。

    **解析失败会抛 ET.ParseError，不要在这里吞掉。** 拿到的东西不是 XML 属于
    取数故障（例如误取了 XSLT 渲染后的 HTML），和「这家公司没有内部人交易」
    是两回事。返回空列表只允许表示后者。调用方负责记录失败。
    """
    trades: list[InsiderTrade] = []
    root = ET.fromstring(xml_text)

    owner_name = _text(root, ".//reportingOwner/reportingOwnerId/rptOwnerName")
    rel = root.find(".//reportingOwner/reportingOwnerRelationship")
    title_parts = []
    if rel is not None:
        if _text(rel, "isDirector") in ("1", "true"):
            title_parts.append("Director")
        if _text(rel, "isOfficer") in ("1", "true"):
            title_parts.append(_text(rel, "officerTitle") or "Officer")
        if _text(rel, "isTenPercentOwner") in ("1", "true"):
            title_parts.append("10% Owner")
    title = ", ".join([p for p in title_parts if p]) or None

    # 两张表都要读：普通股走 nonDerivativeTable，期权/权证/RSU 走 derivativeTable。
    # 有些公司的内部人活动全在衍生品表里（如 SHOP 的认股权证行权），只读前者会
    # 整份报送漏掉，内部人交易显示为 0。
    tables = (
        (".//nonDerivativeTable/nonDerivativeTransaction", False),
        (".//derivativeTable/derivativeTransaction", True),
    )
    for xpath, is_derivative in tables:
        for txn in root.findall(xpath):
            shares = _float(txn, "transactionAmounts/transactionShares/value")
            price = _float(txn, "transactionAmounts/transactionPricePerShare/value")
            value = (
                shares * price
                if (shares is not None and price is not None)
                else None
            )
            trades.append(
                InsiderTrade(
                    ticker=ticker.upper(),
                    insider_name=owner_name,
                    title=title,
                    transaction_date=_text(txn, "transactionDate/value"),
                    transaction_code=_text(txn, "transactionCoding/transactionCode"),
                    acquired_disposed=_text(
                        txn, "transactionAmounts/transactionAcquiredDisposedCode/value"
                    ),
                    shares=shares,
                    price=price,
                    value=value,
                    shares_owned_after=_float(
                        txn,
                        "postTransactionAmounts/sharesOwnedFollowingTransaction/value",
                    ),
                    is_direct=(
                        _text(txn, "ownershipNature/directOrIndirectOwnership/value")
                        == "D"
                    ),
                    filing_url=filing_url,
                    is_derivative=is_derivative,
                    security_title=_text(txn, "securityTitle/value"),
                    exercise_price=_float(txn, "conversionOrExercisePrice/value"),
                    underlying_shares=_float(
                        txn, "underlyingSecurity/underlyingSecurityShares/value"
                    ),
                )
            )
    return trades


class SecEdgarSource(DataSource):
    name = "sec"

    def __init__(self, max_form4: int = 25, max_index_filings: int = 15) -> None:
        self.max_form4 = max_form4
        self.max_index_filings = max_index_filings

    def fetch(self, ticker: str) -> dict[str, Any]:
        client = SecClient()
        issues = IssueLog("SEC 报送与内部人交易")
        try:
            cik = resolve_cik(client, ticker)
            if not cik:
                return {"cik": None, "filings": [], "insider_trades": [],
                        "warning": f"SEC 未找到 {ticker} 的 CIK"}

            subs = client.get_json(SUBMISSIONS_URL.format(cik10=cik))
            recent = subs.get("filings", {}).get("recent", {})
            forms = recent.get("form", [])
            dates = recent.get("filingDate", [])
            report_dates = recent.get("reportDate", [])
            accessions = recent.get("accessionNumber", [])
            primary_docs = recent.get("primaryDocument", [])
            primary_desc = recent.get("primaryDocDescription", [])

            cik_int = str(int(cik))  # 去零填充用于 Archives 路径
            filings: list[Filing] = []
            form4_refs: list[tuple[str, str]] = []  # (accession_nodash, primary_doc)

            for i, form in enumerate(forms):
                acc = accessions[i] if i < len(accessions) else ""
                acc_nodash = acc.replace("-", "")
                pdoc = primary_docs[i] if i < len(primary_docs) else ""
                url = (
                    f"{ARCHIVE_BASE}/{cik_int}/{acc_nodash}/{pdoc}"
                    if pdoc else
                    f"{ARCHIVE_BASE}/{cik_int}/{acc_nodash}/"
                )

                if form in INDEX_FORMS and len(filings) < self.max_index_filings:
                    filings.append(
                        Filing(
                            ticker=ticker.upper(),
                            cik=cik,
                            form_type=form,
                            filing_date=dates[i] if i < len(dates) else "",
                            report_date=report_dates[i] if i < len(report_dates) else None,
                            accession_no=acc,
                            primary_doc=pdoc,
                            url=url,
                            description=primary_desc[i] if i < len(primary_desc) else None,
                        )
                    )

                if form == "4" and len(form4_refs) < self.max_form4:
                    form4_refs.append((acc_nodash, pdoc))

            # 解析 Form 4 明细。单份取不到不影响其余，但必须留痕——
            # 否则「一份都没解析成功」和「这家公司没有内部人交易」无法区分。
            insider_trades: list[InsiderTrade] = []
            for acc_nodash, pdoc in form4_refs:
                try:
                    xml_url = self._find_form4_xml(client, cik_int, acc_nodash, pdoc)
                    if not xml_url:
                        issues.record(f"Form 4 {acc_nodash} 未定位到 XML", "无匹配文件")
                        continue
                    xml_text = client.get_text(xml_url)
                    insider_trades.extend(_parse_form4_xml(xml_text, ticker, xml_url))
                except (httpx.HTTPError, ET.ParseError) as e:
                    issues.record(f"Form 4 {acc_nodash} 解析失败", e)

            out: dict[str, Any] = {
                "cik": cik,
                "filings": filings,
                "insider_trades": insider_trades,
            }
            if issues:
                out["warning"] = issues.as_warning()
            return out
        finally:
            client.close()

    def _find_form4_xml(
        self, client: SecClient, cik_int: str, acc_nodash: str, pdoc: str
    ) -> Optional[str]:
        """定位 Form 4 的原始 XML 文档 URL。"""
        # primaryDocument 若本身是 xml，直接用。
        # 注意：SEC 给的路径常带 XSLT 渲染前缀（如 xslF345X06/form4.xml），
        # 该地址返回的是渲染后的 HTML，解析必然失败，须剥掉前缀取原始 XML。
        if pdoc and pdoc.lower().endswith(".xml"):
            name = pdoc.rsplit("/", 1)[-1] if pdoc.lower().startswith("xsl") else pdoc
            return f"{ARCHIVE_BASE}/{cik_int}/{acc_nodash}/{name}"
        # 否则读取该报送目录的 index.json，找非 xslt 的 xml 文件。
        # 这里的 HTTPError 交给调用方记录，不在此吞掉。
        idx = client.get_json(f"{ARCHIVE_BASE}/{cik_int}/{acc_nodash}/index.json")
        items = idx.get("directory", {}).get("item", [])
        for it in items:
            nm = it.get("name", "")
            if nm.lower().endswith(".xml") and not nm.lower().startswith("r") \
                    and "xslt" not in nm.lower():
                return f"{ARCHIVE_BASE}/{cik_int}/{acc_nodash}/{nm}"
        return None
