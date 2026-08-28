import subprocess
import sys
import time

DOC_TYPE_CHOICES = [
    ("hien_phap", "Hiến pháp"),
    ("bo_luat", "Bộ luật"),
    ("luat", "Luật"),
    ("phap_lenh", "Pháp lệnh"),
    ("nghi_dinh", "Nghị định"),
    ("thong_tu", "Thông tư"),
    ("quyet_dinh", "Quyết định"),
    ("lenh", "Lệnh"),
    ("nghi_quyet", "Nghị quyết"),
    ("nghi_quyet_lien_tich", "Nghị quyết liên tịch"),
    ("van_ban_hop_nhat", "Văn bản hợp nhất"),
    ("van_ban_hanh_chinh_lien_quan", "Văn bản hành chính liên quan"),
    ("ban_dich_van_ban", "Bản dịch văn bản"),
    ("chi_thi", "Chỉ thị"),
    ("van_ban_he_thong_hoa", "Văn bản hệ thống hóa"),
    ("chua_xac_dinh", "Chưa xác định"),
    ("thong_tu_lien_tich", "Thông tư liên tịch"),
    ("thong_tu_lien_bo", "Thông tư liên bộ"),
    ("cong_uoc", "Công ước"),
    ("thong_bao", "Thông báo"),
    ("van_ban_khac", "Văn bản khác"),
    ("sac_luat", "Sắc luật"),
    ("quy_dinh", "Quy định"),
    ("sac_lenh", "Sắc lệnh"),
    ("cong_van", "Công văn"),
    ("van_ban_lien_quan", "Văn bản liên quan"),
]

def main():
    print("Start scraping 10 documents for all categories...")
    total = len(DOC_TYPE_CHOICES)
    for i, (type_id, name) in enumerate(DOC_TYPE_CHOICES, 1):
        print(f"\n[{i}/{total}] Processing: {type_id}")
        cmd = [
            "python", "pipeline.py",
            "--type-id", type_id,
            "--limit", "10",
            "--max-pages", "1"
        ]
        # Run command without NER
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error running {type_id}: {e}")
        time.sleep(1)
        
    print("\nFinished scraping all categories!")

if __name__ == "__main__":
    main()
