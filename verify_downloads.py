"""
verify_downloads.py
--------------------
Kiem tra doi chieu so luong van ban:
- Nguon 1: processed_urls.txt (danh sach item_id da xu ly)
- Nguon 2: Quet thuoc_tinh.json trong tung thu muc de lay item_id thuc te
=> Tim ra nhung item_id bi thieu thu muc (da xu ly nhung khong co file)

Cach dung:
    docker compose run --rm vbpl-crawler python verify_downloads.py
"""

import json
import sys
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

OUTPUT_DIR = Path("output")
DOCS_DIR = OUTPUT_DIR / "documents"
STATE_DIR = OUTPUT_DIR / "state"
PROCESSED_PATH = STATE_DIR / "processed_urls.txt"
MISSING_PATH = STATE_DIR / "missing_items.jsonl"
LIST_DIR = OUTPUT_DIR / "list"


def load_processed_ids() -> set:
    if not PROCESSED_PATH.exists():
        return set()
    return {line.strip() for line in PROCESSED_PATH.read_text(encoding="utf-8").splitlines() if line.strip()}


def scan_downloaded_ids() -> dict:
    """Quet toan bo thuoc_tinh.json, tra ve {item_id: folder_path}."""
    found = {}
    for cat_dir in DOCS_DIR.iterdir():
        if not cat_dir.is_dir():
            continue
        for doc_dir in cat_dir.iterdir():
            if not doc_dir.is_dir():
                continue
            tj = doc_dir / "thuoc_tinh.json"
            if not tj.exists():
                continue
            try:
                data = json.loads(tj.read_text(encoding="utf-8"))
                meta = data.get("metadata", {})
                item_id = str(meta.get("item_id", "") or "").strip()
                if item_id:
                    found[item_id] = str(doc_dir)
            except Exception:
                pass
    return found


def load_list_cache() -> dict:
    """Tai thong tin bo sung (title, doc_number) tu file cache danh sach."""
    info = {}
    if not LIST_DIR.exists():
        return info
    for path in LIST_DIR.glob("*.jsonl"):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    item = json.loads(line)
                    # Lay item_id tu nhieu truong khac nhau
                    item_id = str(
                        item.get("item_id") or item.get("id") or ""
                    ).strip()
                    if item_id and item_id not in info:
                        info[item_id] = {
                            "title": item.get("title", ""),
                            "doc_number": item.get("doc_number") or item.get("docNum", ""),
                            "doc_type": item.get("doc_type") or "",
                            "url": item.get("url_toanvan") or item.get("url", ""),
                        }
        except Exception:
            pass
    return info


def main() -> None:
    print("=" * 60)
    print("  KIEM TRA DOI CHIEU VAN BAN DA TAI")
    print("=" * 60)

    print("\n[1/4] Doc danh sach da xu ly tu processed_urls.txt ...")
    processed_ids = load_processed_ids()
    print(f"      => {len(processed_ids):,} item_id da duoc danh dau 'hoan thanh'")

    print("\n[2/4] Quet thuoc_tinh.json trong output/documents/ ...")
    print("      (Co the mat vai phut...)")
    downloaded = scan_downloaded_ids()
    print(f"      => {len(downloaded):,} thu muc co du lieu hop le")

    print("\n[3/4] Tai thong tin bo sung tu cache danh sach ...")
    list_info = load_list_cache()
    print(f"      => {len(list_info):,} ban ghi co trong cache")

    print("\n[4/4] Tinh toan ket qua ...")
    missing_ids = processed_ids - set(downloaded.keys())
    extra_dirs = set(downloaded.keys()) - processed_ids

    # Xuat file missing
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(MISSING_PATH, "w", encoding="utf-8") as f:
        for item_id in sorted(missing_ids):
            extra = list_info.get(item_id, {})
            record = {
                "item_id": item_id,
                "title": extra.get("title", ""),
                "doc_number": extra.get("doc_number", ""),
                "doc_type": extra.get("doc_type", ""),
                "url": extra.get("url", ""),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print()
    print("=" * 60)
    print("  KET QUA")
    print("=" * 60)
    print(f"  Da xu ly (processed_urls.txt) : {len(processed_ids):,}")
    print(f"  Co thu muc tren o cung        : {len(downloaded):,}")
    print(f"  Chenh lech - Thieu thu muc    : {len(missing_ids):,}")
    if extra_dirs:
        print(f"  Thu muc 'la' khong trong DS   : {len(extra_dirs):,}")
    print()
    if missing_ids:
        print(f"  => Danh sach chi tiet da luu tai:")
        print(f"     {MISSING_PATH.resolve()}")
    else:
        print("  => Khong co van ban nao bi thieu. Du lieu day du!")
    print("=" * 60)


if __name__ == "__main__":
    main()
