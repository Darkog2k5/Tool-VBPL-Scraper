"""
check_signature_in_toc.py

Quét toàn bộ file muc_luc.json trong output/documents.
Logic chặt:
  - Chỉ xét 3 node LÁ CUỐI CÙNG (đi sâu theo nhánh cuối của cây).
  - Chỉ dùng từ khóa CHỮ KÝ THỰC SỰ: KT., TM., TL., ký tên, đóng dấu, đã ký...
    (loại bỏ hoàn toàn chức vụ bình thường như Bộ trưởng, Thủ trưởng...)
Kết quả ghi ra: output/check_signature_in_toc.log
"""

import json
import re
import sys
from pathlib import Path

# ── Cấu hình ────────────────────────────────────────────────────────────────
OUTPUT_DIR  = Path("output/documents")
REPORT_PATH = Path("output/check_signature_in_toc.log")

# Số lá cuối cùng cần xét
N_LAST_LEAVES = 3

# Từ khóa CHỮ KÝ THỰC SỰ - chỉ các ký hiệu xác nhận chữ ký, không phải chức vụ bình thường
STRICT_SIG_PATTERNS = [
    r"\bKT\s*\.",                        # KT. (Ký thay)
    r"\bTM\s*\.",                        # TM. (Thay mặt)
    r"\bTL\s*\.",                        # TL. (Thừa lệnh)
    r"\bTUQ\s*\.",                       # TUQ. (Thừa ủy quyền)
    r"k[yý]\s+t[eê]n",                  # ký tên
    r"[dđ][oô]ng\s+d[aâ]u",             # đóng dấu
    r"k[yý]\s+v[aà]\s+[dđ][oô]ng\s+d[aâ]u",  # ký và đóng dấu
    r"[dđ][aã]\s+k[yý]",                # đã ký
    r"\(?[Đ|đ][aã]\s*k[yý]\)?",         # (Đã ký)
    r"k[yý]\s+thay",                    # ký thay
    r"ch[uứ]ng\s+ki[eế]n\s+giao\s+nh[aậ]n",  # chứng kiến giao nhận
    r"k[yý]\s+v[aà]\s+ghi\s+r[oõ]\s+h[oọ]\s+t[eê]n",  # ký và ghi rõ họ tên
]

STRICT_PATTERN = re.compile("|".join(STRICT_SIG_PATTERNS), re.IGNORECASE | re.MULTILINE)


# ── Hàm lấy N lá cuối cùng ──────────────────────────────────────────────────
def collect_all_leaves(nodes: list, result: list) -> None:
    """DFS thu thập tất cả node lá (không có children) theo thứ tự."""
    for node in nodes:
        children = node.get("children") or []
        if children:
            collect_all_leaves(children, result)
        else:
            result.append(node)


def get_last_n_leaves(toc: list, n: int = 3) -> list[dict]:
    """Trả về n node lá cuối cùng của toàn bộ cây."""
    leaves = []
    collect_all_leaves(toc, leaves)
    return leaves[-n:] if leaves else []


def node_text(node: dict) -> str:
    """Ghép title + content thành chuỗi để kiểm tra."""
    parts = [
        (node.get("title") or "").strip(),
        (node.get("content") or "").strip(),
    ]
    return "\n".join(p for p in parts if p)


# ── Kiểm tra từng file ───────────────────────────────────────────────────────
def check_toc_file(path: Path) -> dict | None:
    try:
        toc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"__error__": True, "path": str(path), "reason": str(exc)}

    if not isinstance(toc, list) or not toc:
        return None

    last_leaves = get_last_n_leaves(toc, n=N_LAST_LEAVES)
    if not last_leaves:
        return None

    hits = []
    for node in last_leaves:
        text = node_text(node)
        m = STRICT_PATTERN.search(text)
        if m:
            hits.append({
                "level":   node.get("level", ""),
                "number":  node.get("number", ""),
                "title":   (node.get("title") or "")[:150],
                "content": (node.get("content") or "")[:300],
                "matched": m.group(0).strip(),
            })

    if not hits:
        return None

    # Đọc metadata từ thuoc_tinh.json
    meta_path = path.parent / "thuoc_tinh.json"
    doc_number = title = doc_type = item_id = url = ""
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
            # Hỗ trợ cả 2 cấu trúc: flat dict và {metadata: {...}}
            flat = meta.get("metadata") if "metadata" in meta else meta
            doc_number = flat.get("doc_number", "") or meta.get("attributes", {}).get("so_hieu", "")
            title      = flat.get("title", "") or meta.get("attributes", {}).get("tieu_de", "")
            doc_type   = flat.get("doc_type", "") or meta.get("attributes", {}).get("loai_vb", "")
            item_id    = flat.get("item_id", "")
            url        = flat.get("url_toanvan", "") or flat.get("url", "")
        except Exception:
            pass

    return {
        "folder":     path.parent.name,
        "item_id":    item_id,
        "doc_number": doc_number,
        "doc_type":   doc_type,
        "title":      title[:120],
        "url":        url,
        "hits":       hits,
    }


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    toc_files = sorted(OUTPUT_DIR.rglob("muc_luc.json"))
    total = len(toc_files)
    print(f"Tổng số file muc_luc.json tìm thấy: {total}")

    results: list[dict] = []
    errors:  list[dict] = []

    for i, path in enumerate(toc_files, 1):
        if i % 200 == 0:
            print(f"  Đang quét {i}/{total}...")
        result = check_toc_file(path)
        if result:
            if result.get("__error__"):
                errors.append(result)
            else:
                results.append(result)

    # ── Ghi báo cáo ─────────────────────────────────────────────────────────
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_PATH.open("w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write("BÁO CÁO: VĂN BẢN CÓ CHỮ KÝ DÍNH VÀO CUỐI MỤC LỤC\n")
        f.write(f"Logic: {N_LAST_LEAVES} node lá cuối cùng | Từ khóa chữ ký nghiêm ngặt\n")
        f.write(f"Tổng file quét : {total}\n")
        f.write(f"Phát hiện      : {len(results)}\n")
        f.write(f"Lỗi đọc file   : {len(errors)}\n")
        f.write("=" * 80 + "\n\n")

        for idx, r in enumerate(results, 1):
            f.write(f"[{idx:03d}] 📄 {r['doc_number'] or '(không số)'} — {r['doc_type']}\n")
            f.write(f"       Tiêu đề : {r['title']}\n")
            f.write(f"       item_id : {r['item_id']}\n")
            f.write(f"       Link    : {r['url'] or 'N/A'}\n")
            f.write(f"       Thư mục : {r['folder']}\n")
            f.write(f"       Phát hiện ({len(r['hits'])} node):\n")
            for h in r["hits"]:
                f.write(f"         [{h['level']} {h['number']}] matched='{h['matched']}'\n")
                f.write(f"           title  : {h['title']}\n")
                if h["content"].strip():
                    preview = "\n                   ".join(
                        h["content"].strip().splitlines()[:4]
                    )
                    f.write(f"           content: {preview}\n")
            f.write("\n")

        if errors:
            f.write("\n" + "=" * 80 + "\n")
            f.write(f"LỖI KHI ĐỌC FILE ({len(errors)}):\n")
            for e in errors:
                f.write(f"  {e['path']}: {e['reason']}\n")

    print(f"\n✅ Xong! Phát hiện {len(results)}/{total} văn bản có chữ ký dính vào cuối mục lục.")
    print(f"📝 Báo cáo: {REPORT_PATH.resolve()}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
