"""Pydantic request/response schemas."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .database import ORDER_STATUSES, PAYMENT_TYPES, SLOT_STATUSES
from .utils import normalize_phone


# ---------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------
class Message(BaseModel):
    message: str


class Page(BaseModel):
    items: List[Any]
    total: int
    page: int = 1
    page_size: int = 20


# ---------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------
class RegisterIn(BaseModel):
    phone: str = Field(min_length=4, max_length=32)
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=128)
    locale: str = Field(default="en", max_length=8)
    address: Optional[str] = Field(default=None, max_length=500)

    @field_validator("phone")
    @classmethod
    def _norm_phone(cls, v: str) -> str:
        n = normalize_phone(v)
        if len(n) < 4:
            raise ValueError("phone too short")
        return n


class LoginIn(BaseModel):
    phone: str
    password: str

    @field_validator("phone")
    @classmethod
    def _norm_phone(cls, v: str) -> str:
        return normalize_phone(v)


class RefreshIn(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    user_id: int
    is_admin: bool


class AccessOnly(BaseModel):
    access_token: str
    token_type: str = "Bearer"


class ForgotPasswordIn(BaseModel):
    phone: str

    @field_validator("phone")
    @classmethod
    def _norm_phone(cls, v: str) -> str:
        return normalize_phone(v)


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


# ---------------------------------------------------------------------
# User profile
# ---------------------------------------------------------------------
class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    phone: str
    full_name: str
    address: Optional[str] = None
    photo_url: Optional[str] = None
    locale: str = "en"
    is_admin: bool = False
    is_active: bool = True
    created_at: datetime


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=120)
    address: Optional[str] = Field(default=None, max_length=500)
    locale: Optional[str] = Field(default=None, max_length=8)


# ---------------------------------------------------------------------
# Cars
# ---------------------------------------------------------------------
class CarIn(BaseModel):
    brand: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=80)
    plate: Optional[str] = Field(default=None, max_length=40)
    color: Optional[str] = Field(default=None, max_length=40)


class CarOut(CarIn):
    id: int
    user_id: int
    created_at: datetime


# ---------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------
class ServiceIn(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    name_i18n: Dict[str, str] = Field(default_factory=dict)
    description_i18n: Dict[str, str] = Field(default_factory=dict)
    icon: Optional[str] = None
    base_price: Decimal = Decimal("0")
    sort_order: int = 0
    requires_car: bool = False
    is_active: bool = True


class ServiceOut(ServiceIn):
    id: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------
# Promotions
# ---------------------------------------------------------------------
class PromotionIn(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    title_i18n: Dict[str, str] = Field(default_factory=dict)
    description_i18n: Dict[str, str] = Field(default_factory=dict)
    image_url: Optional[str] = None
    discount_percent: Optional[Decimal] = None
    flat_discount: Optional[Decimal] = None
    min_services: Optional[int] = None
    applies_to_keys: Optional[List[str]] = None
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    is_active: bool = True


class PromotionOut(PromotionIn):
    id: int
    created_at: datetime


# ---------------------------------------------------------------------
# Orders / Requests
# ---------------------------------------------------------------------
class RequestCreateIn(BaseModel):
    service_keys: List[str] = Field(min_length=1)
    car_id: Optional[int] = None
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None
    address_text: Optional[str] = Field(default=None, max_length=500)
    house_number: Optional[str] = Field(default=None, max_length=40)
    visit1_datetime: Optional[datetime] = None
    visit2_datetime: Optional[datetime] = None
    notes: Optional[str] = None
    promotion_id: Optional[int] = None
    payment_type: str = "cash"

    @field_validator("payment_type")
    @classmethod
    def _validate_payment(cls, v: str) -> str:
        if v not in PAYMENT_TYPES:
            raise ValueError(f"payment_type must be one of {PAYMENT_TYPES}")
        return v


class RequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    status: str
    service_keys: List[str]
    car_id: Optional[int] = None
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None
    address_text: Optional[str] = None
    house_number: Optional[str] = None
    visit1_datetime: Optional[datetime] = None
    visit2_datetime: Optional[datetime] = None
    notes: Optional[str] = None
    total_price: Optional[Decimal] = None
    exec_duration_minutes: Optional[int] = None
    payment_type: str = "cash"
    promotion_id: Optional[int] = None
    cancel_reason: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class CancelIn(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=500)


# ---------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------
class ProposeSlotsIn(BaseModel):
    """Admin proposes up to MAX_SLOTS_PER_REQUEST starting times (UTC)."""
    slots: List[datetime] = Field(min_length=1, max_length=5)


class ConfirmSlotIn(BaseModel):
    """User picks one of the proposed slot ids."""
    schedule_slot_id: int


class SlotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    request_id: int
    start_at: datetime
    end_at: datetime
    status: str
    created_at: datetime


class SetPriceIn(BaseModel):
    total_price: Decimal = Field(ge=Decimal("0"))
    exec_duration_minutes: int = Field(ge=1, le=24 * 60)


# ---------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------
class ReviewIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=1000)


class ReviewPublic(BaseModel):
    id: int
    rating: int
    comment: Optional[str] = None
    masked_phone: str
    created_at: datetime


# ---------------------------------------------------------------------
# Devices / Push
# ---------------------------------------------------------------------
class DeviceTokenIn(BaseModel):
    token: str = Field(min_length=4, max_length=500)
    platform: str = "android"

    @field_validator("platform")
    @classmethod
    def _validate_platform(cls, v: str) -> str:
        v = (v or "android").lower()
        if v not in ("android", "ios", "web"):
            raise ValueError("invalid platform")
        return v


# ---------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------
class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    body: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None
    read_at: Optional[datetime] = None
    created_at: datetime


# ---------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------
class AIChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    context: Optional[Dict[str, Any]] = None


class AIChatOut(BaseModel):
    reply: str
    model: str
