"""
Local model management through Ollama.

Everything the app needs to run with no internet connection lives here:
checking that the local server is up, listing what is already downloaded,
downloading a free open-weights model with progress, and deleting one again.

Downloads stream Ollama's own progress JSON so the UI can show real bytes
rather than a spinner that never moves.
"""

import json
import logging
import shutil
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple

import requests

from config.settings import OLLAMA_BASE_URL

logger = logging.getLogger(__name__)

# The local server answers instantly when it is up; a long connect timeout
# only makes a missing Ollama feel like a hang.
PROBE_TIMEOUT = 3
# (connect, read). A pull sends progress lines continuously, so the read
# timeout is per-chunk, not for the whole download.
PULL_TIMEOUT = (10, 120)


@dataclass(frozen=True)
class CuratedModel:
    """A free model we recommend, with what it costs to keep on disk."""
    name: str
    role: str          # "llm" or "vision"
    size_gb: float
    ram_gb: int        # rough minimum system RAM for a usable speed
    blurb: str


# Free, open-weights models that run on a laptop. Sizes are the download size
# reported by the Ollama library and are approximate.
CURATED_MODELS: List[CuratedModel] = [
    CuratedModel(
        "llama3.2:3b", "llm", 2.0, 8,
        "Best starting point. Fast on a CPU-only laptop, good enough for "
        "routing and short blueprints.",
    ),
    CuratedModel(
        "qwen2.5:7b", "llm", 4.7, 16,
        "Strongest JSON discipline of the small models - the safest pick for "
        "diagram blueprints and reviews.",
    ),
    CuratedModel(
        "mistral:7b", "llm", 4.1, 16,
        "Well-rounded 7B. The project's historical default local model.",
    ),
    CuratedModel(
        "llama3.1:8b", "llm", 4.7, 16,
        "Higher quality reviews, noticeably slower without a GPU.",
    ),
    CuratedModel(
        "phi3:mini", "llm", 2.2, 8,
        "Very small and quick. Use when RAM is tight; expect shorter answers.",
    ),
    CuratedModel(
        "gemma2:2b", "llm", 1.6, 8,
        "Smallest usable option. Fine for routing, weak on long blueprints.",
    ),
    CuratedModel(
        "llava:7b", "vision", 4.7, 16,
        "Reads uploaded diagram images offline. Needed for image review.",
    ),
    CuratedModel(
        "moondream", "vision", 1.7, 8,
        "Tiny vision model. Rougher reading of diagrams, but very light.",
    ),
    CuratedModel(
        "llava:13b", "vision", 8.0, 32,
        "Best offline diagram reading, only worth it with a GPU.",
    ),
]

INSTALL_URL = "https://ollama.com/download"


class OllamaService:
    """Talks to the local Ollama daemon."""

    def __init__(self, base_url: str = OLLAMA_BASE_URL):
        self.base_url = base_url.rstrip("/")

    # ==================== Status ====================

    def is_installed(self) -> bool:
        """True when the ollama binary is on PATH (it may still be stopped)."""
        return shutil.which("ollama") is not None

    def status(self) -> Tuple[bool, str]:
        """
        Check the local server.

        Returns (running, message). The message explains what to do when it
        isn't running, which is the only thing a user can act on.
        """
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=PROBE_TIMEOUT)
        except requests.RequestException as e:
            # The full connection error is a wall of text in the UI; it adds
            # nothing to "the server isn't answering", so it goes to the log.
            logger.info("Ollama not reachable at %s: %s", self.base_url, e)
            if self.is_installed():
                return False, (
                    f"Ollama is installed but not reachable at {self.base_url}. "
                    "Start it with `ollama serve`, then reload this page."
                )
            return False, (
                f"Ollama is not running on this machine. Install it from "
                f"{INSTALL_URL} to use local models."
            )

        if response.status_code != 200:
            return False, f"Ollama returned HTTP {response.status_code} at {self.base_url}"

        return True, f"Connected to Ollama at {self.base_url}"

    # ==================== Inventory ====================

    def installed_models(self) -> List[Dict]:
        """Models already downloaded, newest first. Empty when unreachable."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=PROBE_TIMEOUT)
            response.raise_for_status()
            models = response.json().get("models") or []
        except Exception as e:
            logger.warning("Could not list Ollama models: %s", e)
            return []

        return sorted(
            (
                {
                    "name": m.get("name", ""),
                    "size_bytes": m.get("size", 0),
                    "modified_at": m.get("modified_at", ""),
                    "family": (m.get("details") or {}).get("family", ""),
                }
                for m in models
            ),
            key=lambda m: m["modified_at"],
            reverse=True,
        )

    def is_downloaded(self, name: str) -> bool:
        """
        True when this model is present locally.

        Ollama reports tags as "mistral:latest"; a request for "mistral" and a
        request for "mistral:latest" mean the same model, so bare names are
        matched against the ":latest" tag too.
        """
        wanted = name if ":" in name else f"{name}:latest"
        return any(m["name"] == wanted for m in self.installed_models())

    # ==================== Download / delete ====================

    def pull(self, name: str) -> Iterator[Dict]:
        """
        Download a model, yielding progress as it goes.

        Each yielded dict has: status (str), completed (int), total (int),
        and done (bool). Raises requests.RequestException if the server is
        unreachable, and RuntimeError if Ollama reports an error mid-stream.
        """
        logger.info("Pulling Ollama model: %s", name)

        with requests.post(
            f"{self.base_url}/api/pull",
            json={"name": name, "stream": True},
            stream=True,
            timeout=PULL_TIMEOUT,
        ) as response:
            response.raise_for_status()

            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue

                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("Skipping non-JSON pull line: %s", line[:120])
                    continue

                if payload.get("error"):
                    raise RuntimeError(payload["error"])

                status = payload.get("status", "")
                yield {
                    "status": status,
                    "completed": int(payload.get("completed") or 0),
                    "total": int(payload.get("total") or 0),
                    "done": status == "success",
                }

        logger.info("Finished pulling Ollama model: %s", name)

    def delete(self, name: str) -> Tuple[bool, str]:
        """Remove a downloaded model from disk."""
        try:
            response = requests.delete(
                f"{self.base_url}/api/delete",
                json={"name": name},
                timeout=PROBE_TIMEOUT * 4,
            )
        except requests.RequestException as e:
            return False, f"Could not reach Ollama: {e}"

        if response.status_code == 200:
            logger.info("Deleted Ollama model: %s", name)
            return True, f"Deleted {name}"

        return False, f"Ollama returned HTTP {response.status_code}: {response.text[:200]}"

    # ==================== Helpers ====================

    @staticmethod
    def curated(role: Optional[str] = None) -> List[CuratedModel]:
        """Recommended models, optionally filtered to 'llm' or 'vision'."""
        if role is None:
            return list(CURATED_MODELS)
        return [m for m in CURATED_MODELS if m.role == role]

    @staticmethod
    def format_size(size_bytes: int) -> str:
        """Human-readable size for a downloaded model."""
        gb = size_bytes / 1_073_741_824
        if gb >= 1:
            return f"{gb:.1f} GB"
        return f"{size_bytes / 1_048_576:.0f} MB"


ollama_service = OllamaService()
