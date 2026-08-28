import json
from pathlib import Path
from loguru import logger
from scraper.detail_scraper import VBDocument

def convert_to_json(vb: VBDocument, out_dir: Path) -> tuple[Path, Path]:
    thuoc_tinh_path = out_dir / "thuoc_tinh.json"
    luoc_do_path = out_dir / "luoc_do.json"

    # 1. Tạo file Thuộc tính
    thuoc_tinh_payload = {
        "metadata": {
            "item_id": getattr(vb, "item_id", ""),
            "url_toanvan": getattr(vb, "url_toanvan", getattr(vb, "url", "")),
            "title": vb.title,
        },
        "attributes": {
            "so_hieu": vb.doc_number,
            "nganh": getattr(vb, "industry", "") or "--",
            "linh_vuc": vb.field or "--",
            "tinh_trang_hieu_luc": vb.status or "--",
            "co_quan_ban_hanh": vb.issuer or "--",
            "loai_van_ban": vb.doc_type or "--",
            "ngay_ban_hanh": vb.issue_date or "--",
            "ngay_co_hieu_luc": vb.effective_date or "--",
            "ngay_het_hieu_luc": getattr(vb, "expiration_date", "") or "--",
            "nguoi_ky": vb.signer or "--",
            "chuc_danh_nguoi_ky": vb.signer_title or "--",
        }
    }
    thuoc_tinh_path.write_text(json.dumps(thuoc_tinh_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Đã lưu Thuộc tính: {thuoc_tinh_path}")

    # 2. Tạo file Lược đồ
    luoc_do_payload = getattr(vb, "relationship_graph", {})
    luoc_do_path.write_text(json.dumps(luoc_do_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"Đã lưu Lược đồ: {luoc_do_path}")

    # 3. Tạo file Mục Lục (nếu có)
    muc_luc_path = None
    toc = getattr(vb, "toc", [])
    if toc:
        muc_luc_path = out_dir / "muc_luc.json"
        muc_luc_path.write_text(json.dumps(toc, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"Đã lưu Mục lục: {muc_luc_path}")

    return thuoc_tinh_path, luoc_do_path