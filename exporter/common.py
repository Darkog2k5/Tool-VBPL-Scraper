import re
import unicodedata

def remove_accents(input_str: str) -> str:
    s = re.sub(r'[đĐ]', 'd', input_str)
    s = unicodedata.normalize('NFKD', s).encode('ASCII', 'ignore').decode('utf-8')
    return s

def safe_filename(value: str, fallback: str = "unknown") -> str:
    value = (value or fallback).strip()
    value = re.sub(r"[^\w\-]+", "_", value, flags=re.UNICODE)
    return value.strip("_") or fallback

def normalize_name(value: str, fallback: str = "khac") -> str:
    """Chuẩn hóa tên thư mục: chữ thường, không dấu, nối bằng gạch dưới."""
    value = (value or fallback).strip().lower()
    value = remove_accents(value)
    value = re.sub(r"[^\w]+", "_", value)
    return value.strip("_") or fallback
