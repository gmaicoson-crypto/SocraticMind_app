from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.errors import ApiError, install_api_error_handler


def test_api_error_uses_p0_contract():
    app = FastAPI()
    install_api_error_handler(app)

    @app.get("/conflict")
    def conflict():
        raise ApiError(
            status_code=409,
            code="AGENT_STATE_CONFLICT",
            message="The step is stale",
            retryable=False,
        )

    response = TestClient(app).get("/conflict")

    assert response.status_code == 409
    assert response.json() == {
        "code": "AGENT_STATE_CONFLICT",
        "message": "The step is stale",
        "retryable": False,
    }


def test_retryable_is_optional():
    error = ApiError(status_code=404, code="RUN_NOT_FOUND", message="Not found")
    assert error.payload() == {"code": "RUN_NOT_FOUND", "message": "Not found"}
