import json

import pytest

from models import Node
from schemas.agent import OnboardingRequest
from schemas.structured_ai import (
    AssessmentQuestions,
    DiagnosticQuestions,
    DiagnosticScore,
    PersonalizedGraphDraft,
)
from services.agent.orchestrator import confirm_run, start_onboarding, submit_answer
from services.agent.structured_ai import StructuredResult
from services.assessments import start_assessment


DOMAINS = [
    ("education", "代数教学", "concept", "explanation"),
    ("medical", "急救基础", "procedure", "safety_scenario"),
    ("legal", "合同法", "analysis", "case_analysis"),
    ("finance", "财务报表", "analysis", "calculation"),
    ("art", "水彩创作", "creation", "portfolio_reflection"),
    ("life_skill", "家庭烹饪", "procedure", "demonstration"),
    ("technology", "Web 开发", "procedure", "code_review"),
]


class DomainGenerator:
    def __init__(self, domain: str, input_type: str):
        self.domain = domain
        self.input_type = input_type

    def __call__(self, schema, messages, _context):
        payload = json.loads(messages[-1]["content"])
        params = payload.get("params", payload)
        assert params["domain"] == self.domain
        if schema is DiagnosticQuestions:
            value = schema.model_validate(
                {
                    "questions": [
                        {
                            "question_id": "q1",
                            "dimension": "prior_knowledge",
                            "prompt": f"{self.domain} prior",
                            "input_type": self.input_type,
                        },
                        {
                            "question_id": "q2",
                            "dimension": "application",
                            "prompt": f"{self.domain} application",
                            "input_type": self.input_type,
                        },
                        {
                            "question_id": "q3",
                            "dimension": "limits",
                            "prompt": f"{self.domain} limits",
                            "input_type": self.input_type,
                        },
                    ]
                }
            )
        elif schema is DiagnosticScore:
            value = schema.model_validate(
                {
                    "score": 60,
                    "level": "foundation",
                    "domain": self.domain,
                    "outcome_type": params["outcome_type"],
                    "strengths": [],
                    "weaknesses": [f"{self.domain} boundary"],
                    "graph_guidance": [],
                }
            )
        elif schema is PersonalizedGraphDraft:
            value = schema.model_validate(
                {
                    "emoji": "T",
                    "nodes": [
                        {
                            "key": "root",
                            "label": f"{self.domain} foundation",
                            "parent_keys": [],
                            "estimated_minutes": 20,
                        },
                        {
                            "key": "a",
                            "label": "A",
                            "parent_keys": ["root"],
                            "estimated_minutes": 20,
                        },
                        {
                            "key": "b",
                            "label": "B",
                            "parent_keys": ["root"],
                            "estimated_minutes": 20,
                        },
                        {
                            "key": "c",
                            "label": "C",
                            "parent_keys": ["a"],
                            "estimated_minutes": 20,
                        },
                        {"key": "d", "label": "D", "parent_keys": ["a"], "estimated_minutes": 20},
                        {"key": "e", "label": "E", "parent_keys": ["b"], "estimated_minutes": 20},
                    ],
                }
            )
        elif schema is AssessmentQuestions:
            value = schema.model_validate(
                {
                    "questions": [
                        {
                            "question_id": f"aq{index}",
                            "dimension": dimension,
                            "prompt": f"{self.domain} {dimension}",
                            "input_type": self.input_type,
                            "rubric": [
                                {"criterion": "observable", "observable_standards": ["specific"]}
                            ],
                        }
                        for index, dimension in enumerate(("concept", "application", "boundary"), 1)
                    ]
                }
            )
        else:
            raise AssertionError(f"Unexpected schema {schema}")
        return StructuredResult(value=value, token_usage=1, latency_ms=1, attempts=1)


@pytest.mark.parametrize("domain,topic,outcome,input_type", DOMAINS)
def test_fixed_cross_domain_learning_flows(
    db_session, auth_user, domain, topic, outcome, input_type
):
    generator = DomainGenerator(domain, input_type)
    run = start_onboarding(
        db_session,
        user_id=auth_user.id,
        request=OnboardingRequest(
            topic=topic,
            goal=f"learn {topic}",
            domain=domain,
            outcome_type=outcome,
            familiarity="beginner",
            daily_minutes=30,
            timezone="UTC",
            use_diagnostic=True,
            session_id=f"domain-{domain}",
        ),
        generator=generator,
    )
    assert run.state_json["questions"][0]["input_type"] == input_type
    for index in range(3):
        run = submit_answer(
            db_session,
            user_id=auth_user.id,
            run_id=run.id,
            step_id=run.state_json["step_id"],
            version=run.version,
            answer=f"fixed answer {index}",
            generator=generator,
        )
    assert run.state_json["preview"]["domain"] == domain
    assert run.state_json["preview"]["nodes"][0]["label"].startswith(domain)
    assert bool(run.state_json["preview"]["risk_notice"]) is (
        domain in {"medical", "legal", "finance"}
    )
    completed = confirm_run(
        db_session,
        user_id=auth_user.id,
        run_id=run.id,
        request_id=f"confirm-{domain}",
    )
    root = (
        db_session.query(Node)
        .filter_by(topic_id=completed.result_json["topic_id"], node_key="root")
        .one()
    )
    assessment = start_assessment(
        db_session,
        user_id=auth_user.id,
        node_id=root.id,
        request_id=f"assessment-{domain}",
        session_id=f"domain-{domain}",
        generator=generator,
    )
    assert assessment.state_json["questions"][0]["input_type"] == input_type
