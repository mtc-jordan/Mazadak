"""
Database seed script — populates dev environment with test data.

Usage:
    python -m app.db.seed          (from /backend)
    make seed                      (from repo root)

Requires: migrations applied, PostgreSQL running.
Uses raw SQL inserts to avoid model import issues during early dev.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.core.config import settings


def _uuid() -> str:
    return str(uuid.uuid4())


# ═══════════════════════════════════════════════════════════════════
# Fixed UUIDs for predictable FK references in dev
# ═══════════════════════════════════════════════════════════════════
ADMIN_ID = _uuid()
SELLER_1_ID = _uuid()
SELLER_2_ID = _uuid()
BUYER_1_ID = _uuid()
BUYER_2_ID = _uuid()
MEDIATOR_ID = _uuid()
NGO_ID = _uuid()

NOW = datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════════════
# Categories — 12 top-level (SDD: "12 top-level, ~80 subcategories")
# Phase 1 focus: Electronics, Vehicles, Furniture (BRD §Phase 1)
# ═══════════════════════════════════════════════════════════════════
CATEGORIES = [
    # (id, parent_id, name_ar, name_en, slug, sort_order)
    (1, None, "إلكترونيات", "Electronics", "electronics", 1),
    (2, None, "مركبات", "Vehicles", "vehicles", 2),
    (3, None, "أثاث ومنزل", "Furniture & Home", "furniture-home", 3),
    (4, None, "أزياء وإكسسوارات", "Fashion & Accessories", "fashion", 4),
    (5, None, "مجوهرات وساعات", "Jewelry & Watches", "jewelry-watches", 5),
    (6, None, "مقتنيات وتحف", "Collectibles & Antiques", "collectibles", 6),
    (7, None, "رياضة ولياقة", "Sports & Fitness", "sports", 7),
    (8, None, "عقارات", "Real Estate", "real-estate", 8),
    (9, None, "كتب وفنون", "Books & Art", "books-art", 9),
    (10, None, "ألعاب أطفال", "Toys & Kids", "toys-kids", 10),
    (11, None, "أعمال ومعدات", "Business & Equipment", "business-equipment", 11),
    (12, None, "أخرى", "Other", "other", 12),
    # Subcategories for Phase 1 categories
    (13, 1, "هواتف ذكية", "Smartphones", "electronics-smartphones", 1),
    (14, 1, "حواسيب محمولة", "Laptops", "electronics-laptops", 2),
    (15, 1, "أجهزة لوحية", "Tablets", "electronics-tablets", 3),
    (16, 1, "كاميرات", "Cameras", "electronics-cameras", 4),
    (17, 1, "ألعاب فيديو", "Gaming", "electronics-gaming", 5),
    (18, 2, "سيارات", "Cars", "vehicles-cars", 1),
    (19, 2, "دراجات نارية", "Motorcycles", "vehicles-motorcycles", 2),
    (20, 2, "قطع غيار", "Auto Parts", "vehicles-parts", 3),
    (21, 3, "أثاث غرف نوم", "Bedroom Furniture", "furniture-bedroom", 1),
    (22, 3, "أثاث صالونات", "Living Room", "furniture-living", 2),
    (23, 3, "أجهزة منزلية", "Home Appliances", "furniture-appliances", 3),
]


async def seed():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as db:
        # Check if already seeded
        result = await db.execute(text("SELECT count(*) FROM users"))
        if result.scalar() > 0:
            print("Database already has data — skipping seed. Use 'make reset-db' to start fresh.")
            await engine.dispose()
            return

        print("Seeding database...")

        # ── Categories ────────────────────────────────────────────
        for cat_id, parent_id, name_ar, name_en, slug, sort_order in CATEGORIES:
            await db.execute(text("""
                INSERT INTO categories (id, parent_id, name_ar, name_en, slug, sort_order)
                VALUES (:id, :parent_id, :name_ar, :name_en, :slug, :sort_order)
            """), {
                "id": cat_id, "parent_id": parent_id,
                "name_ar": name_ar, "name_en": name_en,
                "slug": slug, "sort_order": sort_order,
            })
        print(f"  ✓ {len(CATEGORIES)} categories")

        # ── NGO Partner ───────────────────────────────────────────
        await db.execute(text("""
            INSERT INTO ngo_partners (id, name_ar, name_en, registration_number, country_code, is_verified)
            VALUES (:id, :name_ar, :name_en, :reg, :cc, true)
        """), {
            "id": NGO_ID,
            "name_ar": "جمعية الخير الأردنية",
            "name_en": "Jordan Charity Association",
            "reg": "NGO-JO-2024-001",
            "cc": "JO",
        })
        print("  ✓ 1 NGO partner")

        # ── Users ─────────────────────────────────────────────────
        users = [
            (ADMIN_ID, "+962790000001", "مدير النظام", "System Admin", "super_admin", "verified", 1000, "elite"),
            (SELLER_1_ID, "+962790000002", "أحمد البائع", "Ahmed Seller", "seller", "verified", 750, "pro"),
            (SELLER_2_ID, "+962790000003", "سارة التاجرة", "Sara ProSeller", "pro_seller", "verified", 850, "elite"),
            (BUYER_1_ID, "+962790000004", "محمد المشتري", "Mohammed Buyer", "buyer", "verified", 500, "trusted"),
            (BUYER_2_ID, "+962790000005", "ليلى المزايدة", "Layla Bidder", "buyer", "verified", 600, "trusted"),
            (MEDIATOR_ID, "+962790000006", "خالد الوسيط", "Khaled Mediator", "mediator", "verified", 900, "elite"),
        ]
        for uid, phone, name_ar, name_en, role, kyc, ats, tier in users:
            await db.execute(text("""
                INSERT INTO users (id, phone, full_name_ar, full_name_en, role, kyc_status, ats_score, ats_tier)
                VALUES (:id, :phone, :name_ar, :name_en, :role::user_role, :kyc::kyc_status, :ats, :tier::ats_tier)
            """), {
                "id": uid, "phone": phone, "name_ar": name_ar, "name_en": name_en,
                "role": role, "kyc": kyc, "ats": ats, "tier": tier,
            })
        print(f"  ✓ {len(users)} users (admin, 2 sellers, 2 buyers, mediator)")

        # ── Listings ──────────────────────────────────────────────
        listing_1_id = _uuid()  # Active phone listing
        listing_2_id = _uuid()  # Active car listing
        listing_3_id = _uuid()  # Ended laptop listing (sold)
        listing_4_id = _uuid()  # Charity listing
        listing_5_id = _uuid()  # Draft listing

        listings = [
            {
                "id": listing_1_id,
                "seller_id": SELLER_1_ID,
                "title_ar": "آيفون 15 برو ماكس - جديد مغلف",
                "title_en": "iPhone 15 Pro Max - New Sealed",
                "description_ar": "آيفون 15 برو ماكس 256 جيجا، لون تيتانيوم طبيعي، جديد مغلف بالكرتونة الأصلية",
                "description_en": "iPhone 15 Pro Max 256GB, Natural Titanium, brand new sealed in original box",
                "category_id": 13,
                "condition": "new",
                "starting_price": "350.000",
                "reserve_price": "400.000",
                "buy_it_now_price": "500.000",
                "status": "active",
                "image_urls": "{https://placeholder.dev/phone1.jpg,https://placeholder.dev/phone2.jpg}",
                "published_at": str(NOW - timedelta(hours=2)),
            },
            {
                "id": listing_2_id,
                "seller_id": SELLER_2_ID,
                "title_ar": "مرسيدس C200 موديل 2022 - حالة ممتازة",
                "title_en": "Mercedes C200 2022 - Excellent Condition",
                "description_ar": "مرسيدس C200 AMG لاين، 30,000 كم فقط، فحص كامل، بدون حوادث",
                "description_en": "Mercedes C200 AMG Line, only 30,000 km, full inspection, accident-free",
                "category_id": 18,
                "condition": "like_new",
                "starting_price": "18000.000",
                "reserve_price": "22000.000",
                "buy_it_now_price": None,
                "status": "active",
                "image_urls": "{https://placeholder.dev/car1.jpg,https://placeholder.dev/car2.jpg,https://placeholder.dev/car3.jpg}",
                "published_at": str(NOW - timedelta(hours=6)),
            },
            {
                "id": listing_3_id,
                "seller_id": SELLER_1_ID,
                "title_ar": "لابتوب ماك بوك برو M3 - مستعمل نظيف",
                "title_en": "MacBook Pro M3 - Clean Used",
                "description_ar": "ماك بوك برو 14 انش، شريحة M3، 16 جيجا رام، 512 تخزين، ضمان آبل ساري",
                "description_en": "MacBook Pro 14-inch, M3 chip, 16GB RAM, 512GB SSD, Apple warranty active",
                "category_id": 14,
                "condition": "like_new",
                "starting_price": "550.000",
                "reserve_price": "650.000",
                "buy_it_now_price": None,
                "status": "sold",
                "image_urls": "{https://placeholder.dev/laptop1.jpg,https://placeholder.dev/laptop2.jpg}",
                "published_at": str(NOW - timedelta(days=3)),
            },
            {
                "id": listing_4_id,
                "seller_id": SELLER_2_ID,
                "title_ar": "لوحة فنية أصلية - لصالح جمعية الخير",
                "title_en": "Original Art Painting - Charity Auction",
                "description_ar": "لوحة زيتية أصلية للفنان الأردني سامي، العائدات لصالح جمعية الخير الأردنية",
                "description_en": "Original oil painting by Jordanian artist Sami, proceeds go to Jordan Charity Association",
                "category_id": 9,
                "condition": "new",
                "starting_price": "50.000",
                "reserve_price": None,
                "buy_it_now_price": None,
                "status": "active",
                "image_urls": "{https://placeholder.dev/art1.jpg}",
                "published_at": str(NOW - timedelta(hours=1)),
                "is_charity": True,
                "ngo_id": NGO_ID,
            },
            {
                "id": listing_5_id,
                "seller_id": SELLER_1_ID,
                "title_ar": "بلايستيشن 5 مع ألعاب",
                "title_en": "PlayStation 5 with Games",
                "description_ar": "بلايستيشن 5 ديجيتال إيديشن مع 5 ألعاب",
                "description_en": "PS5 Digital Edition with 5 games",
                "category_id": 17,
                "condition": "good",
                "starting_price": "150.000",
                "reserve_price": None,
                "buy_it_now_price": None,
                "status": "draft",
                "image_urls": "{https://placeholder.dev/ps5.jpg}",
                "published_at": None,
            },
        ]

        for lst in listings:
            is_charity = lst.pop("is_charity", False)
            ngo_id = lst.pop("ngo_id", None)
            await db.execute(text("""
                INSERT INTO listings
                    (id, seller_id, title_ar, title_en, description_ar, description_en,
                     category_id, condition, starting_price, reserve_price, buy_it_now_price,
                     status, image_urls, published_at, is_charity, ngo_id)
                VALUES
                    (:id, :seller_id, :title_ar, :title_en, :description_ar, :description_en,
                     :category_id, :condition::item_condition, :starting_price, :reserve_price,
                     :buy_it_now_price, :status::listing_status,
                     :image_urls, :published_at::timestamptz,
                     :is_charity, :ngo_id)
            """), {**lst, "is_charity": is_charity, "ngo_id": ngo_id})
        print(f"  ✓ {len(listings)} listings (3 active, 1 sold, 1 draft)")

        # ── Auctions ──────────────────────────────────────────────
        auction_1_id = _uuid()  # Active phone auction
        auction_2_id = _uuid()  # Active car auction
        auction_3_id = _uuid()  # Ended laptop auction (won by buyer_1)
        auction_4_id = _uuid()  # Active charity auction

        auctions = [
            {
                "id": auction_1_id,
                "listing_id": listing_1_id,
                "status": "active",
                "starts_at": str(NOW - timedelta(hours=2)),
                "ends_at": str(NOW + timedelta(hours=22)),
                "current_price": "385.000",
                "min_increment": "5.000",
                "bid_count": 3,
            },
            {
                "id": auction_2_id,
                "listing_id": listing_2_id,
                "status": "active",
                "starts_at": str(NOW - timedelta(hours=6)),
                "ends_at": str(NOW + timedelta(days=2)),
                "current_price": "19500.000",
                "min_increment": "250.000",
                "bid_count": 2,
            },
            {
                "id": auction_3_id,
                "listing_id": listing_3_id,
                "status": "ended",
                "starts_at": str(NOW - timedelta(days=3)),
                "ends_at": str(NOW - timedelta(days=1)),
                "current_price": "700.000",
                "min_increment": "10.000",
                "bid_count": 7,
                "winner_id": BUYER_1_ID,
                "final_price": "700.000",
                "reserve_met": True,
            },
            {
                "id": auction_4_id,
                "listing_id": listing_4_id,
                "status": "active",
                "starts_at": str(NOW - timedelta(hours=1)),
                "ends_at": str(NOW + timedelta(days=3)),
                "current_price": "75.000",
                "min_increment": "5.000",
                "bid_count": 2,
            },
        ]

        for auc in auctions:
            winner_id = auc.pop("winner_id", None)
            final_price = auc.pop("final_price", None)
            reserve_met = auc.pop("reserve_met", None)
            await db.execute(text("""
                INSERT INTO auctions
                    (id, listing_id, status, starts_at, ends_at, current_price,
                     min_increment, bid_count, winner_id, final_price, reserve_met)
                VALUES
                    (:id, :listing_id, :status::auction_status,
                     :starts_at::timestamptz, :ends_at::timestamptz,
                     :current_price, :min_increment, :bid_count,
                     :winner_id, :final_price, :reserve_met)
            """), {
                **auc, "winner_id": winner_id,
                "final_price": final_price, "reserve_met": reserve_met,
            })
        print(f"  ✓ {len(auctions)} auctions (3 active, 1 ended)")

        # ── Bids (append-only) ────────────────────────────────────
        bids = [
            # Phone auction bids
            (auction_1_id, BUYER_1_ID, "360.000", NOW - timedelta(hours=1, minutes=30)),
            (auction_1_id, BUYER_2_ID, "370.000", NOW - timedelta(hours=1)),
            (auction_1_id, BUYER_1_ID, "385.000", NOW - timedelta(minutes=30)),
            # Car auction bids
            (auction_2_id, BUYER_1_ID, "18500.000", NOW - timedelta(hours=4)),
            (auction_2_id, BUYER_2_ID, "19500.000", NOW - timedelta(hours=2)),
            # Laptop auction bids (ended)
            (auction_3_id, BUYER_1_ID, "570.000", NOW - timedelta(days=2, hours=20)),
            (auction_3_id, BUYER_2_ID, "600.000", NOW - timedelta(days=2, hours=16)),
            (auction_3_id, BUYER_1_ID, "630.000", NOW - timedelta(days=2, hours=12)),
            (auction_3_id, BUYER_2_ID, "650.000", NOW - timedelta(days=2, hours=8)),
            (auction_3_id, BUYER_1_ID, "670.000", NOW - timedelta(days=2, hours=4)),
            (auction_3_id, BUYER_2_ID, "690.000", NOW - timedelta(days=1, hours=12)),
            (auction_3_id, BUYER_1_ID, "700.000", NOW - timedelta(days=1, hours=6)),
            # Charity auction bids
            (auction_4_id, BUYER_2_ID, "60.000", NOW - timedelta(minutes=45)),
            (auction_4_id, BUYER_1_ID, "75.000", NOW - timedelta(minutes=20)),
        ]

        for auction_id, user_id, amount, created_at in bids:
            await db.execute(text("""
                INSERT INTO bids (id, auction_id, user_id, amount, created_at)
                VALUES (:id, :auction_id, :user_id, :amount, :created_at)
            """), {
                "id": _uuid(), "auction_id": auction_id,
                "user_id": user_id, "amount": amount,
                "created_at": str(created_at),
            })
        print(f"  ✓ {len(bids)} bids across 4 auctions")

        # ── Escrow (for ended laptop auction) ─────────────────────
        escrow_id = _uuid()
        await db.execute(text("""
            INSERT INTO escrows
                (id, auction_id, winner_id, seller_id, state, amount, currency,
                 seller_amount, payment_deadline, shipping_deadline)
            VALUES
                (:id, :auction_id, :winner_id, :seller_id, 'funds_held'::escrow_state,
                 :amount, 'JOD', :seller_amount, :pay_dl, :ship_dl)
        """), {
            "id": escrow_id,
            "auction_id": auction_3_id,
            "winner_id": BUYER_1_ID,
            "seller_id": SELLER_1_ID,
            "amount": "700.000",
            "seller_amount": "665.000",  # 5% platform fee
            "pay_dl": str(NOW - timedelta(days=1, hours=12)),
            "ship_dl": str(NOW + timedelta(days=2)),
        })

        # Escrow events — audit trail
        events = [
            ("initiated", "payment_pending", "system", "auction_ended", NOW - timedelta(days=1)),
            ("payment_pending", "funds_held", "buyer", "payment_confirmed", NOW - timedelta(days=1, hours=-6)),
            ("funds_held", "shipping_requested", "system", "payment_cleared", NOW - timedelta(hours=18)),
        ]
        for from_s, to_s, actor_type, trigger, created_at in events:
            actor_id = BUYER_1_ID if actor_type == "buyer" else None
            await db.execute(text("""
                INSERT INTO escrow_events
                    (id, escrow_id, from_state, to_state, actor_id, actor_type, trigger, created_at)
                VALUES
                    (:id, :escrow_id, :from_s, :to_s, :actor_id, :actor_type::actor_type, :trigger, :created_at)
            """), {
                "id": _uuid(), "escrow_id": escrow_id,
                "from_s": from_s, "to_s": to_s,
                "actor_id": actor_id, "actor_type": actor_type,
                "trigger": trigger, "created_at": str(created_at),
            })
        print(f"  ✓ 1 escrow (funds_held) with {len(events)} events")

        # ── Notification preferences ──────────────────────────────
        for uid in [ADMIN_ID, SELLER_1_ID, SELLER_2_ID, BUYER_1_ID, BUYER_2_ID, MEDIATOR_ID]:
            await db.execute(text("""
                INSERT INTO notification_preferences (id, user_id)
                VALUES (:id, :user_id)
            """), {"id": _uuid(), "user_id": uid})
        print("  ✓ 6 notification preferences (defaults)")

        # ── Sample notifications ──────────────────────────────────
        notifications = [
            (BUYER_1_ID, "in_app", "تم تأكيد مزايدتك", "Bid Confirmed",
             "تم تأكيد مزايدتك بقيمة 385 د.أ على آيفون 15 برو ماكس",
             "Your bid of 385 JOD on iPhone 15 Pro Max has been confirmed"),
            (SELLER_1_ID, "in_app", "مزايدة جديدة", "New Bid",
             "مزايدة جديدة على آيفون 15 برو ماكس بقيمة 385 د.أ",
             "New bid of 385 JOD on your iPhone 15 Pro Max listing"),
            (BUYER_1_ID, "in_app", "فزت بالمزاد!", "You Won!",
             "مبروك! فزت بمزاد ماك بوك برو M3 بقيمة 700 د.أ",
             "Congratulations! You won the MacBook Pro M3 auction for 700 JOD"),
        ]
        for user_id, channel, title_ar, title_en, body_ar, body_en in notifications:
            await db.execute(text("""
                INSERT INTO notifications
                    (id, user_id, channel, title_ar, title_en, body_ar, body_en)
                VALUES
                    (:id, :user_id, :channel::notification_channel,
                     :title_ar, :title_en, :body_ar, :body_en)
            """), {
                "id": _uuid(), "user_id": user_id, "channel": channel,
                "title_ar": title_ar, "title_en": title_en,
                "body_ar": body_ar, "body_en": body_en,
            })
        print(f"  ✓ {len(notifications)} notifications")

        # ── Admin audit log ───────────────────────────────────────
        await db.execute(text("""
            INSERT INTO admin_audit_log (id, admin_id, action, target_type, target_id, ip_address)
            VALUES (:id, :admin_id, 'seed_database', 'system', null, '127.0.0.1')
        """), {"id": _uuid(), "admin_id": ADMIN_ID})
        print("  ✓ 1 admin audit log entry")

        await db.commit()
        print("\nDatabase seeded successfully.")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
