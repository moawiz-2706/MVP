from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
    internal_jobs,
    notifications,
    orders,
    public,
    staff,
    staff_ghl,
    stripe_connect,
    stripe_webhooks,
    waivers,
)
from app.core.config import get_settings
from app.core.exceptions import DomainError, domain_error_handler

settings = get_settings()
app = FastAPI(title=settings.app_name, version="1.0.0")


@app.on_event("startup")
async def validate_runtime_settings() -> None:
    settings.validate_runtime()


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


for router in (
    auth.router,
    availability.router,
    bookings.router,
    configuration.router,
    fareharbor_replica.router,
    ghl_oauth.router,
    ghl_webhooks.router,
    internal_jobs.router,
    notifications.router,
    orders.router,
    public.router,
    staff.router,
    staff_ghl.router,
    stripe_connect.router,
    stripe_webhooks.router,
    waivers.router,
):
    app.include_router(router, prefix=settings.api_prefix)
