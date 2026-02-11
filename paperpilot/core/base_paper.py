from __future__ import annotations

import copy
import os
import uuid
from dataclasses import dataclass, field, fields
from typing import Any, Dict, Iterable, Optional


def _normalize_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, "", 0):
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lower = value.strip().lower()
        if lower in {"true", "1", "yes", "y", "on"}:
            return True
        if lower in {"false", "0", "no", "n", "off"}:
            return False
    return default


def _normalize_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass
class Paper:
    """Unified in-memory representation of a PDF paper entry."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    filename: str = ""
    original_filename: str = ""
    file_path: str = ""
    upload_date: str = ""
    title: str = ""
    authors: str = ""
    affiliation: str = ""
    year: str = ""
    journal: str = ""
    abstract: str = ""
    keywords: str = ""
    subject: str = ""
    summary: str = ""  # arXiv summary (Keep original format)
    bibtex: str = ""  # BibTeX Quote
    notes: str = ""  # User remarks
    starred: bool = False
    has_chinese_version: bool = False
    chinese_version_path: Optional[str] = None
    use_chinese_version: bool = False
    has_analysis_result: bool = False
    analysis_result_path: Optional[str] = None
    read_time: int = 0
    analysis_view_time: int = 0
    translation_time: int = 0
    analysis_time: int = 0
    arxiv_id: Optional[str] = None
    arxiv_published_date: Optional[str] = None
    arxiv_url: Optional[str] = None
    github: Optional[str] = None  # GitHub storehouse URL
    homepage: Optional[str] = None  # Project home page URL
    upload_source: Optional[str] = None
    translation_status: str = "idle"
    translation_task_id: Optional[str] = None
    analysis_status: str = "idle"
    analysis_task_id: Optional[str] = None
    status_updated_at: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------
    # Constructors & serialization helpers
    # ------------------------------------------------------------------
    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> Optional["Paper"]:
        if not data:
            return None

        # Separate known dataclass fields and extra data.
        field_names = {f.name for f in fields(cls)}
        kwargs: Dict[str, Any] = {}
        extra: Dict[str, Any] = {}
        for key, value in data.items():
            if key in field_names:
                kwargs[key] = value
            else:
                extra[key] = value

        paper = cls(**kwargs)
        paper.extra = extra
        paper._normalize_fields()
        return paper

    @classmethod
    def create_default(
        cls,
        filename: str,
        file_path: str,
        *,
        original_filename: Optional[str] = None,
        upload_date: Optional[str] = None,
    ) -> "Paper":
        paper = cls(
            filename=filename,
            original_filename=original_filename or filename,
            file_path=file_path,
            upload_date=upload_date or "",
            title=os.path.splitext(filename)[0],
        )
        paper._normalize_fields()
        return paper

    def to_dict(self) -> Dict[str, Any]:
        """Serialize paper to plain dict for JSON responses."""
        data: Dict[str, Any] = {}
        for f in fields(self):
            if f.name == "extra":
                continue
            data[f.name] = copy.deepcopy(getattr(self, f.name))
        # Extra keys should not override core attributes.
        merged = {**self.extra, **data}
        return merged

    # ------------------------------------------------------------------
    # Update helpers
    # ------------------------------------------------------------------
    def update_from_dict(
        self, data: Dict[str, Any], *, allow_extra: bool = True
    ) -> None:
        """Update the paper with values coming from user/API payload."""
        if not data:
            return

        field_names = {f.name for f in fields(self)}

        for key, value in data.items():
            if key in field_names and key != "extra":
                setattr(self, key, value)
            elif allow_extra:
                self.extra[key] = value

        self._normalize_fields()

    def sync_filesystem(self, pdf_path: str, filename: str) -> None:
        """Ensure filesystem-derived attributes stay up-to-date."""
        if pdf_path:
            self.file_path = pdf_path
        if filename:
            self.filename = filename
        if not self.original_filename:
            self.original_filename = filename

    def mark_chinese_version(self, dual_pdf_path: Optional[str]) -> None:
        has_version = bool(dual_pdf_path and os.path.exists(dual_pdf_path))
        self.has_chinese_version = has_version
        self.chinese_version_path = dual_pdf_path if has_version else None

    def mark_analysis_result(self, result_path: Optional[str]) -> None:
        has_result = bool(result_path and os.path.exists(result_path))
        self.has_analysis_result = has_result
        self.analysis_result_path = result_path if has_result else None

    def record_read_time(self, seconds: int) -> None:
        """Accumulated reading time（Second）"""
        self.read_time = self.read_time + _normalize_int(seconds, 0)

    def record_analysis_view_time(self, seconds: int) -> None:
        """Accumulate AI Interpret reading time（Second）"""
        self.analysis_view_time = self.analysis_view_time + _normalize_int(seconds, 0)

    def mark_starred(self, value: Any) -> None:
        self.starred = _normalize_bool(value, False)

    def set_translation_status(
        self,
        status: str,
        *,
        task_id: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> None:
        self.translation_status = status
        if task_id is not None or status in {
            "idle",
            "completed",
            "failed",
            "cancelled",
        }:
            self.translation_task_id = task_id
        if timestamp is not None:
            self.status_updated_at = timestamp

    def set_analysis_status(
        self,
        status: str,
        *,
        task_id: Optional[str] = None,
        timestamp: Optional[str] = None,
    ) -> None:
        self.analysis_status = status
        if task_id is not None or status in {
            "idle",
            "completed",
            "failed",
            "cancelled",
        }:
            self.analysis_task_id = task_id
        if timestamp is not None:
            self.status_updated_at = timestamp

    def clone(self) -> "Paper":
        return Paper.from_dict(self.to_dict())  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Internal utilities
    # ------------------------------------------------------------------
    def _normalize_fields(self) -> None:
        """Ensure primitive fields respect expected types."""
        self.starred = _normalize_bool(self.starred, False)
        self.has_chinese_version = _normalize_bool(self.has_chinese_version, False)
        self.use_chinese_version = _normalize_bool(self.use_chinese_version, False)
        self.has_analysis_result = _normalize_bool(self.has_analysis_result, False)

        self.read_time = _normalize_int(self.read_time, 0)
        self.analysis_view_time = _normalize_int(self.analysis_view_time, 0)
        self.translation_time = _normalize_int(self.translation_time, 0)
        self.analysis_time = _normalize_int(self.analysis_time, 0)
        self.translation_status = (self.translation_status or "idle").strip() or "idle"
        self.analysis_status = (self.analysis_status or "idle").strip() or "idle"

    # ------------------------------------------------------------------
    # Convenience iteration helpers
    # ------------------------------------------------------------------
    @staticmethod
    def to_dict_list(papers: Iterable["Paper"]) -> list[Dict[str, Any]]:
        return [paper.to_dict() for paper in papers]
