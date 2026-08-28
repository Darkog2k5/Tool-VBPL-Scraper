from pathlib import Path

BASE_URL = "https://vbpl.vn"
AREA = "TW"
HOME_URL = f"{BASE_URL}/{AREA}/Pages/Home.aspx"
LIST_URL = f"{BASE_URL}/van-ban/trung-uong"
DETAIL_URL = f"{BASE_URL}/van-ban/chi-tiet"
API_BASE_URL = "https://vbpl-bientap-gateway.moj.gov.vn/api"
API_LIST_URL = f"{API_BASE_URL}/qtdc/public/doc/all"
API_DETAIL_URL = f"{API_BASE_URL}/qtdc/public/doc"

DEFAULT_TYPE_ID = "thong_tu"
DEFAULT_PAGE_SIZE = 10
REQUEST_DELAY = 0
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
OUTPUT_DIR = "output"
LOG_DIR = "logs"
KNOWN_TOTAL_PAGES = 5530

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8",
    "Referer": LIST_URL,
}

API_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": BASE_URL,
    "Referer": LIST_URL,
}

TYPE_ID_NAME_MAP = {
    "1": ("Hiến pháp", "Luật", "Pháp lệnh"),
    "2": ("Nghị định",),
    "3": ("Thông tư",),
    "4": ("Quyết định",),
    "5": ("Thông tư liên tịch",),
    "6": ("Nghị quyết",),
}

DOC_TYPE_CHOICES = [
    ("", "Tất cả hình thức văn bản"),
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

TYPE_ID_NAME_MAP = {
    "hien_phap": ("Hiến pháp",),
    "bo_luat": ("Bộ luật",),
    "luat": ("Luật",),
    "phap_lenh": ("Pháp lệnh",),
    "nghi_dinh": ("Nghị định",),
    "thong_tu": ("Thông tư",),
    "quyet_dinh": ("Quyết định",),
    "lenh": ("Lệnh",),
    "nghi_quyet": ("Nghị quyết",),
    "nghi_quyet_lien_tich": ("Nghị quyết liên tịch",),
    "van_ban_hop_nhat": ("Văn bản hợp nhất",),
    "van_ban_hanh_chinh_lien_quan": ("Văn bản hành chính liên quan",),
    "ban_dich_van_ban": ("Bản dịch văn bản",),
    "chi_thi": ("Chỉ thị",),
    "van_ban_he_thong_hoa": ("Văn bản hệ thống hóa",),
    "chua_xac_dinh": ("Chưa xác định",),
    "thong_tu_lien_tich": ("Thông tư liên tịch",),
    "thong_tu_lien_bo": ("Thông tư liên bộ",),
    "cong_uoc": ("Công ước",),
    "thong_bao": ("Thông báo",),
    "van_ban_khac": ("Văn bản khác",),
    "sac_luat": ("Sắc luật",),
    "quy_dinh": ("Quy định",),
    "sac_lenh": ("Sắc lệnh",),
    "cong_van": ("Công văn",),
    "van_ban_lien_quan": ("Văn bản liên quan",),
}

DOC_TYPE_API_IDS = {
    "hien_phap": ["58bf04c0-a197-4d6e-96e9-2e51066209b5"],
    "bo_luat": ["404b68a7-8e71-4ee5-a6c0-07e59f35f824"],
    "luat": ["11025e19-2dd6-4165-85ad-ab6241186a1a"],
    "phap_lenh": ["1cd0d144-ccb5-4196-8b56-9a3f599c9341"],
    "nghi_dinh": ["0d08b84c-7de7-4800-8760-2a68265e7890"],
    "thong_tu": ["178c63a9-73ff-4fd4-9d91-18d690520090"],
    "quyet_dinh": ["0a5362e8-cdca-436e-96cd-979598df3b16"],
    "lenh": ["43323400-7d47-418e-80ef-a912a349d4e3"],
    "nghi_quyet": ["044d941c-40de-45b9-ae84-51f5a730bfe0"],
    "nghi_quyet_lien_tich": ["048dd409-3441-4c13-a5ae-80236ad3ce68"],
    "van_ban_hop_nhat": ["26b8a9ff-1b59-4c57-9605-f2ad4ed7c324"],
    "van_ban_hanh_chinh_lien_quan": ["25fad6ae-78f6-4acd-a70e-da19032729af"],
    "ban_dich_van_ban": ["9979b9a4-9e4c-4a14-a990-6d86e11b75c5"],
    "chi_thi": ["0045710b-eb54-4ce5-b511-76aa23f3021b"],
    "van_ban_he_thong_hoa": ["c1e77420-856e-4741-973b-82e41c3783e5"],
    "chua_xac_dinh": ["9f3a2c7e-4b6d-4f1a-a9d8-2c8e5b7a41f3"],
    "thong_tu_lien_tich": ["0e4f2bde-5ccb-4001-9e0a-b43f51cca5e8"],
    "thong_tu_lien_bo": ["88516734-9f43-4d32-8f54-256109edfbd4"],
    "cong_uoc": ["956a1482-c8b2-4b1b-8b50-31df8582ae6e"],
    "thong_bao": ["ed938c9b-e50d-42f8-80b9-e945f207bd04"],
    "van_ban_khac": ["39a344bd-d086-4fd9-880c-9ecefdb19a40"],
    "sac_luat": ["276cbd73-5b42-4b90-a6a7-ee1bca492b7d"],
    "quy_dinh": ["608e6760-929a-44b0-9a67-ea41c903e6b9"],
    "sac_lenh": ["1e0386d2-9395-4a0f-9d04-18a9e01f0ca7"],
    "cong_van": ["ecc6bbe0-5d0c-4916-836b-bb2f8146249c"],
    "van_ban_lien_quan": ["e154c97d-d4d8-4968-9b72-feffa38924d5"],
}

DOC_TYPE_ALIASES = {
    "1": "luat",
    "2": "nghi_dinh",
    "3": "thong_tu",
    "4": "quyet_dinh",
    "5": "thong_tu_lien_tich",
    "6": "nghi_quyet",
    "7": "lenh",
    "8": "chi_thi",
    "10": "van_ban_hop_nhat",
}


def ensure_directories() -> None:
    for path in [
        LOG_DIR,
        OUTPUT_DIR,
        f"{OUTPUT_DIR}/docx",
        f"{OUTPUT_DIR}/json",
        f"{OUTPUT_DIR}/list",
        f"{OUTPUT_DIR}/state",
    ]:
        Path(path).mkdir(parents=True, exist_ok=True)
