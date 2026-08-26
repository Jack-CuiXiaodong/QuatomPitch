"""SEC 报送正文与附注表数据源。

补齐两块大模型真正需要的原料：

1. **正文**：10-K 的业务/风险因素/MD&A、10-Q 的 MD&A、8-K 的事件说明。
   报送索引里只有 URL，大模型打不开链接，必须把正文抽进 MD 文件。
2. **附注表**：从 SEC 渲染出的 R*.htm 里抽分部收入、分产品收入、地区收入。
   这些带维度的数据 companyfacts 接口拿不到，只能从渲染文件取。

同样复用 SecClient 的 User-Agent 与全局限速。
"""
from __future__ import annotations

import re
import warnings
import xml.etree.ElementTree as ET
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

from ..config import settings
from ..models import FilingDocument, FilingSection, StatementTable
from .base import DataSource
from .sec_edgar import ARCHIVE_BASE, SUBMISSIONS_URL, SecClient, resolve_cik

try:  # bs4 对带 XML 声明的 .htm 会告警，正文解析不受影响
    from bs4 import XMLParsedAsHTMLWarning

    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except ImportError:  # pragma: no cover
    pass

# 各表单要抽取的章节：Item 编号 → 中文标题
TENK_ITEMS = {
    "1": "业务概述 Business",
    "1A": "风险因素 Risk Factors",
    "3": "法律诉讼 Legal Proceedings",
    "7": "管理层讨论与分析 MD&A",
    "7A": "市场风险 Quantitative and Qualitative Disclosures About Market Risk",
}
TENQ_ITEMS = {
    "2": "管理层讨论与分析 MD&A",
    "1A": "风险因素更新 Risk Factors",
}

# 附注表筛选：各家命名差异极大，单纯正则很容易既漏又误。
#   Apple  : "Revenue - Disaggregated Net Sales ... (Details)"
#   MSFT   : "Segment Revenue, Cost of Revenue, Operating Expenses ... (Detail)"
#            "Revenue Classified by Major Geographic Areas (Detail)"
#   NVIDIA : "Segment Information - Schedule of Revenue by Market (Details)"
# 因此用「必须是明细表 + 命中主题 + 不命中噪音」三重条件。
_DETAIL_RE = re.compile(r"\(detail", re.I)
_TABLE_INCLUDE_RE = re.compile(
    r"segment|geograph|by market|by region|by major|"
    r"product and service|significant product|disaggregat",
    re.I,
)
# 递延/预收收入、纯文字说明、括注表都不是我们要的分部数据
_TABLE_EXCLUDE_RE = re.compile(
    r"unearned revenue|deferred revenue|performance obligation|warranty|"
    r"parenthetical|\(tables\)|narrative|additional information",
    re.I,
)


def _html_to_text(html: str) -> str:
    """报送 HTML → 纯文本，压掉多余空白。

    现代报送是 inline XBRL：`ix:header` / `ix:hidden` 以及 display:none 的节点里
    塞满了机器可读的事实标签（us-gaap:CommonStockMember 之类）。这些东西对人和
    大模型都是噪音，且会淹没 8-K 这种短文档的正文，必须先剥掉。
    """
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for tag in soup.find_all(re.compile(r"^ix:(header|hidden)$", re.I)):
        tag.decompose()
    for tag in soup.select('[style*="display:none"], [style*="display: none"]'):
        tag.decompose()
    text = soup.get_text("\n")
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


# 8-K 的条目编号带小数（Item 2.02 业绩发布、Item 5.02 高管变动…）
_8K_ITEM_RE = re.compile(r"^[ \t]*Item[ \t]+(\d{1,2}\.\d{2})", re.I | re.M)

# 8-K 附件里 EX-99.x 通常是业绩新闻稿，才是真正有信息量的部分
_EX99_RE = re.compile(r"ex-?99", re.I)

# R 文件表头形如 "Sep. 27, 2025" / "Dec. 31, 2025"
_DATE_CELL_RE = re.compile(r"[A-Z][a-z]{2}\.?\s+\d{1,2},\s+\d{4}")


def _looks_like_date(cell: str) -> bool:
    return bool(_DATE_CELL_RE.search(cell or ""))


_ITEM_RE = re.compile(r"^[ \t]*Item[ \t]+(\d{1,2}[A-Z]?)[ \t]*[\.\:\-—]?", re.I | re.M)


def _split_items(text: str) -> dict[str, tuple[int, int]]:
    """定位正文里每个 Item 的正文区间。

    报送开头的目录里同样有 Item 字样，且彼此只隔几十个字符；正文里的 Item
    后面跟着大段内容。所以对每个 Item 取「到下一个 Item 之间跨度最大」的那次
    出现，天然避开目录。
    """
    marks = [(m.start(), m.group(1).upper()) for m in _ITEM_RE.finditer(text)]
    if not marks:
        return {}
    spans: dict[str, tuple[int, int]] = {}
    for i, (pos, item) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        if item not in spans or (end - pos) > (spans[item][1] - spans[item][0]):
            spans[item] = (pos, end)
    return spans


class SecDocsSource(DataSource):
    """抓取并抽取最近的 10-K / 10-Q / 8-K 正文，以及分部收入等附注表。"""

    name = "docs"

    def __init__(
        self,
        max_8k: int = 5,
        max_tables: int = 6,
        section_max_chars: Optional[int] = None,
    ) -> None:
        self.max_8k = max_8k
        self.max_tables = max_tables
        self.section_max_chars = (
            section_max_chars
            if section_max_chars is not None
            else settings.sec_section_max_chars
        )

    # ------------------------------------------------------------------
    def fetch(self, ticker: str) -> dict[str, Any]:
        client = SecClient()
        try:
            cik = resolve_cik(client, ticker)
            if not cik:
                return {"filing_documents": [], "statement_tables": [],
                        "warning": f"报送正文：未找到 {ticker} 的 CIK"}

            subs = client.get_json(SUBMISSIONS_URL.format(cik10=cik))
            recent = subs.get("filings", {}).get("recent", {})
            cik_int = str(int(cik))

            picks = self._pick_filings(recent)
            docs: list[FilingDocument] = []
            tables: list[StatementTable] = []
            notes: list[str] = []

            for form, meta in picks:
                acc_nodash = meta["accession"].replace("-", "")
                url = f"{ARCHIVE_BASE}/{cik_int}/{acc_nodash}/{meta['doc']}"
                try:
                    html = client.get_text(url)
                except httpx.HTTPError as e:
                    notes.append(f"{form} 正文下载失败：{e}")
                    continue

                text = _html_to_text(html)
                sections = self._extract_sections(form, text)
                if form == "8-K":
                    # 8-K 正文往往只说「详见附件」，业绩数字都在 EX-99.x 新闻稿里
                    sections.extend(
                        self._fetch_8k_exhibits(client, cik_int, acc_nodash, meta["doc"])
                    )
                if sections:
                    docs.append(
                        FilingDocument(
                            ticker=ticker.upper(),
                            form_type=form,
                            filing_date=meta["filed"],
                            report_date=meta.get("report"),
                            accession_no=meta["accession"],
                            url=url,
                            sections=sections,
                        )
                    )

                # 分部/分产品表只从最近一份 10-K 取，够用且省请求
                if form == "10-K" and not tables:
                    tables = self._fetch_tables(
                        client, ticker, cik_int, acc_nodash, meta["filed"]
                    )

            out: dict[str, Any] = {
                "filing_documents": docs,
                "statement_tables": tables[: self.max_tables],
            }
            if notes:
                out["warning"] = "；".join(notes)
            return out
        finally:
            client.close()

    # ------------------------------------------------------------------
    def _pick_filings(self, recent: dict) -> list[tuple[str, dict]]:
        """从报送索引里挑：最近 1 份 10-K、1 份 10-Q、若干份 8-K。"""
        forms = recent.get("form", [])
        accs = recent.get("accessionNumber", [])
        docs = recent.get("primaryDocument", [])
        dates = recent.get("filingDate", [])
        reports = recent.get("reportDate", [])

        want = {"10-K": 1, "10-Q": 1, "8-K": self.max_8k}
        picked: list[tuple[str, dict]] = []
        for i, form in enumerate(forms):
            f = (form or "").upper()
            if f not in want or want[f] <= 0:
                continue
            doc = docs[i] if i < len(docs) else ""
            if not doc or not doc.lower().endswith((".htm", ".html")):
                continue
            want[f] -= 1
            picked.append((f, {
                "accession": accs[i] if i < len(accs) else "",
                "doc": doc,
                "filed": dates[i] if i < len(dates) else "",
                "report": reports[i] if i < len(reports) else None,
            }))
            if all(v <= 0 for v in want.values()):
                break
        return picked

    # ------------------------------------------------------------------
    def _extract_sections(self, form: str, text: str) -> list[FilingSection]:
        """按表单类型抽取需要的章节。8-K 很短，整篇留下。"""
        if form == "8-K":
            # 封面那一堆注册地址、电话、证券代码对分析没用，从第一个 Item 处切起
            m = _8K_ITEM_RE.search(text)
            body_text = text[m.start():].strip() if m else text
            body, truncated = self._clip(body_text)
            title = f"8-K 事件正文（Item {m.group(1)}）" if m else "8-K 正文"
            return [FilingSection(
                item=m.group(1) if m else None, title=title, text=body,
                char_count=len(body), truncated=truncated,
            )]

        wanted = TENK_ITEMS if form == "10-K" else TENQ_ITEMS
        spans = _split_items(text)
        sections: list[FilingSection] = []
        for item, title in wanted.items():
            span = spans.get(item)
            if not span:
                continue
            raw = text[span[0]:span[1]].strip()
            if len(raw) < 200:  # 只剩标题、没有正文，跳过
                continue
            body, truncated = self._clip(raw)
            sections.append(FilingSection(
                item=item, title=title, text=body,
                char_count=len(body), truncated=truncated,
            ))
        return sections

    def _fetch_8k_exhibits(
        self, client: SecClient, cik_int: str, acc_nodash: str, primary_doc: str,
    ) -> list[FilingSection]:
        """抓 8-K 的 EX-99.x 附件（业绩新闻稿），最多一份。"""
        base = f"{ARCHIVE_BASE}/{cik_int}/{acc_nodash}"
        try:
            idx = client.get_json(f"{base}/index.json")
        except httpx.HTTPError:
            return []
        for item in idx.get("directory", {}).get("item", []):
            name = item.get("name", "")
            if name == primary_doc or not name.lower().endswith((".htm", ".html")):
                continue
            if not _EX99_RE.search(name):
                continue
            try:
                text = _html_to_text(client.get_text(f"{base}/{name}"))
            except httpx.HTTPError:
                continue
            if len(text) < 200:
                continue
            body, truncated = self._clip(text)
            return [FilingSection(
                item="EX-99", title="附件 EX-99 业绩新闻稿", text=body,
                char_count=len(body), truncated=truncated,
            )]
        return []

    def _clip(self, text: str) -> tuple[str, bool]:
        limit = self.section_max_chars
        if limit <= 0 or len(text) <= limit:
            return text, False
        return text[:limit].rstrip(), True

    # ------------------------------------------------------------------
    def _fetch_tables(
        self, client: SecClient, ticker: str, cik_int: str,
        acc_nodash: str, filed: str,
    ) -> list[StatementTable]:
        """从 FilingSummary.xml 找出分部/分产品明细表并抽成结构化行。"""
        base = f"{ARCHIVE_BASE}/{cik_int}/{acc_nodash}"
        try:
            summary = client.get_text(f"{base}/FilingSummary.xml")
            root = ET.fromstring(summary)
        except (httpx.HTTPError, ET.ParseError):
            return []

        out: list[StatementTable] = []
        for rep in root.findall(".//Report"):
            name = (rep.findtext("ShortName") or "").strip()
            fn = rep.findtext("HtmlFileName") or rep.findtext("XmlFileName") or ""
            if not fn or not name:
                continue
            if not (_DETAIL_RE.search(name) and _TABLE_INCLUDE_RE.search(name)):
                continue
            if _TABLE_EXCLUDE_RE.search(name):
                continue
            try:
                parsed = self._parse_r_table(client.get_text(f"{base}/{fn}"))
            except httpx.HTTPError:
                continue
            if parsed is None or not parsed["rows"]:
                continue
            out.append(StatementTable(
                ticker=ticker.upper(), title=name, source_form="10-K",
                filing_date=filed, url=f"{base}/{fn}",
                units=parsed["units"], period_label=parsed["period_label"],
                columns=parsed["columns"], rows=parsed["rows"],
            ))
            if len(out) >= self.max_tables:
                break
        return out

    @staticmethod
    def _parse_r_table(html: str) -> Optional[dict]:
        """R*.htm → 拍平后的规整表。

        原始结构长这样（每个分组名单独占一行，组内再重复一遍科目名）：

            [标题 - USD ($) $ in Millions] [12 Months Ended]
            [Sep. 27, 2025] [Sep. 28, 2024] [Sep. 30, 2023]
            [Disaggregation of Revenue [Line Items]]      <- XBRL 噪音，丢弃
            [Net sales] [416,161] [391,035] [383,285]
            [iPhone]                                       <- 分组名
            [Disaggregation of Revenue [Line Items]]
            [Net sales] [209,586] [201,183] [200,583]      <- 实为 iPhone 的收入

        拍平后行标签变成「iPhone · Net sales」，每行都能独立读懂。
        """
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table")
        if table is None:
            return None

        raw: list[list[str]] = []
        for tr in table.find_all("tr"):
            cells = [
                re.sub(r"\s+", " ", td.get_text(" ").strip())
                for td in tr.find_all(["th", "td"])
            ]
            cells = [c for c in cells if c not in ("", "$")]
            if cells:
                raw.append(cells)
        if len(raw) < 2:
            return None

        # 第 1 行：标题（含单位）+ 期间口径；第 2 行：各期表头。
        # 有些表把日期直接并在第 1 行（如只有单一时点的长期资产表）。
        head = raw[0]
        title_cell = head[0]
        units = None
        # 标题形如 "Revenue - Disaggregated Net Sales ... (Details) - USD ($) $ in Millions"，
        # 单位在最后一段，按 " - " 切开取尾段，避免正则贪掉整个标题
        tail = [p.strip() for p in title_cell.split(" - ")][-1]
        if re.search(r"USD|in (?:Millions|Thousands|Billions)|shares", tail, re.I):
            units = tail
        period_label = head[1] if len(head) > 1 and not _looks_like_date(head[1]) else None

        if len(head) > 1 and _looks_like_date(head[1]):
            columns, body = head[1:], raw[1:]
        else:
            columns, body = raw[1], raw[2:]

        # 单独成行的标签有两类：XBRL 轴标签（如 NVIDIA 的「Revenues and
        # Long-Lived Assets」，在每个真实分组后都重复一次，会把分组名冲掉）
        # 和真正的分组名（United States、iPhone…）。前者反复出现、后者只出现
        # 一次，据此区分比枚举关键词可靠。
        singles = [c[0] for c in body if len(c) == 1]
        repeated = {s for s in singles if singles.count(s) > 1}

        rows: list[list[str]] = []
        group: Optional[str] = None
        for cells in body:
            if len(cells) == 1:
                label = cells[0]
                # [Line Items] / [Abstract] 等结构标记，以及重复出现的轴标签
                if re.search(r"\[(line items|abstract|member|axis|domain)\]", label, re.I):
                    continue
                if label in repeated:
                    continue
                group = label
                continue
            # 脚注正文会被渲染成一整行：首格以 [1] 之类角标开头，或整格是大段散文。
            # 正常科目名最长也就百来字符（如 Apple 那句「Portion of total net
            # sales...」98 字符），150 是安全阈值。
            if re.match(r"^\[\d+\]", cells[0]) or any(len(x) > 150 for x in cells):
                continue
            label = f"{group} · {cells[0]}" if group else cells[0]
            # 脚注角标 [1] 是「该期未单独披露」的标记，不是数值。
            # 替换成 — 而不是删掉，否则后面的数字会整体左移、对错年份。
            values = ["—" if re.fullmatch(r"\[\d+\]", x) else x for x in cells[1:]]
            # 补齐/截断到表头列数，保证是规整矩形
            values = (values + ["—"] * len(columns))[: len(columns)]
            rows.append([label] + values)

        if not columns or not rows:
            return None
        return {
            "units": units,
            "period_label": period_label,
            "columns": columns,
            "rows": rows,
        }
