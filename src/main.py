import configparser
import csv
import hashlib
import json
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import fitz  # PyMuPDF
import numpy as np
from PIL import Image

APP_NAME = "BizTeam_WorkRequestSplitter3"
APP_VERSION = "2026.04.01"
OUTPUT_DIR_NAME = "output"
CONFIG_FILE_NAME = "conpig.ini"
DEFAULT_LOG_ROOTS = (
    r"\\fiti_fileserver\교육자료\RDMS자동화\Log",
    r"\\192.168.1.7\교육자료\RDMS자동화\Log",
)
DEFAULT_PENDING_DIR_NAME = "pending_logs"
DEFAULT_MACHINE_ID_FILE_NAME = "machine_id.txt"
DEFAULT_LOG_FILE_PREFIX = "usage_log"
DEFAULT_NOTICE_TEXT = (
    "프로그램 개선 및 장애 분석을 위해 최소한의 사용 로그가 기록됩니다. "
    "로그에는 실행 시각, 처리 건수, 페이지 수, 오류 정보, 익명화된 식별값이 포함되며 "
    "원본 파일명과 접수번호 원문은 저장하지 않습니다."
)
CSV_FIELDNAMES = [
    "event_id",
    "run_id",
    "event_type",
    "delivery_state",
    "app_name",
    "app_version",
    "machine_id",
    "logged_at",
    "started_at",
    "finished_at",
    "duration_ms",
    "success",
    "status_code",
    "error_code",
    "target_type",
    "pdf_name_hash",
    "pdf_extension",
    "masked_receipt_numbers",
    "receipt_count",
    "page_count",
    "qr_marker_count",
    "output_file_count",
    "file_count",
    "success_file_count",
    "failed_file_count",
]
MASK_VISIBLE_PREFIX = 6
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


@dataclass(frozen=True)
class LogConfig:
    enabled: bool
    roots: tuple[str, ...]
    pending_dir_name: str
    machine_id_file_name: str
    log_file_prefix: str
    notice_text: str


def get_runtime_folder() -> Path:
    """Return the EXE folder when frozen, otherwise the current working directory."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def get_now() -> datetime:
    return datetime.now().astimezone()


def format_timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def get_date_folder_name(value: datetime) -> str:
    return value.strftime("%Y-%m-%d")


def hash_text(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def dedupe_preserve_order(values: list[str]) -> list[str]:
    unique_values: list[str] = []
    for value in values:
        if value and value not in unique_values:
            unique_values.append(value)
    return unique_values


def mask_receipt_code(code: str, visible_prefix: int = MASK_VISIBLE_PREFIX) -> str:
    normalized = code.strip()
    if not normalized:
        return ""
    if len(normalized) <= visible_prefix:
        return normalized[:1] + ("*" * max(len(normalized) - 1, 0))
    return normalized[:visible_prefix] + ("*" * (len(normalized) - visible_prefix))


def build_default_config_text() -> str:
    return "\n".join(
        [
            "; RDMS usage logging configuration",
            "; root_1, root_2 are tried in order. Logging stops at the first reachable path.",
            "[logging]",
            "enabled = true",
            f"root_1 = {DEFAULT_LOG_ROOTS[0]}",
            f"root_2 = {DEFAULT_LOG_ROOTS[1]}",
            f"pending_dir = {DEFAULT_PENDING_DIR_NAME}",
            f"machine_id_file = {DEFAULT_MACHINE_ID_FILE_NAME}",
            f"log_file_prefix = {DEFAULT_LOG_FILE_PREFIX}",
            f"notice_text = {DEFAULT_NOTICE_TEXT}",
            "",
        ]
    )


def ensure_config_file(runtime_folder: Path) -> Path:
    config_path = runtime_folder / CONFIG_FILE_NAME
    if config_path.exists():
        return config_path

    try:
        config_path.write_text(build_default_config_text(), encoding="utf-8")
        print(f"[안내] 로그 설정 파일을 생성했습니다: {config_path}")
    except OSError as exc:
        print(f"[경고] 로그 설정 파일 생성 실패: {config_path} / {exc}")

    return config_path


def load_log_config(runtime_folder: Path) -> LogConfig:
    config_path = ensure_config_file(runtime_folder)
    parser = configparser.ConfigParser()

    if config_path.exists():
        try:
            parser.read(config_path, encoding="utf-8")
        except configparser.Error as exc:
            print(f"[경고] 로그 설정 파일 읽기 실패, 기본값 사용: {exc}")

    section = parser["logging"] if parser.has_section("logging") else {}

    roots: list[str] = []
    if section:
        for key, value in section.items():
            if key.startswith("root_"):
                candidate = value.strip().rstrip("\\/")
                if candidate:
                    roots.append(candidate)

    if not roots:
        roots = list(DEFAULT_LOG_ROOTS)

    unique_roots: list[str] = []
    seen_roots: set[str] = set()
    for root in roots:
        normalized_key = root.casefold()
        if normalized_key not in seen_roots:
            unique_roots.append(root)
            seen_roots.add(normalized_key)

    enabled = True
    pending_dir_name = DEFAULT_PENDING_DIR_NAME
    machine_id_file_name = DEFAULT_MACHINE_ID_FILE_NAME
    log_file_prefix = DEFAULT_LOG_FILE_PREFIX
    notice_text = DEFAULT_NOTICE_TEXT

    if section:
        try:
            enabled = parser.getboolean("logging", "enabled", fallback=True)
        except ValueError:
            enabled = True
        pending_dir_name = section.get("pending_dir", DEFAULT_PENDING_DIR_NAME).strip() or DEFAULT_PENDING_DIR_NAME
        machine_id_file_name = (
            section.get("machine_id_file", DEFAULT_MACHINE_ID_FILE_NAME).strip()
            or DEFAULT_MACHINE_ID_FILE_NAME
        )
        log_file_prefix = section.get("log_file_prefix", DEFAULT_LOG_FILE_PREFIX).strip() or DEFAULT_LOG_FILE_PREFIX
        notice_text = section.get("notice_text", DEFAULT_NOTICE_TEXT).strip() or DEFAULT_NOTICE_TEXT

    return LogConfig(
        enabled=enabled,
        roots=tuple(unique_roots),
        pending_dir_name=pending_dir_name,
        machine_id_file_name=machine_id_file_name,
        log_file_prefix=log_file_prefix,
        notice_text=notice_text,
    )


def load_or_create_machine_id(runtime_folder: Path, file_name: str) -> str:
    machine_id_path = runtime_folder / file_name
    if machine_id_path.exists():
        try:
            machine_id = machine_id_path.read_text(encoding="utf-8").strip()
            if machine_id:
                return machine_id
        except OSError:
            pass

    machine_id = f"mid-{uuid.uuid4().hex[:12]}"
    try:
        machine_id_path.write_text(machine_id, encoding="utf-8")
    except OSError as exc:
        print(f"[경고] 익명 PC 식별값 저장 실패, 임시 식별값 사용: {exc}")
        return f"mid-temp-{uuid.uuid4().hex[:12]}"

    return machine_id


def parse_event_timestamp(raw_value: str) -> datetime:
    if raw_value:
        try:
            return datetime.fromisoformat(raw_value)
        except ValueError:
            pass
    return get_now()


def normalize_csv_row(event: dict[str, Any]) -> dict[str, str]:
    row: dict[str, str] = {}
    for field_name in CSV_FIELDNAMES:
        value = event.get(field_name, "")
        if isinstance(value, bool):
            row[field_name] = "true" if value else "false"
        elif value is None:
            row[field_name] = ""
        else:
            row[field_name] = str(value)
    return row


class UsageLogger:
    def __init__(self, runtime_folder: Path) -> None:
        self.runtime_folder = runtime_folder
        self.config = load_log_config(runtime_folder)
        self.pending_dir = runtime_folder / self.config.pending_dir_name
        self.machine_id = load_or_create_machine_id(runtime_folder, self.config.machine_id_file_name)
        self._notice_printed = False
        self._is_flushing = False

        try:
            self.pending_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"[경고] pending_logs 폴더 생성 실패: {self.pending_dir} / {exc}")

    def print_notice(self) -> None:
        if not self.config.enabled or self._notice_printed:
            return

        print(f"[안내] {self.config.notice_text}")
        self._notice_printed = True

    def flush_pending_logs(self) -> None:
        if not self.config.enabled or self._is_flushing or not self.pending_dir.exists():
            return

        self._is_flushing = True
        try:
            for pending_file in sorted(self.pending_dir.glob("*.json")):
                try:
                    event = json.loads(pending_file.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    print(f"[경고] pending 로그 읽기 실패: {pending_file.name} / {exc}")
                    continue

                event["delivery_state"] = "replayed"
                if self._deliver_event(event):
                    try:
                        pending_file.unlink()
                    except OSError as exc:
                        print(f"[경고] pending 로그 삭제 실패: {pending_file.name} / {exc}")
        finally:
            self._is_flushing = False

    def log_event(self, event_type: str, **data: Any) -> None:
        if not self.config.enabled:
            return

        event: dict[str, Any] = {field_name: "" for field_name in CSV_FIELDNAMES}
        event.update(data)
        event["event_id"] = data.get("event_id") or str(uuid.uuid4())
        event["event_type"] = event_type
        event["delivery_state"] = data.get("delivery_state", "live")
        event["app_name"] = APP_NAME
        event["app_version"] = APP_VERSION
        event["machine_id"] = self.machine_id
        event["logged_at"] = data.get("logged_at") or format_timestamp(get_now())

        if self._deliver_event(event):
            self.flush_pending_logs()
            return

        self._save_pending_event(event)

    def _save_pending_event(self, event: dict[str, Any]) -> None:
        try:
            self.pending_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return

        pending_name = f"{event['event_id']}.json"
        pending_path = self.pending_dir / pending_name
        try:
            pending_path.write_text(
                json.dumps(event, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            print(f"[경고] pending 로그 저장 실패: {pending_path} / {exc}")

    def _deliver_event(self, event: dict[str, Any]) -> bool:
        for root in self.config.roots:
            target_root = Path(root)
            event_time = parse_event_timestamp(str(event.get("finished_at") or event.get("logged_at") or ""))
            dated_folder = target_root / get_date_folder_name(event_time)
            csv_path = dated_folder / f"{self.config.log_file_prefix}_{self.machine_id}.csv"

            try:
                dated_folder.mkdir(parents=True, exist_ok=True)
                self._append_csv(csv_path, event)
                return True
            except OSError:
                continue

        return False

    def _append_csv(self, csv_path: Path, event: dict[str, Any]) -> None:
        file_exists = csv_path.exists()
        encoding = "utf-8-sig" if not file_exists else "utf-8"

        with csv_path.open("a", newline="", encoding=encoding) as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=CSV_FIELDNAMES)
            if not file_exists:
                writer.writeheader()
            writer.writerow(normalize_csv_row(event))


def render_crop_from_page(
    page: fitz.Page,
    region: tuple[float, float, float, float],
    *,
    scale: float,
) -> Image.Image:
    """Render a relative page region and return it as a PIL image."""
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
    """Build multiple image variants to improve QR detection reliability."""
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

    return dedupe_preserve_order(texts)


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


def build_pdf_result(pdf_file: Path) -> dict[str, Any]:
    return {
        "target_type": "pdf",
        "pdf_name_hash": hash_text(pdf_file.name),
        "pdf_extension": pdf_file.suffix.lower(),
        "masked_receipt_numbers": "",
        "receipt_count": 0,
        "page_count": 0,
        "qr_marker_count": 0,
        "output_file_count": 0,
        "file_count": 1,
        "success_file_count": 0,
        "failed_file_count": 1,
        "success": False,
        "status_code": "",
        "error_code": "",
        "started_at": "",
        "finished_at": "",
        "duration_ms": 0,
    }


def build_folder_result(folder: Path, target_type: str) -> dict[str, Any]:
    return {
        "target_type": target_type,
        "pdf_name_hash": "",
        "pdf_extension": "",
        "masked_receipt_numbers": "",
        "receipt_count": 0,
        "page_count": 0,
        "qr_marker_count": 0,
        "output_file_count": 0,
        "file_count": 0,
        "success_file_count": 0,
        "failed_file_count": 0,
        "success": False,
        "status_code": "",
        "error_code": "",
        "started_at": "",
        "finished_at": "",
        "duration_ms": 0,
        "folder_name_hash": hash_text(folder.name),
    }


def finalize_result(result: dict[str, Any], started_at: datetime) -> None:
    finished_at = get_now()
    result["started_at"] = format_timestamp(started_at)
    result["finished_at"] = format_timestamp(finished_at)
    result["duration_ms"] = int((finished_at - started_at).total_seconds() * 1000)

    if result["success"]:
        result["success_file_count"] = max(int(result.get("success_file_count", 0)), 1)
        if result.get("file_count") == 1:
            result["failed_file_count"] = 0
    elif not result.get("error_code") and result.get("status_code"):
        result["error_code"] = result["status_code"]


def process_pdf(pdf_path: str, logger: UsageLogger | None = None, run_id: str = "") -> dict[str, Any]:
    pdf_file = Path(pdf_path)
    started_at = get_now()
    result = build_pdf_result(pdf_file)

    try:
        if not pdf_file.exists():
            print(f"파일 없음: {pdf_file}")
            result["status_code"] = "file_not_found"
            return result

        if pdf_file.suffix.lower() != ".pdf":
            print(f"PDF 아님: {pdf_file}")
            result["status_code"] = "not_pdf"
            return result

        output_dir = pdf_file.parent / OUTPUT_DIR_NAME
        output_dir.mkdir(parents=True, exist_ok=True)

        doc = fitz.open(pdf_file)
        try:
            result["page_count"] = doc.page_count
            if doc.page_count < 1:
                print(f"[실패] 페이지 수 부족: {pdf_file.name}")
                result["status_code"] = "empty_pdf"
                return result

            markers = find_qr_page_markers(doc)
            result["qr_marker_count"] = len(markers)
            masked_receipts = dedupe_preserve_order([mask_receipt_code(code) for _, code, _ in markers])
            result["masked_receipt_numbers"] = "|".join(masked_receipts)
            result["receipt_count"] = len(masked_receipts)

            if not markers:
                print(f"[건너뜀] QR 코드 추출 실패: {pdf_file.name}")
                result["status_code"] = "qr_not_found"
                return result

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

            result["output_file_count"] = saved_count
            if saved_count == 0:
                print(f"[건너뜀] 저장할 본문 페이지 없음: {pdf_file.name}")
                result["status_code"] = "no_body_pages"
                return result

            result["success"] = True
            result["success_file_count"] = 1
            result["failed_file_count"] = 0
            result["status_code"] = "ok"
            return result
        finally:
            doc.close()
    except Exception as exc:  # pragma: no cover - defensive safety for production runs
        print(f"[실패] 처리 중 예외 발생: {pdf_file.name} / {exc}")
        result["status_code"] = "process_exception"
        result["error_code"] = type(exc).__name__
        return result
    finally:
        finalize_result(result, started_at)
        if logger is not None:
            logger.log_event("pdf_complete", run_id=run_id, **result)


def process_folder(
    folder_path: str,
    logger: UsageLogger | None = None,
    run_id: str = "",
    target_type: str = "folder",
) -> dict[str, Any]:
    folder = Path(folder_path)
    started_at = get_now()
    result = build_folder_result(folder, target_type)

    try:
        if not folder.exists() or not folder.is_dir():
            print(f"폴더 없음: {folder}")
            result["status_code"] = "folder_not_found"
            return result

        pdf_files = sorted(
            file_path
            for file_path in folder.iterdir()
            if file_path.is_file() and file_path.suffix.lower() == ".pdf"
        )
        result["file_count"] = len(pdf_files)

        if not pdf_files:
            print("PDF 파일이 없습니다.")
            result["status_code"] = "folder_has_no_pdf"
            return result

        total_receipt_numbers: list[str] = []
        for pdf_file in pdf_files:
            print("-" * 60)
            pdf_result = process_pdf(str(pdf_file), logger=logger, run_id=run_id)
            result["page_count"] += int(pdf_result.get("page_count", 0))
            result["qr_marker_count"] += int(pdf_result.get("qr_marker_count", 0))
            result["output_file_count"] += int(pdf_result.get("output_file_count", 0))
            result["success_file_count"] += 1 if pdf_result.get("success") else 0
            result["failed_file_count"] += 0 if pdf_result.get("success") else 1

            masked_receipts = str(pdf_result.get("masked_receipt_numbers", "")).split("|")
            total_receipt_numbers.extend([value for value in masked_receipts if value])

        unique_receipts = dedupe_preserve_order(total_receipt_numbers)
        result["masked_receipt_numbers"] = "|".join(unique_receipts)
        result["receipt_count"] = len(unique_receipts)

        if result["success_file_count"] == 0:
            result["status_code"] = "all_failed"
            return result

        result["success"] = True
        result["status_code"] = "ok" if result["failed_file_count"] == 0 else "partial_success"
        return result
    finally:
        finalize_result(result, started_at)
        if logger is not None:
            logger.log_event("folder_complete", run_id=run_id, **result)


def main() -> int:
    runtime_folder = get_runtime_folder()
    logger = UsageLogger(runtime_folder)
    logger.print_notice()
    logger.flush_pending_logs()

    run_id = str(uuid.uuid4())
    run_started_at = get_now()
    if len(sys.argv) < 2:
        target_type = "runtime_folder"
    else:
        requested_target = Path(sys.argv[1])
        if requested_target.is_file():
            target_type = "single_pdf"
        elif requested_target.is_dir():
            target_type = "folder"
        else:
            target_type = "invalid_target"
    run_success = False
    run_status_code = ""
    run_error_code = ""
    run_counts = {
        "page_count": 0,
        "output_file_count": 0,
        "file_count": 0,
        "success_file_count": 0,
        "failed_file_count": 0,
    }

    logger.log_event(
        "run_start",
        run_id=run_id,
        target_type=target_type,
        started_at=format_timestamp(run_started_at),
        success=False,
        status_code="started",
    )

    try:
        if len(sys.argv) < 2:
            runtime_folder = get_runtime_folder()
            print(f"[기본 실행] 실행 폴더의 PDF를 처리합니다: {runtime_folder}")
            folder_result = process_folder(
                str(runtime_folder),
                logger=logger,
                run_id=run_id,
                target_type="runtime_folder",
            )
            target_type = "runtime_folder"
            run_success = bool(folder_result.get("success"))
            run_status_code = str(folder_result.get("status_code", ""))
            run_error_code = str(folder_result.get("error_code", ""))
            run_counts.update(
                page_count=int(folder_result.get("page_count", 0)),
                output_file_count=int(folder_result.get("output_file_count", 0)),
                file_count=int(folder_result.get("file_count", 0)),
                success_file_count=int(folder_result.get("success_file_count", 0)),
                failed_file_count=int(folder_result.get("failed_file_count", 0)),
            )
            return 0

        target = Path(sys.argv[1])

        if target.is_file():
            target_type = "single_pdf"
            pdf_result = process_pdf(str(target), logger=logger, run_id=run_id)
            run_success = bool(pdf_result.get("success"))
            run_status_code = str(pdf_result.get("status_code", ""))
            run_error_code = str(pdf_result.get("error_code", ""))
            run_counts.update(
                page_count=int(pdf_result.get("page_count", 0)),
                output_file_count=int(pdf_result.get("output_file_count", 0)),
                file_count=1,
                success_file_count=1 if pdf_result.get("success") else 0,
                failed_file_count=0 if pdf_result.get("success") else 1,
            )
            return 0

        if target.is_dir():
            target_type = "folder"
            folder_result = process_folder(
                str(target),
                logger=logger,
                run_id=run_id,
                target_type="folder",
            )
            run_success = bool(folder_result.get("success"))
            run_status_code = str(folder_result.get("status_code", ""))
            run_error_code = str(folder_result.get("error_code", ""))
            run_counts.update(
                page_count=int(folder_result.get("page_count", 0)),
                output_file_count=int(folder_result.get("output_file_count", 0)),
                file_count=int(folder_result.get("file_count", 0)),
                success_file_count=int(folder_result.get("success_file_count", 0)),
                failed_file_count=int(folder_result.get("failed_file_count", 0)),
            )
            return 0

        print("올바른 파일 또는 폴더 경로를 입력하세요.")
        run_status_code = "invalid_target"
        run_error_code = "invalid_target"
        return 1
    except Exception as exc:  # pragma: no cover - defensive safety for production runs
        print(f"[실패] 프로그램 실행 중 예외 발생: {exc}")
        run_status_code = "unhandled_exception"
        run_error_code = type(exc).__name__
        return 1
    finally:
        run_finished_at = get_now()
        logger.log_event(
            "run_complete",
            run_id=run_id,
            target_type=target_type,
            started_at=format_timestamp(run_started_at),
            finished_at=format_timestamp(run_finished_at),
            duration_ms=int((run_finished_at - run_started_at).total_seconds() * 1000),
            success=run_success,
            status_code=run_status_code or ("ok" if run_success else "failed"),
            error_code=run_error_code,
            page_count=run_counts["page_count"],
            output_file_count=run_counts["output_file_count"],
            file_count=run_counts["file_count"],
            success_file_count=run_counts["success_file_count"],
            failed_file_count=run_counts["failed_file_count"],
        )


if __name__ == "__main__":
    sys.exit(main())
