"""
Arabic reply templates — PM-10.

All 10 bot reply templates for the WhatsApp Bid Bot.
Each template returns plain text for a free-form WhatsApp message
(not pre-approved template messages — those are for outbound-first).
"""

from __future__ import annotations


def bid_accepted(
    auction_title: str,
    amount: float,
    currency: str = "JOD",
) -> str:
    """PM-10-01: Bid successfully placed."""
    return (
        f"تم تقديم مزايدتك بنجاح! \u2705\n\n"
        f"المزاد: {auction_title}\n"
        f"مبلغ المزايدة: {amount:.2f} {currency}\n\n"
        f"سيتم إعلامك إذا تمت المزايدة عليك."
    )


def bid_rejected_too_low(
    auction_title: str,
    current_price: float,
    min_next: float,
    currency: str = "JOD",
) -> str:
    """PM-10-02: Bid rejected — amount too low."""
    return (
        f"عذراً، مزايدتك أقل من الحد الأدنى المطلوب. \u274C\n\n"
        f"المزاد: {auction_title}\n"
        f"السعر الحالي: {current_price:.2f} {currency}\n"
        f"الحد الأدنى للمزايدة التالية: {min_next:.2f} {currency}\n\n"
        f"أرسل المبلغ الجديد للمزايدة."
    )


def bid_rejected_ended(auction_title: str) -> str:
    """PM-10-03: Bid rejected — auction has ended."""
    return (
        f"عذراً، المزاد \"{auction_title}\" قد انتهى. \u23F0\n\n"
        f"يمكنك تصفح المزادات النشطة على تطبيق مزادك."
    )


def auction_status(
    auction_title: str,
    current_price: float,
    bid_count: int,
    time_left: str,
    currency: str = "JOD",
) -> str:
    """PM-10-04: Auction status / price check response."""
    return (
        f"حالة المزاد \U0001F4CA\n\n"
        f"المزاد: {auction_title}\n"
        f"السعر الحالي: {current_price:.2f} {currency}\n"
        f"عدد المزايدات: {bid_count}\n"
        f"الوقت المتبقي: {time_left}\n\n"
        f"للمزايدة أرسل: ازيد [المبلغ]"
    )


def multiple_auctions_found(
    results: list[dict],
) -> str:
    """PM-10-05: Multiple matching auctions — disambiguation.

    Each result dict has: title, current_price, auction_id
    """
    lines = ["وجدنا أكثر من مزاد مطابق. اختر رقم المزاد: \U0001F50D\n"]
    for i, r in enumerate(results, 1):
        lines.append(
            f"{i}. {r['title']} — {r['current_price']:.2f} JOD"
        )
    lines.append("\nأرسل رقم المزاد (مثلاً: 1)")
    return "\n".join(lines)


def no_auction_found(keyword: str) -> str:
    """PM-10-06: No auction matches the keyword."""
    return (
        f"لم نجد مزاد مطابق لـ \"{keyword}\". \U0001F50D\n\n"
        f"تأكد من الاسم وحاول مجدداً، أو تصفح المزادات على تطبيق مزادك."
    )


def account_not_linked() -> str:
    """PM-10-07: WhatsApp not linked to any MZADAK account."""
    return (
        "رقمك غير مربوط بحساب مزادك. \U0001F517\n\n"
        "لربط حسابك:\n"
        "1. افتح تطبيق مزادك\n"
        "2. اذهب إلى الإعدادات > ربط واتساب\n"
        "3. أدخل رمز التحقق المرسل لهذا الرقم\n\n"
        "بعد الربط، يمكنك المزايدة مباشرة من هنا!"
    )


def help_message() -> str:
    """PM-10-08: Help / usage instructions."""
    return (
        "مرحباً بك في بوت مزادك! \U0001F916\n\n"
        "الأوامر المتاحة:\n"
        "• ازيد [المبلغ] على [اسم المنتج] — للمزايدة\n"
        "• كم وصل [اسم المنتج] — لمعرفة السعر الحالي\n"
        "• مساعدة — لعرض هذه الرسالة\n\n"
        "أمثلة:\n"
        '• "ازيد 500 على الايفون"\n'
        '• "كم وصل اللابتوب"\n\n'
        "يمكنك أيضاً إرسال رسالة صوتية وسنفهم طلبك!"
    )


def rate_limited() -> str:
    """PM-10-09: Too many requests — rate limit hit."""
    return (
        "عذراً، لقد تجاوزت الحد المسموح من المزايدات. \u26A0\uFE0F\n\n"
        "يُرجى الانتظار دقيقة واحدة قبل المحاولة مجدداً."
    )


def error_generic() -> str:
    """PM-10-10: Generic error fallback."""
    return (
        "عذراً، حدث خطأ أثناء معالجة طلبك. \u26A0\uFE0F\n\n"
        "يُرجى المحاولة مجدداً أو استخدام تطبيق مزادك.\n"
        "للمساعدة أرسل: مساعدة"
    )


def transcription_failed() -> str:
    """Audio could not be transcribed."""
    return (
        "عذراً، لم نتمكن من فهم الرسالة الصوتية. \U0001F3A4\n\n"
        "حاول مرة أخرى بصوت واضح، أو أرسل رسالة نصية."
    )


def bid_confirmation_prompt(
    auction_title: str,
    amount: float,
    currency: str = "JOD",
) -> str:
    """Optional: confirm before placing bid (multi-turn)."""
    return (
        f"تأكيد المزايدة \u2753\n\n"
        f"المزاد: {auction_title}\n"
        f"المبلغ: {amount:.2f} {currency}\n\n"
        f'أرسل "نعم" للتأكيد أو "لا" للإلغاء.'
    )
