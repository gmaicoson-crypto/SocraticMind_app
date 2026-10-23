from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable

    def payload(self) -> dict[str, str | bool]:
        payload: dict[str, str | bool] = {"code": self.code, "message": self.message}
        if self.retryable is not None:
            payload["retryable"] = self.retryable
        return payload


async def api_error_handler(_request: Request, error: ApiError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content=error.payload())


def _uses_p0_error_contract(path: str) -> bool:
    return (
        path.startswith("/api/agent")
        or path.startswith("/api/attachments")
        or path.startswith("/api/plans")
        or (path.startswith("/api/topics/") and path.endswith("/plan"))
        or (path.startswith("/api/nodes/") and "/mastery" in path)
    )


async def validation_error_handler(request: Request, error: RequestValidationError) -> JSONResponse:
    if _uses_p0_error_contract(request.url.path):
        return JSONResponse(
            status_code=422,
            content={
                "code": "VALIDATION_ERROR",
                "message": "请求参数校验失败",
                "retryable": False,
            },
        )
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(error.errors())})


def install_api_error_handler(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
