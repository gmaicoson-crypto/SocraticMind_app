from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from models.enums import OutcomeType


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DiagnosticLevel(str, Enum):
    ENTRY = "entry"
    FOUNDATION = "foundation"
    PROFICIENT = "proficient"


class DomainClassification(StrictModel):
    domain: str = Field(min_length=1, max_length=100)
    outcome_type: OutcomeType
    high_risk: bool = False


class GeneratedQuestion(StrictModel):
    question_id: str = Field(min_length=1, max_length=100)
    dimension: str = Field(min_length=1, max_length=50)
    prompt: str = Field(min_length=1, max_length=2000)
    input_type: str = "text"
    choices: list[str] = Field(default_factory=list, max_length=8)


class DiagnosticQuestions(StrictModel):
    questions: list[GeneratedQuestion] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def cover_required_dimensions(self):
        ids = {question.question_id for question in self.questions}
        dimensions = {question.dimension for question in self.questions}
        if len(ids) != 3:
            raise ValueError("diagnostic question ids must be unique")
        if dimensions != {"prior_knowledge", "application", "limits"}:
            raise ValueError("diagnostic questions must cover all required dimensions")
        return self


class DiagnosticScore(StrictModel):
    score: int = Field(ge=0, le=100)
    level: DiagnosticLevel
    domain: str = Field(min_length=1, max_length=100)
    outcome_type: OutcomeType
    strengths: list[str] = Field(default_factory=list, max_length=10)
    weaknesses: list[str] = Field(default_factory=list, max_length=10)
    graph_guidance: list[str] = Field(default_factory=list, max_length=10)


class GraphDraftNode(StrictModel):
    key: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=200)
    sub: str = Field(default="", max_length=500)
    parent_keys: list[str] = Field(default_factory=list, max_length=1)
    estimated_minutes: int = Field(ge=10, le=120)


class PersonalizedGraphDraft(StrictModel):
    emoji: str = Field(default="📚", max_length=10)
    nodes: list[GraphDraftNode] = Field(min_length=6, max_length=10)


class RubricCriterion(StrictModel):
    criterion: str = Field(min_length=1, max_length=300)
    observable_standards: list[str] = Field(min_length=1, max_length=6)


class AssessmentQuestion(GeneratedQuestion):
    rubric: list[RubricCriterion] = Field(min_length=1, max_length=6)


class AssessmentQuestions(StrictModel):
    questions: list[AssessmentQuestion] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def question_ids_are_unique(self):
        if len({question.question_id for question in self.questions}) != 3:
            raise ValueError("assessment question ids must be unique")
        return self


class QuestionScore(StrictModel):
    question_id: str = Field(min_length=1, max_length=100)
    score: int = Field(ge=0, le=4)
    rationale: str = Field(min_length=1, max_length=1000)


class AssessmentScore(StrictModel):
    scores: list[QuestionScore] = Field(min_length=3, max_length=3)
    total_score: int = Field(ge=0, le=12)
    evaluation_confidence: float = Field(ge=0, le=1)
    critical_misconception: bool
    evidence: str = Field(min_length=1, max_length=3000)
    weaknesses: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def total_matches_question_scores(self):
        if len({score.question_id for score in self.scores}) != 3:
            raise ValueError("score question ids must be unique")
        if self.total_score != sum(score.score for score in self.scores):
            raise ValueError("total_score must equal the sum of question scores")
        return self
