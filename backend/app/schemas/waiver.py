import base64
import binascii
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

PNG_PREFIX = "data:image/png;base64,"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_SIGNATURE_BYTES = 300_000


def _strip(value: Any) -> Any:
    return value.strip() if isinstance(value, str) else value


class WaiverSettings(BaseModel):
    """Per-operator waiver content. No waiver text means waivers are switched off."""

    waiver_title: str | None = Field(default=None, max_length=200)
    waiver_website: str | None = Field(default=None, max_length=300)
    waiver_text: str | None = Field(default=None, max_length=60_000)
    waiver_opt_in_label: str | None = Field(default=None, max_length=200)

    @field_validator("*", mode="before")
    @classmethod
    def blank_to_none(cls, value: Any) -> Any:
        value = _strip(value)
        return value or None


class WaiverPerson(BaseModel):
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    date_of_birth: date

    @field_validator("first_name", "last_name", mode="before")
    @classmethod
    def strip_names(cls, value: Any) -> Any:
        return _strip(value)


class WaiverSigner(WaiverPerson):
    email: EmailStr
    phone: str = Field(min_length=3, max_length=40)


class WaiverAddress(BaseModel):
    street: str = Field(min_length=1, max_length=200)
    city: str = Field(min_length=1, max_length=120)
    state: str = Field(min_length=1, max_length=120)
    postal_code: str = Field(min_length=1, max_length=30)
    country: str = Field(min_length=1, max_length=80)

    @field_validator("*", mode="before")
    @classmethod
    def strip_fields(cls, value: Any) -> Any:
        return _strip(value)


class WaiverSignRequest(BaseModel):
    """The lead participant (or guardian) plus everyone else in the booking."""

    signer: WaiverSigner
    address: WaiverAddress
    participants: list[WaiverPerson] = Field(default_factory=list, max_length=99)
    opt_in: bool = False
    agreed: bool
    signature_png: str = Field(max_length=len(PNG_PREFIX) + MAX_SIGNATURE_BYTES * 4 // 3 + 8)

    @field_validator("agreed")
    @classmethod
    def must_agree(cls, value: bool) -> bool:
        if not value:
            raise ValueError("You must agree to the waiver before signing")
        return value

    @field_validator("signature_png")
    @classmethod
    def png_signature(cls, value: str) -> str:
        if not value.startswith(PNG_PREFIX):
            raise ValueError("Signature must be a PNG image")
        try:
            raw = base64.b64decode(value[len(PNG_PREFIX):], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Signature image is not valid") from exc
        if not raw.startswith(PNG_MAGIC) or len(raw) > MAX_SIGNATURE_BYTES:
            raise ValueError("Signature image is not valid")
        return value


class WaiverPrefill(BaseModel):
    first_name: str
    last_name: str
    email: str
    phone: str | None


class PublicWaiver(BaseModel):
    status: Literal["pending", "signed", "unavailable"]
    unavailable_reason: str | None = None
    operator_name: str
    title: str
    website: str | None
    activity_name: str
    activity_start_at: datetime
    activity_end_at: datetime
    time_zone: str
    participants_total: int
    waiver_text: str | None
    opt_in_label: str | None
    prefill: WaiverPrefill | None = None
    signed_at: datetime | None = None
    details: dict[str, Any] | None = None
    signature_png: str | None = None


class WaiverSummary(BaseModel):
    """Waiver state shown on the admin booking panel."""

    status: Literal["signed", "pending", "not_set_up", "not_applicable"]
    signed_at: datetime | None
    url: str | None
