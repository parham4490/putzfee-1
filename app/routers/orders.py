"""User-side order endpoints (create, list, view, cancel, review)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status

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
            notes=body.notes,
            payment_type=body.payment_type,
            promotion_id=body.promotion_id,
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
                updated_at=datetime.now(timezone.utc),
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
