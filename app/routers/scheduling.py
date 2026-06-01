"""Scheduling: admin proposes slots, user confirms one.

Locking strategy
----------------

* When the admin proposes slots for a request, we take a Postgres
  advisory lock on the request id to serialize concurrent admin
  actions on the same order.
* When the user confirms a slot, we take a second advisory lock keyed
  by the slot start (epoch). Both happen inside a single transaction
  so the lock is released at commit/rollback. This eliminates the
  race where two users could confirm overlapping slots.

The ``appointments`` table additionally has a UNIQUE constraint on
``start_at`` as a belt-and-braces safety net.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from asyncpg import UniqueViolationError
from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..config import get_settings
from ..database import (
    acquire_request_lock,
    acquire_slot_lock,
    appointments,
    database,
    requests,
    schedule_slots,
)
from ..deps import current_admin, current_locale, current_user
from ..i18n import Locale, t
from ..push import push_to_admins, push_to_user
from ..schemas import ConfirmSlotIn, ProposeSlotsIn, SlotOut

router = APIRouter(prefix="/scheduling", tags=["scheduling"])


# ---------------------------------------------------------------------
# Admin proposes slots
# ---------------------------------------------------------------------
@router.post(
    "/requests/{request_id}/propose",
    response_model=List[SlotOut],
    status_code=status.HTTP_201_CREATED,
)
async def propose_slots(
    request_id: int,
    body: ProposeSlotsIn,
    admin=Depends(current_admin),
    locale: Locale = Depends(current_locale),
) -> List[SlotOut]:
    s = get_settings()
    if len(body.slots) == 0 or len(body.slots) > s.MAX_SLOTS_PER_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"must propose between 1 and {s.MAX_SLOTS_PER_REQUEST} slots",
        )

    # Validate work-hours and uniqueness, dedup
    slot_duration = timedelta(hours=s.SLOT_DURATION_HOURS)
    seen: set[datetime] = set()
    normalised: list[datetime] = []
    for raw in body.slots:
        start = raw
        if start in seen:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=t("slot.duplicate", locale),
            )
        seen.add(start)
        if not (s.WORK_START_HOUR <= start.hour < s.WORK_END_HOUR):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=t("slot.outside_work_hours", locale),
            )
        normalised.append(start)

    async with database.transaction():
        await acquire_request_lock(request_id)
        row = await database.fetch_one(
            requests.select().where(requests.c.id == request_id)
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=t("order.not_found", locale),
            )
        if row["status"] not in ("PENDING_REVIEW", "AWAITING_USER_CONFIRM"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=t("order.invalid_status", locale),
            )

        # Wipe old proposals on this request.
        await database.execute(
            schedule_slots.delete().where(schedule_slots.c.request_id == request_id)
        )

        rows_out: list[dict] = []
        for start in normalised:
            end = start + slot_duration
            # Verify slot is not blocked by an existing confirmed appointment.
            taken = await database.fetch_one(
                appointments.select().where(appointments.c.start_at == start)
            )
            if taken is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=t("slot.unavailable", locale),
                )
            new_id = await database.execute(
                schedule_slots.insert().values(
                    request_id=request_id,
                    start_at=start,
                    end_at=end,
                    status="PROPOSED",
                )
            )
            r = await database.fetch_one(
                schedule_slots.select().where(schedule_slots.c.id == new_id)
            )
            rows_out.append(dict(r))

        await database.execute(
            requests.update()
            .where(requests.c.id == request_id)
            .values(
                status="AWAITING_USER_CONFIRM",
                updated_at=datetime.now(),
            )
        )

    # Notify user (outside transaction).
    await push_to_user(
        int(row["user_id"]),
        title=t("notify.times_proposed", locale),
        body=t("order.times_proposed", locale),
        data={"type": "times_proposed", "request_id": int(request_id)},
    )
    return [SlotOut(**r) for r in rows_out]


# ---------------------------------------------------------------------
# User confirms one slot
# ---------------------------------------------------------------------
@router.post(
    "/requests/{request_id}/confirm",
    response_model=SlotOut,
)
async def confirm_slot(
    request_id: int,
    body: ConfirmSlotIn,
    user=Depends(current_user),
    locale: Locale = Depends(current_locale),
) -> SlotOut:
    async with database.transaction():
        await acquire_request_lock(request_id)
        req = await database.fetch_one(
            requests.select().where(requests.c.id == request_id)
        )
        if req is None or req["user_id"] != user["id"]:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=t("order.not_found", locale),
            )
        if req["status"] != "AWAITING_USER_CONFIRM":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=t("order.invalid_status", locale),
            )

        slot = await database.fetch_one(
            schedule_slots.select().where(schedule_slots.c.id == body.schedule_slot_id)
        )
        if (
            slot is None
            or slot["request_id"] != request_id
            or slot["status"] != "PROPOSED"
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=t("slot.unavailable", locale),
            )

        await acquire_slot_lock(int(slot["start_at"].timestamp()))

        # Insert appointment; UNIQUE on start_at protects us.
        try:
            await database.execute(
                appointments.insert().values(
                    request_id=request_id,
                    start_at=slot["start_at"],
                    end_at=slot["end_at"],
                )
            )
        except UniqueViolationError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=t("slot.unavailable", locale),
            ) from exc
        except Exception as exc:  # pragma: no cover - safety net
            # databases lib may wrap the underlying error
            if "unique" in str(exc).lower():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=t("slot.unavailable", locale),
                ) from exc
            raise

        # Mark confirmed slot, reject the others.
        await database.execute(
            schedule_slots.update()
            .where(schedule_slots.c.id == slot["id"])
            .values(status="CONFIRMED")
        )
        await database.execute(
            schedule_slots.update()
            .where(schedule_slots.c.request_id == request_id)
            .where(schedule_slots.c.id != slot["id"])
            .values(status="REJECTED")
        )
        await database.execute(
            requests.update()
            .where(requests.c.id == request_id)
            .values(
                status="TIME_CONFIRMED",
                updated_at=datetime.now(),
            )
        )

    await push_to_admins(
        title=t("notify.time_confirmed", locale),
        body=f"#{request_id}",
        data={"type": "time_confirmed", "request_id": int(request_id)},
    )
    out = await database.fetch_one(
        schedule_slots.select().where(schedule_slots.c.id == slot["id"])
    )
    return SlotOut(**dict(out))


# ---------------------------------------------------------------------
# Admin: free slots in a window (for the proposal UI)
# ---------------------------------------------------------------------
@router.get("/availability", response_model=List[SlotOut])
async def list_taken_slots(
    from_date: str,
    to_date: str,
    admin=Depends(current_admin),
) -> List[SlotOut]:
    """Return confirmed appointments in the [from_date, to_date] range.

    The admin UI uses this to grey out unavailable slots when proposing.
    Dates are ISO ``YYYY-MM-DD``.
    """
    from datetime import date as _date

    s = get_settings()
    d_from = _date.fromisoformat(from_date)
    d_to = _date.fromisoformat(to_date)
    start_local = datetime.combine(d_from, datetime.min.time())
    end_local = datetime.combine(d_to, datetime.max.time())
    rows = await database.fetch_all(
        appointments.select()
        .where(appointments.c.start_at >= start_local)
        .where(appointments.c.start_at <= end_local)
        .order_by(appointments.c.start_at)
    )
    return [
        SlotOut(
            id=int(r["id"]),
            request_id=int(r["request_id"]),
            start_at=r["start_at"],
            end_at=r["end_at"],
            status="CONFIRMED",
            created_at=r["created_at"],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------
# User: available slots for a specific date
# ---------------------------------------------------------------------
@router.get("/available-slots", response_model=List[SlotOut])
async def list_available_slots(
    date: str,
    user=Depends(current_user),
) -> List[SlotOut]:
    """Return available time slots for a specific date.

    Returns all slots within working hours (8:00 - 19:00).
    Date is ISO ``YYYY-MM-DD``.
    """
    from datetime import date as _date

    s = get_settings()
    d = _date.fromisoformat(date)

    # Create start and end of day
    start_of_day = datetime.combine(d, datetime.min.time())
    end_of_day = datetime.combine(d, datetime.max.time())

    # Get all taken slots for this date
    taken_rows = await database.fetch_all(
        appointments.select()
        .where(appointments.c.start_at >= start_of_day)
        .where(appointments.c.start_at <= end_of_day)
    )
    taken_starts = {r["start_at"] for r in taken_rows}

    # Generate all possible slots within working hours (8:00 - 19:00)
    slot_duration = timedelta(hours=s.SLOT_DURATION_HOURS)
    available_slots: list[dict] = []

    # Start at 8:00 AM
    current = datetime.combine(d, datetime.min.time()).replace(
        hour=s.WORK_START_HOUR
    )
    # End at 7:00 PM (19:00)
    end_time = datetime.combine(d, datetime.min.time()).replace(
        hour=s.WORK_END_HOUR
    )

    while current + slot_duration <= end_time:
        if current not in taken_starts:
            available_slots.append({
                "id": 0,  # Placeholder ID for available slots
                "request_id": 0,
                "start_at": current,
                "end_at": current + slot_duration,
                "status": "AVAILABLE",
                "created_at": datetime.now(),
            })
        current += slot_duration

    return [SlotOut(**slot) for slot in available_slots]
