"""
Database seed script — populates dev environment with test data.

Usage:
    python -m scripts.seed          (from /backend)
    docker compose exec api python -m scripts.seed

Requires: migrations applied, PostgreSQL running.
Uses raw SQL inserts matching the 0001_initial_schema migration.
All monetary values are INTEGER cents (1 JOD = 1000 fils).
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

        # ── Users ─────────────────────────────────────────────────
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
                     :role::user_role, :status::user_status, :kyc::kyc_status,
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
                     :category_id, :condition::listing_condition,
                     :starting_price, :reserve_price, :buy_it_now_price,
                     :current_price, :bid_count,
                     :status::listing_status, :starts_at, :ends_at,
                     :is_charity, :ngo_id,
                     'approved', 2500, 'JO')
            """), lst)
        print(f"  + {len(listings)} listings (3 active, 1 ended, 1 draft)")

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

        # ── Auctions (match migration schema) ─────────────────────
        auction_1_id = _uuid()  # Active phone auction
        auction_2_id = _uuid()  # Active car auction
        auction_3_id = _uuid()  # Ended laptop auction
        auction_4_id = _uuid()  # Active charity auction

        auctions = [
            {
                "id": auction_1_id,
                "listing_id": listing_1_id,
                "seller_id": SELLER_1_ID,
                "status": "active",
                "started_at": NOW - timedelta(hours=2),
                "ended_at": None,
                "final_price": None,
                "winner_id": None,
            },
            {
                "id": auction_2_id,
                "listing_id": listing_2_id,
                "seller_id": SELLER_2_ID,
                "status": "active",
                "started_at": NOW - timedelta(hours=6),
                "ended_at": None,
                "final_price": None,
                "winner_id": None,
            },
            {
                "id": auction_3_id,
                "listing_id": listing_3_id,
                "seller_id": SELLER_1_ID,
                "status": "ended",
                "started_at": NOW - timedelta(days=3),
                "ended_at": NOW - timedelta(days=2),
                "final_price": 700000,  # 700 JOD in cents
                "winner_id": BUYER_1_ID,
            },
            {
                "id": auction_4_id,
                "listing_id": listing_4_id,
                "seller_id": SELLER_2_ID,
                "status": "active",
                "started_at": NOW - timedelta(hours=1),
                "ended_at": None,
                "final_price": None,
                "winner_id": None,
            },
        ]

        for auc in auctions:
            await db.execute(text("""
                INSERT INTO auctions
                    (id, listing_id, seller_id, status, started_at, ended_at,
                     final_price, winner_id)
                VALUES
                    (:id, :listing_id, :seller_id, :status::auction_status,
                     :started_at, :ended_at, :final_price, :winner_id)
            """), auc)
        print(f"  + {len(auctions)} auctions (3 active, 1 ended)")

        # ── Bids (append-only, INTEGER cents, migration columns) ──
        bids = [
            # (listing_id, auction_id, bidder_id, amount_cents, is_proxy, created_at)
            # Phone auction
            (listing_1_id, auction_1_id, BUYER_1_ID, 360000, False,
             NOW - timedelta(hours=1, minutes=30)),
            (listing_1_id, auction_1_id, BUYER_2_ID, 370000, False,
             NOW - timedelta(hours=1)),
            (listing_1_id, auction_1_id, BUYER_1_ID, 385000, False,
             NOW - timedelta(minutes=30)),
            # Car auction
            (listing_2_id, auction_2_id, BUYER_1_ID, 18500000, False,
             NOW - timedelta(hours=4)),
            (listing_2_id, auction_2_id, BUYER_2_ID, 19500000, False,
             NOW - timedelta(hours=2)),
            # Laptop auction (ended)
            (listing_3_id, auction_3_id, BUYER_1_ID, 570000, False,
             NOW - timedelta(days=2, hours=20)),
            (listing_3_id, auction_3_id, BUYER_2_ID, 600000, False,
             NOW - timedelta(days=2, hours=16)),
            (listing_3_id, auction_3_id, BUYER_1_ID, 630000, False,
             NOW - timedelta(days=2, hours=12)),
            (listing_3_id, auction_3_id, BUYER_2_ID, 650000, False,
             NOW - timedelta(days=2, hours=8)),
            (listing_3_id, auction_3_id, BUYER_1_ID, 670000, False,
             NOW - timedelta(days=2, hours=4)),
            (listing_3_id, auction_3_id, BUYER_2_ID, 690000, False,
             NOW - timedelta(days=1, hours=12)),
            (listing_3_id, auction_3_id, BUYER_1_ID, 700000, False,
             NOW - timedelta(days=1, hours=6)),
            # Charity auction
            (listing_4_id, auction_4_id, BUYER_2_ID, 60000, False,
             NOW - timedelta(minutes=45)),
            (listing_4_id, auction_4_id, BUYER_1_ID, 75000, False,
             NOW - timedelta(minutes=20)),
        ]

        for listing_id, auction_id, bidder_id, amount, is_proxy, created_at in bids:
            await db.execute(text("""
                INSERT INTO bids
                    (id, listing_id, auction_id, bidder_id, amount,
                     status, is_proxy, created_at)
                VALUES
                    (:id, :listing_id, :auction_id, :bidder_id, :amount,
                     'accepted'::bid_status, :is_proxy, :created_at)
            """), {
                "id": _uuid(), "listing_id": listing_id,
                "auction_id": auction_id, "bidder_id": bidder_id,
                "amount": amount, "is_proxy": is_proxy,
                "created_at": created_at,
            })
        print(f"  + {len(bids)} bids across 4 auctions")

        # ── Escrow (ended laptop auction, INTEGER cents) ──────────
        escrow_id = _uuid()
        platform_fee = 35000    # 5% of 700 JOD = 35 JOD
        seller_payout = 665000  # 700 - 35 = 665 JOD

        await db.execute(text("""
            INSERT INTO escrows
                (id, auction_id, listing_id, buyer_id, seller_id,
                 amount, platform_fee, seller_payout,
                 state, payment_deadline, shipping_deadline)
            VALUES
                (:id, :auction_id, :listing_id, :buyer_id, :seller_id,
                 :amount, :platform_fee, :seller_payout,
                 'shipping_requested'::escrow_status,
                 :pay_dl, :ship_dl)
        """), {
            "id": escrow_id,
            "auction_id": auction_3_id,
            "listing_id": listing_3_id,
            "buyer_id": BUYER_1_ID,
            "seller_id": SELLER_1_ID,
            "amount": 700000,
            "platform_fee": platform_fee,
            "seller_payout": seller_payout,
            "pay_dl": NOW - timedelta(days=1, hours=12),
            "ship_dl": NOW + timedelta(days=2),
        })

        # Escrow events — append-only audit trail
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
                     actor_id, actor_type, trigger, metadata, created_at)
                VALUES
                    (:id, :escrow_id,
                     :from_s::escrow_status, :to_s::escrow_status,
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

        # ── Sample notifications ──────────────────────────────────
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
                    (:id, :user_id, :event::notification_event,
                     :entity_id, :entity_type,
                     :t_ar, :t_en, :b_ar, :b_en)
            """), {
                "id": _uuid(), "user_id": user_id, "event": event,
                "entity_id": entity_id, "entity_type": entity_type,
                "t_ar": t_ar, "t_en": t_en, "b_ar": b_ar, "b_en": b_en,
            })
        print(f"  + {len(notifications)} notifications")

        # ── Admin audit log ───────────────────────────────────────
        await db.execute(text("""
            INSERT INTO admin_audit_log
                (id, admin_id, action, entity_type, entity_id, ip_address)
            VALUES
                (:id, :admin_id, 'seed_database', 'system', null, '127.0.0.1'::inet)
        """), {"id": _uuid(), "admin_id": ADMIN_ID})
        print("  + 1 admin audit log entry")

        await db.commit()
        print("\nDatabase seeded successfully!")
        print(f"\nDev accounts (all phone-verified, KYC approved):")
        print(f"  Admin:    +962790000001")
        print(f"  Seller 1: +962790000002 (Ahmed)")
        print(f"  Seller 2: +962790000003 (Sara, Pro Seller)")
        print(f"  Buyer 1:  +962790000004 (Mohammed)")
        print(f"  Buyer 2:  +962790000005 (Layla)")
        print(f"  Mediator: +962790000006 (Khaled)")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
