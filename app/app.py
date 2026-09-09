# -*- coding: utf-8 -*-
"""
مصعب فون - موقع حجز آيفون 18
تطبيق ويب باستخدام Flask + SQLite
"""

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session, Response, abort
import psycopg2
import psycopg2.extras
import os
import json
import mimetypes
import qrcode
from datetime import datetime, timedelta
import re
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "musab-phone-super-secret-key-2026")  # غيّرها في الإنتاج

# ---------------------------------------------------------
# رابط الاتصال بقاعدة بيانات PostgreSQL (مثل Neon أو Supabase)
# يجب ضبط متغيّر البيئة DATABASE_URL قبل تشغيل الموقع، مثال:
#   postgresql://user:password@host/dbname?sslmode=require
# ---------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://neondb_owner:npg_x3a9ohjbCuKz@ep-odd-wind-aea2pu6n-pooler.c-2.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require")
if not DATABASE_URL:
    raise RuntimeError(
        "لم يتم ضبط متغيّر البيئة DATABASE_URL. أضف رابط قاعدة بيانات PostgreSQL "
        "(من Neon أو Supabase مثلاً) قبل تشغيل الموقع."
    )
# بعض المزوّدين (مثل Heroku القديم) يعطون رابطاً يبدأ بـ postgres:// بدل postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

QR_DIR = os.path.join(os.path.dirname(__file__), "static", "qrcodes")
PRODUCTS_IMG_DIR = os.path.join(os.path.dirname(__file__), "static", "img", "products")
os.makedirs(QR_DIR, exist_ok=True)
os.makedirs(PRODUCTS_IMG_DIR, exist_ok=True)

ALLOWED_IMAGE_EXT = {
    "png", "jpg", "jpeg", "jpe", "jfif", "webp", "gif", "bmp",
    "tif", "tiff", "heic", "heif", "avif", "svg", "ico",
}

# ---------------------------------------------------------
# إعداد موعد الحجز: بعد 11 يوماً من الآن الساعة 7:00 مساءً
# ---------------------------------------------------------
RESERVATION_DEADLINE = (datetime.now() + timedelta(days=7)).replace(
    hour=19, minute=0, second=0, microsecond=0
)

# ---------------------------------------------------------
# ===== إعدادات دخول لوحة التحكم (عدّل هذي القيم قبل النشر) =====
# لوحة التحكم مبنية بحيث تكون منفصلة تماماً عن الموقع العام:
# - لا يوجد أي رابط لها من الموقع الرئيسي
# - محمية باسم مستخدم + كلمة مرور
# - يمكن تشغيلها على استضافة/دومين فرعي منفصل تماماً عبر متغيّر البيئة:
#     ADMIN_ONLY=1   -> نسخة تحتوي فقط على مسارات لوحة التحكم /admin
#     PUBLIC_ONLY=1  -> نسخة تحتوي فقط على مسارات الموقع العام
#   شغّل النسختين على استضافتين منفصلتين (مثلاً admin.musabphone.com
#   و musabphone.com) مع الإشارة لنفس قاعدة البيانات (أو مزامنتها).
# ---------------------------------------------------------
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "musab2026"  # كلمة مرور لوحة التحكم (غيّرها قبل النشر)

ADMIN_ONLY = os.environ.get("ADMIN_ONLY") == "1"
PUBLIC_ONLY = os.environ.get("PUBLIC_ONLY") == "1"

# ---------------------------------------------------------
# ===== إعدادات التواصل =====
# ---------------------------------------------------------
COMPANY_NAME = "مصعب فون"
SALES_PHONE = "0922051000"        # رقم قسم المبيعات (نفس الرقم القديم)
MAINTENANCE_PHONE = "0942051000"  # رقم قسم الصيانة (نفس الرقم بس بادئة 094)
WHATSAPP_BUSINESS_NUMBER = "218922051000"

# روابط السوشيال ميديا - تيك توك مضبوط على الحساب الرسمي musab_phone
SOCIAL_LINKS = {
    "facebook": "https://www.facebook.com/share/19D2kWMAGM/?mibextid=wwXIfr",
    "tiktok": "https://www.tiktok.com/@musab_phone?_r=1&_t=ZS-99HlY1xk3SD",
    "instagram": "https://www.instagram.com/musab.phone?igsi=dTNwcTNwZjVlM2pl&utm_source=qr",
}

CURRENCY = "د.ل"
SHOW_PRICES = False
TOTAL_STOCK = 200

# ---------------------------------------------------------
# قاعدة البيانات
# ---------------------------------------------------------
class _ConnWrapper:
    """غلاف بسيط يجعل استخدام psycopg2 يشبه sqlite3 (conn.execute / fetchone / fetchall)."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        sql = sql.replace("?", "%s")
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql, params)
        return cur

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    return _ConnWrapper(conn)


def _column_exists(conn, table, column):
    row = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = ? AND column_name = ?",
        (table, column),
    ).fetchone()
    return row is not None


def init_db():
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reservations (
            id SERIAL PRIMARY KEY,
            full_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            email TEXT,
            city TEXT,
            model TEXT NOT NULL,
            color TEXT NOT NULL,
            storage TEXT NOT NULL,
            notes TEXT,
            custom_request TEXT,
            booking_ref TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    if not _column_exists(conn, "reservations", "custom_request"):
        conn.execute("ALTER TABLE reservations ADD COLUMN custom_request TEXT")
    if not _column_exists(conn, "reservations", "status"):
        conn.execute("ALTER TABLE reservations ADD COLUMN status TEXT DEFAULT 'pending'")
        conn.execute("UPDATE reservations SET status = 'pending' WHERE status IS NULL")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS categories (
            id SERIAL PRIMARY KEY,
            name_ar TEXT NOT NULL,
            name_en TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id SERIAL PRIMARY KEY,
            category_id INTEGER,
            name TEXT NOT NULL,
            description TEXT,
            price REAL DEFAULT 0,
            image TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY(category_id) REFERENCES categories(id)
        )
        """
    )
    # نخزّن بيانات الصورة نفسها داخل قاعدة البيانات (bytea) بدل القرص المحلي للسيرفر،
    # لأن استضافات مثل Render تمسح ملفات القرص المحلي مع كل عملية نشر جديدة (redeploy)،
    # بينما قاعدة بيانات Postgres (Neon) تبقى دائمة. هذا يمنع مشكلة صور 404 بعد كل تحديث للموقع.
    if not _column_exists(conn, "products", "image_data"):
        conn.execute("ALTER TABLE products ADD COLUMN image_data BYTEA")
    if not _column_exists(conn, "products", "image_mime"):
        conn.execute("ALTER TABLE products ADD COLUMN image_mime TEXT")
    conn.commit()

    count = conn.execute("SELECT COUNT(*) AS c FROM categories").fetchone()["c"]
    if count == 0:
        defaults = [
            ("هواتف آيفون", "iPhones"),
            ("أكفار وحمايات", "Cases & Protectors"),
            ("سماعات وإكسسوارات", "Headphones & Accessories"),
            ("شواحن وكابلات", "Chargers & Cables"),
        ]
        now = datetime.now().isoformat()
        for ar, en in defaults:
            conn.execute(
                "INSERT INTO categories (name_ar, name_en, created_at) VALUES (?, ?, ?)",
                (ar, en, now),
            )
        conn.commit()
    conn.close()


def get_reserved_count():
    conn = get_db()
    row = conn.execute("SELECT COUNT(*) AS c FROM reservations").fetchone()
    conn.close()
    return row["c"] if row else 0


def get_stock_status():
    reserved = get_reserved_count()
    remaining = max(TOTAL_STOCK - reserved, 0)
    percent = round((reserved / TOTAL_STOCK) * 100) if TOTAL_STOCK else 0
    percent = min(percent, 100)
    return {
        "total": TOTAL_STOCK,
        "reserved": reserved,
        "remaining": remaining,
        "percent": percent,
        "sold_out": remaining <= 0,
    }


# ---------------------------------------------------------
# الألوان الأربعة الرسمية لأجهزة آيفون 18 (أبيض / سماوي / أسود / بنفسجي)
# كل لون له مُعرّف ثابت (id) لا يتغيّر، واسم عربي وإنجليزي يُعرضان
# حسب لغة الموقع الحالية، مع صورة الهاتف ولون العينة (hex) الخاصين به.
# ---------------------------------------------------------
COLOR_DEFS = [
    {"id": "snow_white",  "ar": "أبيض تلجي",   "en": "Snow White",  "hex": "#eeeeee", "file": "phone-2.png"},
    {"id": "sky_blue",    "ar": "سماوي فاتح",  "en": "Sky Blue",    "hex": "#c1cde5", "file": "phone-4.jpg"},
    {"id": "space_black", "ar": "أسود فضائي",  "en": "Space Black", "hex": "#1c1c1e", "file": "phone-3.png"},
    {"id": "dark_purple", "ar": "بنفسجي داكن", "en": "Dark Purple", "hex": "#3e1c2e", "file": "phone-5.png"},
]

# ألوان طلب VIP الخاص (منفصلة عن الألوان الأربعة الرسمية أعلاه)
VIP_COLOR_DEFS = [
    {"id": "vip_gold24",       "ar": "طلاء ذهبي 24 قيراط",     "en": "24-Karat Gold Plating"},
    {"id": "vip_silver",       "ar": "طلاء فضي",                "en": "Silver Plating"},
    {"id": "vip_custom_design", "ar": "تصميم مخصص حسب الطلب",   "en": "Fully Custom Design"},
]

# قاموس موحّد لكل الألوان (الرسمية + VIP) بالمعرّف كمفتاح، يُستخدم للترجمة والعرض
COLOR_BY_ID = {c["id"]: c for c in COLOR_DEFS + VIP_COLOR_DEFS}


def color_display(color_id, lang="ar"):
    """يحوّل مُعرّف اللون إلى اسمه المترجم حسب اللغة. إن كان النص المخزَّن
    قديماً (نص عربي حر من نسخة سابقة) يُعاد كما هو دون تعديل."""
    c = COLOR_BY_ID.get(color_id)
    if c:
        return c.get(lang) or c.get("ar") or color_id
    return color_id


# ---------------------------------------------------------
# بيانات المنتج: كل موديل له مجموعة ألوان وسعات خاصة فيه
# (iPhone 11 له ألوانه الأصلية الخاصة، منفصلة عن ألوان 18)
# ---------------------------------------------------------
MODELS = [

    {
        "id": "iphone18",
        "name": "iPhone 18",
        "price": 0,
        "colors": [c["id"] for c in COLOR_DEFS],
        "storages": ["256GB", "512GB", "1TB", "2TB"],
        "is_vip": False,
    },
    {
        "id": "iphone18_pro",
        "name": "iPhone 18 Pro",
        "price": 0,
        "colors": [c["id"] for c in COLOR_DEFS],
        "storages": ["256GB", "512GB", "1TB", "2TB"],
        "is_vip": False,
    },
    {
        "id": "iphone18_pro_max",
        "name": "iPhone 18 Pro Max",
        "price": 0,
        "colors": [c["id"] for c in COLOR_DEFS],
        "storages": ["256GB", "512GB", "1TB", "2TB"],
        "is_vip": False,
    },
    {
        "id": "vip_custom",
        "name": "VIP - طلب خاص",
        "price": 0,
        "colors": [c["id"] for c in VIP_COLOR_DEFS],
        "storages": ["256GB", "512GB", "1TB", "2TB"],
        "is_vip": True,
    },
]

# ---------------------------------------------------------
# حالات الطلب (تُستخدم في لوحة التحكم لمتابعة كل حجز)
# ---------------------------------------------------------
ORDER_STATUSES = [
    {"id": "pending",    "label_ar": "قيد الانتظار",  "label_en": "Pending",    "color": "#f39c12", "icon": "⏳"},
    {"id": "processing", "label_ar": "قيد التجهيز",   "label_en": "Processing", "color": "#2f80ed", "icon": "⚙️"},
    {"id": "shipped",    "label_ar": "تم الشحن",      "label_en": "Shipped",    "color": "#8e44ad", "icon": "🚚"},
    {"id": "delivered",  "label_ar": "تم التسليم",    "label_en": "Delivered",  "color": "#27ae60", "icon": "✅"},
    {"id": "cancelled",  "label_ar": "ملغي",          "label_en": "Cancelled",  "color": "#c0392b", "icon": "✖️"},
]
ORDER_STATUS_MAP = {s["id"]: s for s in ORDER_STATUSES}
VALID_STATUS_IDS = {s["id"] for s in ORDER_STATUSES}


def status_info(status_id):
    return ORDER_STATUS_MAP.get(status_id, ORDER_STATUS_MAP["pending"])


def _normalize_color_text(s):
    return re.sub(r"\s+", " ", (s or "").strip())


def get_color_sales_counts():
    """يرجع عدد الحجوزات لكل لون حتى الآن (لعرض 'الأكثر مبيعاً')."""
    conn = get_db()
    rows = conn.execute(
        "SELECT color, COUNT(*) AS c FROM reservations GROUP BY color"
    ).fetchall()
    conn.close()
    return {row["color"]: row["c"] for row in rows}


def get_gallery_with_sales():
    """يبني قائمة الألوان الأربعة (مع صورها ومبيعاتها) لعرضها في قسم
    'اختر لونك المفضل' بالصفحة الرئيسية، مترجمة حسب لغة الموقع الحالية."""
    lang = get_lang()
    counts = get_color_sales_counts()
    gallery = []
    for c in COLOR_DEFS:
        # الحجوزات الجديدة تُخزَّن بمعرّف اللون (id)، والحجوزات القديمة قد تكون
        # مخزَّنة بنص عربي حر - نجمع الاثنين هنا لعرض عدد مبيعات صحيح
        count = counts.get(c["id"], 0)
        target_norm = _normalize_color_text(c["ar"])
        for raw_color, n in counts.items():
            if raw_color != c["id"] and _normalize_color_text(raw_color) == target_norm:
                count += n
        gallery.append({
            "id": c["id"],
            "color": c.get(lang) or c["ar"],
            "hex": c["hex"],
            "file": c["file"],
            "count": count,
        })
    max_count = max((g["count"] for g in gallery), default=0)
    for g in gallery:
        g["is_bestseller"] = max_count > 0 and g["count"] == max_count
    return gallery


def valid_phone(phone: str) -> bool:
    return bool(re.match(r"^\+?[0-9\s\-]{8,15}$", phone))


def model_by_id(model_id):
    return next((m for m in MODELS if m["id"] == model_id), None)


# ---------------------------------------------------------
# الترجمة: عربي / إنجليزي - نفس التصميم، فقط النصوص والاتجاه يتغيران
# ---------------------------------------------------------
TRANSLATIONS = {
    "ar": {
        "dir": "rtl", "html_lang": "ar",
        "nav_home": "الرئيسية", "nav_features": "المميزات", "nav_gallery": "الألوان",
        "nav_models": "المنتجات", "nav_growth": "الحجوزات", "nav_reserve": "الحجز",
        "nav_lookup": "استرجاع حجزي",
        "book_now": "احجز الآن",
        "hero_badge": "🚀 حجوزات مسبقة محدودة",
        "hero_title_pre": "احجز جهازك", "hero_title_high": "iPhone 18", "hero_title_post": "قبل أي أحد آخر",
        "hero_sub": "مصعب فون يقدّم لك فرصة الحجز المسبق لأحدث إصدار من آيفون بأفضل الأسعار وأولوية استلام فور توفر الجهاز.",
        "hero_cta1": "احجز جهازك الآن", "hero_cta2": "تصفح منتجات آبل الجديدة",
        "countdown_title": "⏳ ينتهي وقت الحجز خلال",
        "deadline_prefix": "الموعد النهائي:",
        "cd_day": "يوم", "cd_hour": "ساعة", "cd_min": "دقيقة", "cd_sec": "ثانية",
        "countdown_expired": "⏰ انتهى وقت استقبال الحجوزات",
        "stock_label": "🔥 الكمية المتاحة للحجز",
        "stock_remaining": "متبقي", "stock_of": "من", "stock_device": "جهاز",
        "stock_percent_note": "من الكمية تم حجزها",
        "stock_soldout": "نفدت الكمية بالكامل! الحجز مغلق الآن.",
        "growth_title": "نمو الحجوزات لحظة بلحظة", "growth_sub": "الخط يرتفع مباشرة مع كل عملية حجز جديدة",
        "growth_label": "📈 إجمالي الحجوزات حتى الآن",
        "features_title": "لماذا تحجز عبر مصعب فون؟", "features_sub": "نوفر لك تجربة حجز موثوقة وسريعة وآمنة",
        "f1_title": "أولوية الاستلام", "f1_desc": "كن من أوائل من يستلم جهاز آيفون 18 فور وصوله للمتجر.",
        "f2_title": "حجز آمن 100%", "f2_desc": "بياناتك محمية بالكامل، ولا يتم أي خصم مالي عند الحجز.",
        "f3_title": "دعم فوري", "f3_desc": "فريق مصعب فون جاهز للرد على استفساراتك في أي وقت.",
        "f4_title": "أفضل الأسعار", "f4_desc": "أسعار تنافسية وعروض حصرية للحاجزين الأوائل فقط.",
        "gallery_title": "اختر لونك المفضل", "gallery_sub": " متوفر بأربعة ألوان مميزة  IPHONE 18 PRO MAX - 18PRO",
        "gallery_sold_label": "حجز حتى الآن", "gallery_bestseller": "🏆 الأكثر مبيعاً",
        "brand_tagline": "رقم واحد في السوق الليبي لمنتجات Apple واكسسواراتها",
        "models_title": "اختر موديلك المفضل",
        "models_sub": "جميع الموديلات متاحة للحجز المسبق - لكل موديل ألوان وسعات خاصة به",
        "price_tbd": "السعر يُعلن قريباً 🔔", "popular_badge": "الأكثر طلباً",
        "book_this_model": "احجز هذا الموديل",
        "vip_title": "✨ طلب VIP خاص", "vip_sub": "صمّم جهازك بنفسك",
        "vip_desc": "عندك ذوق خاص؟ اطلب تصميماً حصرياً لجهازك مثل طلاء ذهبي عيار 24 قيراط أو أي تصميم آخر تحدده أنت، ويقوم فريقنا بتنفيذه لك.",
        "vip_cta": "اطلب تصميمك الخاص",
        "reserve_title": "نموذج الحجز", "reserve_sub": "عبّئ بياناتك وسيتواصل معك فريقنا لتأكيد الحجز",
        "label_name": "الاسم الكامل *", "label_phone": "رقم الجوال *", "label_email": "البريد الإلكتروني",
        "label_city": "المدينة", "label_model": "الموديل *", "label_color": "اللون *",
        "label_storage": "سعة التخزين *", "label_notes": "ملاحظات إضافية",
        "label_custom_request": "تفاصيل التصميم الخاص (VIP) *",
        "ph_name": "مثال: مصعب أحمد", "ph_phone": "09xxxxxxxx", "ph_email": "example@email.com",
        "ph_city": "مدينتك", "ph_choose_model": "اختر الموديل", "ph_choose_color": "اختر اللون",
        "ph_choose_storage": "اختر السعة", "ph_notes": "أي تفاصيل إضافية ترغب بإخبارنا بها",
        "ph_custom_request": "مثال: أريد طلاء ذهبي 24 قيراط بالكامل مع شعار مخصص...",
        "btn_confirm": "تأكيد الحجز",
        "footer_tagline": "وجهتك الأولى لحجز أحدث أجهزة آيفون بثقة وسهولة.",
        "footer_quicklinks": "روابط سريعة", "footer_contact": "تواصل معنا",
        "footer_maintenance": "قسم الصيانة", "footer_whatsapp": "تواصل واتساب",
        "footer_sales": "قسم المبيعات",
        "footer_rights": "© 2026 مصعب فون. جميع الحقوق محفوظة.",
        "theme_toggle": "الوضع الليلي",
        "lookup_title": "استرجاع الباركود عن طريق رقم الهاتف",
        "lookup_sub": "أدخل رقم جوالك المستخدَم بالحجز وستظهر لك كل حجوزاتك مع الباركود الخاص بكل حجز",
        "lookup_placeholder": "أدخل رقم جوالك", "lookup_btn": "بحث",
        "lookup_none": "لا توجد أي حجوزات مرتبطة بهذا الرقم.",
        "lookup_found": "تم العثور على الحجوزات التالية:",
        "lookup_view": "عرض الباركود", "lookup_ref": "رقم الحجز", "lookup_model": "الموديل",
        "lookup_date": "تاريخ الحجز",
    },
    "en": {
        "dir": "ltr", "html_lang": "en",
        "nav_home": "Home", "nav_features": "Features", "nav_gallery": "Colors",
        "nav_models": "Products", "nav_growth": "Bookings", "nav_reserve": "Reserve",
        "nav_lookup": "Find my booking",
        "book_now": "Book Now",
        "hero_badge": "🚀 Limited Pre-Orders",
        "hero_title_pre": "Reserve your", "hero_title_high": "iPhone 18", "hero_title_post": "before anyone else",
        "hero_sub": "Musab Phone gives you the chance to pre-order the newest iPhone at the best prices, with priority pickup as soon as it's available.",
        "hero_cta1": "Reserve now", "hero_cta2": "Browse Apple's new products",
        "countdown_title": "⏳ Booking closes in",
        "deadline_prefix": "Deadline:",
        "cd_day": "Days", "cd_hour": "Hours", "cd_min": "Min", "cd_sec": "Sec",
        "countdown_expired": "⏰ Booking window has closed",
        "stock_label": "🔥 Units available",
        "stock_remaining": "Remaining", "stock_of": "of", "stock_device": "units",
        "stock_percent_note": "of stock reserved",
        "stock_soldout": "Sold out! Booking is now closed.",
        "growth_title": "Live booking growth", "growth_sub": "The line rises instantly with every new booking",
        "growth_label": "📈 Total bookings so far",
        "features_title": "Why book with Musab Phone?", "features_sub": "A reliable, fast and secure booking experience",
        "f1_title": "Priority pickup", "f1_desc": "Be among the first to receive iPhone 18 as soon as it arrives.",
        "f2_title": "100% secure booking", "f2_desc": "Your data is fully protected, no charge is taken at booking time.",
        "f3_title": "Instant support", "f3_desc": "The Musab Phone team is ready to answer your questions anytime.",
        "f4_title": "Best prices", "f4_desc": "Competitive prices and exclusive offers for early bookers.",
        "gallery_title": "Pick your favorite color", "gallery_sub": "iPhone 18 comes in four stunning colors",
        "gallery_sold_label": "booked so far", "gallery_bestseller": "🏆 Best seller",
        "brand_tagline": "Libya's #1 destination for Apple products & accessories",
        "models_title": "Choose your model",
        "models_sub": "All models are open for pre-order - each model has its own colors and storage options",
        "price_tbd": "Price to be announced 🔔", "popular_badge": "Most popular",
        "book_this_model": "Book this model",
        "vip_title": "✨ VIP Custom Order", "vip_sub": "Design your own device",
        "vip_desc": "Have a unique taste? Request an exclusive design for your device, such as a 24-karat gold plating or any custom design you choose, and our team will make it happen.",
        "vip_cta": "Request your custom design",
        "reserve_title": "Booking form", "reserve_sub": "Fill in your details and our team will contact you to confirm the booking",
        "label_name": "Full name *", "label_phone": "Phone number *", "label_email": "Email",
        "label_city": "City", "label_model": "Model *", "label_color": "Color *",
        "label_storage": "Storage *", "label_notes": "Additional notes",
        "label_custom_request": "Custom (VIP) design details *",
        "ph_name": "e.g. Musab Ahmed", "ph_phone": "09xxxxxxxx", "ph_email": "example@email.com",
        "ph_city": "Your city", "ph_choose_model": "Choose a model", "ph_choose_color": "Choose a color",
        "ph_choose_storage": "Choose storage", "ph_notes": "Any extra details you'd like us to know",
        "ph_custom_request": "e.g. Full 24-karat gold plating with a custom logo...",
        "btn_confirm": "Confirm booking",
        "footer_tagline": "Your first destination to book the newest iPhones with trust and ease.",
        "footer_quicklinks": "Quick links", "footer_contact": "Contact us",
        "footer_maintenance": "Support line", "footer_whatsapp": "Chat on WhatsApp",
        "footer_sales": "Sales line",
        "footer_rights": "© 2026 Musab Phone. All rights reserved.",
        "theme_toggle": "Dark mode",
        "lookup_title": "Retrieve your barcode by phone number",
        "lookup_sub": "Enter the phone number used for your booking to see all your bookings and their barcodes",
        "lookup_placeholder": "Enter your phone number", "lookup_btn": "Search",
        "lookup_none": "No bookings were found for this number.",
        "lookup_found": "The following bookings were found:",
        "lookup_view": "View barcode", "lookup_ref": "Booking ref", "lookup_model": "Model",
        "lookup_date": "Booking date",
    },
}


def get_lang():
    lang = session.get("lang", "ar")
    return lang if lang in TRANSLATIONS else "ar"


@app.context_processor
def inject_lang_helpers():
    lang = get_lang()
    # color_name متاحة داخل القوالب لترجمة مُعرّف اللون المخزَّن في قاعدة
    # البيانات إلى اسمه بلغة الموقع الحالية، مثال: {{ color_name(r.color) }}
    return {"t": TRANSLATIONS[lang], "lang": lang, "color_name": lambda cid: color_display(cid, lang)}


@app.route("/lang/<code>")
def set_lang(code):
    if code in TRANSLATIONS:
        session["lang"] = code
    ref = request.referrer or url_for("index")
    return redirect(ref)


# ---------------------------------------------------------
# توليد رمز QR يحتوي بيانات الحجز الكاملة
# ---------------------------------------------------------
def generate_booking_qr(booking: dict) -> str:
    payload = {
        "الشركة": COMPANY_NAME,
        "رقم_الحجز": booking["booking_ref"],
        "الاسم": booking["full_name"],
        "الجوال": booking["phone"],
        "البريد": booking.get("email") or "-",
        "المدينة": booking.get("city") or "-",
        "الموديل": booking["model_name"],
        "اللون": color_display(booking["color"], "ar"),
        "السعة": booking["storage"],
        "تاريخ_الحجز": booking["created_at"],
    }
    qr_text = json.dumps(payload, ensure_ascii=False)

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=3,
    )
    qr.add_data(qr_text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0a2540", back_color="#ffffff")

    filename = f"{booking['booking_ref']}.png"
    filepath = os.path.join(QR_DIR, filename)
    img.save(filepath)
    return filename


def ensure_qr_exists(booking_row):
    """يعيد توليد صورة الباركود إن كانت غير موجودة (استخدام مسار الاسترجاع)."""
    filename = f"{booking_row['booking_ref']}.png"
    filepath = os.path.join(QR_DIR, filename)
    if not os.path.exists(filepath):
        model_name = next((m["name"] for m in MODELS if m["id"] == booking_row["model"]), booking_row["model"])
        generate_booking_qr(
            {
                "booking_ref": booking_row["booking_ref"],
                "full_name": booking_row["full_name"],
                "phone": booking_row["phone"],
                "email": booking_row["email"],
                "city": booking_row["city"],
                "model_name": model_name,
                "color": booking_row["color"],
                "storage": booking_row["storage"],
                "created_at": booking_row["created_at"],
            }
        )
    return filename


# ===========================================================
# مسارات الموقع العام
# ===========================================================
if not ADMIN_ONLY:

    @app.route("/", methods=["GET"])
    def index():
        conn = get_db()
        products = conn.execute(
            "SELECT p.*, c.name_ar AS cat_ar, c.name_en AS cat_en FROM products p "
            "LEFT JOIN categories c ON c.id = p.category_id WHERE p.active = 1 "
            "ORDER BY p.created_at DESC"
        ).fetchall()
        conn.close()

        # نسخة من الموديلات مُجهَّزة لجافاسكريبت: كل لون يصبح كائن
        # {id, name, file} بدل مجرّد نص، بحيث تُطابق الصورة الصحيحة دائماً
        # وتُترجم تلقائياً حسب لغة الموقع الحالية (عربي/إنجليزي).
        lang = get_lang()
        models_for_js = []
        for m in MODELS:
            mm = dict(m)
            mm["colors"] = [
                {
                    "id": cid,
                    "name": color_display(cid, lang),
                    "file": COLOR_BY_ID.get(cid, {}).get("file"),
                }
                for cid in m["colors"]
            ]
            models_for_js.append(mm)

        return render_template(
            "index.html",
            models=MODELS,
            models_json=models_for_js,
            gallery=get_gallery_with_sales(),
            deadline_iso=RESERVATION_DEADLINE.isoformat(),
            deadline_readable=RESERVATION_DEADLINE.strftime("%Y-%m-%d %I:%M %p"),
            stock=get_stock_status(),
            maintenance_phone=MAINTENANCE_PHONE,
            sales_phone=SALES_PHONE,
            whatsapp_number=WHATSAPP_BUSINESS_NUMBER,
            company_name=COMPANY_NAME,
            social_links=SOCIAL_LINKS,
            currency=CURRENCY,
            show_prices=SHOW_PRICES,
            products=products,
        )

    @app.route("/reserve", methods=["POST"])
    def reserve():
        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        city = request.form.get("city", "").strip()
        model = request.form.get("model", "").strip()
        color = request.form.get("color", "").strip()
        storage = request.form.get("storage", "").strip()
        notes = request.form.get("notes", "").strip()
        custom_request = request.form.get("custom_request", "").strip()

        stock = get_stock_status()
        m = model_by_id(model)
        is_ar = get_lang() == "ar"

        errors = []
        if stock["sold_out"]:
            errors.append("عذراً، نفدت كامل الكمية المتاحة للحجز." if is_ar else "Sorry, we are sold out.")
        if len(full_name) < 3:
            errors.append("الرجاء إدخال الاسم الكامل بشكل صحيح." if is_ar else "Please enter a valid full name.")
        if not valid_phone(phone):
            errors.append("رقم الجوال غير صالح." if is_ar else "Invalid phone number.")
        if not m:
            errors.append("الرجاء اختيار موديل الجهاز." if is_ar else "Please choose a device model.")
        if m and color not in m["colors"]:
            errors.append("الرجاء اختيار لون متاح لهذا الموديل." if is_ar else "Please choose a color available for this model.")
        if m and storage not in m["storages"]:
            errors.append("الرجاء اختيار سعة تخزين متاحة لهذا الموديل." if is_ar else "Please choose a storage option available for this model.")
        if m and m.get("is_vip") and len(custom_request) < 5:
            errors.append("الرجاء وصف تصميمك الخاص (VIP)." if is_ar else "Please describe your custom VIP design.")
        if datetime.now() > RESERVATION_DEADLINE:
            errors.append("عذراً، انتهى وقت استقبال الحجوزات." if is_ar else "Sorry, the booking window has closed.")

        if errors:
            for e in errors:
                flash(e, "error")
            return redirect(url_for("index") + "#reserve")

        created_at = datetime.now().isoformat()

        conn = get_db()
        cur = conn.execute(
            """INSERT INTO reservations
               (full_name, phone, email, city, model, color, storage, notes, custom_request, booking_ref, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
            (full_name, phone, email, city, model, color, storage, notes, custom_request, "", created_at),
        )
        new_id = cur.fetchone()["id"]
        booking_ref = f"MF-{new_id:05d}"
        conn.execute("UPDATE reservations SET booking_ref = ? WHERE id = ?", (booking_ref, new_id))
        conn.commit()
        conn.close()

        model_name = m["name"] if m else model

        generate_booking_qr(
            {
                "booking_ref": booking_ref,
                "full_name": full_name,
                "phone": phone,
                "email": email,
                "city": city,
                "model_name": model_name,
                "color": color,
                "storage": storage,
                "created_at": created_at,
            }
        )

        flash(
            ("تم استلام حجزك بنجاح! سيتم التواصل معك قريباً من فريق " + COMPANY_NAME + ".")
            if is_ar else "Your booking was received! Our team will contact you soon.",
            "success",
        )
        return redirect(url_for("thankyou", ref=booking_ref))

    @app.route("/thankyou")
    def thankyou():
        ref = request.args.get("ref", "")
        booking = None
        if ref:
            conn = get_db()
            row = conn.execute("SELECT * FROM reservations WHERE booking_ref = ?", (ref,)).fetchone()
            conn.close()
            if row:
                booking = dict(row)
                booking["model_name"] = next(
                    (m["name"] for m in MODELS if m["id"] == row["model"]), row["model"]
                )
                ensure_qr_exists(row)

        whatsapp_link = None
        if booking:
            wa_text = (
                f"مرحباً {COMPANY_NAME}، تم تأكيد حجزي ✅\n"
                f"رقم الحجز: {booking['booking_ref']}\n"
                f"الاسم: {booking['full_name']}\n"
                f"الموديل: {booking['model_name']} - {color_display(booking['color'], 'ar')} - {booking['storage']}\n"
                f"للاستفسار أو المبيعات: {SALES_PHONE}\n"
                f"للصيانة: {MAINTENANCE_PHONE}"
            )
            from urllib.parse import quote

            whatsapp_link = f"https://wa.me/{WHATSAPP_BUSINESS_NUMBER}?text={quote(wa_text)}"

        return render_template(
            "thankyou.html",
            deadline_iso=RESERVATION_DEADLINE.isoformat(),
            booking=booking,
            maintenance_phone=MAINTENANCE_PHONE,
            sales_phone=SALES_PHONE,
            whatsapp_link=whatsapp_link,
            company_name=COMPANY_NAME,
            social_links=SOCIAL_LINKS,
        )

    # -------------------------------------------------------
    # استرجاع/إعادة تصدير الباركود عن طريق رقم الهاتف
    # -------------------------------------------------------
    @app.route("/lookup", methods=["GET", "POST"])
    def lookup():
        results = []
        searched = False
        phone = ""
        if request.method == "POST":
            phone = request.form.get("phone", "").strip()
            searched = True
            if phone:
                digits = re.sub(r"\D", "", phone)
                conn = get_db()
                rows = conn.execute(
                    "SELECT * FROM reservations WHERE REPLACE(REPLACE(phone,' ',''),'-','') LIKE ? "
                    "ORDER BY created_at DESC",
                    (f"%{digits}%",),
                ).fetchall()
                conn.close()
                for row in rows:
                    ensure_qr_exists(row)
                    d = dict(row)
                    d["model_name"] = next((m["name"] for m in MODELS if m["id"] == row["model"]), row["model"])
                    results.append(d)

        return render_template(
            "lookup.html",
            results=results,
            searched=searched,
            phone=phone,
            social_links=SOCIAL_LINKS,
            company_name=COMPANY_NAME,
        )

    @app.route("/product-image/<int:prod_id>")
    def product_image(prod_id):
        # نقرأ الصورة من قاعدة البيانات مباشرة (لا من القرص المحلي) حتى تبقى ثابتة
        # ولا تختفي بعد كل عملية نشر جديدة (redeploy) على الاستضافة.
        conn = get_db()
        row = conn.execute(
            "SELECT image_data, image_mime FROM products WHERE id = ?", (prod_id,)
        ).fetchone()
        conn.close()
        if not row or not row["image_data"]:
            abort(404)
        data = bytes(row["image_data"])
        mime = row["image_mime"] or "image/jpeg"
        resp = Response(data, mimetype=mime)
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp

    @app.route("/api/stock")
    def api_stock():
        return jsonify(get_stock_status())

    @app.route("/api/deadline")
    def api_deadline():
        return jsonify({"deadline_iso": RESERVATION_DEADLINE.isoformat()})

    @app.route("/api/timeline")
    def api_timeline():
        conn = get_db()
        rows = conn.execute(
            "SELECT created_at FROM reservations ORDER BY created_at ASC"
        ).fetchall()
        conn.close()

        labels = []
        cumulative = []
        timestamps = []
        count = 0
        for row in rows:
            count += 1
            cumulative.append(count)
            labels.append(f"#{count}")
            timestamps.append(row["created_at"])

        return jsonify({"labels": labels, "values": cumulative, "timestamps": timestamps, "total": count})


# ===========================================================
# لوحة التحكم - منفصلة تماماً عن الموقع العام
# محمية باسم مستخدم + كلمة مرور، ولا يوجد أي رابط لها من الموقع
# ===========================================================
if not PUBLIC_ONLY:

    def admin_required():
        return session.get("is_admin") is True

    @app.route("/admin", methods=["GET", "POST"])
    def admin():
        if request.method == "POST":
            username = request.form.get("username", "")
            password = request.form.get("password", "")
            if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
                session["is_admin"] = True
            else:
                flash("بيانات الدخول غير صحيحة.", "error")
                return redirect(url_for("admin"))

        if not admin_required():
            return render_template("admin_login.html")

        conn = get_db()
        rows = conn.execute("SELECT * FROM reservations ORDER BY id DESC").fetchall()
        status_counts = {s["id"]: 0 for s in ORDER_STATUSES}
        for row in rows:
            st = row["status"] if row["status"] in VALID_STATUS_IDS else "pending"
            status_counts[st] = status_counts.get(st, 0) + 1
        conn.close()

        model_names = {m["id"]: m["name"] for m in MODELS}
        return render_template(
            "admin.html",
            reservations=rows,
            model_names=model_names,
            stock=get_stock_status(),
            active_tab="reservations",
            order_statuses=ORDER_STATUSES,
            status_counts=status_counts,
        )

    @app.route("/admin/logout")
    def admin_logout():
        session.pop("is_admin", None)
        return redirect(url_for("admin"))

    @app.route("/admin/delete/<int:res_id>", methods=["POST"])
    def admin_delete(res_id):
        if not admin_required():
            return redirect(url_for("admin"))
        conn = get_db()
        conn.execute("DELETE FROM reservations WHERE id = ?", (res_id,))
        conn.commit()
        conn.close()
        return redirect(url_for("admin"))

    @app.route("/admin/status/<int:res_id>", methods=["POST"])
    def admin_update_status(res_id):
        if not admin_required():
            if request.is_json or request.headers.get("X-Requested-With") == "fetch":
                return jsonify({"ok": False, "error": "unauthorized"}), 401
            return redirect(url_for("admin"))

        new_status = (request.form.get("status") or (request.get_json(silent=True) or {}).get("status") or "").strip()
        if new_status not in VALID_STATUS_IDS:
            if request.is_json or request.headers.get("X-Requested-With") == "fetch":
                return jsonify({"ok": False, "error": "invalid_status"}), 400
            flash("حالة غير صالحة.", "error")
            return redirect(url_for("admin"))

        conn = get_db()
        conn.execute("UPDATE reservations SET status = ? WHERE id = ?", (new_status, res_id))
        conn.commit()
        conn.close()

        if request.headers.get("X-Requested-With") == "fetch":
            info = status_info(new_status)
            return jsonify({"ok": True, "status": new_status, "label_ar": info["label_ar"], "color": info["color"], "icon": info["icon"]})

        return redirect(url_for("admin"))

    # -------------------------------------------------------
    # إدارة الأقسام والمنتجات (هواتف، أكفار، إكسسوارات...)
    # -------------------------------------------------------
    @app.route("/admin/catalog")
    def admin_catalog():
        if not admin_required():
            return redirect(url_for("admin"))
        conn = get_db()
        categories = conn.execute("SELECT * FROM categories ORDER BY name_ar").fetchall()
        products = conn.execute(
            "SELECT p.*, c.name_ar AS cat_ar FROM products p "
            "LEFT JOIN categories c ON c.id = p.category_id ORDER BY p.created_at DESC"
        ).fetchall()
        conn.close()
        return render_template(
            "admin.html",
            categories=categories,
            products=products,
            stock=get_stock_status(),
            active_tab="catalog",
        )

    @app.route("/admin/categories/add", methods=["POST"])
    def admin_add_category():
        if not admin_required():
            return redirect(url_for("admin"))
        name_ar = request.form.get("name_ar", "").strip()
        name_en = request.form.get("name_en", "").strip()
        if name_ar:
            conn = get_db()
            conn.execute(
                "INSERT INTO categories (name_ar, name_en, created_at) VALUES (?, ?, ?)",
                (name_ar, name_en, datetime.now().isoformat()),
            )
            conn.commit()
            conn.close()
            flash("تمت إضافة القسم.", "success")
        return redirect(url_for("admin_catalog"))

    @app.route("/admin/categories/delete/<int:cat_id>", methods=["POST"])
    def admin_delete_category(cat_id):
        if not admin_required():
            return redirect(url_for("admin"))
        conn = get_db()
        conn.execute("DELETE FROM categories WHERE id = ?", (cat_id,))
        conn.commit()
        conn.close()
        return redirect(url_for("admin_catalog"))

    @app.route("/admin/products/add", methods=["POST"])
    def admin_add_product():
        if not admin_required():
            return redirect(url_for("admin"))
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        price = request.form.get("price", "0").strip() or "0"
        category_id = request.form.get("category_id") or None
        category_id = int(category_id) if category_id else None
        image_filename = None
        image_bytes = None
        image_mime = None

        file = request.files.get("image")
        if file and file.filename:
            ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
            if ext in ALLOWED_IMAGE_EXT:
                raw = file.read()
                if len(raw) > 8 * 1024 * 1024:
                    flash("حجم الصورة كبير جداً (الحد الأقصى 8 ميجابايت).", "error")
                else:
                    image_filename = secure_filename(file.filename)
                    image_bytes = psycopg2.Binary(raw)
                    image_mime = file.mimetype or mimetypes.guess_type(image_filename)[0] or "image/jpeg"
            else:
                flash("صيغة الصورة غير مدعومة.", "error")

        if name:
            conn = get_db()
            conn.execute(
                """INSERT INTO products (category_id, name, description, price, image, image_data, image_mime, active, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                (category_id, name, description, float(price or 0), image_filename, image_bytes, image_mime, datetime.now().isoformat()),
            )
            conn.commit()
            conn.close()
            flash("تمت إضافة المنتج.", "success")
        return redirect(url_for("admin_catalog"))

    @app.route("/admin/products/delete/<int:prod_id>", methods=["POST"])
    def admin_delete_product(prod_id):
        if not admin_required():
            return redirect(url_for("admin"))
        conn = get_db()
        conn.execute("DELETE FROM products WHERE id = ?", (prod_id,))
        conn.commit()
        conn.close()
        return redirect(url_for("admin_catalog"))

    @app.route("/admin/products/toggle/<int:prod_id>", methods=["POST"])
    def admin_toggle_product(prod_id):
        if not admin_required():
            return redirect(url_for("admin"))
        conn = get_db()
        row = conn.execute("SELECT active FROM products WHERE id = ?", (prod_id,)).fetchone()
        if row is not None:
            conn.execute("UPDATE products SET active = ? WHERE id = ?", (0 if row["active"] else 1, prod_id))
            conn.commit()
        conn.close()
        return redirect(url_for("admin_catalog"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="0.0.0.0", port=5000)
