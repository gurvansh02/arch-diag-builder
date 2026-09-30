"""File type detection and validation for uploads"""

import logging
from pathlib import Path
from typing import Optional, Tuple

from config.settings import (
    ALLOWED_DIAGRAM_FORMATS,
    ALLOWED_DOCUMENT_FORMATS,
    ALLOWED_IMAGE_FORMATS,
)

logger = logging.getLogger(__name__)


class FileProcessor:
    """Classifies uploaded files by extension."""

    @staticmethod
    def get_file_type(file_path: str) -> Optional[str]:
        """Return 'image', 'drawio', 'pdf', or None for unsupported files."""
        extension = Path(file_path).suffix.lower()

        if extension in ALLOWED_IMAGE_FORMATS:
            return "image"
        if extension in ALLOWED_DIAGRAM_FORMATS:
            return "drawio"
        if extension in ALLOWED_DOCUMENT_FORMATS:
            return "pdf"

        return None

    @staticmethod
    def is_valid_file(file_path: str) -> Tuple[bool, Optional[str]]:
        """
        Validate an uploaded file.

        Returns (True, file_type) on success, or (False, reason) on failure.
        """
        path = Path(file_path)

        if not path.exists():
            return False, "File not found"

        if path.stat().st_size == 0:
            return False, "File is empty"

        file_type = FileProcessor.get_file_type(file_path)
        if not file_type:
            return False, f"Unsupported file type: {path.suffix or 'no extension'}"

        return True, file_type


file_processor = FileProcessor()
