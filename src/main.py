import re
import sys
from pathlib import Path

import cv2
import fitz  # PyMuPDF
import numpy as np
from PIL import Image

OUTPUT_DIR_NAME = "output"
QR_REGION_SPECS = (
    ("full", (0.00, 0.00, 1.00, 1.00), 2.0),
    ("right-half", (0.50, 0.00, 1.00, 1.00), 3.0),
    ("top-right", (0.55, 0.00, 1.00, 0.40), 4.0),
    ("qr-tight", (0.68, 0.02, 0.98, 0.28), 5.0),
)
QR_CODE_PATTERNS = (
    re.compile(r"@([A-Za-z]\d{10})@"),
    re.compile(r"\b([A-Za-z]\d{10})\b"),
    re.compile(r"@([A-Za-z0-9]+)@"),
)


def get_runtime_folder() -> Path:
    """exe 실행 시 exe 폴더, 스크립트 실행 시 현재 작업 폴더를 반환"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def render_crop_from_page(
    page: fitz.Page,
    region: tuple[float, float, float, float],
    *,
    scale: float,
) -> Image.Image:
    """상대 좌표 영역을 렌더링해 PIL 이미지로 반환"""
    page_rect = page.rect
    x0, y0, x1, y1 = region
    clip = fitz.Rect(
        page_rect.x0 + page_rect.width * x0,
        page_rect.y0 + page_rect.height * y0,
        page_rect.x0 + page_rect.width * x1,
        page_rect.y0 + page_rect.height * y1,
    )
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
    mode = "RGB" if pix.n < 4 else "RGBA"
    image = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
    return image.convert("RGB")


def pil_to_bgr(image: Image.Image) -> np.ndarray:
    rgb = np.array(image.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def build_qr_variants(image: Image.Image) -> list[tuple[str, np.ndarray]]:
    """QR 디코딩 성공률을 높이기 위한 변형 이미지들"""
    bgr = pil_to_bgr(image)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    adaptive = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        11,
    )
    return [
        ("raw", bgr),
        ("gray", gray),
        ("otsu", otsu),
        ("adaptive", adaptive),
    ]


def decode_qr_texts(image: np.ndarray, detector: cv2.QRCodeDetector) -> list[str]:
    texts: list[str] = []

    data, _, _ = detector.detectAndDecode(image)
    if data:
        texts.append(data)

    try:
        found, decoded_info, _, _ = detector.detectAndDecodeMulti(image)
    except cv2.error:
        found, decoded_info = False, ()

    if found:
        texts.extend(text for text in decoded_info if text)

    unique_texts: list[str] = []
    for text in texts:
        if text not in unique_texts:
            unique_texts.append(text)
    return unique_texts


def extract_code_from_qr_text(text: str) -> str:
    normalized = text.strip()

    for pattern in QR_CODE_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return match.group(1)

    return ""


def extract_code_from_page(page: fitz.Page) -> tuple[str, str]:
    """
    Extract the filename code from a QR page.
    Example: @H2312603706@ -> H2312603706
    """
    detector = cv2.QRCodeDetector()
    best_raw_text = ""

    for region_label, region, scale in QR_REGION_SPECS:
        image = render_crop_from_page(page, region, scale=scale)

        for variant_label, candidate in build_qr_variants(image):
            for qr_text in decode_qr_texts(candidate, detector):
                tagged_text = f"[{region_label}/{variant_label}] {qr_text}"
                if not best_raw_text:
                    best_raw_text = tagged_text

                code = extract_code_from_qr_text(qr_text)
                if code:
                    return code, tagged_text

    return "", best_raw_text


def extract_code_from_first_page(page: fitz.Page) -> tuple[str, str]:
    """Backward-compatible wrapper."""
    return extract_code_from_page(page)


def code_to_filename(code: str) -> str:
    sanitized = re.sub(r'[<>:"/\\\\|?*]+', "_", code.strip())
    sanitized = sanitized.rstrip(". ")
    if not sanitized:
        raise ValueError("파일명으로 사용할 코드가 비어 있습니다.")
    return sanitized


def save_pdf_page_range(
    doc: fitz.Document,
    start_page: int,
    end_page: int,
    output_pdf: Path,
) -> None:
    if start_page > end_page:
        raise ValueError("start_page must be less than or equal to end_page.")

    output_doc = fitz.open()
    try:
        output_doc.insert_pdf(doc, from_page=start_page, to_page=end_page)
        output_doc.save(output_pdf, garbage=4, deflate=True)
    finally:
        output_doc.close()


def save_pdf_without_first_page(doc: fitz.Document, output_pdf: Path) -> None:
    save_pdf_page_range(doc, 1, doc.page_count - 1, output_pdf)


def build_unique_output_path(output_dir: Path, filename: str) -> Path:
    output_pdf = output_dir / filename
    if not output_pdf.exists():
        return output_pdf

    stem = output_pdf.stem
    suffix = output_pdf.suffix
    idx = 2
    while True:
        candidate = output_dir / f"{stem}_{idx}{suffix}"
        if not candidate.exists():
            return candidate
        idx += 1


def find_qr_page_markers(doc: fitz.Document) -> list[tuple[int, str, str]]:
    markers: list[tuple[int, str, str]] = []

    for page_index in range(doc.page_count):
        code, qr_raw = extract_code_from_page(doc[page_index])
        if code:
            markers.append((page_index, code, qr_raw))

    return markers


def process_pdf(pdf_path: str) -> None:
    pdf_file = Path(pdf_path)

    if not pdf_file.exists():
        print(f"파일 없음: {pdf_file}")
        return

    if pdf_file.suffix.lower() != ".pdf":
        print(f"PDF 아님: {pdf_file}")
        return

    output_dir = pdf_file.parent / OUTPUT_DIR_NAME
    output_dir.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(pdf_file)
    try:
        if doc.page_count < 1:
            print(f"[실패] 페이지 수 부족: {pdf_file.name}")
            return

        markers = find_qr_page_markers(doc)
        if not markers:
            print(f"[건너뜀] QR 코드 추출 실패: {pdf_file.name}")
            return

        for page_index, _, qr_raw in markers:
            print(f"[QR] {pdf_file.name} / page {page_index + 1}: {repr(qr_raw)}")

        saved_count = 0
        for marker_index, (qr_page_index, code, _) in enumerate(markers):
            body_start = qr_page_index + 1
            if marker_index + 1 < len(markers):
                body_end = markers[marker_index + 1][0] - 1
            else:
                body_end = doc.page_count - 1

            if body_start > body_end:
                print(
                    f"[건너뜀] 본문 페이지 없음: {pdf_file.name} / "
                    f"QR page {qr_page_index + 1} / 추출코드: {code}"
                )
                continue

            new_name = code_to_filename(code) + ".pdf"
            output_pdf = build_unique_output_path(output_dir, new_name)
            save_pdf_page_range(doc, body_start, body_end, output_pdf)

            print(
                f"[완료] {pdf_file.name} -> {output_pdf.name} / 추출코드: {code} / "
                f"저장페이지: {body_start + 1}-{body_end + 1}"
            )
            saved_count += 1

        if saved_count == 0:
            print(f"[건너뜀] 저장할 본문 페이지 없음: {pdf_file.name}")
    finally:
        doc.close()


def process_folder(folder_path: str) -> None:
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        print(f"폴더 없음: {folder}")
        return

    pdf_files = sorted(
        file_path
        for file_path in folder.iterdir()
        if file_path.is_file() and file_path.suffix.lower() == ".pdf"
    )
    if not pdf_files:
        print("PDF 파일이 없습니다.")
        return

    for pdf_file in pdf_files:
        print("-" * 60)
        process_pdf(str(pdf_file))


if __name__ == "__main__":
    """
    사용 예시
    1) 인자 없이 실행
       python src/main.py
       -> 현재 작업 폴더의 PDF 전체 처리

    2) 특정 폴더 전체 처리
       python src/main.py "C:\\work"

    3) 단일 파일 처리
       python src/main.py "C:\\work\\test.pdf"
    """
    if len(sys.argv) < 2:
        runtime_folder = get_runtime_folder()
        print(f"[기본 실행] 실행 폴더의 PDF를 처리합니다: {runtime_folder}")
        process_folder(str(runtime_folder))
        sys.exit(0)

    target = Path(sys.argv[1])

    if target.is_file():
        process_pdf(str(target))
    elif target.is_dir():
        process_folder(str(target))
    else:
        print("올바른 파일 또는 폴더 경로를 입력하세요.")
