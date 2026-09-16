from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class DomainError(Exception):
    def __init__(self, message: str, *, status_code: int = 400, code: str = "domain_error"):
        self.message = message
        self.status_code = status_code
        self.code = code
        super().__init__(message)


class NotFoundError(DomainError):
    def __init__(self, message: str = "Not found") -> None:
        super().__init__(message, status_code=404, code="not_found")


class ConflictError(DomainError):
    def __init__(self, message: str, *, details: Any | None = None) -> None:
        self.details = details
        super().__init__(message, status_code=409, code="conflict")


async def domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
    body: dict[str, Any] = {"error": {"code": exc.code, "message": exc.message}}
    if isinstance(exc, ConflictError) and exc.details is not None:
        body["error"]["details"] = exc.details
    return JSONResponse(status_code=exc.status_code, content=body)

