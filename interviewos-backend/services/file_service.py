import asyncio
import logging
from pathlib import Path
from uuid import uuid4
from io import BytesIO
from zipfile import ZipFile
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, UploadFile, status

from config import settings

logger = logging.getLogger("interviewos.file_service")


def extract_upload_text(file_name: str, content: bytes) -> str:
    suffix = Path(file_name).suffix.lower()

    if suffix == ".pdf":
        try:
            import pdfplumber

            with pdfplumber.open(BytesIO(content)) as pdf:
                return "\n".join(page.extract_text() or "" for page in pdf.pages).strip()
        except Exception:
            try:
                from PyPDF2 import PdfReader

                reader = PdfReader(BytesIO(content))
                return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
            except Exception:
                return ""

    if suffix == ".docx":
        try:
            with ZipFile(BytesIO(content)) as docx:
                xml = docx.read("word/document.xml")
            root = ET.fromstring(xml)
            text_nodes = [
                node.text
                for node in root.iter()
                if node.tag.endswith("}t") and node.text
            ]
            return re.sub(r"\s+", " ", " ".join(text_nodes)).strip()
        except Exception:
            return ""

    return content.decode("utf-8", errors="ignore").strip()


async def save_upload(file: UploadFile, *, extract_text: bool = True) -> dict:
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds {settings.max_file_size_mb}MB limit",
        )

    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "resume.pdf").suffix
    stored_name = f"{uuid4()}{suffix}"
    path = upload_dir / stored_name
    await asyncio.to_thread(path.write_bytes, content)
    extracted_text = ""
    if extract_text:
        extracted_text = await asyncio.to_thread(extract_upload_text, file.filename or stored_name, content)
    return {
        "file_name": file.filename or stored_name,
        "file_path": str(path),
        "content": content,
        "text": extracted_text,
    }


async def cleanup_expired_resume_uploads() -> dict[str, int]:
    retention_hours = max(0, int(settings.resume_file_retention_hours))
    upload_dir = Path(settings.upload_dir)
    if not upload_dir.exists():
        return {"scanned": 0, "deleted": 0, "failed": 0}

    cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
    scanned = 0
    deleted = 0
    failed = 0

    for path in upload_dir.iterdir():
        if not path.is_file():
            continue
        scanned += 1
        try:
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if modified_at > cutoff:
                continue
            await asyncio.to_thread(path.unlink)
            deleted += 1
        except FileNotFoundError:
            continue
        except OSError as exc:
            failed += 1
            logger.warning("Unable to delete expired resume upload %s: %s", path, exc)

    if deleted or failed:
        logger.info(
            "Resume upload retention cleanup scanned=%s deleted=%s failed=%s retention_hours=%s",
            scanned,
            deleted,
            failed,
            retention_hours,
        )
    return {"scanned": scanned, "deleted": deleted, "failed": failed}


async def resume_upload_cleanup_loop() -> None:
    interval_seconds = max(60, int(settings.resume_file_cleanup_interval_seconds))
    while True:
        await cleanup_expired_resume_uploads()
        await asyncio.sleep(interval_seconds)
