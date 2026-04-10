"""
Notification templates — PM-11, FR-NOTIF-001 -> FR-NOTIF-012.

20 bilingual (Arabic + English) templates covering all platform events.
Each template has: event_type (NotificationEvent enum), title/body with
Jinja2 {{variable}} interpolation, icon category, is_financial flag.

Financial events (FINANCIAL_EVENTS frozenset) bypass user preference checks.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

from jinja2 import BaseLoader, Environment, Undefined


class _SilentUndefined(Undefined):
    """Return empty string for missing variables instead of raising."""

    def __str__(self) -> str:
        return ""

    def __iter__(self):
        return iter([])

    def __bool__(self) -> bool:
        return False


_jinja_env = Environment(loader=BaseLoader(), undefined=_SilentUndefined)


class NotificationEvent(str, enum.Enum):
    BID_PLACED_CONFIRMED = "bid_placed_confirmed"
    OUTBID = "outbid"
    LEADING_BID = "leading_bid"
    AUCTION_WON = "auction_won"
    AUCTION_ENDED_NO_WINNER = "auction_ended_no_winner"
    PAYMENT_REQUEST = "payment_request"
    PAYMENT_CAPTURED = "payment_captured"
    SHIPPING_REQUIRED = "shipping_required"
    LABEL_GENERATED = "label_generated"
    ITEM_SHIPPED = "item_shipped"
    ITEM_DELIVERED = "item_delivered"
    INSPECTION_STARTED = "inspection_started"
    FUNDS_RELEASED = "funds_released"
    DISPUTE_OPENED = "dispute_opened"
    DISPUTE_RESOLVED = "dispute_resolved"
    KYC_APPROVED = "kyc_approved"
    KYC_REJECTED = "kyc_rejected"
    LISTING_APPROVED = "listing_approved"
    LISTING_REJECTED = "listing_rejected"
    SYSTEM_MESSAGE = "system_message"


@dataclass(frozen=True, slots=True)
class Template:
    event_type: str
    title_ar: str
    title_en: str
    body_ar: str
    body_en: str
    icon: str
    is_financial: bool
    whatsapp_template: str | None = None


# -- All 20 templates ------------------------------------------------

TEMPLATES: dict[str, Template] = {}


def _t(event_type: str, **kwargs) -> None:
    TEMPLATES[event_type] = Template(event_type=event_type, **kwargs)


# -- 1. Bidding -------------------------------------------------------

_t(
    "bid_placed_confirmed",
    title_ar="تم تأكيد مزايدتك",
    title_en="Bid Confirmed",
    body_ar='تم تأكيد مزايدتك بمبلغ {{amount}} {{currency}} على "{{title}}".',
    body_en='Your bid of {{amount}} {{currency}} on "{{title}}" has been confirmed.',
    icon="bid",
    is_financial=False,
    whatsapp_template="bid_confirmed_v1",
)

_t(
    "outbid",
    title_ar="تم تجاوز مزايدتك!",
    title_en="You've Been Outbid!",
    body_ar='تم تجاوز مزايدتك على "{{title}}". السعر الحالي: {{price}} {{currency}}',
    body_en='You\'ve been outbid on "{{title}}". Current price: {{price}} {{currency}}',
    icon="bid",
    is_financial=False,
    whatsapp_template="outbid_v1",
)

_t(
    "leading_bid",
    title_ar="أنت صاحب أعلى مزايدة!",
    title_en="You're the Leading Bidder!",
    body_ar='أنت صاحب أعلى مزايدة على "{{title}}" بمبلغ {{amount}} {{currency}}.',
    body_en='You\'re the leading bidder on "{{title}}" at {{amount}} {{currency}}.',
    icon="bid",
    is_financial=False,
)

# -- 2. Auction -------------------------------------------------------

_t(
    "auction_won",
    title_ar="مبروك! فزت بالمزاد",
    title_en="Congratulations! You Won",
    body_ar='فزت بالمزاد على "{{title}}" بسعر {{price}} {{currency}}. يرجى إتمام الدفع خلال {{deadline_hours}} ساعة.',
    body_en='You won the auction for "{{title}}" at {{price}} {{currency}}. Please complete payment within {{deadline_hours}} hours.',
    icon="auction",
    is_financial=True,
    whatsapp_template="auction_won_v1",
)

_t(
    "auction_ended_no_winner",
    title_ar="انتهى المزاد بدون فائز",
    title_en="Auction Ended - No Winner",
    body_ar='انتهى المزاد على "{{title}}" بدون أي مزايدة.',
    body_en='Auction for "{{title}}" ended with no bids.',
    icon="auction",
    is_financial=False,
)

# -- 3. Payment (FINANCIAL) -------------------------------------------

_t(
    "payment_request",
    title_ar="تنبيه: موعد الدفع يقترب",
    title_en="Payment Deadline Approaching",
    body_ar="يرجى إتمام الدفع خلال {{hours_remaining}} ساعة وإلا سيتم إلغاء المعاملة.",
    body_en="Please complete payment within {{hours_remaining}} hours or the transaction will be cancelled.",
    icon="payment",
    is_financial=True,
    whatsapp_template="payment_deadline_v1",
)

_t(
    "payment_captured",
    title_ar="تم استلام الدفع",
    title_en="Payment Received",
    body_ar="تم استلام دفعتك بمبلغ {{amount}} {{currency}}. الأموال محفوظة في الضمان.",
    body_en="Your payment of {{amount}} {{currency}} has been received. Funds are held in escrow.",
    icon="payment",
    is_financial=True,
    whatsapp_template="payment_received_v1",
)

# -- 4. Shipping -------------------------------------------------------

_t(
    "shipping_required",
    title_ar="يرجى شحن المنتج",
    title_en="Please Ship the Item",
    body_ar='تم تأكيد الدفع لـ "{{title}}". يرجى شحن المنتج خلال 48 ساعة.',
    body_en='Payment confirmed for "{{title}}". Please ship the item within 48 hours.',
    icon="shipping",
    is_financial=False,
    whatsapp_template="shipping_requested_v1",
)

_t(
    "label_generated",
    title_ar="تم إنشاء بطاقة الشحن",
    title_en="Shipping Label Generated",
    body_ar='تم إنشاء بطاقة الشحن لـ "{{title}}". رقم التتبع: {{tracking_number}}',
    body_en='Shipping label generated for "{{title}}". Tracking: {{tracking_number}}',
    icon="shipping",
    is_financial=False,
)

_t(
    "item_shipped",
    title_ar="تم شحن المنتج!",
    title_en="Item Shipped!",
    body_ar='تم شحن المنتج "{{title}}" عبر {{carrier}}. رقم التتبع: {{tracking}}',
    body_en='Item "{{title}}" shipped via {{carrier}}. Tracking: {{tracking}}',
    icon="shipping",
    is_financial=False,
    whatsapp_template="item_shipped_v1",
)

_t(
    "item_delivered",
    title_ar="تم تسليم المنتج",
    title_en="Item Delivered",
    body_ar='تم تسليم المنتج "{{title}}". لديك {{hours}} ساعة لفحص المنتج.',
    body_en='Item "{{title}}" delivered. You have {{hours}} hours to inspect it.',
    icon="shipping",
    is_financial=False,
    whatsapp_template="item_delivered_v1",
)

# -- 5. Escrow ---------------------------------------------------------

_t(
    "inspection_started",
    title_ar="بدأت فترة الفحص",
    title_en="Inspection Period Started",
    body_ar='بدأت فترة فحص المنتج "{{title}}". لديك {{hours}} ساعة.',
    body_en='Inspection period started for "{{title}}". You have {{hours}} hours.',
    icon="escrow",
    is_financial=False,
)

_t(
    "funds_released",
    title_ar="تم تحرير الأموال",
    title_en="Funds Released",
    body_ar="تم تحرير مبلغ {{amount}} {{currency}} إلى حسابك.",
    body_en="Amount of {{amount}} {{currency}} has been released to your account.",
    icon="escrow",
    is_financial=True,
    whatsapp_template="escrow_released_v1",
)

# -- 6. Dispute (FINANCIAL) -------------------------------------------

_t(
    "dispute_opened",
    title_ar="تم فتح نزاع",
    title_en="Dispute Opened",
    body_ar="تم فتح نزاع على الصفقة. سيقوم وسيط بمراجعة القضية.",
    body_en="A dispute has been opened on the transaction. A mediator will review the case.",
    icon="dispute",
    is_financial=True,
    whatsapp_template="dispute_opened_v1",
)

_t(
    "dispute_resolved",
    title_ar="تم حل النزاع",
    title_en="Dispute Resolved",
    body_ar="تم حل النزاع. القرار: {{resolution}}. المبلغ: {{amount}} {{currency}}.",
    body_en="Dispute resolved. Decision: {{resolution}}. Amount: {{amount}} {{currency}}.",
    icon="dispute",
    is_financial=True,
)

# -- 7. KYC -----------------------------------------------------------

_t(
    "kyc_approved",
    title_ar="تم التحقق من هويتك!",
    title_en="Identity Verified!",
    body_ar="تم الموافقة على التحقق من هويتك. يمكنك الآن إنشاء إعلانات.",
    body_en="Your KYC verification is approved. You can now create listings.",
    icon="kyc",
    is_financial=False,
    whatsapp_template="kyc_approved_v1",
)

_t(
    "kyc_rejected",
    title_ar="تحديث التحقق من الهوية",
    title_en="KYC Verification Update",
    body_ar="لم تتم الموافقة على التحقق من هويتك. السبب: {{reason}}",
    body_en="Your KYC verification was not approved. Reason: {{reason}}",
    icon="kyc",
    is_financial=False,
    whatsapp_template="kyc_rejected_v1",
)

# -- 8. Listing --------------------------------------------------------

_t(
    "listing_approved",
    title_ar="تمت الموافقة على إعلانك",
    title_en="Listing Approved",
    body_ar='تمت الموافقة على إعلانك "{{title}}". المزاد يبدأ قريباً.',
    body_en='Your listing "{{title}}" has been approved. Auction starts soon.',
    icon="listing",
    is_financial=False,
    whatsapp_template="listing_approved_v1",
)

_t(
    "listing_rejected",
    title_ar="إعلانك يحتاج تعديل",
    title_en="Listing Needs Changes",
    body_ar='إعلانك "{{title}}" يحتاج تعديل. السبب: {{reason}}',
    body_en='Your listing "{{title}}" needs changes. Reason: {{reason}}',
    icon="listing",
    is_financial=False,
)

# -- 9. System ---------------------------------------------------------

_t(
    "system_message",
    title_ar="رسالة من النظام",
    title_en="System Message",
    body_ar="{{message}}",
    body_en="{{message}}",
    icon="system",
    is_financial=False,
)


# =====================================================================
#  Financial events bypass user preference checks
# =====================================================================

FINANCIAL_EVENTS: frozenset[str] = frozenset(
    t.event_type for t in TEMPLATES.values() if t.is_financial
)


# =====================================================================
#  Jinja2 template rendering
# =====================================================================

def render_template(
    event_type: str, data: dict | None = None,
) -> Template | None:
    """Look up a template by event_type and render Jinja2 {{variables}}.

    Returns None if the event_type is unknown.
    """
    tmpl = TEMPLATES.get(event_type)
    if tmpl is None:
        return None

    d = data or {}
    try:
        return Template(
            event_type=tmpl.event_type,
            title_ar=_jinja_env.from_string(tmpl.title_ar).render(**d),
            title_en=_jinja_env.from_string(tmpl.title_en).render(**d),
            body_ar=_jinja_env.from_string(tmpl.body_ar).render(**d),
            body_en=_jinja_env.from_string(tmpl.body_en).render(**d),
            icon=tmpl.icon,
            is_financial=tmpl.is_financial,
            whatsapp_template=tmpl.whatsapp_template,
        )
    except Exception:
        return tmpl
