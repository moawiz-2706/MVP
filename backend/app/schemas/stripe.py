from pydantic import BaseModel


class StripeConnectionStatus(BaseModel):
    connected: bool
    account_display: str | None = None
    details_submitted: bool = False
    payouts_enabled: bool = False
    transfers_capability_status: str | None = None
    onboarding_complete: bool = False


class StripeOnboardingResponse(BaseModel):
    url: str
    status: StripeConnectionStatus

