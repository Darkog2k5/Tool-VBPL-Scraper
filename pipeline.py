import argparse
import json
import re
import sys
from pathlib import Path

from loguru import logger

from config import (
    DEFAULT_PAGE_SIZE,
    DEFAULT_TYPE_ID,
    DOC_TYPE_CHOICES,
    KNOWN_TOTAL_PAGES,
    OUTPUT_DIR,
    ensure_directories,
)
from exporter.to_docx import convert_to_docx
from exporter.to_json import convert_to_json
from logging_setup import setup_logging
from exporter.common import safe_filename
from scraper.detail_scraper import scrape_document
from scraper.list_scraper import get_total_pages, scrape_all_pages

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

PROCESSED_PATH = Path(OUTPUT_DIR) / "state" / "processed_urls.txt"
FAILED_PATH = Path(OUTPUT_DIR) / "state" / "failed_urls.jsonl"


def _safe_cache_key(type_id: str, keyword: str, page_size: int) -> str:
    type_part = f"type_{type_id or 'all'}"
    keyword_part = re.sub(r"[^A-Za-z0-9_-]+", "_", keyword.strip()) or "no_keyword"
    return f"vbpl_api_list_items_{type_part}_{keyword_part}_ps{page_size}.jsonl"


def _list_cache_path(type_id: str, keyword: str, page_size: int) -> Path:
    return Path(OUTPUT_DIR) / "list" / _safe_cache_key(type_id, keyword, page_size)


def _load_processed_urls() -> set[str]:
    if not PROCESSED_PATH.exists():
        return set()
    return {line.strip() for line in PROCESSED_PATH.read_text(encoding="utf-8").splitlines() if line.strip()}


def _mark_processed(key: str) -> None:
    PROCESSED_PATH.parent.mkdir(parents=True, exist_ok=True)
    with PROCESSED_PATH.open("a", encoding="utf-8") as handle:
        handle.write(key + "\n")


def _mark_failed(item: dict, reason: str) -> None:
    FAILED_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "item_id": item.get("item_id", ""),
        "url": item.get("url_toanvan", item.get("url", "")),
        "title": item.get("title", ""),
        "reason": reason,
    }
    with FAILED_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _item_key(item: dict) -> str:
    return item.get("item_id") or item.get("url_toanvan") or item.get("url", "")


def _ask_yes_no(prompt: str, default: bool = False) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        answer = input(f"{prompt} ({suffix}): ").strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes", "co", "c", "1"}:
            return True
        if answer in {"n", "no", "khong", "k", "0"}:
            return False
        print("Vui lòng nhập y hoặc n.")


def _ask_positive_int(prompt: str, default: int = 1, allow_zero: bool = False) -> int:
    while True:
        answer = input(f"{prompt} [{default}]: ").strip()
        if not answer:
            return default
        try:
            value = int(answer)
        except ValueError:
            print("Vui lòng nhập số nguyên.")
            continue
        if value > 0 or (allow_zero and value == 0):
            return value
        print("Giá trị phải lớn hơn 0.")


def _ask_doc_type(page_size: int = DEFAULT_PAGE_SIZE) -> str:
    print("\nĐang lấy số văn bản/page theo từng hình thức từ VBPL...")
    summaries = {}
    for type_id, _ in DOC_TYPE_CHOICES:
        try:
            summaries[type_id] = get_total_pages(type_id=type_id, keyword="", page_size=page_size)
        except Exception:
            summaries[type_id] = (0, 0)

    print(f"\nChọn hình thức văn bản cần download (page size tạm tính: {page_size}):")
    for index, (_, label) in enumerate(DOC_TYPE_CHOICES, start=1):
        total_items, total_pages = summaries.get(DOC_TYPE_CHOICES[index - 1][0], (0, 0))
        if total_pages:
            print(f"  {index:>2}. {label} - {total_items} văn bản - {total_pages} page")
        else:
            print(f"  {index:>2}. {label} - chưa có dữ liệu")

    default_index = next(
        (index for index, (type_id, _) in enumerate(DOC_TYPE_CHOICES, start=1) if type_id == DEFAULT_TYPE_ID),
        1,
    )
    while True:
        answer = input(f"Nhập số lựa chọn [{default_index}]: ").strip()
        if not answer:
            return DOC_TYPE_CHOICES[default_index - 1][0]
        try:
            index = int(answer)
        except ValueError:
            print("Vui lòng nhập số trong danh sách.")
            continue
        if 1 <= index <= len(DOC_TYPE_CHOICES):
            return DOC_TYPE_CHOICES[index - 1][0]
        print("Lựa chọn không hợp lệ.")


def _doc_type_label(type_id: str) -> str:
    return next((label for choice_id, label in DOC_TYPE_CHOICES if choice_id == type_id), "Không rõ")


def _interactive_args() -> argparse.Namespace:
    print("=== VBPL downloader ===")
    print("Chương trình sẽ tải văn bản theo số page và hình thức văn bản bạn chọn.\n")

    type_id = _ask_doc_type(page_size=DEFAULT_PAGE_SIZE)
    keyword = input("\nTừ khóa tìm kiếm, bỏ trống nếu không cần: ").strip()
    page_size = _ask_positive_int("Số item mỗi page", default=DEFAULT_PAGE_SIZE)

    print("\nĐang kiểm tra tổng số page theo lựa chọn...")
    total_items, total_pages = get_total_pages(type_id=type_id, keyword=keyword, page_size=page_size)
    if total_pages:
        print(f"{_doc_type_label(type_id)} có khoảng {total_items} văn bản, tương ứng {total_pages} page.")
    else:
        total_pages = KNOWN_TOTAL_PAGES
        print("Chưa lấy được tổng page từ API, sẽ dùng mốc dự phòng.")

    all_pages = _ask_yes_no(f"Tải tất cả {total_pages} page theo lựa chọn này?", default=False)
    max_pages = total_pages if all_pages else _ask_positive_int("Tải bao nhiêu page", default=1)
    if max_pages > total_pages:
        print(f"Bạn nhập lớn hơn tổng page hiện có, sẽ tải tối đa {total_pages} page.")
        max_pages = total_pages

    limit = _ask_positive_int("Giới hạn số văn bản xử lý sau khi lấy danh sách, nhập 0 để không giới hạn", default=0,
                              allow_zero=True)
    resume = _ask_yes_no("Tiếp tục từ dữ liệu đã tải trước đó nếu có?", default=True)

    return argparse.Namespace(
        type_id=type_id,
        keyword=keyword,
        doc_type=None,
        max_pages=max_pages,
        all_pages=all_pages,
        page_size=page_size,
        limit=limit,
        no_resume=not resume,
        url="",
        interactive=True,
    )


def run_pipeline(
        type_id: str = DEFAULT_TYPE_ID,
        keyword: str = "",
        max_pages: int = 1,
        limit: int = 0,
        resume: bool = True,
        page_size: int = DEFAULT_PAGE_SIZE,
) -> None:
    ensure_directories()
    setup_logging("pipeline")
    logger.info("=" * 60)
    logger.info(
        f"Start pipeline | type_id={type_id!r} | keyword={keyword!r} | "
        f"max_pages={max_pages} | page_size={page_size} | resume={resume}"
    )

    doc_list = scrape_all_pages(
        type_id=type_id,
        keyword=keyword,
        max_pages=max_pages,
        checkpoint_path=_list_cache_path(type_id, keyword, page_size),
        resume=resume,
        page_size=page_size,
    )
    if limit:
        doc_list = doc_list[:limit]
        logger.info(f"Limited to {len(doc_list)} document(s)")

    if not doc_list:
        logger.warning("Document list is empty. Check TypeID, keyword, network, or selectors.")
        return

    processed = _load_processed_urls() if resume else set()
    logger.info(f"Already processed: {len(processed)} document(s)")

    success = 0
    failed = 0
    for index, item in enumerate(doc_list, start=1):
        key = _item_key(item)
        if key in processed:
            logger.info(f"[{index}/{len(doc_list)}] Skipped processed item: {key}")
            continue

        logger.info(f"[{index}/{len(doc_list)}] {item.get('doc_number', '?')} - {item.get('title', '')[:70]}")
        vb = scrape_document(item)
        if not vb:
            logger.warning(f"Skipped because detail scraping failed: {key}")
            _mark_failed(item, "detail_scrape_failed")
            failed += 1
            continue

        try:
            # --- CODE MỚI CẬP NHẬT ---
            # 1. Lấy tên loại văn bản (Ví dụ: "Bộ luật", "Sắc luật") làm thư mục cha
            loai_vb = safe_filename(vb.doc_type) if vb.doc_type else "Khac"

            # 2. Xử lý tên thư mục con (Số hiệu) để không bị trùng lặp các văn bản "Không số"
            raw_num = vb.doc_number
            if not raw_num or raw_num.strip().lower() == "không số":
                raw_num = f"Khong_so_{vb.item_id[:8]}"

            safe_num = safe_filename(raw_num)

            # 3. Cấu trúc đường dẫn mới: output/documents/Loại_văn_bản/Số_hiệu/
            doc_dir = Path(OUTPUT_DIR) / "documents" / loai_vb / safe_num
            doc_dir.mkdir(parents=True, exist_ok=True)

            # 4. Lưu file Word và 2 file JSON vào folder vừa tạo
            docx_path = convert_to_docx(vb, doc_dir)
            thuoc_tinh_path, luoc_do_path = convert_to_json(vb, doc_dir)

            _mark_processed(key)
            success += 1
            # --- KẾT THÚC CODE MỚI ---

        except Exception as exc:
            logger.exception(f"Failed while exporting {key}: {exc}")
            _mark_failed(item, str(exc))
            failed += 1

    logger.info("=" * 60)
    logger.info(f"Pipeline finished | success={success} | failed={failed}")
    logger.info(f"Output directory: {Path(OUTPUT_DIR).resolve()}")


def run_single_url(url: str) -> None:
    ensure_directories()
    setup_logging("pipeline")
    logger.info("=" * 60)
    logger.info(f"Start single document scrape | url={url!r}")

    vb = scrape_document(url)
    if not vb:
        logger.error("Single document scrape failed")
        return

    try:
        # --- CODE MỚI ĐƯỢC ĐỒNG BỘ ---
        safe_num = safe_filename(vb.doc_number or vb.item_id or vb.title)
        doc_dir = Path(OUTPUT_DIR) / "documents" / safe_num
        doc_dir.mkdir(parents=True, exist_ok=True)

        docx_path = convert_to_docx(vb, doc_dir)
        thuoc_tinh_path, luoc_do_path = convert_to_json(vb, doc_dir)

        logger.info(f"Single document finished: {vb.doc_number or vb.item_id}")
        # --- KẾT THÚC CODE MỚI ---

    except Exception as exc:
        logger.exception(f"Failed while exporting {url}: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pipeline scraper VBPLTW - vbpl.vn/TW")
    parser.add_argument(
        "--type-id",
        "--type_id",
        default=DEFAULT_TYPE_ID,
        help="TypeID: 2=Nghi dinh, 3=Thong tu, 4=Quyet dinh, empty=all.",
    )
    parser.add_argument("--keyword", default="", help="Search keyword.")
    parser.add_argument("--doc-type", default=None, help="Old alias for --type-id.")
    parser.add_argument("--max-pages", "--max_pages", default=1, type=int,
                        help="Maximum list pages. 0 means unlimited.")
    parser.add_argument("--all-pages", action="store_true", help=f"Scrape all known {KNOWN_TOTAL_PAGES} list pages.")
    parser.add_argument("--page-size", "--page_size", default=DEFAULT_PAGE_SIZE, type=int, help="API page size.")
    parser.add_argument("--limit", default=0, type=int, help="Maximum documents to process after listing. 0 means all.")
    parser.add_argument("--no-resume", action="store_true", help="Ignore cached list and processed item state.")
    parser.add_argument("--url", default="", help="Download one detail URL directly.")

    interactive = len(sys.argv) == 1
    args = _interactive_args() if interactive else parser.parse_args()

    try:
        if args.url:
            run_single_url(args.url)
            return

        max_pages = KNOWN_TOTAL_PAGES if args.all_pages else args.max_pages
        type_id = args.doc_type if args.doc_type is not None else args.type_id

        run_pipeline(
            type_id=type_id,
            keyword=args.keyword,
            max_pages=max_pages,
            limit=args.limit,
            resume=not args.no_resume,
            page_size=args.page_size,
        )
    finally:
        if interactive:
            input("\nHoàn tất. Nhấn Enter để đóng cửa sổ...")


if __name__ == "__main__":
    main()