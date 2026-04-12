"""
Database seed script — populates dev environment with test data.

Usage:
    python -m app.db.seed                          (from /backend)
    docker compose exec api python -m app.db.seed  (from Docker)

Requires: migrations applied (0001 + 0002), PostgreSQL running.

Price units:
  listings  → INTEGER cents  (1 JOD = 100 cents)
  auctions  → Numeric(10,3)  (JOD float, e.g. 25.000)
  bids      → Numeric(10,3)  (JOD float)
  escrows   → Numeric(10,3)  (JOD float)
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

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

NOW = datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════════════
# Categories — 12 top-level + subcategories for Phase 1
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
    # Subcategories for Phase 1
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
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )

    async with session_factory() as db:
        # Check if already seeded
        result = await db.execute(text("SELECT count(*) FROM users"))
        if result.scalar() > 0:
            print(
                "Database already has data — skipping seed. "
                "Use 'docker compose down -v && docker compose up -d' to start fresh.",
            )
            await engine.dispose()
            return

        print("Seeding database...")

        # ── Categories ────────────────────────────────────────────
        # Migration seeds 8 basic categories; replace with full set
        await db.execute(text("DELETE FROM categories"))
        for cat_id, parent_id, name_ar, name_en, slug, sort_order in CATEGORIES:
            await db.execute(text("""
                INSERT INTO categories (id, parent_id, name_ar, name_en, slug, sort_order)
                VALUES (:id, :parent_id, :name_ar, :name_en, :slug, :sort_order)
            """), {
                "id": cat_id, "parent_id": parent_id,
                "name_ar": name_ar, "name_en": name_en,
                "slug": slug, "sort_order": sort_order,
            })
        # Reset sequence so next auto-insert gets id > 23
        await db.execute(text(
            "SELECT setval('categories_id_seq', (SELECT MAX(id) FROM categories))",
        ))
        print(f"  + {len(CATEGORIES)} categories (12 top-level + subcategories)")

        # ── NGO Partner ───────────────────────────────────────────
        await db.execute(text("""
            INSERT INTO ngo_partners (name_ar, name_en, is_zakat_eligible, is_active)
            VALUES (:name_ar, :name_en, true, true)
        """), {
            "name_ar": "جمعية الخير الأردنية",
            "name_en": "Jordan Charity Association",
        })
        # Fetch auto-generated NGO id
        ngo_result = await db.execute(text(
            "SELECT id FROM ngo_partners WHERE name_en = 'Jordan Charity Association'",
        ))
        ngo_id = ngo_result.scalar()
        print("  + 1 NGO partner")

        # ── Users (String columns, no enum casts) ─────────────────
        users = [
            # (id, phone, name_ar, name_en, role, status, kyc, ats, is_pro)
            (ADMIN_ID, "+962790000001", "مدير النظام", "System Admin",
             "superadmin", "active", "verified", 1000, False),
            (SELLER_1_ID, "+962790000002", "أحمد البائع", "Ahmed Seller",
             "seller", "active", "verified", 750, False),
            (SELLER_2_ID, "+962790000003", "سارة التاجرة", "Sara ProSeller",
             "seller", "active", "verified", 850, True),
            (BUYER_1_ID, "+962790000004", "محمد المشتري", "Mohammed Buyer",
             "buyer", "active", "verified", 500, False),
            (BUYER_2_ID, "+962790000005", "ليلى المزايدة", "Layla Bidder",
             "buyer", "active", "verified", 600, False),
            (MEDIATOR_ID, "+962790000006", "خالد الوسيط", "Khaled Admin",
             "admin", "active", "verified", 900, False),
        ]
        for uid, phone, name_ar, name_en, role, st, kyc, ats, is_pro in users:
            await db.execute(text("""
                INSERT INTO users
                    (id, phone, full_name_ar, full_name, role, status,
                     kyc_status, ats_score, phone_verified, is_pro_seller,
                     fcm_tokens, preferred_language)
                VALUES
                    (:id, :phone, :name_ar, :name_en,
                     :role, :status, :kyc,
                     :ats, true, :is_pro, '[]'::jsonb, 'ar')
            """), {
                "id": uid, "phone": phone, "name_ar": name_ar,
                "name_en": name_en, "role": role, "status": st,
                "kyc": kyc, "ats": ats, "is_pro": is_pro,
            })
        print(f"  + {len(users)} users (superadmin, 2 sellers, 2 buyers, 1 admin)")

        # ── Listings (prices in INTEGER cents) ────────────────────
        listing_1_id = _uuid()  # Active phone auction
        listing_2_id = _uuid()  # Active car auction
        listing_3_id = _uuid()  # Ended laptop (sold)
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
                "condition": "brand_new",
                "starting_price": 350000,  # 350 JOD
                "reserve_price": 400000,
                "buy_it_now_price": 500000,
                "current_price": 385000,
                "bid_count": 3,
                "status": "active",
                "starts_at": NOW - timedelta(hours=2),
                "ends_at": NOW + timedelta(hours=22),
                "is_charity": False,
                "ngo_id": None,
            },
            {
                "id": listing_2_id,
                "seller_id": SELLER_2_ID,
                "title_ar": "مرسيدس C200 موديل 2022 - حالة ممتازة",
                "title_en": "Mercedes C200 2022 - Excellent Condition",
                "description_ar": "مرسيدس C200 AMG لاين، 30,000 كم فقط، فحص كامل، بدون حوادث",
                "description_en": "Mercedes C200 AMG Line, only 30k km, full inspection, accident-free",
                "category_id": 18,
                "condition": "like_new",
                "starting_price": 18000000,  # 18,000 JOD
                "reserve_price": 22000000,
                "buy_it_now_price": None,
                "current_price": 19500000,
                "bid_count": 2,
                "status": "active",
                "starts_at": NOW - timedelta(hours=6),
                "ends_at": NOW + timedelta(hours=18),
                "is_charity": False,
                "ngo_id": None,
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
                "starting_price": 550000,  # 550 JOD
                "reserve_price": 650000,
                "buy_it_now_price": None,
                "current_price": 700000,
                "bid_count": 7,
                "status": "ended",
                "starts_at": NOW - timedelta(days=3),
                "ends_at": NOW - timedelta(days=2),
                "is_charity": False,
                "ngo_id": None,
            },
            {
                "id": listing_4_id,
                "seller_id": SELLER_2_ID,
                "title_ar": "لوحة فنية أصلية - لصالح جمعية الخير",
                "title_en": "Original Art Painting - Charity Auction",
                "description_ar": "لوحة زيتية أصلية للفنان الأردني سامي، العائدات لصالح جمعية الخير الأردنية",
                "description_en": "Original oil painting by Jordanian artist Sami, proceeds go to Jordan Charity",
                "category_id": 9,
                "condition": "brand_new",
                "starting_price": 50000,  # 50 JOD
                "reserve_price": None,
                "buy_it_now_price": None,
                "current_price": 75000,
                "bid_count": 2,
                "status": "active",
                "starts_at": NOW - timedelta(hours=1),
                "ends_at": NOW + timedelta(hours=23),
                "is_charity": True,
                "ngo_id": ngo_id,
            },
            {
                "id": listing_5_id,
                "seller_id": SELLER_1_ID,
                "title_ar": "بلايستيشن 5 مع ألعاب",
                "title_en": "PlayStation 5 with Games",
                "description_ar": "بلايستيشن 5 ديجيتال إيديشن مع 5 ألعاب",
                "description_en": "PS5 Digital Edition with 5 games bundle",
                "category_id": 17,
                "condition": "good",
                "starting_price": 150000,  # 150 JOD
                "reserve_price": None,
                "buy_it_now_price": None,
                "current_price": None,
                "bid_count": 0,
                "status": "draft",
                "starts_at": NOW + timedelta(hours=1),
                "ends_at": NOW + timedelta(hours=25),
                "is_charity": False,
                "ngo_id": None,
            },
        ]

        for lst in listings:
            await db.execute(text("""
                INSERT INTO listings
                    (id, seller_id, title_ar, title_en, description_ar, description_en,
                     category_id, condition, starting_price, reserve_price,
                     buy_it_now_price, current_price, bid_count,
                     status, starts_at, ends_at, is_charity, ngo_id,
                     moderation_status, min_increment, location_country)
                VALUES
                    (:id, :seller_id, :title_ar, :title_en, :description_ar, :description_en,
                     :category_id, :condition,
                     :starting_price, :reserve_price, :buy_it_now_price,
                     :current_price, :bid_count,
                     :status, :starts_at, :ends_at,
                     :is_charity, :ngo_id,
                     'approved', 2500, 'JO')
            """), lst)

        # Feature the Mercedes listing (0002 migration columns)
        await db.execute(text("""
            UPDATE listings
            SET is_featured = true,
                featured_at = :now,
                featured_until = :until
            WHERE id = :id
        """), {"id": listing_2_id, "now": NOW, "until": NOW + timedelta(days=7)})

        print(f"  + {len(listings)} listings (3 active, 1 ended, 1 draft, 1 featured)")

        # ── Listing Images ────────────────────────────────────────
        listing_images = [
            (listing_1_id, "listings/phone1.webp", 0),
            (listing_1_id, "listings/phone2.webp", 1),
            (listing_2_id, "listings/car1.webp", 0),
            (listing_2_id, "listings/car2.webp", 1),
            (listing_2_id, "listings/car3.webp", 2),
            (listing_3_id, "listings/laptop1.webp", 0),
            (listing_3_id, "listings/laptop2.webp", 1),
            (listing_4_id, "listings/art1.webp", 0),
            (listing_5_id, "listings/ps5.webp", 0),
        ]
        for listing_id, s3_key, order in listing_images:
            await db.execute(text("""
                INSERT INTO listing_images (id, listing_id, s3_key, display_order)
                VALUES (gen_random_uuid(), :listing_id, :s3_key, :order)
            """), {"listing_id": listing_id, "s3_key": s3_key, "order": order})
        print(f"  + {len(listing_images)} listing images")

        # ── Auctions (Numeric prices in JOD, new column names) ───
        auction_1_id = _uuid()  # Active phone auction
        auction_2_id = _uuid()  # Active car auction
        auction_3_id = _uuid()  # Ended laptop auction
        auction_4_id = _uuid()  # Active charity auction

        # Convert listing cents → auction JOD float
        auctions = [
            {
                "id": auction_1_id,
                "listing_id": listing_1_id,
                "status": "active",
                "starts_at": NOW - timedelta(hours=2),
                "ends_at": NOW + timedelta(hours=22),
                "current_price": 3850.000,   # 385000 cents = 3850 JOD
                "min_increment": 25.000,
                "bid_count": 3,
                "extension_count": 0,
                "winner_id": None,
                "final_price": None,
            },
            {
                "id": auction_2_id,
                "listing_id": listing_2_id,
                "status": "active",
                "starts_at": NOW - timedelta(hours=6),
                "ends_at": NOW + timedelta(hours=18),
                "current_price": 195000.000,  # 19500000 cents = 195000 JOD
                "min_increment": 250.000,
                "bid_count": 2,
                "extension_count": 0,
                "winner_id": None,
                "final_price": None,
            },
            {
                "id": auction_3_id,
                "listing_id": listing_3_id,
                "status": "ended",
                "starts_at": NOW - timedelta(days=3),
                "ends_at": NOW - timedelta(days=2),
                "current_price": 7000.000,   # 700000 cents = 7000 JOD
                "min_increment": 25.000,
                "bid_count": 7,
                "extension_count": 0,
                "winner_id": BUYER_1_ID,
                "final_price": 7000.000,
            },
            {
                "id": auction_4_id,
                "listing_id": listing_4_id,
                "status": "active",
                "starts_at": NOW - timedelta(hours=1),
                "ends_at": NOW + timedelta(hours=23),
                "current_price": 750.000,    # 75000 cents = 750 JOD
                "min_increment": 10.000,
                "bid_count": 2,
                "extension_count": 0,
                "winner_id": None,
                "final_price": None,
            },
        ]

        for auc in auctions:
            await db.execute(text("""
                INSERT INTO auctions
                    (id, listing_id, status, starts_at, ends_at,
                     current_price, min_increment, bid_count,
                     extension_count, winner_id, final_price)
                VALUES
                    (:id, :listing_id, :status, :starts_at, :ends_at,
                     :current_price, :min_increment, :bid_count,
                     :extension_count, :winner_id, :final_price)
            """), auc)
        print(f"  + {len(auctions)} auctions (3 active, 1 ended)")

        # ── Bids (Numeric JOD, user_id, currency) ─────────────────
        bids = [
            # (auction_id, user_id, amount_jod, is_proxy, created_at)
            # Phone auction
            (auction_1_id, BUYER_1_ID, 3600.000, False,
             NOW - timedelta(hours=1, minutes=30)),
            (auction_1_id, BUYER_2_ID, 3700.000, False,
             NOW - timedelta(hours=1)),
            (auction_1_id, BUYER_1_ID, 3850.000, False,
             NOW - timedelta(minutes=30)),
            # Car auction
            (auction_2_id, BUYER_1_ID, 185000.000, False,
             NOW - timedelta(hours=4)),
            (auction_2_id, BUYER_2_ID, 195000.000, False,
             NOW - timedelta(hours=2)),
            # Laptop auction (ended)
            (auction_3_id, BUYER_1_ID, 5700.000, False,
             NOW - timedelta(days=2, hours=20)),
            (auction_3_id, BUYER_2_ID, 6000.000, False,
             NOW - timedelta(days=2, hours=16)),
            (auction_3_id, BUYER_1_ID, 6300.000, False,
             NOW - timedelta(days=2, hours=12)),
            (auction_3_id, BUYER_2_ID, 6500.000, False,
             NOW - timedelta(days=2, hours=8)),
            (auction_3_id, BUYER_1_ID, 6700.000, False,
             NOW - timedelta(days=2, hours=4)),
            (auction_3_id, BUYER_2_ID, 6900.000, False,
             NOW - timedelta(days=1, hours=12)),
            (auction_3_id, BUYER_1_ID, 7000.000, False,
             NOW - timedelta(days=1, hours=6)),
            # Charity auction
            (auction_4_id, BUYER_2_ID, 600.000, False,
             NOW - timedelta(minutes=45)),
            (auction_4_id, BUYER_1_ID, 750.000, False,
             NOW - timedelta(minutes=20)),
        ]

        for auction_id, user_id, amount, is_proxy, created_at in bids:
            await db.execute(text("""
                INSERT INTO bids
                    (id, auction_id, user_id, amount, currency,
                     is_proxy, created_at)
                VALUES
                    (:id, :auction_id, :user_id, :amount, 'JOD',
                     :is_proxy, :created_at)
            """), {
                "id": _uuid(), "auction_id": auction_id,
                "user_id": user_id, "amount": amount,
                "is_proxy": is_proxy, "created_at": created_at,
            })
        print(f"  + {len(bids)} bids across 4 auctions")

        # ── Escrow (ended laptop auction, Numeric JOD) ────────────
        escrow_id = _uuid()
        escrow_amount = 7000.000     # 7000 JOD
        seller_amount = 6300.000     # 7000 - 10% fee = 6300 JOD

        await db.execute(text("""
            INSERT INTO escrows
                (id, auction_id, winner_id, seller_id,
                 amount, currency, seller_amount,
                 state, payment_deadline, shipping_deadline)
            VALUES
                (:id, :auction_id, :winner_id, :seller_id,
                 :amount, 'JOD', :seller_amount,
                 'shipping_requested',
                 :pay_dl, :ship_dl)
        """), {
            "id": escrow_id,
            "auction_id": auction_3_id,
            "winner_id": BUYER_1_ID,
            "seller_id": SELLER_1_ID,
            "amount": escrow_amount,
            "seller_amount": seller_amount,
            "pay_dl": NOW - timedelta(days=1, hours=12),
            "ship_dl": NOW + timedelta(days=2),
        })

        # Escrow events — append-only audit trail (Text columns, meta not metadata)
        events = [
            ("payment_pending", "funds_held", BUYER_1_ID, "buyer",
             "payment_confirmed", NOW - timedelta(days=1)),
            ("funds_held", "shipping_requested", None, "system",
             "payment_cleared", NOW - timedelta(hours=18)),
        ]
        for from_s, to_s, actor_id, actor_type, trigger, created_at in events:
            await db.execute(text("""
                INSERT INTO escrow_events
                    (id, escrow_id, from_state, to_state,
                     actor_id, actor_type, trigger, meta, created_at)
                VALUES
                    (:id, :escrow_id,
                     :from_s, :to_s,
                     :actor_id, :actor_type, :trigger,
                     '{}'::jsonb, :created_at)
            """), {
                "id": _uuid(), "escrow_id": escrow_id,
                "from_s": from_s, "to_s": to_s,
                "actor_id": actor_id, "actor_type": actor_type,
                "trigger": trigger, "created_at": created_at,
            })
        print(f"  + 1 escrow (shipping_requested) with {len(events)} events")

        # ── Notification preferences ──────────────────────────────
        for uid in [ADMIN_ID, SELLER_1_ID, SELLER_2_ID,
                    BUYER_1_ID, BUYER_2_ID, MEDIATOR_ID]:
            await db.execute(text("""
                INSERT INTO notification_preferences (id, user_id)
                VALUES (:id, :user_id)
            """), {"id": _uuid(), "user_id": uid})
        print("  + 6 notification preferences (defaults)")

        # ── User address fields (0002 migration) ─────────────────
        address_data = [
            (SELLER_1_ID, "عمّان", "JO"),
            (SELLER_2_ID, "إربد", "JO"),
            (BUYER_1_ID, "عمّان", "JO"),
            (BUYER_2_ID, "العقبة", "JO"),
        ]
        for uid, city, country in address_data:
            await db.execute(text("""
                UPDATE users SET address_city = :city, address_country = :country
                WHERE id = :id
            """), {"id": uid, "city": city, "country": country})
        print(f"  + {len(address_data)} user addresses")

        # ── Announcements (0002 migration table) ─────────────────
        announcements = [
            {
                "title_ar": "مرحباً بكم في مزادك!",
                "title_en": "Welcome to MZADAK!",
                "body_ar": "أول منصة مزادات ذكية في الأردن. سجّل الآن واحصل على مزايدات مجانية.",
                "body_en": "Jordan's first AI-powered auction marketplace. Register now and get free bids.",
                "type": "info",
                "is_active": True,
                "target_audience": "all",
                "starts_at": NOW - timedelta(days=1),
                "expires_at": NOW + timedelta(days=30),
            },
            {
                "title_ar": "صيانة مجدولة",
                "title_en": "Scheduled Maintenance",
                "body_ar": "سيتم إجراء صيانة مجدولة يوم الجمعة من 2-4 صباحاً. قد تتأثر بعض الخدمات.",
                "body_en": "Scheduled maintenance this Friday 2-4 AM. Some services may be affected.",
                "type": "warning",
                "is_active": False,
                "target_audience": "all",
                "starts_at": None,
                "expires_at": None,
            },
        ]
        for ann in announcements:
            await db.execute(text("""
                INSERT INTO announcements
                    (id, title_ar, title_en, body_ar, body_en,
                     type, is_active, starts_at, expires_at,
                     target_audience, created_by)
                VALUES
                    (gen_random_uuid(), :title_ar, :title_en, :body_ar, :body_en,
                     :type, :is_active, :starts_at, :expires_at,
                     :target_audience, :created_by)
            """), {**ann, "created_by": ADMIN_ID})
        print(f"  + {len(announcements)} announcements")

        # ── Sample notifications (String event_type, no enum) ─────
        notifications = [
            (BUYER_1_ID, "new_bid", listing_1_id, "listing",
             "تم تأكيد مزايدتك", "Bid Confirmed",
             "تم تأكيد مزايدتك بقيمة 385 د.أ على آيفون 15 برو ماكس",
             "Your bid of 385 JOD on iPhone 15 Pro Max has been confirmed"),
            (SELLER_1_ID, "new_bid", listing_1_id, "listing",
             "مزايدة جديدة", "New Bid",
             "مزايدة جديدة على آيفون 15 برو ماكس بقيمة 385 د.أ",
             "New bid of 385 JOD on your iPhone 15 Pro Max listing"),
            (BUYER_1_ID, "won", listing_3_id, "listing",
             "فزت بالمزاد!", "You Won!",
             "مبروك! فزت بمزاد ماك بوك برو M3 بقيمة 700 د.أ",
             "Congratulations! You won the MacBook Pro M3 auction for 700 JOD"),
        ]
        for user_id, event, entity_id, entity_type, t_ar, t_en, b_ar, b_en in notifications:
            await db.execute(text("""
                INSERT INTO notifications
                    (id, user_id, event_type, entity_id, entity_type,
                     title_ar, title_en, body_ar, body_en)
                VALUES
                    (:id, :user_id, :event,
                     :entity_id, :entity_type,
                     :t_ar, :t_en, :b_ar, :b_en)
            """), {
                "id": _uuid(), "user_id": user_id, "event": event,
                "entity_id": entity_id, "entity_type": entity_type,
                "t_ar": t_ar, "t_en": t_en, "b_ar": b_ar, "b_en": b_en,
            })
        print(f"  + {len(notifications)} notifications")

        # ── Admin audit log (ip_address is Text, not INET) ────────
        await db.execute(text("""
            INSERT INTO admin_audit_log
                (id, admin_id, action, entity_type, entity_id, ip_address)
            VALUES
                (:id, :admin_id, 'seed_database', 'system', null, '127.0.0.1')
        """), {"id": _uuid(), "admin_id": ADMIN_ID})
        print("  + 1 admin audit log entry")

        await db.commit()
        print("\nDatabase seeded successfully!")
        print(f"\nDev accounts (all phone-verified, KYC approved):")
        print(f"  Superadmin: +962790000001 (login to web admin)")
        print(f"  Seller 1:   +962790000002 (Ahmed, Amman)")
        print(f"  Seller 2:   +962790000003 (Sara, Pro Seller, Irbid)")
        print(f"  Buyer 1:    +962790000004 (Mohammed, Amman)")
        print(f"  Buyer 2:    +962790000005 (Layla, Aqaba)")
        print(f"  Admin:      +962790000006 (Khaled, mediator)")
        print(f"\nSample data:")
        print(f"  - 3 active auctions (iPhone, Mercedes [featured], Charity Art)")
        print(f"  - 1 ended auction (MacBook) with escrow in shipping_requested")
        print(f"  - 1 draft listing (PS5)")
        print(f"  - 14 bids across all auctions")
        print(f"  - 2 announcements (welcome + maintenance)")
        print(f"  - OTP in dev mode: any 6 digits work (SMS_PROVIDER=mock)")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
