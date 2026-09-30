"""
Review storage and retrieval.

One JSON file per review under user_data/reviews/<user_id>/, mirroring how
diagrams and conversations are stored. Reviews used to exist only as a chat
message, so a user could not go back to one after the conversation moved on.
"""

import json
import logging
from pathlib import Path
from typing import List, Optional

from config.models import Review
from config.settings import REVIEWS_DIR

logger = logging.getLogger(__name__)


class ReviewStore:
    """Manages review persistence."""

    def __init__(self, base_dir: Path = REVIEWS_DIR):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_user_dir(self, user_id: str) -> Path:
        user_dir = self.base_dir / user_id
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir

    def _get_review_path(self, user_id: str, review_id: str) -> Path:
        return self._get_user_dir(user_id) / f"{review_id}.json"

    def save_review(self, review: Review) -> bool:
        """Persist one review."""
        try:
            path = self._get_review_path(review.user_id, review.review_id)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(
                    json.loads(review.model_dump_json()), f, indent=2, default=str
                )
            logger.info("Saved review: %s for user: %s", review.review_id, review.user_id)
            return True
        except Exception as e:
            logger.error("Error saving review: %s", e)
            return False

    def load_review(self, user_id: str, review_id: str) -> Optional[Review]:
        """Load one review, or None if it is missing or unreadable."""
        path = self._get_review_path(user_id, review_id)
        if not path.exists():
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                return Review(**json.load(f))
        except Exception as e:
            logger.error("Error loading review %s: %s", review_id, e)
            return None

    def get_user_reviews(self, user_id: str) -> List[Review]:
        """Every review for a user, newest first."""
        reviews = []

        for review_file in self._get_user_dir(user_id).glob("*.json"):
            try:
                with open(review_file, "r", encoding="utf-8") as f:
                    reviews.append(Review(**json.load(f)))
            except Exception as e:
                logger.warning("Skipping unreadable review %s: %s", review_file, e)

        reviews.sort(key=lambda r: r.created_at, reverse=True)
        return reviews

    def delete_review(self, user_id: str, review_id: str) -> bool:
        """Delete one review."""
        path = self._get_review_path(user_id, review_id)
        if not path.exists():
            return False

        try:
            path.unlink()
            logger.info("Deleted review: %s", review_id)
            return True
        except OSError as e:
            logger.error("Error deleting review %s: %s", review_id, e)
            return False


review_store = ReviewStore()
