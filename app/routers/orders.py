"""User-side order endpoints (create, list, view, cancel, review)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..config import get_settings
from ..database import (
    appointments,
    cars,
    database,
    requests,
    reviews,
    schedule_slots,
    services,
)
from ..deps import current_locale, current_user
from ..i18n import Locale, t
from ..push import push_to_admins
from ..schemas import (
    CancelIn,
    Message,
    RequestCreateIn,
    RequestOut,
    ReviewIn,
    SlotOut,
)

router = APIRouter(prefix="/orders", tags=["orders"])


# ---------------------------------------------------------------------
# Check for active order by service key
# ---------------------------------------------------------------------
@router.get("/check-active")
async def check_active_order(
    service_key: str,
    user=Depends(current_user),
) -> dict:
    """Check if user has an active order with the given service key."""
    if not service_key:
        return {"has_active_order": False, "order_id": None}
    
    active_statuses = [
        "PENDING_REVIEW",
        "AWAITING_USER_CONFIRM",
        "TIME_CONFIRMED",
        "PRICE_CONFIRMED",
        "IN_PROGRESS",
    ]
    
    row = await database.fetch_one(
        requests.select().where(
            (requests.c.user_id == user['id']) &
            (requests.c.status.in_(active_statuses))
        )
    )
    
    if row is None:
        return {"has_active_order": False, "order_id": None}
    
    # Check if the order contains the service key
    service_keys = row["service_keys"] or []
    if service_key not in service_keys:
        return {"has_active_order": False, "order_id": None}
    
    return {"has_active_order": True, "order_id": row["id"]}


# ---------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------
@router.post(
    "", response_model=RequestOut, status_code=status.HTTP_201_CREATED
)
async def create_order(
    body: RequestCreateIn,
    user=Depends(current_user),
    locale: Locale = Depends(current_locale),
) -> RequestOut:
    # Validate service keys
    valid_rows = await database.fetch_all(
        services.select().where(services.c.key.in_(body.service_keys))
    )
    valid_keys = {r["key"] for r in valid_rows if r["is_active"]}
    missing = set(body.service_keys) - valid_keys
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"invalid service keys: {sorted(missing)}",
        )
    
    # Parse datetime strings without timezone conversion
    visit1_datetime = None
    visit2_datetime = None
    if body.visit1_datetime:
        visit1_datetime = datetime.fromisoformat(body.visit1_datetime)
    if body.visit2_datetime:
        visit2_datetime = datetime.fromisoformat(body.visit2_datetime)
    
    # Check for time conflicts with existing slots
    requested_times = []
    if visit1_datetime:
        requested_times.append(visit1_datetime)
    if visit2_datetime:
        requested_times.append(visit2_datetime)
    
    if requested_times:
        for requested_time in requested_times:
            # Check if there's any existing slot that overlaps with the requested time
            conflict = await database.fetch_one(
                schedule_slots.select().where(
                    (schedule_slots.c.start_at < requested_time + timedelta(hours=1)) &
                    (schedule_slots.c.end_at > requested_time) &
                    (schedule_slots.c.status.in_(["REQUESTED", "PROPOSED", "CONFIRMED"]))
                )
            )
            if conflict:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Time slot {requested_time} is already booked",
                )
            # Also check appointments table
            appointment_conflict = await database.fetch_one(
                appointments.select().where(
                    (appointments.c.start_at < requested_time + timedelta(hours=1)) &
                    (appointments.c.end_at > requested_time)
                )
            )
            if appointment_conflict:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Time slot {requested_time} is already booked",
                )

    requires_car = any(r["requires_car"] for r in valid_rows)
    if requires_car and body.car_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="car_id is required for car-related services",
        )
    if body.car_id is not None:
        car_row = await database.fetch_one(
            cars.select().where(cars.c.id == body.car_id)
        )
        if car_row is None or car_row["user_id"] != user["id"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="car not owned by user",
            )

    new_id = await database.execute(
        requests.insert().values(
            user_id=user["id"],
            status="PENDING_REVIEW",
            service_keys=list(body.service_keys),
            car_id=body.car_id,
            latitude=body.latitude,
            longitude=body.longitude,
            address_text=body.address_text,
            house_number=body.house_number,
            visit1_datetime=visit1_datetime,
            visit2_datetime=visit2_datetime,
            total_price=body.base_price,
            notes=body.notes,
            payment_type=body.payment_type,
            promotion_id=body.promotion_id,
        )
    )
    
    # Add requested times to schedule_slots to prevent conflicts
    if visit1_datetime:
        await database.execute(
            schedule_slots.insert().values(
                request_id=new_id,
                start_at=visit1_datetime,
                end_at=visit1_datetime + timedelta(hours=1),
                status="REQUESTED",
            )
        )
    if visit2_datetime:
        await database.execute(
            schedule_slots.insert().values(
                request_id=new_id,
                start_at=visit2_datetime,
                end_at=visit2_datetime + timedelta(hours=1),
                status="REQUESTED",
            )
        )
    
    row = await database.fetch_one(requests.select().where(requests.c.id == new_id))

    # Notify admins.
    await push_to_admins(
        title=t("notify.new_order", locale),
        body=f"#{int(row['id'])} – {', '.join(body.service_keys)}",
        data={"type": "new_order", "request_id": int(row["id"])},
    )
    return RequestOut(**dict(row))


# ---------------------------------------------------------------------
# List
# ---------------------------------------------------------------------
@router.get("", response_model=List[RequestOut])
async def list_my_orders(
    user=Depends(current_user),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> List[RequestOut]:
    q = requests.select().where(requests.c.user_id == user["id"])
    if status_filter:
        q = q.where(requests.c.status == status_filter)
    q = q.order_by(requests.c.created_at.desc()).limit(limit).offset(offset)
    rows = await database.fetch_all(q)
    return [RequestOut(**dict(r)) for r in rows]


# ---------------------------------------------------------------------
# Detail
# ---------------------------------------------------------------------
@router.get("/{request_id}", response_model=RequestOut)
async def get_order(
    request_id: int,
    user=Depends(current_user),
    locale: Locale = Depends(current_locale),
) -> RequestOut:
    row = await database.fetch_one(
        requests.select().where(requests.c.id == request_id)
    )
    if row is None or (row["user_id"] != user["id"] and not user["is_admin"]):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("order.not_found", locale),
        )
    return RequestOut(**dict(row))


@router.get("/{request_id}/slots", response_model=List[SlotOut])
async def list_order_slots(
    request_id: int,
    user=Depends(current_user),
    locale: Locale = Depends(current_locale),
) -> List[SlotOut]:
    row = await database.fetch_one(
        requests.select().where(requests.c.id == request_id)
    )
    if row is None or (row["user_id"] != user["id"] and not user["is_admin"]):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("order.not_found", locale),
        )
    rows = await database.fetch_all(
        schedule_slots.select()
        .where(schedule_slots.c.request_id == request_id)
        .order_by(schedule_slots.c.start_at)
    )
    return [SlotOut(**dict(r)) for r in rows]


# ---------------------------------------------------------------------
# Cancel
# ---------------------------------------------------------------------
@router.post("/{request_id}/cancel", response_model=RequestOut)
async def cancel_order(
    request_id: int,
    body: CancelIn,
    user=Depends(current_user),
    locale: Locale = Depends(current_locale),
) -> RequestOut:
    row = await database.fetch_one(
        requests.select().where(requests.c.id == request_id)
    )
    if row is None or row["user_id"] != user["id"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("order.not_found", locale),
        )
    if row["status"] in ("IN_PROGRESS", "COMPLETED", "CANCELLED"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=t("order.invalid_status", locale),
        )
    async with database.transaction():
        await database.execute(
            requests.update()
            .where(requests.c.id == request_id)
            .values(
                status="CANCELLED",
                cancel_reason=body.reason,
                updated_at=datetime.now(),
            )
        )
        await database.execute(
            appointments.delete().where(appointments.c.request_id == request_id)
        )
    row = await database.fetch_one(
        requests.select().where(requests.c.id == request_id)
    )
    return RequestOut(**dict(row))


# ---------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------
@router.post("/{request_id}/review", response_model=Message)
async def submit_review(
    request_id: int,
    body: ReviewIn,
    user=Depends(current_user),
    locale: Locale = Depends(current_locale),
) -> Message:
    row = await database.fetch_one(
        requests.select().where(requests.c.id == request_id)
    )
    if row is None or row["user_id"] != user["id"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=t("order.not_found", locale),
        )
    if row["status"] != "COMPLETED":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=t("order.invalid_status", locale),
        )
    existing = await database.fetch_one(
        reviews.select().where(reviews.c.request_id == request_id)
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="review already exists"
        )
    await database.execute(
        reviews.insert().values(
            request_id=request_id,
            user_id=user["id"],
            rating=int(body.rating),
            comment=body.comment,
        )
    )
    return Message(message="ok")
