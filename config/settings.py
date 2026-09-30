"""
Configuration and settings for the Architecture Diagram Builder application
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ==================== TLS / Corporate Proxy ====================
# Networks that do TLS inspection (most corporate networks) present their own
# root CA. Python does NOT read the OS certificate store, so every HTTPS call
# fails with CERTIFICATE_VERIFY_FAILED even though browsers work fine.
# Point CA_BUNDLE at a PEM file containing that root CA and Python will trust
# it. This keeps certificate verification ON - never disable it.
CA_BUNDLE = os.getenv("CA_BUNDLE", "").strip()
if CA_BUNDLE and Path(CA_BUNDLE).is_file():
    # Must be set before httpx / litellm build their SSL contexts.
    os.environ["SSL_CERT_FILE"] = CA_BUNDLE
    os.environ["REQUESTS_CA_BUNDLE"] = CA_BUNDLE

# ==================== Application Settings ====================
APP_NAME = os.getenv("APP_NAME", "Architecture Diagram Builder")
DEBUG = os.getenv("DEBUG", "False").lower() == "true"
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# ==================== Paths ====================
BASE_DIR = Path(__file__).parent.parent
USER_DATA_DIR = BASE_DIR / "user_data"
CONVERSATIONS_DIR = USER_DATA_DIR / "conversations"
DIAGRAMS_DIR = USER_DATA_DIR / "diagrams"
REVIEWS_DIR = USER_DATA_DIR / "reviews"
UPLOADS_DIR = USER_DATA_DIR / "uploads"
ACTIVITY_LOGS_DIR = USER_DATA_DIR / "activity_logs"
BACKUPS_DIR = USER_DATA_DIR / "backups"
CONFIG_DIR = USER_DATA_DIR / "config"
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
# Settings an admin changes from the UI (offline mode, chosen local models).
# Kept out of .env so a toggle survives a restart without editing files.
RUNTIME_CONFIG_FILE = CONFIG_DIR / "runtime.json"

# Create directories if they don't exist
for directory in [
    USER_DATA_DIR,
    CONVERSATIONS_DIR,
    DIAGRAMS_DIR,
    REVIEWS_DIR,
    UPLOADS_DIR,
    ACTIVITY_LOGS_DIR,
    BACKUPS_DIR,
    CONFIG_DIR,
]:
    directory.mkdir(parents=True, exist_ok=True)

# ==================== Offline Mode ====================
# When on, only providers that run on this machine are used - nothing leaves
# the network. Everything else in the chain (Groq, Gemini, Claude) is skipped
# even if an API key is present. This is the .env default; an admin can flip
# it at runtime from Admin Dashboard -> Local Models, which is stored in
# RUNTIME_CONFIG_FILE and wins over this value.
OFFLINE_MODE = os.getenv("OFFLINE_MODE", "False").lower() == "true"

# Providers that need no internet connection.
LOCAL_PROVIDERS = {"ollama", "tesseract"}

# ==================== Model Selection ====================
# Every model name is overridable from .env so the fallback chains below
# stay in sync with whatever you configure. Change models here, not in code.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_LLM_MODEL = os.getenv("OLLAMA_LLM_MODEL", "mistral")
OLLAMA_VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "llava")

GROQ_LLM_MODEL = os.getenv("GROQ_LLM_MODEL", "llama-3.3-70b-versatile")
# gemini-3.8-flash is frequently rate-limited with 503 "high demand" on the
# free tier; 3.7-flash answered reliably in testing. Override in .env if the
# availability picture changes.
GOOGLE_LLM_MODEL = os.getenv("GOOGLE_LLM_MODEL", "gemini-3.7-flash")
GOOGLE_VISION_MODEL = os.getenv("GOOGLE_VISION_MODEL", "gemini-3.7-flash")
ANTHROPIC_LLM_MODEL = os.getenv("ANTHROPIC_LLM_MODEL", "claude-opus-5")
ANTHROPIC_VISION_MODEL = os.getenv("ANTHROPIC_VISION_MODEL", "claude-opus-5")

# LLM Generation Settings
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.4"))
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "16000"))

# ==================== API Keys ====================
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# ==================== LLM Priority Chain ====================
# Deliberate order: free / cheap providers first, paid Claude as last resort.
LLM_FALLBACK_CHAIN = [
    {
        "provider": "groq",
        "model": GROQ_LLM_MODEL,
        "api_key_env": "GROQ_API_KEY",
        "base_url": None,
    },
    {
        "provider": "ollama",
        "model": OLLAMA_LLM_MODEL,
        "api_key_env": None,
        "base_url": OLLAMA_BASE_URL,
    },
    {
        # Gemini free tier - another no-cost tier ahead of paid Claude.
        "provider": "google",
        "model": GOOGLE_LLM_MODEL,
        "api_key_env": "GOOGLE_API_KEY",
        "base_url": None,
    },
    {
        "provider": "claude",
        "model": ANTHROPIC_LLM_MODEL,
        "api_key_env": "ANTHROPIC_API_KEY",
        "base_url": None,
    },
]

# ==================== Vision Priority Chain ====================
# Tesseract sits ahead of Claude to keep the free tiers first, but it only
# counts as a success when it returns usable text (see vision_service) -
# otherwise OCR noise would absorb every request and Claude would never run.
VISION_FALLBACK_CHAIN = [
    {
        "provider": "google",
        "model": GOOGLE_VISION_MODEL,
        "api_key_env": "GOOGLE_API_KEY",
        "base_url": None,
    },
    {
        "provider": "ollama",
        "model": OLLAMA_VISION_MODEL,
        "api_key_env": None,
        "base_url": OLLAMA_BASE_URL,
    },
    {
        "provider": "tesseract",
        "model": "tesseract-ocr",
        "api_key_env": None,
        "base_url": None,
    },
    {
        "provider": "claude",
        "model": ANTHROPIC_VISION_MODEL,
        "api_key_env": "ANTHROPIC_API_KEY",
        "base_url": None,
    },
]

# ==================== Diagram Settings ====================
DIAGRAM_TYPES = ["Infrastructure", "C4", "DFD", "Sequence"]
DEFAULT_DIAGRAM_TYPE = "Infrastructure"  # Phase 1: Infrastructure only

# ==================== Storage Settings ====================
MAX_UPLOAD_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", 10485760))  # 10MB

# Supported file types for upload
ALLOWED_IMAGE_FORMATS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
ALLOWED_DIAGRAM_FORMATS = {".drawio", ".xml"}
ALLOWED_DOCUMENT_FORMATS = {".pdf"}

# ==================== Authentication Settings ====================
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
SESSION_TIMEOUT_MINUTES = int(os.getenv("SESSION_TIMEOUT_MINUTES", "120"))
SESSION_TIMEOUT = SESSION_TIMEOUT_MINUTES * 60  # seconds

# ==================== OCR Settings ====================
# Leave unset to use whatever `tesseract` is on PATH.
TESSERACT_PATH = os.getenv("TESSERACT_PATH", "")

# ==================== Cloud Service Catalogue ====================
# Fed into the generation prompt so the model names real services.
CLOUD_ICONS = {
    "AWS": {
        "name": "Amazon Web Services",
        "colors": ["#FF9900", "#FFFFFF"],
        "common_services": [
            "EC2", "S3", "Lambda", "RDS", "DynamoDB", "CloudFront",
            "ECS", "ELB", "SQS", "SNS", "IAM", "VPC", "API Gateway",
            "CloudWatch", "Route53", "ElastiCache", "Kinesis"
        ]
    },
    "Azure": {
        "name": "Microsoft Azure",
        "colors": ["#0078D4", "#FFFFFF"],
        "common_services": [
            "VM", "App Service", "SQL Database", "Cosmos DB", "Blob Storage",
            "Function Apps", "Logic Apps", "API Management", "Load Balancer",
            "Virtual Network", "Service Bus", "Event Hubs", "Azure DevOps"
        ]
    },
    "GCP": {
        "name": "Google Cloud Platform",
        "colors": ["#4285F4", "#FFFFFF"],
        "common_services": [
            "Compute Engine", "Cloud Run", "Cloud Functions", "Cloud SQL",
            "Firestore", "Cloud Storage", "Pub/Sub", "Cloud Load Balancing",
            "Cloud CDN", "Cloud Armor", "Cloud Endpoints", "Cloud IAM"
        ]
    }
}

# ==================== Diagram Generation Prompts ====================
ARCHITECTURE_BLUEPRINT_SYSTEM_PROMPT = """You are an expert cloud architect.

You design realistic, scalable cloud architectures and describe them as strict \
JSON blueprints that a downstream renderer converts into draw.io diagrams.

Guidelines:
1. Use real service names for the requested cloud provider.
2. Organise components by layer (Presentation, Application, Data, Integration).
3. Every connection must reference component names exactly as you declared them.
4. Include the components a production deployment actually needs - load
   balancing, caching, persistence, observability - without inventing scope
   the user did not ask for.

Respond with a single JSON object and nothing else. No markdown fences, no
commentary before or after the JSON."""

ORCHESTRATION_SYSTEM_PROMPT = """You are a routing agent for architecture \
diagram requests. You classify the user's intent and extract structured \
parameters from their description.

Respond with a single JSON object and nothing else. No markdown fences, no
commentary before or after the JSON."""

DIAGRAM_REVIEW_SYSTEM_PROMPT = """You are an expert cloud architect \
specialising in reviewing and critiquing infrastructure architectures.

Analyse the provided architecture and identify:
1. Security gaps and vulnerabilities
2. Cost optimization opportunities
3. Performance bottlenecks and scalability issues
4. Compliance and governance concerns
5. Missing components or unnecessary redundancy

Be constructive and specific: cite the components involved and give an
actionable improvement for every issue you raise.

Respond with a single JSON object and nothing else. No markdown fences, no
commentary before or after the JSON."""


VALIDATION_SYSTEM_PROMPT = """You are a meticulous architecture reviewer \
checking a diagram for correctness.

This is not a design critique. You are not being asked whether the
architecture is a good idea, whether it follows best practice, or how it could
be improved. You are being asked a narrower question: taken on its own terms,
is what this diagram says internally consistent and workable?

Hold yourself to these standards:
1. Ground every finding in something actually drawn. Name the components
   involved. If you cannot point at it, do not raise it.
2. Do not invent components. If a diagram omits something, that is a finding
   about an omission, not licence to assume it is there.
3. Distinguish "this cannot work" from "I would have done it differently".
   Only the first belongs here.
4. An empty findings list is a valid and useful answer. Do not manufacture
   problems to appear thorough - a diagram with nothing wrong scores 100.
5. Prefer silence over a claim you are unsure of. Your answer is compared
   against other models independently reviewing the same diagram, and a
   confident wrong claim is worse than a gap.

Respond with a single JSON object and nothing else. No markdown fences, no
commentary before or after the JSON."""
