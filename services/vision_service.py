"""
Vision service for reading architecture diagrams from images.

Cloud vision providers all go through LiteLLM using one image payload format,
so Gemini / LLaVA / Claude differ only by model string. Tesseract is the local
OCR fallback and is handled separately.
"""

import base64
import logging
from pathlib import Path
from typing import Dict, Optional

from litellm import completion

from config.model_fallback import model_fallback
from config.settings import TESSERACT_PATH

logger = logging.getLogger(__name__)

PROVIDER_PREFIX = {
    "google": "gemini",
    "ollama": "ollama",
    "claude": "anthropic",
}

MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}

# OCR returns *something* for almost any image. Below this many characters we
# treat it as noise and keep walking the chain, so Tesseract sitting ahead of
# Claude doesn't silently absorb every request.
MIN_USABLE_OCR_CHARS = 40

ARCHITECTURE_PROMPT = """Analyse this architecture diagram and describe:
1. Every cloud component / service shown, by name
2. The connections between them and their direction
3. The cloud provider(s) in use
4. The architectural pattern
5. Any security or performance concerns visible in the design

Respond as structured plain text."""


class VisionService:
    """Extracts architecture descriptions from diagram images."""

    def analyze_architecture_from_image(self, image_path: str) -> Optional[str]:
        """Describe the architecture shown in a diagram image."""
        return self.extract_text_from_image(image_path, ARCHITECTURE_PROMPT)

    def extract_text_from_image(
        self,
        image_path: str,
        prompt: str = "Extract all text from this image",
    ) -> Optional[str]:
        """
        Read an image with the best available vision provider.

        Walks the configured chain and returns the first usable result, or
        None if every provider failed.
        """
        candidates = model_fallback.vision_candidates()
        if not candidates:
            logger.error("No vision providers configured - cannot read images.")
            return None

        last_error: Optional[str] = None

        for config in candidates:
            label = f"{config['provider']}/{config['model']}"
            try:
                if config["provider"] == "tesseract":
                    text = self._extract_with_ocr(image_path)
                    if text and len(text.strip()) >= MIN_USABLE_OCR_CHARS:
                        model_fallback.remember_vision(config)
                        return text
                    last_error = "OCR returned too little text to be usable"
                    logger.warning("%s: %s, trying next provider", label, last_error)
                    continue

                text = self._extract_with_vision(config, image_path, prompt)
                if text and text.strip():
                    model_fallback.remember_vision(config)
                    return text

                last_error = "empty response"
                logger.warning("%s returned an empty response, trying next provider", label)

            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                logger.warning("%s failed (%s), trying next provider", label, last_error)

        logger.error("All vision providers failed. Last error: %s", last_error)
        return None

    # ==================== Providers ====================

    def _extract_with_vision(self, config: Dict, image_path: str, prompt: str) -> Optional[str]:
        """Call a cloud/local vision model through LiteLLM."""
        provider = config["provider"]
        prefix = PROVIDER_PREFIX.get(provider)
        if not prefix:
            raise ValueError(f"Unsupported vision provider: {provider}")

        data_uri = self._image_data_uri(image_path)

        kwargs = {
            "model": f"{prefix}/{config['model']}",
            # OpenAI-style multimodal content. LiteLLM translates this into
            # each provider's native format, including Anthropic's
            # image/source blocks - which is why we no longer hand-build them.
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }],
            "max_tokens": 4000,
        }

        if provider == "ollama":
            kwargs["api_base"] = config.get("base_url") or "http://localhost:11434"

        logger.info("Reading image with %s", kwargs["model"])
        response = completion(**kwargs)

        return response.choices[0].message.content

    def _extract_with_ocr(self, image_path: str) -> Optional[str]:
        """Local Tesseract OCR fallback."""
        try:
            import pytesseract
            from PIL import Image
        except ImportError:
            logger.warning("pytesseract/Pillow not installed - skipping OCR")
            return None

        if TESSERACT_PATH:
            pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH

        logger.info("Reading image with Tesseract OCR")
        with Image.open(image_path) as image:
            return pytesseract.image_to_string(image)

    # ==================== Helpers ====================

    @staticmethod
    def _image_data_uri(image_path: str) -> str:
        """Base64 data URI with the media type taken from the real extension."""
        path = Path(image_path)
        media_type = MEDIA_TYPES.get(path.suffix.lower())

        if not media_type:
            raise ValueError(f"Unsupported image format: {path.suffix or 'no extension'}")

        encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
        return f"data:{media_type};base64,{encoded}"


vision_service = VisionService()
