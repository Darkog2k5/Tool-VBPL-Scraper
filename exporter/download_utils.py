import os
import re
import json
import base64
import shutil
import requests
from loguru import logger
from docxcompose.composer import Composer
from docx import Document
from pdf2docx import Converter


def get_attachment_links(item_id: str) -> list:
    """
    Lấy danh sách file đính kèm từ API (?parts=1,2,4).
    Ưu tiên: documentDownloadFiles > documentContentFileDocName > documentContentFileName (PDF).
    Trả về list dạng: [{"fileName": "...", "type": "docx|doc|pdf"}]
    """
    links = []
    try:
        r = requests.get(
            f"https://vbpl-bientap-gateway.moj.gov.vn/api/qtdc/public/doc/{item_id}?parts=1,2,4",
            verify=False, timeout=12
        )
        data = r.json().get("data", {})

        # Ưu tiên 1: documentDownloadFiles (danh sách file đính kèm chính thức)
        dl_files = data.get("documentDownloadFiles") or []
        for f in dl_files:
            if isinstance(f, dict):
                fname = f.get("fileName") or f.get("name") or f.get("objectName") or ""
            elif isinstance(f, str):
                fname = f
            else:
                fname = ""
            if fname and "template" not in fname.lower():
                links.append(f"nextjs://{item_id}/{fname}")

        # Ưu tiên 2: documentContentFileDocName (tên file Word gốc)
        doc_name = data.get("documentContentFileDocName") or ""
        if doc_name and "template" not in doc_name.lower():
            link = f"nextjs://{item_id}/{doc_name}"
            if link not in links:
                links.append(link)

        # Ưu tiên 3: documentContentFileName (thường là PDF)
        pdf_name = data.get("documentContentFileName") or ""
        if pdf_name and "template" not in pdf_name.lower():
            link = f"nextjs://{item_id}/{pdf_name}"
            if link not in links:
                links.append(link)

        # Ưu tiên 4: Tự động đoán tên file từ docNum (Vì frontend VBPL hiển thị các file này dù API không trả về)
        docNum = data.get("docNum") or ""
        if docNum:
            safe_name = re.sub(r"[^\w.\-]", "_", docNum)
            # Rút gọn tên file nếu docNum quá dài (bảo vệ khỏi trường hợp cán bộ nhập nhầm base64 vào Số hiệu)
            if len(safe_name) > 100:
                safe_name = safe_name[:100]
            for ext in [".doc", ".docx", ".pdf"]:
                guessed_link = f"nextjs://{item_id}/{safe_name}{ext}"
                if guessed_link not in links:
                    links.append(guessed_link)

    except Exception as e:
        logger.warning(f"Error fetching attachment list for {item_id}: {e}")

    return links


def download_file(url: str, out_path: str) -> bool:
    """Download file từ URL thường hoặc Next.js Server Action."""
    if not url.startswith("nextjs://"):
        try:
            r = requests.get(url, verify=False, stream=True, timeout=20)
            r.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
            return True
        except Exception as e:
            logger.warning(f"Direct download failed for {url}: {e}")
            return False

    parts = url.replace("nextjs://", "").split("/", 1)
    if len(parts) != 2:
        return False
    folder_name, object_name = parts

    # Xây target_url từ item_id (cần có slug hợp lệ để Next.js route không bị lỗi 500)
    target_url = f"https://vbpl.vn/van-ban/chi-tiet/van-ban--{folder_name}?tabs=tai-ve"

    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        logger.error("curl_cffi not installed. Run: pip install curl_cffi")
        return False

    hash_id = "bad13391811d5f14d7670e66189def56c08ceb1f"
    headers = {
        "accept": "text/x-component",
        "content-type": "text/plain;charset=UTF-8",
        "next-action": hash_id,
        "origin": "https://vbpl.vn",
        "referer": target_url,
    }

    for bucket in ["vbpl", "moj"]:
        payload = json.dumps([{
            "bucketName": bucket,
            "folderName": folder_name,
            "objectName": object_name,
            "preview": None
        }])

        import time
        # Thử tối đa 2 lần cho mỗi bucket (tổng cộng 4 lần cho cả 2 bucket) để cân bằng giữa rate limit và tốc độ
        for attempt in range(2):
            try:
                if attempt == 0:
                    logger.info(f"Downloading {object_name} from bucket={bucket}...")
                r = cffi_requests.post(
                    target_url, headers=headers, data=payload,
                    impersonate="chrome110", verify=False, timeout=30
                )
                if r.status_code == 200:
                    break

                # Lỗi 500 digest của Next.js có thể là 404 (file không tồn tại) hoặc 429 (rate limit).
                # Vì Frontend VBPL thường xuyên hiển thị "nút bấm ma" cho các file không có thật (logic tự đoán tên file),
                # nên ta chỉ thử lại 1 lần duy nhất cho mỗi bucket. Nếu vẫn 500, khả năng 99% là file ảo.
                if r.status_code == 500 and b'"digest":' in r.content:
                    if attempt >= 1:
                        logger.debug(f"File {object_name} trên {bucket} văng lỗi Next.js liên tục (chắc chắn là file ảo). Bỏ qua.")
                        break
                    time.sleep(2)
                    continue

                logger.warning(f"Got status {r.status_code} for {object_name} (attempt {attempt+1}/2), retrying in 3s...")
                time.sleep(3)
            except Exception as e:
                logger.warning(f"POST request failed (bucket={bucket}, attempt {attempt+1}/2): {e}")
                time.sleep(3)

        if r.status_code != 200 or b"Sorry, you have been blocked" in r.content[:200]:
            if not (r.status_code == 500 and b'"digest":' in r.content):
                logger.warning(f"Blocked or error (status={r.status_code}) for bucket={bucket}")
            continue

        content_text = r.content.decode("utf-8", errors="ignore")

        # --- Parse RSC response format ---
        # Format mới: JSON object {data: "<base64>", mimeType: "..."} trong RSC stream
        # Tìm pattern: 0:{"data":"<base64>","mimeType":"..."} hoặc tương tự


        json_match = re.search(
            r'(?:^|\n)[0-9a-zA-Z]+:(\{"data":"([A-Za-z0-9+/=]+)","mimeType":"([^"]+)"\})',
            content_text
        )
        if json_match:
            try:
                decoded = base64.b64decode(json_match.group(2))
                # Kiểm tra không phải fake Excel
                if b"xl/workbook.xml" in decoded and not out_path.lower().endswith((".xlsx", ".xls")):
                    logger.warning(f"Fake Excel file detected from bucket={bucket}, skipping")
                    continue
                with open(out_path, "wb") as f:
                    f.write(decoded)
                logger.info(f"Downloaded {object_name} via RSC JSON format ({len(decoded)} bytes)")
                return True
            except Exception as e:
                logger.warning(f"Failed to decode base64 from RSC JSON: {e}")

        # Format cũ (dự phòng): RSC binary stream với hex-length prefix
        old_match = re.search(r"(?:\n|^)[0-9a-zA-Z]+:T([0-9a-fA-F]+),", content_text)
        if old_match:
            try:
                length = int(old_match.group(1), 16)
                start_idx = old_match.end()
                b64_data = content_text[start_idx: start_idx + length]
                decoded = base64.b64decode(b64_data)
                if b"xl/workbook.xml" in decoded and not out_path.lower().endswith((".xlsx", ".xls")):
                    logger.warning(f"Fake Excel from bucket={bucket}, skipping")
                    continue
                with open(out_path, "wb") as f:
                    f.write(decoded)
                logger.info(f"Downloaded {object_name} via RSC T-format ({len(decoded)} bytes)")
                return True
            except Exception as e:
                logger.warning(f"Failed to decode RSC T-format: {e}")

        # Raw binary fallback (DOCX/DOC magic bytes)
        if b"PK\x03\x04" in r.content[:10] or b"\xd0\xcf\x11\xe0" in r.content[:10]:
            if b"xl/workbook.xml" in r.content and not out_path.lower().endswith((".xlsx", ".xls")):
                logger.warning(f"Fake Excel (raw) from bucket={bucket}, skipping")
                continue
            with open(out_path, "wb") as f:
                f.write(r.content)
            logger.info(f"Downloaded {object_name} as raw binary from bucket={bucket}")
            return True

    logger.warning(f"All buckets failed for {object_name}")
    return False


def merge_docx(files: list, out_file: str) -> None:
    """Merge nhiều file docx thành một."""
    if not files:
        return
    if len(files) == 1:
        shutil.copy(files[0], out_file)
        return
    master = Document(files[0])
    composer = Composer(master)
    for file in files[1:]:
        composer.append(Document(file))
    composer.save(out_file)


def pdf_to_docx(pdf_file: str, docx_file: str) -> bool:
    """Convert PDF sang DOCX."""
    try:
        cv = Converter(pdf_file)
        cv.convert(docx_file, start=0, end=None)
        cv.close()
        return True
    except Exception as e:
        logger.error(f"Failed to convert {pdf_file} to docx: {e}")
        return False


def process_fallback_downloads(item_id: str, out_dir: str) -> str | None:
    """
    Tải file đính kèm cho văn bản không có nội dung HTML.
    Ưu tiên: DOCX → DOC → PDF.
    Trả về đường dẫn file lớn nhất nếu thành công, None nếu thất bại.
    """
    links = get_attachment_links(item_id)
    if not links:
        logger.warning(f"No attachments found for item_id={item_id}")
        return None

    logger.info(f"Found {len(links)} attachment link(s) for {item_id}: {[l.split('/')[-1] for l in links]}")

    # Phân nhóm theo định dạng
    docx_links = [l for l in links if l.lower().endswith(".docx")]
    doc_links  = [l for l in links if l.lower().endswith(".doc")]
    pdf_links  = [l for l in links if l.lower().endswith(".pdf")]
    other_links = [l for l in links if l not in docx_links + doc_links + pdf_links]

    targets = docx_links + doc_links + pdf_links + other_links
    if not targets:
        logger.warning(f"No downloadable links after filtering for {item_id}")
        return None

    downloaded_files = []
    for i, link in enumerate(targets):
        fname = link.split("/")[-1]
        ext = os.path.splitext(fname)[1] or ".bin"
        tmp_path = os.path.join(out_dir, f"_tmp_part_{i}{ext}")
        if download_file(link, tmp_path) and os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            downloaded_files.append((tmp_path, fname))

    if not downloaded_files:
        logger.warning(f"All downloads failed for {item_id}")
        return None

    largest_file = None
    largest_size = 0
    for tmp_path, orig_name in downloaded_files:
        # Tên file an toàn
        safe_name = re.sub(r"[^\w.\-]", "_", orig_name)
        if not safe_name:
            safe_name = f"noi_dung_{i}{os.path.splitext(tmp_path)[1]}"
        target_path = os.path.join(out_dir, safe_name)
        # Tránh ghi đè
        counter = 1
        base_part, ext_part = os.path.splitext(target_path)
        while os.path.exists(target_path):
            target_path = f"{base_part}_{counter}{ext_part}"
            counter += 1
        shutil.copy(tmp_path, target_path)
        logger.info(f"Saved attachment: {target_path}")
        size = os.path.getsize(target_path)
        if size > largest_size:
            largest_size = size
            largest_file = target_path

    # Dọn temp files
    for tmp_path, _ in downloaded_files:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass

    return largest_file

