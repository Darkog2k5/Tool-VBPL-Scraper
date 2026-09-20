import csv
import datetime
import os
from pathlib import Path
from config import OUTPUT_DIR
from scraper.detail_scraper import VBDocument

FIELDNAMES = [
    "ItemID",
    "So_Hieu",
    "URL_Van_Ban",
    "Ngay_Cao_Du_Lieu",
    "Trang_Thai",
    "Ma_Loi",
    "Chi_Tiet_Loi",
    "Ten_File_Tai_Ve",
    "Dung_Luong_KB",
    "Co_Muc_Luc",
    "Co_Luoc_Do",
    "Co_Thuoc_Tinh"
]

class DocumentLogger:
    def __init__(self, loai_vb: str):
        self.loai_vb = loai_vb
        self.log_dir = Path(OUTPUT_DIR) / "logs" / loai_vb
        self.log_file = self.log_dir / "log.csv"
        self.log_data = {}  # In-memory dictionary
        self._load_existing_log()

    def _load_existing_log(self):
        if not self.log_file.exists():
            return
        
        try:
            with open(self.log_file, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    item_id = row.get("ItemID")
                    if item_id:
                        self.log_data[item_id] = row
        except Exception as e:
            from loguru import logger
            logger.error(f"Error loading existing log {self.log_file}: {e}")

    def log_success(self, item_id: str, so_hieu: str, url: str, saved_file_path: Path, vb: VBDocument):
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        
        ten_file = saved_file_path.name if saved_file_path else ""
        dung_luong = round(os.path.getsize(saved_file_path) / 1024, 2) if saved_file_path and saved_file_path.exists() else 0
        
        co_muc_luc = "Yes" if getattr(vb, 'toc', None) else "No"
        co_luoc_do = "Yes" if getattr(vb, 'relationship_graph', None) else "No"
        
        # Check if basic attributes exist to determine if it has Thuoc Tinh
        has_thuoc_tinh = any([
            getattr(vb, 'doc_number', None),
            getattr(vb, 'status', None),
            getattr(vb, 'issue_date', None)
        ])
        co_thuoc_tinh = "Yes" if has_thuoc_tinh else "No"
        
        self.log_data[item_id] = {
            "ItemID": item_id,
            "So_Hieu": so_hieu or "Khong_so",
            "URL_Van_Ban": url,
            "Ngay_Cao_Du_Lieu": today,
            "Trang_Thai": "Thành công",
            "Ma_Loi": "",
            "Chi_Tiet_Loi": "",
            "Ten_File_Tai_Ve": ten_file,
            "Dung_Luong_KB": dung_luong,
            "Co_Muc_Luc": co_muc_luc,
            "Co_Luoc_Do": co_luoc_do,
            "Co_Thuoc_Tinh": co_thuoc_tinh
        }

    def log_error(self, item_id: str, so_hieu: str, url: str, error_code: str, error_details: str):
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        self.log_data[item_id] = {
            "ItemID": item_id,
            "So_Hieu": so_hieu or "Khong_so",
            "URL_Van_Ban": url,
            "Ngay_Cao_Du_Lieu": today,
            "Trang_Thai": "Lỗi",
            "Ma_Loi": error_code,
            "Chi_Tiet_Loi": error_details,
            "Ten_File_Tai_Ve": "",
            "Dung_Luong_KB": 0,
            "Co_Muc_Luc": "No",
            "Co_Luoc_Do": "No",
            "Co_Thuoc_Tinh": "No"
        }

    def save_to_disk(self):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.log_file, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
                writer.writeheader()
                for row in self.log_data.values():
                    writer.writerow(row)
        except Exception as e:
            from loguru import logger
            logger.error(f"Error saving log {self.log_file}: {e}")
