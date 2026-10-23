from enum import Enum


class AgentRunType(str, Enum):
    ONBOARDING = "onboarding"
    TOPIC_PLAN = "topic_plan"
    ASSESSMENT = "assessment"


class AgentRunStatus(str, Enum):
    COLLECTING = "collecting"
    DIAGNOSING = "diagnosing"
    DRAFTING = "drafting"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    ASSESSING = "assessing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OutcomeType(str, Enum):
    CONCEPT = "concept"
    PROCEDURE = "procedure"
    ANALYSIS = "analysis"
    EXPRESSION = "expression"
    CREATION = "creation"
    MIXED = "mixed"


class Familiarity(str, Enum):
    NEW = "new"
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class MemoryKind(str, Enum):
    GOAL = "goal"
    BACKGROUND = "background"
    PREFERENCE = "preference"
    STRENGTH = "strength"
    WEAKNESS = "weakness"


class MemorySource(str, Enum):
    USER = "user"
    DIAGNOSTIC = "diagnostic"
    ASSESSMENT = "assessment"


class PlanStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class PlanItemStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"


class AssessmentStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class MasterySource(str, Enum):
    ASSESSMENT = "assessment"
    SELF_REPORTED = "self_reported"
    LEGACY = "legacy"
    REVERT = "revert"
