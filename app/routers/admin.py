"""Admin endpoints: services, promotions, orders lifecycle and history."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List

import sqlalchemy as sa
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from ..database import (
    appointments,
    cars,
    database,
    notifications,
    promotions,
    requests,
    schedule_slots,
    services,
    users,
)
from ..deps import current_admin, current_locale
from ..i18n import Locale, t
from ..media import absolute_url, save_image
from ..push import push_to_user
from ..schemas import (
    CarOut,
    Message,
    Page,
    PromotionIn,
    PromotionOut,
    RequestOut,
    ServiceIn,
    ServiceOut,
    SetPriceIn,
    UserPublic,
)

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(current_admin)])


# ---------------------------------------------------------------------
# Services CRUD
# ---------------------------------------------------------------------
@router.get("/services", response_model=List[ServiceOut])
async def list_services() -> List[ServiceOut]:
    rows = await database.fetch_all(
        services.select().order_by(services.c.sort_order, services.c.id)
    )
    return [ServiceOut(**dict(r)) for r in rows]


@router.post("/services", response_model=ServiceOut, status_code=status.HTTP_201_CREATED)
async def upsert_service(body: ServiceIn) -> ServiceOut:
    existing = await database.fetch_one(
        services.select().where(services.c.key == body.key)
    )
    now = datetime.now(timezone.utc)
    if existing is None:
        # Check for duplicate sort order and swap if needed
        duplicate = await database.fetch_one(
            services.select().where(services.c.sort_order == body.sort_order)
        )
        if duplicate is not None:
            # Swap sort orders
            await database.execute(
                services.update().where(services.c.id == duplicate["id"]).values(
                    sort_order=existing["sort_order"] if existing else 0,
                    updated_at=now
                )
            )
        new_id = await database.execute(
            services.insert().values(
                key=body.key,
                name_i18n=body.name_i18n,
                description_i18n=body.description_i18n,
                icon=body.icon,
                base_price=body.base_price,
                sort_order=body.sort_order,
                requires_car=body.requires_car,
                is_active=body.is_active,
            )
        )
        sid = int(new_id)
    else:
        sid = int(existing["id"])
        # Check for duplicate sort order (excluding current service)
        duplicate = await database.fetch_one(
            services.select()
            .where(services.c.sort_order == body.sort_order)
            .where(services.c.id != sid)
        )
        if duplicate is not None:
            # Swap sort orders
            await database.execute(
                services.update().where(services.c.id == duplicate["id"]).values(
                    sort_order=existing["sort_order"],
                    updated_at=now
                )
            )
        await database.execute(
            services.update().where(services.c.id == sid).values(
                name_i18n=body.name_i18n,
                description_i18n=body.description_i18n,
                icon=body.icon,
                base_price=body.base_price,
                sort_order=body.sort_order,
                requires_car=body.requires_car,
                is_active=body.is_active,
                updated_at=now,
            )
        )
    row = await database.fetch_one(services.select().where(services.c.id == sid))
    return ServiceOut(**dict(row))


@router.delete("/services/{service_id}", response_model=Message)
async def delete_service(service_id: int) -> Message:
    await database.execute(services.delete().where(services.c.id == service_id))
    return Message(message="ok")


@router.post("/services/{service_id}/icon", response_model=ServiceOut)
async def upload_service_icon(service_id: int, file: UploadFile = File(...)) -> ServiceOut:
    row = await database.fetch_one(services.select().where(services.c.id == service_id))
    if row is None:
        raise HTTPException(status_code=404, detail="service not found")
    url = await save_image(file, sub_dir="services")
    absolute = absolute_url(url)
    await database.execute(
        services.update().where(services.c.id == service_id).values(
            icon=absolute, updated_at=datetime.now(timezone.utc)
        )
    )
    row = await database.fetch_one(services.select().where(services.c.id == service_id))
    return ServiceOut(**dict(row))


# ---------------------------------------------------------------------
# Promotions CRUD
# ---------------------------------------------------------------------
@router.get("/promotions", response_model=List[PromotionOut])
async def list_promotions() -> List[PromotionOut]:
    rows = await database.fetch_all(promotions.select().order_by(promotions.c.id.desc()))
    return [PromotionOut(**dict(r)) for r in rows]


@router.post(
    "/promotions", response_model=PromotionOut, status_code=status.HTTP_201_CREATED
)
async def upsert_promotion(body: PromotionIn) -> PromotionOut:
    existing = await database.fetch_one(
        promotions.select().where(promotions.c.key == body.key)
    )
    if existing is None:
        new_id = await database.execute(
            promotions.insert().values(
                key=body.key,
                title_i18n=body.title_i18n,
                description_i18n=body.description_i18n,
                image_url=body.image_url,
                discount_percent=body.discount_percent,
                flat_discount=body.flat_discount,
                min_services=body.min_services,
                applies_to_keys=body.applies_to_keys,
                valid_from=body.valid_from,
                valid_to=body.valid_to,
                is_active=body.is_active,
            )
        )
        pid = int(new_id)
    else:
        pid = int(existing["id"])
        await database.execute(
            promotions.update().where(promotions.c.id == pid).values(
                title_i18n=body.title_i18n,
                description_i18n=body.description_i18n,
                image_url=body.image_url,
                discount_percent=body.discount_percent,
                flat_discount=body.flat_discount,
                min_services=body.min_services,
                applies_to_keys=body.applies_to_keys,
                valid_from=body.valid_from,
                valid_to=body.valid_to,
                is_active=body.is_active,
            )
        )
    row = await database.fetch_one(promotions.select().where(promotions.c.id == pid))
    return PromotionOut(**dict(row))


@router.delete("/promotions/{promotion_id}", response_model=Message)
async def delete_promotion(promotion_id: int) -> Message:
    await database.execute(promotions.delete().where(promotions.c.id == promotion_id))
    return Message(message="ok")


@router.post("/promotions/{promotion_id}/image", response_model=PromotionOut)
async def upload_promo_image(promotion_id: int, file: UploadFile = File(...)) -> PromotionOut:
    row = await database.fetch_one(promotions.select().where(promotions.c.id == promotion_id))
    if row is None:
        raise HTTPException(status_code=404, detail="promotion not found")
    url = await save_image(file, sub_dir="promotions")
    await database.execute(
        promotions.update()
        .where(promotions.c.id == promotion_id)
        .values(image_url=url)
    )
    row = await database.fetch_one(promotions.select().where(promotions.c.id == promotion_id))
    return PromotionOut(**dict(row))


# ---------------------------------------------------------------------
# Orders – active queue
# ---------------------------------------------------------------------
@router.get("/orders", response_model=Page)
async def list_active_orders(
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page:
    q = requests.select()
    if status_filter:
        q = q.where(requests.c.status == status_filter)
    else:
        q = q.where(
            requests.c.status.in_(
                [
                    "PENDING_REVIEW",
                    "AWAITING_USER_CONFIRM",
                    "TIME_CONFIRMED",
                    "PRICE_CONFIRMED",
                    "IN_PROGRESS",
                ]
            )
        )
    count_row = await database.fetch_one(
        sa.select(sa.func.count()).select_from(q.alias())
    )
    total = int(count_row[0]) if count_row else 0
    rows = await database.fetch_all(
        q.order_by(requests.c.created_at.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    return Page(
        items=[dict(r) for r in rows], total=total, page=page, page_size=page_size
    )


@router.get("/orders/history", response_model=Page)
async def list_history(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> Page:
    q = requests.select().where(requests.c.status.in_(["COMPLETED", "CANCELLED"]))
    count_row = await database.fetch_one(
        sa.select(sa.func.count()).select_from(q.alias())
    )
    total = int(count_row[0]) if count_row else 0
    rows = await database.fetch_all(
        q.order_by(requests.c.created_at.desc())
        .limit(page_size)
        .offset((page - 1) * page_size)
    )
    return Page(
        items=[dict(r) for r in rows], total=total, page=page, page_size=page_size
    )


@router.get("/orders/{request_id}", response_model=RequestOut)
async def order_detail(request_id: int) -> RequestOut:
    row = await database.fetch_one(
        requests.select().where(requests.c.id == request_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="order not found")
    return RequestOut(**dict(row))


# ---------------------------------------------------------------------
# Orders – lifecycle transitions
# ---------------------------------------------------------------------
@router.post("/orders/{request_id}/price", response_model=RequestOut)
async def set_price(
    request_id: int,
    body: SetPriceIn,
    locale: Locale = Depends(current_locale),
) -> RequestOut:
    row = await database.fetch_one(
        requests.select().where(requests.c.id == request_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="order not found")
    if row["status"] != "TIME_CONFIRMED":
        raise HTTPException(
            status_code=400, detail=t("order.invalid_status", locale)
        )
    await database.execute(
        requests.update().where(requests.c.id == request_id).values(
            total_price=body.total_price,
            exec_duration_minutes=body.exec_duration_minutes,
            status="PRICE_CONFIRMED",
            updated_at=datetime.now(timezone.utc),
        )
    )
    await push_to_user(
        int(row["user_id"]),
        title=t("notify.price_set", locale),
        body=str(body.total_price),
        data={
            "type": "price_set",
            "request_id": int(request_id),
            "total_price": str(body.total_price),
        },
    )
    row = await database.fetch_one(
        requests.select().where(requests.c.id == request_id)
    )
    return RequestOut(**dict(row))


@router.post("/orders/{request_id}/start", response_model=RequestOut)
async def start_order(
    request_id: int,
    locale: Locale = Depends(current_locale),
) -> RequestOut:
    row = await database.fetch_one(
        requests.select().where(requests.c.id == request_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="order not found")
    if row["status"] != "PRICE_CONFIRMED":
        raise HTTPException(
            status_code=400, detail=t("order.invalid_status", locale)
        )
    now = datetime.now(timezone.utc)
    await database.execute(
        requests.update().where(requests.c.id == request_id).values(
            status="IN_PROGRESS",
            started_at=now,
            updated_at=now,
        )
    )
    await push_to_user(
        int(row["user_id"]),
        title=t("notify.work_started", locale),
        body=t("order.started", locale),
        data={"type": "work_started", "request_id": int(request_id)},
    )
    row = await database.fetch_one(
        requests.select().where(requests.c.id == request_id)
    )
    return RequestOut(**dict(row))


@router.post("/orders/{request_id}/finish", response_model=RequestOut)
async def finish_order(
    request_id: int,
    locale: Locale = Depends(current_locale),
) -> RequestOut:
    row = await database.fetch_one(
        requests.select().where(requests.c.id == request_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="order not found")
    if row["status"] != "IN_PROGRESS":
        raise HTTPException(
            status_code=400, detail=t("order.invalid_status", locale)
        )
    now = datetime.now(timezone.utc)
    await database.execute(
        requests.update().where(requests.c.id == request_id).values(
            status="COMPLETED",
            finished_at=now,
            updated_at=now,
        )
    )
    await push_to_user(
        int(row["user_id"]),
        title=t("notify.work_finished", locale),
        body=t("order.finished", locale),
        data={"type": "work_finished", "request_id": int(request_id)},
    )
    row = await database.fetch_one(
        requests.select().where(requests.c.id == request_id)
    )
    return RequestOut(**dict(row))


@router.post("/orders/{request_id}/cancel", response_model=RequestOut)
async def admin_cancel(
    request_id: int,
    reason: str | None = None,
    locale: Locale = Depends(current_locale),
) -> RequestOut:
    row = await database.fetch_one(
        requests.select().where(requests.c.id == request_id)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="order not found")
    if row["status"] in ("COMPLETED", "CANCELLED"):
        raise HTTPException(
            status_code=400, detail=t("order.invalid_status", locale)
        )
    async with database.transaction():
        await database.execute(
            requests.update().where(requests.c.id == request_id).values(
                status="CANCELLED",
                cancel_reason=reason,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await database.execute(
            appointments.delete().where(appointments.c.request_id == request_id)
        )
        await database.execute(
            schedule_slots.delete().where(schedule_slots.c.request_id == request_id)
        )
    await push_to_user(
        int(row["user_id"]),
        title=t("notify.work_finished", locale),
        body=t("order.cancelled", locale),
        data={"type": "cancelled", "request_id": int(request_id)},
    )
    row = await database.fetch_one(
        requests.select().where(requests.c.id == request_id)
    )
    return RequestOut(**dict(row))


# ---------------------------------------------------------------------
# Cars management (read-only for admin)
# ---------------------------------------------------------------------
@router.get("/cars/{car_id}", response_model=CarOut)
async def get_car(car_id: int) -> CarOut:
    row = await database.fetch_one(cars.select().where(cars.c.id == car_id))
    if row is None:
        raise HTTPException(status_code=404, detail="car not found")
    return CarOut(**dict(row))


# ---------------------------------------------------------------------
# Users management (read-only listing for admin)
# ---------------------------------------------------------------------
@router.get("/users", response_model=List[UserPublic])
async def list_users(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> List[UserPublic]:
    rows = await database.fetch_all(
        users.select().order_by(users.c.id.desc()).limit(limit).offset(offset)
    )
    return [UserPublic(**dict(r)) for r in rows]
