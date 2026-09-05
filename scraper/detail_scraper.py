import re
import time
from dataclasses import asdict, dataclass, field as dc_field

from typing import List, Dict, Optional
import requests
from bs4 import BeautifulSoup
from loguru import logger

from config import API_DETAIL_URL, API_HEADERS, MAX_RETRIES, REQUEST_DELAY, REQUEST_TIMEOUT


UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)
LEGACY_ID_RE = re.compile(r"--([A-Za-z0-9_]+)(?:[/?#].*)?$")


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
    issuing_people: List[dict] = dc_field(default_factory=list)
    full_text: str = ""
    articles: List[dict] = dc_field(default_factory=list)
    toc: List[dict] = dc_field(default_factory=list)
    related_docs: List[dict] = dc_field(default_factory=list)
    signature: dict = dc_field(default_factory=dict)
    relationship_graph: dict = dc_field(default_factory=dict)
    content_html: str = ""
    attached_files: List[str] = dc_field(default_factory=list)

    @property
    def url(self) -> str:
        return self.url_toanvan

    def to_dict(self) -> dict:
        return asdict(self)


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

    # [LỚP BẢO VỆ 1]: Cơ chế Fallback (Dự phòng)
    # Thử tìm class 'preview-content' (với các văn bản form mới).
    # Nếu KHÔNG CÓ (do văn bản quá cũ hoặc cấu trúc web khác), tự động lấy toàn bộ trang để không bị mất dữ liệu.
    content_div = soup.find(class_="preview-content")
    target_soup = content_div if content_div else soup

    # [LỚP BẢO VỆ 2]: Dọn rác cấp độ sâu
    # Chặn đứng mọi thẻ rác có thể phá hỏng format (script, style, iframe, meta, form, nút bấm...)
    for tag in target_soup(["script", "style", "noscript", "meta", "link", "iframe", "button", "form"]):
        tag.decompose()

    # Chuyển đổi thẻ ngắt dòng trực tiếp
    for br in target_soup.find_all("br"):
        br.replace_with("\n")

    # [LỚP BẢO VỆ 3]: Ép xuống dòng bằng Danh sách Thẻ khối (Block-level) toàn diện
    # Tôi đã bổ sung thêm table, ul, ol, blockquote để quét sạch mọi cấu trúc dữ liệu bảng biểu/danh sách.
    block_tags = ["p", "div", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "ul", "ol", "blockquote"]
    for block in target_soup.find_all(block_tags):
        block.append("\n")

    # Rút trích text (dùng dấu cách " " làm vách ngăn an toàn cho các thẻ nằm ngang như span, b, i, a)
    raw_text = target_soup.get_text(separator=" ")

    # Làm sạch khoảng trắng và các dòng trống vô nghĩa
    lines = []
    for line in raw_text.split('\n'):
        clean_line = re.sub(r"\s+", " ", line).strip()
        if clean_line:
            lines.append(clean_line)

    # [LỚP BẢO VỆ 4]: Khử nhiễu các dòng trùng lặp liên tiếp
    deduped = []
    for line in lines:
        if deduped and deduped[-1] == line:
            continue
        deduped.append(line)

    return "\n".join(deduped)


def _html_lines(html: str) -> list[str]:
    """
    Kế thừa toàn bộ 4 lớp bảo vệ từ _html_to_text.
    Giúp việc bóc tách Người ký / Chức vụ cho file JSON đạt độ chính xác tối đa.
    """
    if not html:
        return []
    return _html_to_text(html).split('\n')

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


CLOSING_LINE_PATTERNS = [
    # Nơi nhận / Nơi gửi
    r"^nơi\s+(?:nhận|gửi)\s*[:\.]?",
    r"^kính\s+gửi\s*[:\.]?",
    # Thẩm quyền ký
    r"^(?:tm\.|kt\.|tl\.|tuq\.)(?:\s+|$)",
    # Xác nhận chữ ký
    r"^\s*\(?\s*(?:đã\s+ký|ký\s+thay|ký\s+(?:tên\s*)?(?:(?:và|,)\s*)?(?:đóng\s+dấu|ghi\s+rõ\s+họ\s+tên|chức\s+danh|chức\s+vụ).*|đóng\s+dấu.*)\s*\)?\s*$",
    # Chức vụ độc lập trên dòng ngắn
    r"^(?:thủ\s+tướng|phó\s+thủ\s+tướng|bộ\s+trưởng|thứ\s+trưởng|chủ\s+tịch|phó\s+chủ\s+tịch|chánh\s+án|viện\s+trưởng|tổng\s+kiểm\s+toán|thống\s+đốc|chánh\s+văn\s+phòng|cục\s+trưởng|vụ\s+trưởng|tổng\s+cục\s+trưởng)(?:\s+chính\s+phủ|\s+bộ|\s+ubnd|\s+nước)?\s*$",
    # Header văn bản lặp lại ở cuối VBHN
    r"^(?:cộng\s+hòa\s+xã\s+hội\s+chủ\s+nghĩa\s+việt\s+nam|độc\s+lập\s+-\s+tự\s+do\s+-\s+hạnh\s+phúc)\s*$",
    r"^số\s*:\s*[0-9/a-z_-]*vbhn[0-9/a-z_-]*\s*$",
    r"^ngân\s+hàng\s+nhà\s+nước(?:\s+việt\s+nam)?\s*$",
    r"^ban\s+thi\s+đua\s*-\s*khen\s+thưởng(?:\s+trung\s+ương)?\s*$",
]
CLOSING_LINE_RE = re.compile("|".join(CLOSING_LINE_PATTERNS), re.IGNORECASE)


def _strip_closing_text(text: str) -> str:
    """Lọc bỏ phần nơi nhận và chữ ký ở cuối nội dung."""
    if not text:
        return ""
    lines = text.split("\n")
    cut_idx = None
    for idx, line in enumerate(lines):
        line_clean = line.strip()
        if not line_clean:
            continue
        if CLOSING_LINE_RE.match(line_clean):
            cut_idx = idx
            break
    if cut_idx is not None:
        return "\n".join(lines[:cut_idx]).strip()
    return text.strip()


TOC_PATTERNS = [
    (1, "Phần", re.compile(r"^Phần\s+([IVXLCDM]+|\d+|[A-Z]|thứ\s+[a-zA-Zàáâãèéêìíòóôõùúýđ\s]+)(?:[\.:]\s*|\s+)(.*)$", re.IGNORECASE)),
    (2, "Chương", re.compile(r"^Chương\s+([0-9IVXLCDM]+|thứ\s+[a-zA-Zàáâãèéêìíòóôõùúýđ\s]+)(?:[\.:]\s*|\s+)(.*)$", re.IGNORECASE)),
    (3, "Mục", re.compile(r"^Mục\s+(\d+|[IVXLCDM]+)(?:[\.:]\s*|\s+)(.*)$")),
    (4, "Tiểu mục", re.compile(r"^Tiểu\s+mục\s+(\d+|[IVXLCDM]+)(?:[\.:]\s*|\s+)(.*)$")),
    (5, "Điều", re.compile(r"^Điều\s+(\d+[a-zA-Z]?)(?:[\.:]\s*|\s+)(.*)$", re.IGNORECASE)),
    (6, "Khoản", re.compile(r"^(\d+)\.\s+(.*)$")),
    (7, "Điểm", re.compile(r"^([a-zđĐ])\)\s+(.*)$")),
]

def _extract_toc(full_text: str) -> List[dict]:
    toc_tree = []
    stack = []
    
    lines = full_text.split('\n')
    in_closing_block = False
    
    for line in lines:
        line_clean = line.strip()
        if not line_clean:
            continue
            
        matched = False
        for level_num, level_name, pattern in TOC_PATTERNS:
            match = pattern.match(line_clean)
            if match:
                # Validation phòng tránh nhận diện nhầm
                if level_name == "Phần":
                    num = match.group(1).strip()
                    if not (num.isdigit() or re.match(r"^[IVXLCDM]+$", num, re.I) or (len(num) == 1 and num.isalpha()) or num.lower().startswith("thứ")):
                        continue
                        
                if level_name in ("Khoản", "Điểm"):
                    # Khoản và Điểm chỉ hợp lệ khi đã ở trong một Điều/Mục/Chương
                    if not stack:
                        continue
                        
                number = match.group(1).strip()
                title_remainder = match.group(2).strip()
                
                # Bắt đầu node TOC mới thì kết thúc cờ in_closing_block
                in_closing_block = False
                
                if level_name in ("Khoản", "Điểm"):
                    if level_name == "Khoản":
                        full_title = f"{number}. {title_remainder}".strip()
                    else:
                        full_title = f"{number}) {title_remainder}".strip()
                else:
                    full_title = f"{level_name} {number}. {title_remainder}".strip() if title_remainder else f"{level_name} {number}"
                
                node = {
                    "level": level_name,
                    "number": number,
                    "title": full_title,
                    "content": "",
                    "children": []
                }
                
                while stack and stack[-1][0] >= level_num:
                    stack.pop()
                    
                if not stack:
                    toc_tree.append(node)
                else:
                    stack[-1][1]["children"].append(node)
                    
                stack.append((level_num, node))
                matched = True
                break
                
        if not matched:
            if CLOSING_LINE_RE.match(line_clean):
                in_closing_block = True
                
            if stack and not in_closing_block:
                stack[-1][1]["content"] += ("\n" + line_clean) if stack[-1][1]["content"] else line_clean
                
    def _clean_content(nodes):
        for n in nodes:
            n["content"] = _strip_closing_text(n["content"])
            _clean_content(n["children"])
            
    _clean_content(toc_tree)
    
    def _filter_nodes(nodes):
        valid = []
        for n in nodes:
            title_clean = n.get("title", "").strip()
            if CLOSING_LINE_RE.match(title_clean):
                continue
            n["children"] = _filter_nodes(n.get("children", []))
            valid.append(n)
        return valid

    toc_tree = _filter_nodes(toc_tree)
    
    # Filter root noise
    valid_roots = ("Phần", "Chương", "Mục", "Tiểu mục", "Điều")
    toc_tree = [node for node in toc_tree if node["level"] in valid_roots]
    
    return toc_tree


def _extract_articles(full_text: str) -> list[dict]:
    pattern = re.compile(
        r"(Điều\s+\d+[\.:]?\s*[^\n]*)\n(.*?)(?=Điều\s+\d+|$)",
        re.IGNORECASE | re.DOTALL,
    )
    articles = []
    for match in pattern.finditer(full_text):
        header = match.group(1).strip()
        content = _strip_closing_text(match.group(2).strip())
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
    "1": {"outgoing": "Văn bản bị bãi bỏ", "incoming": "Văn bản bãi bỏ"},
    "2": {"outgoing": "Bản dịch", "incoming": "Bản dịch"},
    "3": {"outgoing": "Căn cứ ban hành", "incoming": "Văn bản áp dụng"},
    "4": {"outgoing": "Văn bản được dẫn chiếu", "incoming": "Văn bản dẫn chiếu"},
    "5": {"outgoing": "Văn bản bị đình chỉ thi hành", "incoming": "Văn bản đình chỉ thi hành"},
    "6": {"outgoing": "Văn bản được đính chính", "incoming": "Văn bản đính chính"},
    "7": {"outgoing": "Văn bản được hợp nhất", "incoming": "Văn bản hợp nhất"},
    "8": {"outgoing": "Văn bản được hướng dẫn áp dụng", "incoming": "Văn bản hướng dẫn áp dụng"},
    "9": {"outgoing": "Văn bản được quy định chi tiết, hướng dẫn thi hành", "incoming": "Văn bản quy định chi tiết, hướng dẫn thi hành"},
    "10": {"outgoing": "Văn bản được sửa đổi bổ sung", "incoming": "Văn bản sửa đổi bổ sung"},
    "11": {"outgoing": "Văn bản bị tạm ngưng hiệu lực", "incoming": "Văn bản tạm ngưng hiệu lực"},
    "12": {"outgoing": "Văn bản được thay thế", "incoming": "Văn bản thay thế"},
    "13": {"outgoing": "Văn bản được sửa đổi bổ sung", "incoming": "Văn bản sửa đổi bổ sung"},
    "14": {"outgoing": "Văn bản được giải thích", "incoming": "Văn bản giải thích"},
    "15": {"outgoing": "Văn bản được công bố", "incoming": "Văn bản công bố"},
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
    }
    
    relations_summary = []
    
    # Process both directions for all 15 relation codes
    for relation_code, label_data in RELATION_TYPE_LABELS.items():
        for direction, label in label_data.items():
            bucket_name = "documentNamesByType" if direction == "outgoing" else "documentNamesBySource"
            
            # Find documents for this relation
            documents = []
            bucket_data = diagram.get(bucket_name) or {}
            if isinstance(bucket_data, dict):
                docs = bucket_data.get(relation_code) or []
                if isinstance(docs, list):
                    for doc in docs:
                        if isinstance(doc, dict):
                            ref = _doc_ref(doc)
                            if ref["item_id"]:
                                documents.append(ref)
            
            relations_summary.append({
                "relation_type_code": relation_code,
                "direction": direction,
                "relation_type": label,
                "documents": documents
            })
            
    return {"current_document": current, "relations": relations_summary, "raw": diagram}

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
    content_html = ""
    if isinstance(data.get("documentContent"), dict):
        content_html = data["documentContent"].get("content") or ""
    full_text = _html_to_text(content_html) or data.get("docAbs") or item.get("summary", "")
    articles = _extract_articles(full_text)
    toc = _extract_toc(full_text)
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
        articles=articles,
        toc=toc,
        related_docs=_related_docs(data),
        signature=signature,
        relationship_graph=_relationship_graph(diagram, data),
    )

    logger.info(f"Document parsed: {doc.doc_number or doc.item_id} ({len(articles)} article(s), toc items: {len(toc)})")
    time.sleep(REQUEST_DELAY)
    return doc
