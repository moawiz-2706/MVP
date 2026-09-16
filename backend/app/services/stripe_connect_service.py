import uuid

import stripe
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.entities import StripeConnection
from app.schemas.stripe import StripeConnectionStatus, StripeOnboardingResponse


class StripeConnectService:
    def __init__(self, db: Session, settings: Settings, operator_id: uuid.UUID) -> None:
        if not settings.stripe_secret_key:
            raise RuntimeError("STRIPE_SECRET_KEY is not configured")
        self.db = db
        self.settings = settings
        self.operator_id = operator_id
        self.client = stripe.StripeClient(settings.stripe_secret_key, max_network_retries=2)

    def _connection(self) -> StripeConnection | None:
        return self.db.scalar(
            select(StripeConnection).where(StripeConnection.operator_id == self.operator_id)
        )

    @staticmethod
    def _status(connection: StripeConnection | None) -> StripeConnectionStatus:
        if connection is None:
            return StripeConnectionStatus(connected=False)
        return StripeConnectionStatus(
            connected=True,
            account_display=f"•••• {connection.stripe_account_id[-4:].upper()}",
            details_submitted=connection.details_submitted,
            payouts_enabled=connection.payouts_enabled,
            transfers_capability_status=connection.transfers_capability_status,
            onboarding_complete=connection.onboarding_complete,
        )

    def status(self, *, refresh: bool = False) -> StripeConnectionStatus:
        connection = self._connection()
        if connection and refresh:
            account = self.client.v1.accounts.retrieve(connection.stripe_account_id)
            self._sync(connection, account)
            self.db.commit()
        return self._status(connection)

    def connect(self) -> StripeOnboardingResponse:
        connection = self._connection()
        if connection is None:
            account = self.client.v1.accounts.create(
                {
                    "type": "express",
                    "capabilities": {"transfers": {"requested": True}},
                    "metadata": {"operator_id": str(self.operator_id)},
                },
                {"idempotency_key": f"operator:{self.operator_id}:connected_account"},
            )
            connection = StripeConnection(
                operator_id=self.operator_id,
                stripe_account_id=account.id,
                account_type=account.type,
                country=account.country,
            )
            self._sync(connection, account)
            self.db.add(connection)
            self.db.commit()
        return StripeOnboardingResponse(
            url=self._account_link(connection.stripe_account_id), status=self._status(connection)
        )

    def onboarding_link(self) -> StripeOnboardingResponse:
        connection = self._connection()
        if connection is None:
            return self.connect()
        return StripeOnboardingResponse(
            url=self._account_link(connection.stripe_account_id), status=self._status(connection)
        )

    def _account_link(self, account_id: str) -> str:
        base = self.settings.frontend_url.rstrip("/")
        link = self.client.v1.account_links.create(
            {
                "account": account_id,
                "refresh_url": f"{base}/stripe/connect/refresh",
                "return_url": f"{base}/stripe/connect/return",
                "type": "account_onboarding",
            }
        )
        return link.url

    @staticmethod
    def _sync(connection: StripeConnection, account) -> None:
        capabilities = account.capabilities or {}
        transfers = capabilities.get("transfers")
        connection.account_type = account.type
        connection.country = account.country
        connection.details_submitted = bool(account.details_submitted)
        connection.payouts_enabled = bool(account.payouts_enabled)
        connection.charges_enabled = bool(account.charges_enabled)
        connection.transfers_capability_status = transfers
        connection.onboarding_complete = (
            connection.details_submitted and connection.payouts_enabled and transfers == "active"
        )

