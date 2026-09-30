"""
Pydantic data models for the application
"""

from typing import List, Dict, Optional, Any
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum


class DiagramType(str, Enum):
    INFRASTRUCTURE = "Infrastructure"
    C4 = "C4"
    DFD = "DFD"
    SEQUENCE = "Sequence"


class TaskType(str, Enum):
    GENERATE = "generate"
    REVIEW = "review"
    BOTH = "both"


class ReviewSeverity(str, Enum):
    CRITICAL = "Critical"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class ReviewCategory(str, Enum):
    SECURITY = "Security"
    COST = "Cost Optimization"
    PERFORMANCE = "Performance"
    SCALABILITY = "Scalability"
    COMPLIANCE = "Compliance"
    ARCHITECTURE = "Architecture"


# ==================== User Models ====================

class User(BaseModel):
    """User account model"""
    user_id: str
    username: str
    password_hash: str
    is_admin: bool = False
    created_at: datetime
    last_login: Optional[datetime] = None
    status: str = "active"  # active, inactive, suspended
    email: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "usr_123",
                "username": "john_doe",
                "password_hash": "$2b$12$...",
                "is_admin": False,
                "created_at": "2024-01-01T00:00:00",
                "status": "active"
            }
        }


# ==================== Conversation Models ====================

class Message(BaseModel):
    """Individual message in a conversation"""
    id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    type: str = "text"  # text, diagram, review, feedback
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Conversation(BaseModel):
    """Conversation thread model"""
    conversation_id: str
    user_id: str
    title: str
    messages: List[Message] = Field(default_factory=list)
    diagram_ids: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    is_archived: bool = False


# ==================== Diagram Models ====================

class DiagramMetadata(BaseModel):
    """Metadata for generated diagrams"""
    diagram_id: str
    conversation_id: str
    user_id: str
    diagram_type: DiagramType = DiagramType.INFRASTRUCTURE
    cloud_providers: List[str] = Field(default_factory=list)
    architectural_pattern: Optional[str] = None
    project_description: str
    drawio_xml: str
    thumbnail: Optional[str] = None  # base64 encoded
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    version: int = 1
    tags: List[str] = Field(default_factory=list)


class ReviewIssue(BaseModel):
    """Individual issue found during review"""
    category: ReviewCategory
    severity: ReviewSeverity
    description: str
    suggestion: str
    affected_components: List[str] = Field(default_factory=list)


class Review(BaseModel):
    """Architecture review report"""
    review_id: str
    diagram_id: str
    user_id: str
    uploaded_file_type: str  # image, drawio, pdf
    uploaded_file_path: str
    # Name the user recognises. uploaded_file_path points at a temp file that
    # is deleted once the review finishes, so it is useless in a history list.
    source_filename: Optional[str] = None
    issues: List[ReviewIssue] = Field(default_factory=list)
    overall_score: Optional[float] = None  # 0-100
    created_at: datetime = Field(default_factory=datetime.utcnow)
    summary: Optional[str] = None


# ==================== Activity Log Models ====================

class ActivityLog(BaseModel):
    """User activity log entry"""
    log_id: str = Field(default_factory=lambda: str(__import__('uuid').uuid4()))
    user_id: str
    action: str  # "login", "create_diagram", "review_diagram", "upload_file", etc.
    details: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status: str = "success"  # success, failure, warning
    error_message: Optional[str] = None


class SystemHealthMetric(BaseModel):
    """System health monitoring metric"""
    metric_name: str
    value: float
    unit: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    status: str = "ok"  # ok, warning, critical


# ==================== LangGraph State Models ====================

class DiagramState(BaseModel):
    """State for LangGraph workflow"""
    # Session info
    user_id: str
    conversation_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # User input
    user_input: str
    task_type: TaskType = TaskType.GENERATE
    
    # Generation parameters
    project_description: Optional[str] = None
    diagram_type: DiagramType = DiagramType.INFRASTRUCTURE
    cloud_providers: List[str] = Field(default_factory=list)
    architectural_pattern: Optional[str] = None
    
    # Review parameters
    uploaded_file_path: Optional[str] = None
    uploaded_file_name: Optional[str] = None  # name the user uploaded it under
    uploaded_file_type: Optional[str] = None  # image, drawio, pdf
    extracted_architecture: Optional[str] = None
    
    # Execution context
    conversation_history: List[Message] = Field(default_factory=list)
    previous_diagrams: List[str] = Field(default_factory=list)

    # Outputs
    generated_diagram: Optional[str] = None  # draw.io XML
    diagram_id: Optional[str] = None
    review_results: Optional[Review] = None
    error: Optional[str] = None
    execution_status: str = "pending"  # pending, processing, completed, failed


# ==================== File Upload Models ====================

class FileUploadInfo(BaseModel):
    """Information about uploaded file"""
    file_id: str
    user_id: str
    filename: str
    file_type: str  # image, drawio, pdf
    file_size: int
    upload_path: str
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)
    mime_type: str


# ==================== Configuration Models ====================

class SystemConfig(BaseModel):
    """System-wide configuration"""
    default_llm_provider: str = "groq"
    default_vision_provider: str = "google"
    model_availability: Dict[str, bool] = Field(default_factory=dict)
    last_health_check: Optional[datetime] = None
    total_users: int = 0
    total_conversations: int = 0
    total_diagrams_generated: int = 0
    storage_usage_mb: float = 0.0


# ==================== API Request/Response Models ====================

class GenerateDiagramRequest(BaseModel):
    """Request to generate a diagram"""
    project_description: str
    diagram_type: DiagramType = DiagramType.INFRASTRUCTURE
    cloud_providers: List[str] = Field(default_factory=list)
    architectural_pattern: Optional[str] = None


class ReviewArchitectureRequest(BaseModel):
    """Request to review an architecture"""
    file_type: str  # image, drawio, pdf
    file_path: str
    project_description: Optional[str] = None


class RefineRequest(BaseModel):
    """Request to refine existing diagram"""
    diagram_id: str
    refinement_request: str
    feedback: Optional[str] = None


class ChatMessage(BaseModel):
    """Chat message for API"""
    role: str
    content: str
    type: str = "text"


# ==================== Validation Models ====================

class Agreement(str, Enum):
    """How many of the cross-checking models raised the same point."""

    UNANIMOUS = "Unanimous"      # every model that answered agreed
    MAJORITY = "Majority"        # more than half
    SINGLE = "Single model"      # only one model raised it - treat with care
    STRUCTURAL = "Structural"    # a deterministic check, not a model opinion


class ValidationFinding(BaseModel):
    """One problem found in a diagram, with how confident we are in it."""

    check: str                                   # stable id or short slug
    severity: str                                # Critical | High | Medium | Low | Info
    title: str
    detail: str
    components: List[str] = Field(default_factory=list)

    # Provenance. A structural finding is a fact about the file; a model
    # finding is an opinion, and agreement across models is what makes it
    # trustworthy.
    source: str = "model"                        # "structural" | "model"
    agreement: Agreement = Agreement.SINGLE
    raised_by: List[str] = Field(default_factory=list)   # model labels
    confidence: float = 0.0                      # 0-1


class ModelVerdict(BaseModel):
    """What one model concluded, on its own."""

    model_label: str                             # e.g. "groq/openai/gpt-oss-120b"
    reachable: bool = True
    verdict: Optional[str] = None                # Correct | Correct with issues | Incorrect
    score: Optional[float] = None                # 0-100
    summary: Optional[str] = None
    finding_count: int = 0
    error: Optional[str] = None


class ValidationResult(BaseModel):
    """The combined outcome of validating one diagram."""

    validation_id: str
    user_id: str
    source_name: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

    verdict: str = "Unknown"                     # Pass | Pass with warnings | Fail
    consensus_score: Optional[float] = None      # 0-100, averaged across models
    structural_ok: bool = True

    findings: List[ValidationFinding] = Field(default_factory=list)
    model_verdicts: List[ModelVerdict] = Field(default_factory=list)

    component_count: int = 0
    connection_count: int = 0
    notes: Optional[str] = None

    @property
    def models_consulted(self) -> int:
        return sum(1 for verdict in self.model_verdicts if verdict.reachable)

    @property
    def disputed(self) -> List[ValidationFinding]:
        """Findings only one model raised when more than one was consulted."""
        if self.models_consulted < 2:
            return []
        return [
            finding for finding in self.findings
            if finding.source == "model" and finding.agreement == Agreement.SINGLE
        ]


# ==================== Admin Models ====================

class AdminStats(BaseModel):
    """Admin dashboard statistics"""
    total_users: int
    active_users_today: int
    total_conversations: int
    total_diagrams_generated: int
    most_used_cloud: str
    most_common_pattern: str
    system_health_score: float  # 0-100
    last_updated: datetime = Field(default_factory=datetime.utcnow)


class UserActivitySummary(BaseModel):
    """Summary of user activities"""
    user_id: str
    username: str
    total_diagrams: int
    total_reviews: int
    diagrams_this_week: int
    last_active: datetime
    average_diagram_rating: Optional[float] = None
