"""
LLM service with a cheap-first fallback chain, via LiteLLM.

One code path serves every request: walk the configured providers in priority
order and return the first usable response. There is no separate "selected
model" copy to drift out of sync with the chain.
"""

import logging
import time
from typing import Dict, List, Optional

import litellm
from litellm import completion

from config.model_fallback import model_fallback
from config.settings import LLM_MAX_TOKENS, LLM_TEMPERATURE

logger = logging.getLogger(__name__)

# Keep LiteLLM's "Give Feedback / Get Help" banners out of the app logs; we
# report provider errors ourselves.
litellm.suppress_debug_info = True

# Transient failures worth retrying on the *same* provider before falling
# through to the next one. Free tiers return these routinely - a 503 "high
# demand" from Gemini is usually gone a second later, and dropping straight
# to the next provider wastes a working free tier.
TRANSIENT_ERRORS = (
    litellm.RateLimitError,
    litellm.ServiceUnavailableError,
    litellm.InternalServerError,
    litellm.Timeout,
    litellm.APIConnectionError,
)

RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 2.0

# LiteLLM provider prefixes. Anthropic models are "anthropic/..." - there is
# no "claude/" provider in LiteLLM, which is why the previous code never
# reached Claude at all.
PROVIDER_PREFIX = {
    "groq": "groq",
    "ollama": "ollama",
    "claude": "anthropic",
    "google": "gemini",
}

# Output-token ceilings per provider, so a large default doesn't 400 on a
# model with a small output limit.
MAX_OUTPUT_TOKENS = {
    "groq": 8000,
    "ollama": 4096,
    "claude": 16000,
    "google": 8192,
}

# Current Claude models (Opus 5 / Sonnet 5 / the 4.6+ family) removed the
# sampling parameters - sending temperature is rejected outright:
#   "claude-opus-5 does not support temperature=0.2"
# Reasoning depth is controlled by thinking/effort instead, so we simply omit
# it for this provider rather than globally enabling litellm.drop_params,
# which would silently swallow genuinely wrong parameters too.
# Gemini 3+ still accepts temperature but warns it is being removed, and
# steers you to put sampling guidance in the system prompt - which is where
# ours already lives. Omitting it keeps the logs clean and is forward-safe.
PROVIDERS_WITHOUT_TEMPERATURE = {"claude", "google"}


class LLMService:
    """Text generation with automatic provider fallback."""

    def generate_text(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = LLM_TEMPERATURE,
        max_tokens: int = LLM_MAX_TOKENS,
    ) -> Optional[str]:
        """
        Generate text, trying each configured provider in priority order.

        Returns the response text, or None if every provider failed.
        """
        messages: List[Dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        candidates = model_fallback.llm_candidates()
        if not candidates:
            logger.error(
                "No LLM providers configured - set an API key in .env or start Ollama."
            )
            return None

        last_error: Optional[str] = None

        for config in candidates:
            label = f"{config['provider']}/{config['model']}"

            for attempt in range(1, RETRY_ATTEMPTS + 1):
                try:
                    text = self._call(config, messages, temperature, max_tokens)

                    if text and text.strip():
                        model_fallback.remember_llm(config)
                        return text

                    last_error = "empty response"
                    logger.warning("%s returned an empty response", label)
                    break  # an empty reply won't change on retry - next provider

                except TRANSIENT_ERRORS as e:
                    last_error = f"{type(e).__name__}: {e}"

                    if attempt < RETRY_ATTEMPTS:
                        delay = RETRY_BACKOFF_SECONDS * attempt
                        logger.warning(
                            "%s hit a transient error (attempt %d/%d), retrying in %.0fs: %s",
                            label, attempt, RETRY_ATTEMPTS, delay, type(e).__name__,
                        )
                        time.sleep(delay)
                        continue

                    logger.warning(
                        "%s still failing after %d attempts, trying next provider",
                        label, RETRY_ATTEMPTS,
                    )

                except Exception as e:
                    # Permanent failure (bad key, unknown model, bad request) -
                    # retrying the same provider cannot help.
                    last_error = f"{type(e).__name__}: {e}"
                    logger.warning("%s failed (%s), trying next provider", label, last_error)
                    break

        logger.error("All LLM providers failed. Last error: %s", last_error)
        return None

    def generate_with(
        self,
        config: Dict,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = LLM_TEMPERATURE,
        max_tokens: int = LLM_MAX_TOKENS,
    ) -> Optional[str]:
        """
        Generate using one named provider, with no fallback.

        generate_text() returns as soon as any provider answers, which is what
        you want for a single result and exactly what you do not want when the
        point is to compare providers. Cross-model validation needs each model's
        own answer, so this pins the request to one and returns None if that
        one cannot serve it.
        """
        messages: List[Dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        label = f"{config.get('provider')}/{config.get('model')}"

        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                text = self._call(config, messages, temperature, max_tokens)
                if text and text.strip():
                    return text

                logger.warning("%s returned an empty response", label)
                return None

            except TRANSIENT_ERRORS as e:
                if attempt < RETRY_ATTEMPTS:
                    delay = RETRY_BACKOFF_SECONDS * attempt
                    logger.warning(
                        "%s hit a transient error (attempt %d/%d), retrying in %.0fs: %s",
                        label, attempt, RETRY_ATTEMPTS, delay, type(e).__name__,
                    )
                    time.sleep(delay)
                    continue
                logger.warning("%s still failing after %d attempts", label, RETRY_ATTEMPTS)
                return None

            except Exception as e:
                logger.warning("%s failed: %s: %s", label, type(e).__name__, e)
                return None

        return None

    def _call(
        self,
        config: Dict,
        messages: List[Dict],
        temperature: float,
        max_tokens: int,
    ) -> Optional[str]:
        """Issue one completion request against a single provider."""
        provider = config["provider"]
        model = config["model"]

        prefix = PROVIDER_PREFIX.get(provider)
        if not prefix:
            raise ValueError(f"Unsupported LLM provider: {provider}")

        kwargs = {
            "model": f"{prefix}/{model}",
            "messages": messages,
            "max_tokens": min(max_tokens, MAX_OUTPUT_TOKENS.get(provider, max_tokens)),
        }

        if provider not in PROVIDERS_WITHOUT_TEMPERATURE:
            kwargs["temperature"] = temperature

        if provider == "ollama":
            kwargs["api_base"] = config.get("base_url") or "http://localhost:11434"

        logger.info("Calling %s", kwargs["model"])
        response = completion(**kwargs)

        return response.choices[0].message.content


llm_service = LLMService()
