"""Configuration package"""

from config.model_fallback import initialize_models, model_fallback

__all__ = [
    "model_fallback",
    "initialize_models",
]
