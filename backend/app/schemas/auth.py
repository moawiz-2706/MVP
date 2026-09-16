import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class GHLSessionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    encrypted_data: str = Field(alias="encryptedData", min_length=20, max_length=32_000)


class GHLSessionResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MeUser(BaseModel):
    id: uuid.UUID
    ghl_user_id: str
    name: str | None
    email: EmailStr | None
    role: str
    is_agency_owner: bool


class MeOperator(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    time_zone: str
    ghl_location_id: str


class MeResponse(BaseModel):
    user: MeUser
    operator: MeOperator

