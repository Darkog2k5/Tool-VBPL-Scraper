import base64
import re
import time
from dataclasses import asdict, dataclass, field as dc_field

import requests
from bs4 import BeautifulSoup
from loguru import logger

from config import API_DETAIL_URL, API_HEADERS, MAX_RETRIES, REQUEST_DELAY, REQUEST_TIMEOUT
from scraper.pdf_extractor import extract_text_from_pdf, is_pdf, save_pdf


UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
LEGACY_ID_RE = re.compile(r"--(\d+)(?:[/?#].*)?$")


@dataclass
class VBDocument:
    item_id: str = ""
    url_toanvan: str = ""
    title: str = ""
    doc_number: str = ""
    doc_type: str = ""
    issue_date: str = ""
    effective_date: str = ""
    expiration_date: str = ""
    issuer: str = ""
    signer: str = ""
    signer_title: str = ""
    gazette_number: str = ""
    gazette_date: str = ""
    industry: str = ""
    field: str = ""
    scope: str = ""
    status: str = ""
    issuing_people: list[dict] = dc_field(default_factory=list)
    full_text: str = ""
    content_html: str = dc_field(default="", repr=False)  # HTML gốc để giữ formatting
    content_source: str = ""          # "html", "pdf", "pdf_ocr", "summary_only", "none"
    pdf_bytes: bytes = dc_field(default=b"", repr=False)
    articles: list[dict] = dc_field(default_factory=list)
    related_docs: list[dict] = dc_field(default_factory=list)
    signature: dict = dc_field(default_factory=dict)
    relationship_graph: dict = dc_field(default_factory=dict)

    @property
    def url(self) -> str:
        return self.url_toanvan

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("pdf_bytes", None)
        d.pop("content_html", None)  # Không serialize HTML lớn vào JSON
        return d


def _get_json(session: requests.Session, url: str) -> dict | None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning(f"API detail request failed {attempt}/{MAX_RETRIES}: {exc}")
            time.sleep(REQUEST_DELAY * attempt)
    return None


def _unwrap_response(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else payload


def _name(value) -> str:
    if isinstance(value, dict):
        return value.get("name") or value.get("title") or value.get("code") or ""
    return str(value or "")


def _date(value: str | None) -> str:
    return (value or "").split("T", 1)[0]


def _join_names(items: list | None) -> str:
    if not isinstance(items, list):
        return ""
    return ", ".join(name for name in (_name(item) for item in items) if name)


def _issuing_people(data: dict) -> list[dict]:
    people = []
    issues = data.get("documentIssues") or []
    if not isinstance(issues, list):
        return people

    for issue in issues:
        if not isinstance(issue, dict):
            continue
        people.append(
            {
                "agency_id": issue.get("agencyId") or "",
                "agency_name": issue.get("agencyName") or "",
                "person_id": issue.get("personId") or "",
                "person_name": issue.get("personName") or "",
                "job_title_id": issue.get("jobTitleId") or "",
                "job_title_code": issue.get("jobTitleCode") or "",
                "job_title_name": issue.get("jobTitleName") or "",
                "order_index": issue.get("orderIndex"),
            }
        )
    return people


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    lines = []
    for block in soup.select("p, li, h1, h2, h3, h4, h5, h6"):
        text = block.get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            lines.append(text)
    if not lines:
        text = soup.get_text(" ", strip=True)
        return re.sub(r"\s+", " ", text).strip()

    deduped = []
    for line in lines:
        if deduped and deduped[-1] == line:
            continue
        deduped.append(line)
    return "\n".join(deduped)


def _html_lines(html: str) -> list[str]:
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()

    lines = []
    for block in soup.select("p, td, th"):
        text = block.get_text(" ", strip=True)
        text = re.sub(r"\s+", " ", text).strip()
        if text and text not in lines[-3:]:
            lines.append(text)
    return lines


def _is_signature_title(line: str) -> bool:
    text = re.sub(r"\s+", " ", line or "").strip().upper()
    if not text:
        return False
    if len(text) > 160 or text.startswith(("NƠI NHẬN", "LƯU:", "KÍNH GỬI")):
        return False
    title_markers = (
        "TM.",
        "KT.",
        "TL.",
        "TUQ.",
        "THỦ TƯỚNG",
        "PHÓ THỦ TƯỚNG",
        "BỘ TRƯỞNG",
        "THỨ TRƯỞNG",
        "CHỦ TỊCH",
        "PHÓ CHỦ TỊCH",
        "CHÁNH ÁN",
        "VIỆN TRƯỞNG",
        "TỔNG KIỂM TOÁN",
        "THỐNG ĐỐC",
    )
    if text.startswith(("TM.", "KT.", "TL.", "TUQ.")):
        return True
    return any(text.startswith(marker) for marker in title_markers[4:])


def _is_person_name(line: str) -> bool:
    text = re.sub(r"\s+", " ", line or "").strip()
    if not text or re.search(r"\d", text):
        return False
    upper = text.upper()
    blocked = (
        "TM.",
        "KT.",
        "THỦ TƯỚNG",
        "PHÓ THỦ TƯỚNG",
        "BỘ TRƯỞNG",
        "CHỦ TỊCH",
        "PHỤ LỤC",
        "NƠI NHẬN",
        "LƯU:",
        "CHÍNH PHỦ",
        "CỘNG HÒA",
        "ĐÃ KÝ",
    )
    if any(item in upper for item in blocked):
        return False
    words = text.split()
    return 2 <= len(words) <= 6 and all(word[:1].isupper() for word in words if word[:1].isalpha())


def _extract_signature(html: str, data: dict) -> tuple[str, str, dict]:
    people = _issuing_people(data)
    signer = data.get("signer") or data.get("signerName") or ""
    signer_title = data.get("signerTitle") or data.get("positionName") or data.get("position") or ""
    if people:
        signer = signer or ", ".join(person["person_name"] for person in people if person.get("person_name"))
        signer_title = signer_title or ", ".join(person["job_title_name"] for person in people if person.get("job_title_name"))
        if signer or signer_title:
            return signer, signer_title, {
                "signer": signer,
                "signer_title": signer_title,
                "issuing_people": people,
                "confidence": "api_document_issues",
            }

    lines = _html_lines(html)
    confidence = "api" if signer or signer_title else ""

    signed_indexes = [index for index, line in enumerate(lines) if "Đã ký" in line or "Ðã ký" in line]
    search_starts = signed_indexes or [
        index
        for index, line in enumerate(lines)
        if _is_signature_title(line)
    ][-5:]

    for index in search_starts:
        window_before = lines[max(0, index - 5) : index + 1]
        window_after = lines[index + 1 : index + 8]
        signed_line = lines[index]

        if not signer_title:
            title_parts = [line for line in window_before if _is_signature_title(line)]
            if title_parts:
                signer_title = re.sub(r"\(?Đã ký\)?.*$", "", " ".join(title_parts[-3:])).strip()

        if not signer:
            signed_match = re.search(r"\(?Đã ký\)?\s*(.+)$", signed_line, re.IGNORECASE)
            if signed_match and _is_person_name(signed_match.group(1)):
                signer = signed_match.group(1).strip()
            for line in window_after:
                if _is_person_name(line):
                    signer = line
                    break

        if signer and signer_title:
            confidence = confidence or "content"
            break

    return signer, signer_title, {
        "signer": signer,
        "signer_title": signer_title,
        "issuing_people": people,
        "confidence": confidence or "not_found",
    }


def _extract_articles(full_text: str) -> list[dict]:
    pattern = re.compile(
        r"(Điều\s+\d+[\.:]?\s*[^\n]*)\n(.*?)(?=Điều\s+\d+|$)",
        re.IGNORECASE | re.DOTALL,
    )

    articles = []

    # ── Trích preamble (phần trước Điều 1): quốc hiệu, căn cứ... ────────────
    first_match = pattern.search(full_text)
    if first_match and first_match.start() > 0:
        preamble_text = full_text[: first_match.start()].strip()
        if preamble_text:
            articles.append(
                {
                    "article_number": "",
                    "title": "",
                    "content": preamble_text,
                    "_is_preamble": True,
                }
            )

    # ── Trích các Điều ───────────────────────────────────────────────────────
    for match in pattern.finditer(full_text):
        header = match.group(1).strip()
        content = match.group(2).strip()
        number_match = re.search(r"Điều\s+(\d+)", header, re.IGNORECASE)
        articles.append(
            {
                "article_number": number_match.group(1) if number_match else "",
                "title": header,
                "content": content,
            }
        )
    return articles


def _extract_item_id(item_or_url, base_meta: dict | None = None) -> tuple[str, dict]:
    if isinstance(item_or_url, dict):
        item = dict(item_or_url)
        item_id = item.get("item_id") or item.get("id") or ""
        if item_id:
            return item_id, item
        for key in ("url_toanvan", "url", "api_detail_url"):
            raw = item.get(key, "") or ""
            match = UUID_RE.search(raw)
            if match:
                return match.group(0), item
            legacy_match = LEGACY_ID_RE.search(raw)
            if legacy_match:
                return legacy_match.group(1), item
        return "", item

    item = dict(base_meta or {})
    raw = str(item_or_url)
    item["url_toanvan"] = raw
    item["url"] = raw
    match = UUID_RE.search(raw)
    if match:
        return match.group(0), item
    legacy_match = LEGACY_ID_RE.search(raw)
    return (legacy_match.group(1) if legacy_match else ""), item


def _related_docs(data: dict) -> list[dict]:
    related = data.get("documentRelatedList") or data.get("references") or []
    docs = []
    if not isinstance(related, list):
        return docs

    for item in related:
        if not isinstance(item, dict):
            continue
        doc = item.get("document") if isinstance(item.get("document"), dict) else item
        item_id = doc.get("id") or doc.get("docId") or ""
        docs.append(
            {
                "item_id": item_id,
                "title": doc.get("title") or item.get("title") or "",
                "doc_number": doc.get("docNum") or item.get("docNum") or "",
                "url": f"https://vbpl.vn/van-ban/chi-tiet/{item_id}" if item_id else "",
            }
        )
    return docs


RELATION_TYPE_LABELS = {
    "1": "Quan hệ loại 1",
    "3": "Văn bản căn cứ / dẫn chiếu",
    "4": "Văn bản liên quan",
    "9": "Văn bản được hướng dẫn, quy định chi tiết",
    "10": "Văn bản sửa đổi, bổ sung",
    "12": "Văn bản thay thế, bãi bỏ, hết hiệu lực",
}


def _doc_ref(item: dict) -> dict:
    item_id = str(item.get("id") or item.get("docId") or "")
    return {
        "item_id": item_id,
        "title": item.get("name") or item.get("title") or "",
        "url": f"https://vbpl.vn/van-ban/chi-tiet/{item_id}" if item_id else "",
    }


def _relationship_graph(diagram: dict, current_doc: dict) -> dict:
    current = {
        "item_id": current_doc.get("id") or "",
        "title": current_doc.get("title") or "",
        "doc_number": current_doc.get("docNum") or "",
    }
    nodes = {current["item_id"]: {**current, "role": "current"}}
    edges = []

    def add_bucket(bucket_name: str, direction: str) -> None:
        groups = diagram.get(bucket_name) or {}
        if not isinstance(groups, dict):
            return
        for relation_type, docs in groups.items():
            if not isinstance(docs, list):
                continue
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                ref = _doc_ref(doc)
                if not ref["item_id"]:
                    continue
                nodes.setdefault(ref["item_id"], {**ref, "role": "related"})
                if direction == "outgoing":
                    source_id, target_id = current["item_id"], ref["item_id"]
                else:
                    source_id, target_id = ref["item_id"], current["item_id"]
                edges.append(
                    {
                        "source_id": source_id,
                        "target_id": target_id,
                        "relation_type_code": str(relation_type),
                        "relation_type": RELATION_TYPE_LABELS.get(str(relation_type), f"Quan hệ loại {relation_type}"),
                        "source_bucket": bucket_name,
                    }
                )

    add_bucket("documentNamesByType", "outgoing")
    add_bucket("documentNamesBySource", "incoming")
    return {"nodes": list(nodes.values()), "edges": edges, "raw": diagram}


def _find_pdf_urls(data: dict) -> list[str]:
    """
    Tìm tất cả URL có thể tải PDF từ response data.
    API trả về cấu trúc khác nhau tùy loại văn bản.
    """
    urls = []

    # Kiểm tra các trường phổ biến chứa file URL
    for key in ("fileUrl", "pdfUrl", "filePath", "downloadUrl", "contentUrl"):
        val = data.get(key)
        if val and isinstance(val, str):
            urls.append(val)

    # Kiểm tra trong documentContent
    doc_content = data.get("documentContent")
    if isinstance(doc_content, dict):
        for key in ("fileUrl", "pdfUrl", "filePath", "downloadUrl"):
            val = doc_content.get(key)
            if val and isinstance(val, str):
                urls.append(val)

    # Kiểm tra documentFiles / attachments
    for list_key in ("documentFiles", "files", "attachments", "documentAttachments"):
        file_list = data.get(list_key)
        if not isinstance(file_list, list):
            continue
        for file_item in file_list:
            if not isinstance(file_item, dict):
                continue
            for url_key in ("url", "fileUrl", "downloadUrl", "path", "filePath"):
                val = file_item.get(url_key)
                if val and isinstance(val, str):
                    urls.append(val)
                    break

    return urls


def _try_decode_base64_pdf(data: dict) -> bytes | None:
    """
    Kiểm tra nếu response chứa PDF base64-encoded.
    Một số văn bản cũ trả về dạng này thay vì HTML.
    """
    doc_content = data.get("documentContent")
    if isinstance(doc_content, dict):
        # Tìm trường chứa base64 data
        for key in ("content", "fileContent", "pdfContent", "base64", "data"):
            val = doc_content.get(key)
            if not val or not isinstance(val, str):
                continue
            # Kiểm tra nếu là base64 PDF (bắt đầu bằng JVBERi = %PDF-)
            if val.startswith("JVBERi") or val.startswith("JVBER"):
                try:
                    pdf_bytes = base64.b64decode(val)
                    if is_pdf(pdf_bytes):
                        logger.info("Found base64-encoded PDF in documentContent")
                        return pdf_bytes
                except Exception:
                    pass

    # Kiểm tra top-level fields
    for key in ("content", "fileContent", "pdfContent", "base64Content"):
        val = data.get(key)
        if not val or not isinstance(val, str):
            continue
        if val.startswith("JVBERi") or val.startswith("JVBER"):
            try:
                pdf_bytes = base64.b64decode(val)
                if is_pdf(pdf_bytes):
                    logger.info(f"Found base64-encoded PDF in field '{key}'")
                    return pdf_bytes
            except Exception:
                pass

    return None


def _download_pdf(session: requests.Session, url: str) -> bytes | None:
    """Tải PDF từ URL."""
    try:
        if not url.startswith("http"):
            url = f"https://vbpl-bientap-gateway.moj.gov.vn{url}"
        logger.info(f"Downloading PDF: {url}")
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        content = resp.content
        if is_pdf(content):
            return content
        # Có thể response trả về JSON chứa base64
        try:
            json_data = resp.json()
            if isinstance(json_data, dict):
                for key in ("data", "content", "file", "fileContent"):
                    val = json_data.get(key)
                    if isinstance(val, str) and val.startswith("JVBERi"):
                        return base64.b64decode(val)
        except (ValueError, KeyError):
            pass
    except requests.RequestException as exc:
        logger.debug(f"PDF download failed: {exc}")
    return None


def _try_pdf_endpoints(session: requests.Session, item_id: str) -> bytes | None:
    """
    Thử tải PDF từ các endpoint phổ biến của API.
    Kiểm tra nhiều pattern vì cấu trúc API có thể khác nhau.
    """
    endpoints = [
        f"{API_DETAIL_URL}/{item_id}/file",
        f"{API_DETAIL_URL}/{item_id}/download",
        f"{API_DETAIL_URL}/{item_id}/content",
        f"{API_DETAIL_URL}/{item_id}/pdf",
    ]
    for url in endpoints:
        pdf_bytes = _download_pdf(session, url)
        if pdf_bytes:
            return pdf_bytes
    return None


def _log_available_keys(data: dict, label: str = "API response") -> None:
    """Log tất cả keys trong data để debug cấu trúc response."""
    if not data:
        return
    keys = sorted(data.keys())
    logger.debug(f"{label} keys ({len(keys)}): {keys}")
    # Log sub-keys cho documentContent
    dc = data.get("documentContent")
    if isinstance(dc, dict):
        dc_keys = sorted(dc.keys())
        logger.debug(f"  documentContent keys: {dc_keys}")


def _extract_content_with_fallback(
    session: requests.Session,
    data: dict,
    item_id: str,
    item: dict,
) -> tuple[str, str, bytes]:
    """
    Trích xuất nội dung văn bản với chuỗi fallback nhiều tầng.

    Returns:
        tuple[str, str, bytes]: (full_text, content_source, pdf_bytes)
            content_source: "html" | "pdf" | "pdf_ocr" | "summary_only" | "none"
    """
    _log_available_keys(data, "Document API")

    full_text = ""
    content_source = "none"
    pdf_bytes = b""

    # ── Source 1: HTML content từ documentContent ────────────────────────────
    content_html = ""
    if isinstance(data.get("documentContent"), dict):
        raw_content = data["documentContent"].get("content") or ""
        # Kiểm tra nếu content là HTML thật (không phải base64 PDF)
        if raw_content and not raw_content.startswith("JVBERi"):
            content_html = raw_content

    if content_html:
        full_text = _html_to_text(content_html)
        if full_text and len(full_text.strip()) > 50:
            content_source = "html"
            logger.info(f"Content source: HTML ({len(full_text)} chars)")
            return full_text, content_source, pdf_bytes

    # ── Source 2: Base64 PDF trong response ──────────────────────────────────
    logger.info("HTML content not found or too short, checking for PDF...")
    pdf_bytes = _try_decode_base64_pdf(data) or b""

    # ── Source 3: PDF từ file URLs trong response ────────────────────────────
    if not pdf_bytes:
        pdf_urls = _find_pdf_urls(data)
        for url in pdf_urls:
            pdf_bytes = _download_pdf(session, url) or b""
            if pdf_bytes:
                break

    # ── Source 4: Thử các PDF endpoints ──────────────────────────────────────
    if not pdf_bytes:
        pdf_bytes = _try_pdf_endpoints(session, item_id) or b""

    # ── Extract text từ PDF nếu có ───────────────────────────────────────────
    if pdf_bytes:
        logger.info(f"PDF found ({len(pdf_bytes):,} bytes), extracting text...")
        full_text, method = extract_text_from_pdf(pdf_bytes)
        if full_text:
            content_source = "pdf" if method == "text_layer" else "pdf_ocr"
            logger.info(f"Content source: {content_source} ({len(full_text)} chars)")
            return full_text, content_source, pdf_bytes
        else:
            logger.warning("PDF found but text extraction failed")

    # ── Source 5: Tóm tắt (docAbs / summary) ────────────────────────────────
    summary = data.get("docAbs") or item.get("summary", "")
    if summary:
        full_text = summary
        content_source = "summary_only"
        logger.warning(
            f"Only summary available ({len(full_text)} chars). "
            "Full text could not be extracted."
        )
        return full_text, content_source, pdf_bytes

    # ── Không lấy được nội dung ──────────────────────────────────────────────
    logger.error(
        f"Cannot extract any content for document {item_id}. "
        "documentContent, PDF, and summary are all empty."
    )
    return "", "none", pdf_bytes


def scrape_document(item_or_url, base_meta: dict | None = None) -> VBDocument | None:
    item_id, item = _extract_item_id(item_or_url, base_meta)
    if not item_id:
        logger.warning("Missing UUID document id")
        return None

    session = requests.Session()
    session.headers.update(API_HEADERS)
    api_url = f"{API_DETAIL_URL}/{item_id}"
    logger.info(f"Scraping document API: {api_url}")

    response = _get_json(session, api_url)
    if response is None:
        logger.error(f"Cannot fetch document API: {api_url}")
        return None

    data = _unwrap_response(response)
    diagram = _unwrap_response(_get_json(session, f"{api_url}/diagram"))

    # ── Trích xuất nội dung với fallback chain ────────────────────────────────
    full_text, content_source, pdf_bytes = _extract_content_with_fallback(
        session, data, item_id, item
    )

    # ── Lấy HTML cho signature extraction (nếu có) ──────────────────────────
    content_html = ""
    if isinstance(data.get("documentContent"), dict):
        raw = data["documentContent"].get("content") or ""
        if raw and not raw.startswith("JVBERi"):
            content_html = raw

    articles = _extract_articles(full_text)
    signer, signer_title, signature = _extract_signature(content_html, data)
    issuing_people = _issuing_people(data)

    doc = VBDocument(
        item_id=item_id,
        url_toanvan=item.get("url_toanvan") or item.get("url") or f"https://vbpl.vn/van-ban/chi-tiet/{item_id}",
        title=data.get("title") or item.get("title", ""),
        doc_number=data.get("docNum") or item.get("doc_number", ""),
        doc_type=_name(data.get("docType")) or item.get("doc_type", ""),
        issue_date=_date(data.get("issueDate")) or item.get("issue_date", ""),
        effective_date=_date(data.get("effFrom")) or item.get("effective_date", ""),
        expiration_date=_date(data.get("effTo")),
        issuer=data.get("agencyName") or _name(data.get("organization")) or item.get("issuer", ""),
        signer=signer,
        signer_title=signer_title,
        gazette_number=data.get("gazetteNumber") or "",
        gazette_date=_date(data.get("gazetteDate")),
        industry=_join_names(data.get("documentMajors")),
        field=_join_names(data.get("documentFields")),
        scope=data.get("scope") or "",
        status=_name(data.get("effStatus")) or data.get("status") or item.get("status", ""),
        issuing_people=issuing_people,
        full_text=full_text,
        content_html=content_html,
        content_source=content_source,
        pdf_bytes=pdf_bytes,
        articles=articles,
        related_docs=_related_docs(data),
        signature=signature,
        relationship_graph=_relationship_graph(diagram, data),
    )

    logger.info(
        f"Document parsed: {doc.doc_number or doc.item_id} "
        f"({len(articles)} article(s), source={content_source})"
    )
    time.sleep(REQUEST_DELAY)
    return doc
