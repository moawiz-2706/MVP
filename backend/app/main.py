import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.v1 import (
    auth,
    availability,
    bookings,
    configuration,
    fareharbor_replica,
    ghl_oauth,
    ghl_webhooks,
    ghl_workflow_trigger,
    internal_jobs,
    messages,
    notifications,
    orders,
    pwa,
    pwa_auth,
    public,
    reports,
    staff,
    staff_booking,
    staff_ghl,
    stripe_connect,
    stripe_webhooks,
    waivers,
)
from app.core.config import Settings, get_settings
from app.core.exceptions import DomainError, domain_error_handler
from app.core.database import check_database_readiness

logger = logging.getLogger("passport.startup")

# Why the API refused to serve, as safe text (setting names, never values).
# A crash at import or startup takes every route down with no diagnosis, so
# configuration failures instead lock the business API behind a 503 while
# /api/health and /api/readiness keep explaining what is wrong.
startup_error: str | None = None
try:
    settings = get_settings()
except ValidationError as exc:
    fields = sorted({str(error["loc"][0]).upper() for error in exc.errors() if error.get("loc")})
    startup_error = "Invalid settings: " + ", ".join(fields)
    logger.error("Passport settings are invalid: %s", ", ".join(fields))
    settings = Settings.model_construct()
app = FastAPI(title=settings.app_name, version="1.0.0")


@app.on_event("startup")
async def validate_runtime_settings() -> None:
    global startup_error
    if startup_error:
        return
    try:
        settings.validate_runtime()
        if settings.is_production:
            check_database_readiness()
    except Exception as exc:
        startup_error = str(exc)[:500]
        logger.error("Passport startup checks failed: %s", startup_error)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "Stripe-Signature",
        "X-Cron-Secret",
        "X-GHL-Signature",
        "X-Checkout-Key",
        "X-Staff-Booking-Key",
        "X-Passport-Client",
    ],
)
app.add_exception_handler(DomainError, domain_error_handler)


@app.exception_handler(IntegrityError)
async def integrity_error_handler(_request: Request, _exc: IntegrityError) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "code": "integrity_conflict",
                "message": "That value conflicts with existing data",
            }
        },
    )


@app.middleware("http")
async def iframe_security_headers(request: Request, call_next):
    if startup_error and request.url.path.startswith(settings.api_prefix):
        # Fail closed: no booking or payment work on a misconfigured deployment.
        response = JSONResponse(
            status_code=503,
            content={"error": {"code": "not_ready", "message": "Passport is not configured correctly. See /api/readiness."}},
        )
    else:
        response = await call_next(request)
    # frame-ancestors https: allows embedding inside HighLevel and any agency
    # white-label domain (unknowable in advance for a Marketplace app). Security
    # comes from the encrypted GHL user-context handshake, not from framing.
    response.headers["Content-Security-Policy"] = "frame-ancestors https:"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/api/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/readiness", tags=["health"])
def readiness() -> JSONResponse:
    if startup_error:
        return JSONResponse(status_code=503, content={"status": "not_ready", "detail": startup_error})
    try:
        settings.validate_runtime()
        if settings.is_production:
            payload = check_database_readiness()
        else:
            payload = {"status": "ready", "schema_version": "development"}
        payload["environment"] = "production" if settings.is_production else "non-production"
        warnings = settings.environment_warnings + list(payload.get("warnings", []))
        if warnings:
            payload["warnings"] = warnings
        return JSONResponse(status_code=200, content=payload)
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "detail": str(exc)[:500]},
        )


for router in (
    auth.router,
    availability.router,
    bookings.router,
    configuration.router,
    fareharbor_replica.router,
    ghl_oauth.router,
    ghl_webhooks.router,
    ghl_workflow_trigger.router,
    internal_jobs.router,
    messages.router,
    notifications.router,
    orders.router,
    pwa.router,
    pwa_auth.router,
    public.router,
    reports.router,
    staff.router,
    staff_booking.router,
    staff_ghl.router,
    stripe_connect.router,
    stripe_webhooks.router,
    waivers.router,
):
    app.include_router(router, prefix=settings.api_prefix)
