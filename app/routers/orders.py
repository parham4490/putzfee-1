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
    users,
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
# Get booked slots for a specific date
# ---------------------------------------------------------------------
@router.get("/booked-slots")
async def get_booked_slots(
    date: str,  # Format: YYYY-MM-DD
    user=Depends(current_user),
) -> dict:
    """Get list of booked hours for a specific date."""
    try:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date format. Use YYYY-MM-DD",
        )
    
    # Get start and end of the target date
    start_of_day = datetime.combine(target_date, datetime.min.time())
    end_of_day = datetime.combine(target_date, datetime.max.time())
    
    # Get booked slots from schedule_slots
    booked_slots = await database.fetch_all(
        schedule_slots.select().where(
            (schedule_slots.c.start_at >= start_of_day) &
            (schedule_slots.c.end_at <= end_of_day) &
            (schedule_slots.c.status.in_(["REQUESTED", "PROPOSED", "CONFIRMED"]))
        )
    )
    
    # Get booked slots from appointments
    booked_appointments = await database.fetch_all(
        appointments.select().where(
            (appointments.c.start_at >= start_of_day) &
            (appointments.c.end_at <= end_of_day)
        )
    )
    
    # Extract booked hours
    booked_hours = set()
    for slot in booked_slots:
        hour = slot["start_at"].hour
        booked_hours.add(hour)
    
    for appointment in booked_appointments:
        hour = appointment["start_at"].hour
        booked_hours.add(hour)
    
    return {"booked_hours": sorted(booked_hours)}


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
    
    # Query for active order that contains the specific service key
    row = await database.fetch_one(
        requests.select().where(
            (requests.c.user_id == user['id']) &
            (requests.c.status.in_(active_statuses)) &
            (requests.c.service_keys.contains([service_key]))
        )
    )
    
    if row is None:
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
        await database.execute(
            schedule_slots.delete().where(schedule_slots.c.request_id == request_id)
        )
    row = await database.fetch_one(
        requests.select().where(requests.c.id == request_id)
    )
    
    # Get user phone and service names for notification
    user_row = await database.fetch_one(
        users.select().where(users.c.id == row["user_id"])
    )
    service_keys = row["service_keys"] or []
    service_names = []
    if service_keys:
        service_rows = await database.fetch_all(
            services.select().where(services.c.key.in_(service_keys))
        )
        for s in service_rows:
            name_i18n = s["name_i18n"] or {}
            try:
                default_name = s["name"]
            except KeyError:
                default_name = ""
            service_name = name_i18n.get(locale, default_name)
            if not service_name:
                service_name = name_i18n.get("fa", default_name)
            service_names.append(service_name)
    
    service_list = ", ".join(service_names) if service_names else "unknown"
    phone = user_row["phone"] if user_row else "unknown"
    
    # Notify admins
    await push_to_admins(
        title=t("notify.order_cancelled", locale).format(phone=phone, service=service_list),
        body=f"#{request_id}",
        data={"type": "order_cancelled", "request_id": request_id},
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
 
