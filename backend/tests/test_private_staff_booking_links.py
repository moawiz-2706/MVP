import uuid
from datetime import timedelta

import pytest

from app.models.entities import Operator, Staff
from app.services.public_access_service import PublicAccessService
from app.api.v1.staff_booking import _staff_for_token


@pytest.mark.usefixtures("engine")
def test_staff_booking_token_is_digest_only_and_revocable(db):
    operator = Operator(
        ghl_location_id=f"loc-{uuid.uuid4()}",
        name="Test Operator",
        slug=f"test-{uuid.uuid4().hex[:10]}",
        time_zone="UTC",
    )
    db.add(operator)
    db.flush()
    staff = Staff(operator_id=operator.id, name="Mobile Staff", is_active=True)
    db.add(staff)
    db.flush()

    service = PublicAccessService(db)
    raw = service.issue(
        operator_id=operator.id,
        staff_id=staff.id,
        purpose="staff_booking",
        lifetime=timedelta(days=365),
    )
    db.commit()

    credential = service.verify(raw, purpose="staff_booking", staff_id=staff.id, touch=False)
    assert credential.token_digest != raw
    assert credential.staff_id == staff.id
    assert _staff_for_token(db, raw).id == staff.id

    service.revoke(staff_id=staff.id, purpose="staff_booking")
    db.commit()
    with pytest.raises(Exception):
        service.verify(raw, purpose="staff_booking", staff_id=staff.id, touch=False)


def test_inactive_staff_cannot_use_a_private_booking_link(db):
    operator = Operator(
        ghl_location_id=f"loc-{uuid.uuid4()}",
        name="Test Operator",
        slug=f"test-{uuid.uuid4().hex[:10]}",
        time_zone="UTC",
    )
    db.add(operator)
    db.flush()
    staff = Staff(operator_id=operator.id, name="Inactive Staff", is_active=False)
    db.add(staff)
    db.flush()
    raw = PublicAccessService(db).issue(
        operator_id=operator.id,
        staff_id=staff.id,
        purpose="staff_booking",
        lifetime=timedelta(days=365),
    )
    db.commit()

    with pytest.raises(Exception):
        _staff_for_token(db, raw)
