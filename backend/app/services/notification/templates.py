"""
Notification templates — PM-11, FR-NOTIF-001 → FR-NOTIF-012.

20 bilingual (Arabic + English) templates covering all platform events.
Each template has: event_type, title_ar, title_en, body_ar, body_en.
Body strings accept .format(**data) for dynamic interpolation.

Financial events (FINANCIAL_EVENTS set) bypass user preference checks.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Template:
    event_type: str
    title_ar: str
    title_en: str
    body_ar: str
    body_en: str
    whatsapp_template: str | None = None  # Pre-approved Meta template name


# ── All 20 templates ─────────────────────────────────────────────

TEMPLATES: dict[str, Template] = {}


def _t(event_type: str, **kwargs) -> None:
    TEMPLATES[event_type] = Template(event_type=event_type, **kwargs)


# ── 1. Authentication & KYC ──────────────────────────────────────

_t(
    "kyc_approved",
    title_ar="تم التحقق من هويتك!",
    title_en="Identity Verified!",
    body_ar="تم الموافقة على التحقق من هويتك. يمكنك الآن إنشاء إعلانات.",
    body_en="Your KYC verification is approved. You can now create listings.",
    whatsapp_template="kyc_approved_v1",
)

_t(
    "kyc_rejected",
    title_ar="تحديث التحقق من الهوية",
    title_en="KYC Verification Update",
    body_ar="لم تتم الموافقة على التحقق من هويتك. السبب: {reason}",
    body_en="Your KYC verification was not approved. Reason: {reason}",
    whatsapp_template="kyc_rejected_v1",
)

# ── 2. Listing ───────────────────────────────────────────────────

_t(
    "listing_approved",
    title_ar="تمت الموافقة على إعلانك",
    title_en="Listing Approved",
    body_ar='تمت الموافقة على إعلانك "{title}". المزاد يبدأ قريباً.',
    body_en='Your listing "{title}" has been approved. Auction starts soon.',
    whatsapp_template="listing_approved_v1",
)

_t(
    "listing_rejected",
    title_ar="إعلانك يحتاج تعديل",
    title_en="Listing Needs Changes",
    body_ar='إعلانك "{title}" يحتاج تعديل. السبب: {reason}',
    body_en='Your listing "{title}" needs changes. Reason: {reason}',
)

# ── 3. Auction ───────────────────────────────────────────────────

_t(
    "auction_started",
    title_ar="المزاد بدأ!",
    title_en="Auction Started!",
    body_ar='المزاد على "{title}" بدأ الآن. السعر الحالي: {price} {currency}',
    body_en='Auction for "{title}" is now live. Current price: {price} {currency}',
    whatsapp_template="auction_started_v1",
)

_t(
    "outbid",
    title_ar="تم تجاوز مزايدتك!",
    title_en="You've Been Outbid!",
    body_ar='تم تجاوز مزايدتك على "{title}". السعر الحالي: {price} {currency}',
    body_en='You\'ve been outbid on "{title}". Current price: {price} {currency}',
    whatsapp_template="outbid_v1",
)

_t(
    "auction_won",
    title_ar="مبروك! فزت بالمزاد",
    title_en="Congratulations! You Won",
    body_ar='فزت بالمزاد على "{title}" بسعر {price} {currency}. يرجى إتمام الدفع خلال {deadline_hours} ساعة.',
    body_en='You won the auction for "{title}" at {price} {currency}. Please complete payment within {deadline_hours} hours.',
    whatsapp_template="auction_won_v1",
)

_t(
    "auction_ended_seller",
    title_ar="انتهى المزاد على إعلانك",
    title_en="Your Auction Has Ended",
    body_ar='انتهى المزاد على "{title}". السعر النهائي: {price} {currency}',
    body_en='Auction for "{title}" has ended. Final price: {price} {currency}',
    whatsapp_template="auction_ended_seller_v1",
)

_t(
    "auction_no_bids",
    title_ar="انتهى المزاد بدون مزايدات",
    title_en="Auction Ended — No Bids",
    body_ar='انتهى المزاد على "{title}" بدون أي مزايدة.',
    body_en='Auction for "{title}" ended with no bids.',
)

_t(
    "anti_snipe_extended",
    title_ar="تم تمديد المزاد!",
    title_en="Auction Extended!",
    body_ar='تم تمديد المزاد على "{title}" دقيقتين إضافيتين بسبب مزايدة أخيرة.',
    body_en='Auction for "{title}" extended by 2 minutes due to a last-moment bid.',
)

# ── 4. Payment & Escrow (FINANCIAL) ──────────────────────────────

_t(
    "payment_received",
    title_ar="تم استلام الدفع",
    title_en="Payment Received",
    body_ar="تم استلام دفعتك بمبلغ {amount} {currency}. الأموال محفوظة في الضمان.",
    body_en="Your payment of {amount} {currency} has been received. Funds are held in escrow.",
    whatsapp_template="payment_received_v1",
)

_t(
    "payment_failed",
    title_ar="فشل الدفع",
    title_en="Payment Failed",
    body_ar="فشلت عملية الدفع. المحاولة {retry_count} من 3. يرجى المحاولة مرة أخرى.",
    body_en="Payment failed. Attempt {retry_count} of 3. Please try again.",
    whatsapp_template="payment_failed_v1",
)

_t(
    "payment_deadline_warning",
    title_ar="تنبيه: موعد الدفع يقترب",
    title_en="Payment Deadline Approaching",
    body_ar="يرجى إتمام الدفع خلال {hours_remaining} ساعة وإلا سيتم إلغاء المعاملة.",
    body_en="Please complete payment within {hours_remaining} hours or the transaction will be cancelled.",
    whatsapp_template="payment_deadline_v1",
)

# ── 5. Shipping ──────────────────────────────────────────────────

_t(
    "shipping_requested",
    title_ar="يرجى شحن المنتج",
    title_en="Please Ship the Item",
    body_ar='تم تأكيد الدفع لـ "{title}". يرجى شحن المنتج خلال 48 ساعة.',
    body_en='Payment confirmed for "{title}". Please ship the item within 48 hours.',
    whatsapp_template="shipping_requested_v1",
)

_t(
    "item_shipped",
    title_ar="تم شحن المنتج!",
    title_en="Item Shipped!",
    body_ar='تم شحن المنتج "{title}" عبر {carrier}. رقم التتبع: {tracking}',
    body_en='Item "{title}" shipped via {carrier}. Tracking: {tracking}',
    whatsapp_template="item_shipped_v1",
)

_t(
    "item_delivered",
    title_ar="تم تسليم المنتج",
    title_en="Item Delivered",
    body_ar='تم تسليم المنتج "{title}". لديك {hours} ساعة لفحص المنتج.',
    body_en='Item "{title}" delivered. You have {hours} hours to inspect it.',
    whatsapp_template="item_delivered_v1",
)

# ── 6. Dispute & Resolution (FINANCIAL) ──────────────────────────

_t(
    "dispute_opened",
    title_ar="تم فتح نزاع",
    title_en="Dispute Opened",
    body_ar="تم فتح نزاع على الصفقة. سيقوم وسيط بمراجعة القضية.",
    body_en="A dispute has been opened on the transaction. A mediator will review the case.",
    whatsapp_template="dispute_opened_v1",
)

_t(
    "escrow_released",
    title_ar="تم تحرير الأموال",
    title_en="Funds Released",
    body_ar="تم تحرير مبلغ {amount} {currency} إلى حسابك.",
    body_en="Amount of {amount} {currency} has been released to your account.",
    whatsapp_template="escrow_released_v1",
)

_t(
    "escrow_refunded",
    title_ar="تم استرداد المبلغ",
    title_en="Refund Processed",
    body_ar="تم استرداد مبلغ {amount} {currency} إلى حسابك.",
    body_en="Amount of {amount} {currency} has been refunded to your account.",
    whatsapp_template="escrow_refunded_v1",
)

_t(
    "seller_strike",
    title_ar="تحذير: مخالفة على حسابك",
    title_en="Warning: Account Strike",
    body_ar="تم تسجيل مخالفة على حسابك بسبب {reason}. المخالفات الحالية: {count}",
    body_en="A strike has been recorded on your account for {reason}. Current strikes: {count}",
)

# ═══════════════════════════════════════════════════════════════════
#  Financial events bypass user preference checks
# ═══════════════════════════════════════════════════════════════════

FINANCIAL_EVENTS: frozenset[str] = frozenset({
    "payment_received",
    "payment_failed",
    "payment_deadline_warning",
    "escrow_released",
    "escrow_refunded",
    "dispute_opened",
    "auction_won",
})


def render_template(
    event_type: str, data: dict | None = None,
) -> Template | None:
    """Look up a template by event_type and interpolate data into body strings.

    Returns None if the event_type is unknown.
    """
    tmpl = TEMPLATES.get(event_type)
    if tmpl is None:
        return None

    d = data or {}
    try:
        return Template(
            event_type=tmpl.event_type,
            title_ar=tmpl.title_ar.format(**d),
            title_en=tmpl.title_en.format(**d),
            body_ar=tmpl.body_ar.format(**d),
            body_en=tmpl.body_en.format(**d),
            whatsapp_template=tmpl.whatsapp_template,
        )
    except KeyError:
        # Missing interpolation keys → return raw template
        return tmpl
