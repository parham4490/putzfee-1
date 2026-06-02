"""Server-side i18n for error / notification messages.

The client app handles UI translation. The server still needs to send
human-readable strings for notifications and a few error payloads. We
ship a tiny translation table for Persian (fa), English (en) and
German (de). Unknown keys fall back to English.
"""

from __future__ import annotations

from typing import Any, Dict, Literal

Locale = Literal["fa", "en", "de"]
DEFAULT_LOCALE: Locale = "en"
SUPPORTED_LOCALES: tuple[Locale, ...] = ("fa", "en", "de")

_MESSAGES: Dict[str, Dict[Locale, str]] = {
    # Auth
    "auth.invalid_credentials": {
        "fa": "شماره موبایل یا رمز عبور نادرست است.",
        "en": "Invalid phone or password.",
        "de": "Telefonnummer oder Passwort ist falsch.",
    },
    "auth.account_locked": {
        "fa": "حساب موقتاً به دلیل تلاش‌های ناموفق قفل شده است.",
        "en": "Account temporarily locked due to failed attempts.",
        "de": "Konto wegen fehlgeschlagener Anmeldungen vorübergehend gesperrt.",
    },
    "auth.phone_taken": {
        "fa": "این شماره موبایل قبلاً ثبت شده است.",
        "en": "This phone number is already registered.",
        "de": "Diese Telefonnummer ist bereits registriert.",
    },
    "auth.password_too_weak": {
        "fa": "رمز عبور باید حداقل ۸ کاراکتر باشد.",
        "en": "Password must be at least 8 characters.",
        "de": "Passwort muss mindestens 8 Zeichen haben.",
    },
    "auth.user_not_found": {
        "fa": "کاربری با این مشخصات یافت نشد.",
        "en": "User not found.",
        "de": "Benutzer nicht gefunden.",
    },
    "auth.token_invalid": {
        "fa": "توکن نامعتبر است.",
        "en": "Invalid token.",
        "de": "Ungültiges Token.",
    },
    "auth.token_expired": {
        "fa": "لطفا مجدد وارد شوید.",
        "en": "Please log in again.",
        "de": "Bitte melden Sie sich erneut an.",
    },

    # Orders
    "order.not_found": {
        "fa": "سفارش یافت نشد.",
        "en": "Order not found.",
        "de": "Bestellung nicht gefunden.",
    },
    "order.invalid_status": {
        "fa": "این عملیات در وضعیت فعلی سفارش مجاز نیست.",
        "en": "Operation not allowed in current order status.",
        "de": "Diese Aktion ist im aktuellen Status nicht erlaubt.",
    },
    "order.created": {
        "fa": "درخواست شما با موفقیت ثبت شد.",
        "en": "Your request has been submitted.",
        "de": "Ihre Anfrage wurde übermittelt.",
    },
    "order.times_proposed": {
        "fa": "زمان‌های پیشنهادی برای سفارش شما ارسال شد.",
        "en": "Proposed times have been sent for your order.",
        "de": "Vorgeschlagene Termine wurden für Ihre Bestellung gesendet.",
    },
    "order.time_confirmed": {
        "fa": "زمان سفارش شما تایید شد.",
        "en": "Your order time was confirmed.",
        "de": "Ihr Termin wurde bestätigt.",
    },
    "order.price_confirmed": {
        "fa": "قیمت و زمان اجرای سفارش شما تایید شد.",
        "en": "Price and execution time confirmed.",
        "de": "Preis und Ausführungstermin bestätigt.",
    },
    "order.started": {
        "fa": "اجرای سفارش شما آغاز شد.",
        "en": "Your order has started.",
        "de": "Ihre Bestellung wurde gestartet.",
    },
    "order.finished": {
        "fa": "سفارش شما به پایان رسید.",
        "en": "Your order is completed.",
        "de": "Ihre Bestellung ist abgeschlossen.",
    },
    "order.cancelled": {
        "fa": "سفارش لغو شد.",
        "en": "Order cancelled.",
        "de": "Bestellung storniert.",
    },

    # Scheduling
    "slot.unavailable": {
        "fa": "این بازه زمانی در دسترس نیست.",
        "en": "This time slot is unavailable.",
        "de": "Dieses Zeitfenster ist nicht verfügbar.",
    },
    "slot.outside_work_hours": {
        "fa": "زمان انتخابی خارج از ساعات کاری است.",
        "en": "Selected time is outside work hours.",
        "de": "Die gewählte Zeit liegt außerhalb der Arbeitszeiten.",
    },
    "slot.too_close": {
        "fa": "زمان انتخابی به سفارش دیگری خیلی نزدیک است.",
        "en": "Selected time is too close to another booking.",
        "de": "Die gewählte Zeit liegt zu nahe an einer anderen Buchung.",
    },
    "slot.duplicate": {
        "fa": "زمان‌های پیشنهادی نباید تکراری باشند.",
        "en": "Proposed times must not be duplicated.",
        "de": "Die vorgeschlagenen Zeiten dürfen nicht doppelt sein.",
    },

    # Admin / permissions
    "permission.denied": {
        "fa": "دسترسی غیرمجاز.",
        "en": "Permission denied.",
        "de": "Zugriff verweigert.",
    },
    "rate.limited": {
        "fa": "تعداد درخواست‌ها بیش از حد است. کمی بعد تلاش کنید.",
        "en": "Too many requests. Please try again later.",
        "de": "Zu viele Anfragen. Bitte später erneut versuchen.",
    },

    # Notifications
    "notify.new_order": {
        "fa": "سفارش جدید از کاربر {phone}: {service}",
        "en": "New order from user {phone}: {service}",
        "de": "Neue Bestellung von Benutzer {phone}: {service}",
    },
    "notify.order_cancelled": {
        "fa": "کاربر {phone} درخواست {service} را کنسل کرد.",
        "en": "User {phone} cancelled request {service}.",
        "de": "Benutzer {phone} hat Anfrage {service} storniert.",
    },
    "notify.times_proposed": {
        "fa": "زمان‌های پیشنهادی",
        "en": "Proposed times",
        "de": "Vorgeschlagene Termine",
    },
    "notify.time_confirmed": {
        "fa": "زمان تایید شد",
        "en": "Time confirmed",
        "de": "Termin bestätigt",
    },
    "notify.price_set": {
        "fa": "قیمت تعیین شد",
        "en": "Price set",
        "de": "Preis festgelegt",
    },
    "notify.work_started": {
        "fa": "کار شروع شد",
        "en": "Work started",
        "de": "Arbeit gestartet",
    },
    "notify.work_finished": {
        "fa": "کار پایان یافت",
        "en": "Work finished",
        "de": "Arbeit beendet",
    },
}


def normalise_locale(value: str | None) -> Locale:
    """Best-effort coerce an Accept-Language-ish value to a supported locale."""
    if not value:
        return DEFAULT_LOCALE
    head = value.split(",")[0].strip().lower()
    short = head.split("-")[0]
    if short in SUPPORTED_LOCALES:
        return short  # type: ignore[return-value]
    return DEFAULT_LOCALE


def t(key: str, locale: Locale | str | None = None, **kwargs: Any) -> str:
    """Translate *key* for *locale* with optional format kwargs."""
    loc: Locale = normalise_locale(locale if isinstance(locale, str) else None) if not isinstance(locale, str) or locale not in SUPPORTED_LOCALES else locale  # type: ignore[assignment]
    entry = _MESSAGES.get(key)
    if entry is None:
        return key
    text = entry.get(loc) or entry.get(DEFAULT_LOCALE) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text
