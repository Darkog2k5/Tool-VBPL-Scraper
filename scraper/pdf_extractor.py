"""
Trích xuất text từ PDF văn bản pháp luật.

Chiến lược:
  1. Extract text layer (pdfplumber → PyMuPDF) — nhanh, chính xác
  2. Nếu text rỗng/quá ngắn → OCR bằng Tesseract (ngôn ngữ vie)
  3. Post-process: chuẩn hoá Unicode, sửa lỗi OCR phổ biến tiếng Việt

Dependencies:
  pip install pdfplumber PyMuPDF pytesseract pdf2image Pillow
  Cài Tesseract OCR: https://github.com/tesseract-ocr/tesseract
  Tải Vietnamese language data: tesseract --list-langs | cần có 'vie'
"""

import io
import re
import unicodedata
from pathlib import Path

from loguru import logger

# Ngưỡng tối thiểu để coi text extraction là thành công
_MIN_TEXT_LENGTH = 50


# ── Public API ───────────────────────────────────────────────────────────────


def extract_text_from_pdf(pdf_bytes: bytes) -> tuple[str, str]:
    """
    Trích xuất text từ PDF bytes.

    Returns:
        tuple[str, str]: (extracted_text, method)
            method: "text_layer" | "ocr" | "empty"
    """
    if not pdf_bytes:
        return "", "empty"

    # ── Bước 1: Text layer extraction ────────────────────────────────────────
    text = _extract_text_layer(pdf_bytes)
    if text and len(text.strip()) > _MIN_TEXT_LENGTH:
        cleaned = _post_process_vietnamese(text.strip())
        logger.info(f"PDF text layer extracted: {len(cleaned)} chars")
        return cleaned, "text_layer"

    # ── Bước 2: OCR fallback ─────────────────────────────────────────────────
    logger.info("Text layer empty or too short, falling back to OCR...")
    ocr_text = _ocr_pdf(pdf_bytes)
    if ocr_text and len(ocr_text.strip()) > _MIN_TEXT_LENGTH:
        cleaned = _post_process_vietnamese(ocr_text.strip())
        logger.info(f"PDF OCR completed: {len(cleaned)} chars")
        return cleaned, "ocr"

    logger.warning("Cannot extract text from PDF (both text layer and OCR failed)")
    return "", "empty"


def save_pdf(pdf_bytes: bytes, output_path: Path) -> Path:
    """Lưu PDF bytes ra file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(pdf_bytes)
    logger.info(f"Saved PDF: {output_path} ({len(pdf_bytes):,} bytes)")
    return output_path


def is_pdf(data: bytes) -> bool:
    """Kiểm tra bytes có phải PDF không (magic bytes)."""
    return data[:5] == b"%PDF-"


# ── Text layer extraction ────────────────────────────────────────────────────


def _extract_text_layer(pdf_bytes: bytes) -> str:
    """Trích text layer bằng pdfplumber, fallback sang PyMuPDF."""
    text = _extract_with_pdfplumber(pdf_bytes)
    if text:
        return text
    return _extract_with_pymupdf(pdf_bytes)


def _extract_with_pdfplumber(pdf_bytes: bytes) -> str:
    try:
        import pdfplumber
    except ImportError:
        logger.debug("pdfplumber not installed, skipping")
        return ""

    try:
        texts = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text()
                if page_text:
                    texts.append(page_text)
                # Cũng thử extract từ bảng nếu có
                tables = page.extract_tables()
                for table in tables:
                    for row in table:
                        row_text = " | ".join(cell or "" for cell in row)
                        if row_text.strip():
                            texts.append(row_text.strip())
        return "\n\n".join(texts)
    except Exception as exc:
        logger.warning(f"pdfplumber extraction failed: {exc}")
        return ""


def _extract_with_pymupdf(pdf_bytes: bytes) -> str:
    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.debug("PyMuPDF not installed, skipping")
        return ""

    try:
        texts = []
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page in doc:
            page_text = page.get_text("text")
            if page_text:
                texts.append(page_text)
        doc.close()
        return "\n\n".join(texts)
    except Exception as exc:
        logger.warning(f"PyMuPDF extraction failed: {exc}")
        return ""


# ── OCR ──────────────────────────────────────────────────────────────────────


def _ocr_pdf(pdf_bytes: bytes) -> str:
    """OCR từng trang PDF bằng Tesseract với ngôn ngữ tiếng Việt."""
    try:
        from pdf2image import convert_from_bytes
        import pytesseract
    except ImportError as exc:
        logger.warning(
            f"OCR dependencies not installed: {exc}.\n"
            "  pip install pytesseract pdf2image Pillow\n"
            "  Cài Tesseract OCR engine: https://github.com/tesseract-ocr/tesseract\n"
            "  Windows: https://github.com/UB-Mannheim/tesseract/wiki"
        )
        return ""

    try:
        # Kiểm tra Tesseract có sẵn không
        tesseract_version = pytesseract.get_tesseract_version()
        logger.info(f"Tesseract version: {tesseract_version}")
    except pytesseract.TesseractNotFoundError:
        logger.error(
            "Tesseract OCR engine not found!\n"
            "  Windows: Download from https://github.com/UB-Mannheim/tesseract/wiki\n"
            "  Sau khi cài, thêm đường dẫn vào PATH hoặc set:\n"
            '  pytesseract.pytesseract.tesseract_cmd = r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"'
        )
        return ""

    try:
        # Kiểm tra Vietnamese language pack
        available_langs = pytesseract.get_languages()
        has_vie = "vie" in available_langs
        if not has_vie:
            logger.warning(
                "Vietnamese OCR language pack ('vie') not found.\n"
                "  Download from: https://github.com/tesseract-ocr/tessdata\n"
                "  Copy 'vie.traineddata' to Tesseract tessdata folder.\n"
                "  Falling back to English OCR."
            )

        # Convert PDF → images
        logger.info("Converting PDF to images for OCR...")
        images = convert_from_bytes(pdf_bytes, dpi=300, fmt="png")
        logger.info(f"PDF has {len(images)} page(s)")

        texts = []
        for i, image in enumerate(images):
            logger.info(f"  OCR page {i + 1}/{len(images)}...")

            # Pre-process image for better OCR accuracy
            processed_image = _preprocess_image_for_ocr(image)

            # OCR with Vietnamese language
            lang = "vie+eng" if has_vie else "eng"
            config = (
                "--psm 6 "      # Assume uniform block of text
                "--oem 3 "      # LSTM neural net mode
            )

            try:
                page_text = pytesseract.image_to_string(
                    processed_image,
                    lang=lang,
                    config=config,
                )
            except pytesseract.TesseractError as exc:
                logger.warning(f"  OCR error on page {i + 1}: {exc}")
                # Last resort fallback
                page_text = pytesseract.image_to_string(processed_image, config="--psm 6")

            if page_text and page_text.strip():
                texts.append(page_text.strip())

        return "\n\n".join(texts)

    except Exception as exc:
        logger.error(f"OCR failed: {exc}")
        return ""


def _preprocess_image_for_ocr(image):
    """
    Tiền xử lý ảnh để cải thiện chất lượng OCR cho văn bản tiếng Việt.

    - Chuyển sang grayscale
    - Tăng contrast
    - Binarize (ngưỡng adaptive)
    - Loại bỏ noise
    """
    try:
        from PIL import Image, ImageFilter, ImageEnhance
    except ImportError:
        return image

    try:
        # Chuyển sang grayscale
        if image.mode != "L":
            gray = image.convert("L")
        else:
            gray = image.copy()

        # Tăng contrast
        enhancer = ImageEnhance.Contrast(gray)
        contrast = enhancer.enhance(1.5)

        # Tăng sharpness
        enhancer = ImageEnhance.Sharpness(contrast)
        sharp = enhancer.enhance(2.0)

        # Binarize (Otsu-like thresholding)
        # Dùng point() để threshold
        threshold = 128
        binary = sharp.point(lambda x: 255 if x > threshold else 0, "1")

        # Loại bỏ noise nhỏ
        denoised = binary.filter(ImageFilter.MedianFilter(size=3))

        return denoised

    except Exception as exc:
        logger.debug(f"Image preprocessing failed, using original: {exc}")
        return image


# ── Vietnamese text post-processing ──────────────────────────────────────────


def _post_process_vietnamese(text: str) -> str:
    """
    Chuẩn hoá và sửa lỗi OCR phổ biến cho text tiếng Việt.
    """
    if not text:
        return ""

    # 1. Chuẩn hoá Unicode NFC (đảm bảo dấu tiếng Việt đúng dạng)
    text = unicodedata.normalize("NFC", text)

    # 2. Sửa lỗi OCR phổ biến trong tiếng Việt
    text = _fix_common_ocr_errors(text)

    # 3. Chuẩn hoá khoảng trắng
    text = re.sub(r"[ \t]+", " ", text)           # Multiple spaces → single
    text = re.sub(r"\n{3,}", "\n\n", text)         # Max 2 newlines
    text = re.sub(r"(\S)\n(\S)", r"\1 \2", text)   # Nối dòng bị ngắt giữa chừng

    # 4. Sửa dấu câu bị dính
    text = re.sub(r"(\w)\.(\w)", r"\1. \2", text)  # "abc.def" → "abc. def"
    text = re.sub(r"(\w),(\w)", r"\1, \2", text)   # "abc,def" → "abc, def"

    return text.strip()


def _fix_common_ocr_errors(text: str) -> str:
    """Sửa các lỗi OCR phổ biến khi nhận dạng tiếng Việt."""
    replacements = {
        # Dấu bị nhận sai
        "ðiều": "Điều",
        "ðã": "Đã",
        "ðể": "Để",
        "ðó": "Đó",
        "ðược": "Được",
        "ðịnh": "Định",
        "ðạt": "Đạt",
        "ðề": "Đề",
        "ðối": "Đối",
        "ðồng": "Đồng",
        # Chữ Đ bị nhận sai thành ð (eth)
        "ð": "đ",
        "Ð": "Đ",
        # Số bị nhận sai
        "l0": "10",
        "O0": "00",
        # Dấu ngoặc kép bị nhận sai
        "''": '"',
        "``": '"',
        # Ký tự đặc biệt bị nhận sai
        "°": "o",  # Chỉ trong context text, không phải nhiệt độ
    }

    for wrong, correct in replacements.items():
        text = text.replace(wrong, correct)

    # Sửa pattern "Đi ều" → "Điều" (OCR thêm space giữa chữ)
    text = re.sub(r"Đi\s+ều", "Điều", text)
    text = re.sub(r"Ngh\s+ị\s+đ\s*ịnh", "Nghị định", text, flags=re.IGNORECASE)
    text = re.sub(r"Th\s*ông\s+t\s*ư", "Thông tư", text, flags=re.IGNORECASE)
    text = re.sub(r"Quy\s*ết\s+đ\s*ịnh", "Quyết định", text, flags=re.IGNORECASE)

    return text
