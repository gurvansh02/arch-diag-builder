"""
LLM and Vision model fallback chains.

Provider order is defined in config.settings and is deliberately cheap-first:
    LLM     : Groq -> Ollama -> Claude
    Vision  : Gemini -> LLaVA -> Tesseract -> Claude

This module answers one question: which providers are *configured* right now,
in priority order. It deliberately does NOT send test completions - a health
check that calls a paid API costs money on every startup and still proves
nothing about the call path the app actually uses. Real failures surface at
call time, where llm_service / vision_service walk the chain and fall through.

Only free, local probes run here: an Ollama /api/tags lookup and a Tesseract
binary check.

Offline mode (Admin Dashboard -> Local Models) narrows both chains to the
providers that run on this machine, so no request can leave the network even
when API keys are configured.
"""

import os
import logging
from typing import Dict, List, Optional

import requests

from config.runtime_config import runtime_config
from config.settings import (
    LLM_FALLBACK_CHAIN,
    LOCAL_PROVIDERS,
    VISION_FALLBACK_CHAIN,
    TESSERACT_PATH,
)

logger = logging.getLogger(__name__)

# Seconds to wait on the local Ollama probe.
OLLAMA_PROBE_TIMEOUT = 3


class ModelFallback:
    """Tracks which LLM / Vision providers are usable, in priority order."""

    def __init__(self):
        self.llm_chain = LLM_FALLBACK_CHAIN
        self.vision_chain = VISION_FALLBACK_CHAIN
        self.model_availability: Dict[str, bool] = {}
        # Provider that last served a successful request, promoted to the front
        # of the candidate list so we stop re-trying known-dead providers.
        self._preferred_llm: Optional[Dict] = None
        self._preferred_vision: Optional[Dict] = None

    # ==================== Candidate lists ====================

    def llm_candidates(self, refresh: bool = False) -> List[Dict]:
        """Configured LLM providers, best first."""
        return self._candidates(
            self.llm_chain,
            self._preferred_llm,
            refresh,
            runtime_config.get("ollama_llm_model"),
        )

    def vision_candidates(self, refresh: bool = False) -> List[Dict]:
        """Configured vision providers, best first."""
        return self._candidates(
            self.vision_chain,
            self._preferred_vision,
            refresh,
            runtime_config.get("ollama_vision_model"),
        )

    def _candidates(
        self,
        chain: List[Dict],
        preferred: Optional[Dict],
        refresh: bool,
        ollama_model: Optional[str] = None,
    ) -> List[Dict]:
        if refresh:
            self.model_availability.clear()

        resolved = self._resolve(chain, ollama_model)
        usable = [c for c in resolved if self._is_configured(c)]

        # Promote the last known-good provider without dropping the others.
        # Compared by value, not identity: entries are rebuilt on every call
        # so the model an admin picked at runtime is picked up immediately.
        if preferred in usable:
            usable = [preferred] + [c for c in usable if c != preferred]

        return usable

    @staticmethod
    def _resolve(chain: List[Dict], ollama_model: Optional[str]) -> List[Dict]:
        """Apply offline mode and the admin's chosen local model to a chain."""
        offline = bool(runtime_config.get("offline_mode"))
        resolved = []

        for entry in chain:
            provider = entry.get("provider")

            if offline and provider not in LOCAL_PROVIDERS:
                continue

            if provider == "ollama" and ollama_model and ollama_model != entry["model"]:
                entry = {**entry, "model": ollama_model}

            resolved.append(entry)

        return resolved

    @staticmethod
    def offline_mode() -> bool:
        """True when only on-machine providers may serve requests."""
        return bool(runtime_config.get("offline_mode"))

    # ==================== Success tracking ====================

    def remember_llm(self, config: Dict) -> None:
        """Record the provider that just served a request."""
        self._preferred_llm = config
        logger.info("Active LLM: %s/%s", config["provider"], config["model"])

    def remember_vision(self, config: Dict) -> None:
        """Record the vision provider that just served a request."""
        self._preferred_vision = config
        logger.info("Active vision model: %s/%s", config["provider"], config["model"])

    # ==================== Configuration probes ====================

    def _is_configured(self, config: Dict) -> bool:
        """Cheap, free check that a provider could plausibly serve a request."""
        provider = config.get("provider")
        model = config.get("model")
        key = f"{provider}/{model}"

        if key in self.model_availability:
            return self.model_availability[key]

        available = False
        reason = ""

        try:
            api_key_env = config.get("api_key_env")
            if api_key_env:
                # API-backed provider: a key is all we can verify for free.
                if os.getenv(api_key_env):
                    available = True
                else:
                    reason = f"{api_key_env} not set"

            elif provider == "ollama":
                available, reason = self._probe_ollama(config)

            elif provider == "tesseract":
                available, reason = self._probe_tesseract()

            else:
                reason = f"unknown provider '{provider}'"

        except Exception as e:  # never let a probe break startup
            reason = f"probe error: {e}"

        self.model_availability[key] = available
        if available:
            logger.info("Available: %s", key)
        else:
            logger.info("Unavailable: %s (%s)", key, reason)

        return available

    @staticmethod
    def _probe_ollama(config: Dict) -> tuple:
        """Check the local Ollama server is up and has the model pulled."""
        base_url = config.get("base_url") or "http://localhost:11434"
        try:
            response = requests.get(f"{base_url}/api/tags", timeout=OLLAMA_PROBE_TIMEOUT)
        except requests.RequestException as e:
            return False, f"Ollama unreachable at {base_url} ({type(e).__name__})"

        if response.status_code != 200:
            return False, f"Ollama returned HTTP {response.status_code}"

        # Tags look like "mistral:latest" - match on the name before the colon.
        pulled = {m.get("name", "").split(":")[0] for m in response.json().get("models", [])}
        wanted = config["model"].split(":")[0]

        if wanted not in pulled:
            return False, f"model not pulled (run: ollama pull {wanted})"

        return True, ""

    @staticmethod
    def _probe_tesseract() -> tuple:
        """Check the Tesseract binary is callable."""
        try:
            import pytesseract
        except ImportError:
            return False, "pytesseract not installed"

        if TESSERACT_PATH:
            pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

        try:
            pytesseract.get_tesseract_version()
            return True, ""
        except Exception as e:
            return False, f"tesseract binary not found ({type(e).__name__})"

    # ==================== Reporting ====================

    def refresh_model_availability(self) -> Dict[str, bool]:
        """Re-probe every provider and return the availability map."""
        self.llm_candidates(refresh=True)
        self.vision_candidates()
        return self.model_availability

    def get_model_info(self) -> Dict:
        """Current model configuration, for the admin dashboard."""
        llm = self.llm_candidates()
        vision = self.vision_candidates()

        return {
            "offline_mode": self.offline_mode(),
            "active_llm": self._describe(self._preferred_llm or (llm[0] if llm else None)),
            "active_vision_model": self._describe(
                self._preferred_vision or (vision[0] if vision else None)
            ),
            "llm_chain": [self._describe(c) for c in llm],
            "vision_chain": [self._describe(c) for c in vision],
            "availability": self.model_availability,
        }

    @staticmethod
    def _describe(config: Optional[Dict]) -> Optional[str]:
        if not config:
            return None
        return f"{config['provider']}/{config['model']}"


# Global instance
model_fallback = ModelFallback()


def initialize_models() -> bool:
    """
    Probe providers on startup.

    Returns True when at least one LLM provider is configured. Vision is
    optional - diagram generation works without it; only review-from-image
    needs it.
    """
    offline = model_fallback.offline_mode()
    logger.info("Checking model availability%s...", " (offline mode)" if offline else "")

    llm = model_fallback.llm_candidates(refresh=True)
    vision = model_fallback.vision_candidates()

    if not llm:
        if offline:
            logger.error(
                "Offline mode is on but no local model is available. Install "
                "Ollama and download a model from Admin Dashboard -> Local Models."
            )
        else:
            logger.error(
                "No LLM providers configured. Set GROQ_API_KEY or ANTHROPIC_API_KEY "
                "in .env, or start Ollama with the configured model pulled."
            )
        return False

    logger.info("LLM chain: %s", " -> ".join(f"{c['provider']}/{c['model']}" for c in llm))

    if vision:
        logger.info(
            "Vision chain: %s", " -> ".join(f"{c['provider']}/{c['model']}" for c in vision)
        )
    else:
        logger.warning("No vision providers configured - image review is unavailable.")

    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    initialize_models()
    print("\nModel configuration:")
    for key, value in model_fallback.get_model_info().items():
        print(f"  {key}: {value}")
