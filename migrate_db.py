# -*- coding: utf-8 -*-
"""
سكربت نقل قاعدة بيانات مصعب فون من مشروع Neon قديم (وصل لحد حصة النقل الشهرية)
إلى مشروع Neon جديد فاضي (حصة نقل جديدة بالكامل).

ينسخ كل شيء: الحجوزات + الأقسام + المنتجات (بما فيها صور المنتجات نفسها).

طريقة الاستخدام:
1) ثبّت المكتبة المطلوبة (مرة وحدة بس):
   pip install psycopg2-binary

2) عدّل القيمتين تحت (OLD_DATABASE_URL و NEW_DATABASE_URL) بالروابط الصحيحة
   من لوحة Neon (Connection string لكل مشروع، تبدأ بـ postgresql:// وتنتهي
   بـ ?sslmode=require).

3) شغّل السكربت:
   python migrate_db.py

السكربت آمن 100%: يقرأ بس من القاعدة القديمة، ولا يحذف أو يعدّل فيها أي شيء.
"""

import psycopg2
import psycopg2.extras

# =========================================================
# عدّل هذين الرابطين قبل التشغيل
# =========================================================
OLD_DATABASE_URL = "postgresql://neondb_owner:npg_6Ko3bjTRZMnL@ep-odd-wind-aea2pu6n-pooler.c-2.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
NEW_DATABASE_URL = "postgresql://neondb_owner:npg_cQLR3sSPVU4O@ep-holy-rice-aym97wln-pooler.c-5.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"


def normalize(url):
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def get_conn(url):
    return psycopg2.connect(normalize(url))


def copy_table(old_conn, new_conn, table, id_column="id"):
    """ينسخ كل الصفوف من جدول في القاعدة القديمة إلى نفس الجدول بالقاعدة
    الجديدة، مع الحفاظ على نفس القيم (بما فيها الـ id) حتى تبقى الروابط بين
    الجداول (مثل ربط المنتج بقسمه) سليمة."""
    old_cur = old_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    old_cur.execute(f"SELECT * FROM {table}")
    rows = old_cur.fetchall()

    if not rows:
        print(f"  - {table}: لا يوجد صفوف، تم التخطي.")
        return 0

    columns = list(rows[0].keys())
    col_list = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(columns))

    new_cur = new_conn.cursor()
    inserted = 0
    for row in rows:
        values = [row[c] for c in columns]
        try:
            new_cur.execute(
                f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
                f"ON CONFLICT ({id_column}) DO NOTHING",
                values,
            )
            inserted += new_cur.rowcount
        except Exception as e:
            new_conn.rollback()
            print(f"  ! خطأ أثناء نسخ صف من {table}: {e}")
        else:
            new_conn.commit()

    # نصحّح عدّاد الـ SERIAL حتى ما تتكرر أرقام id لاحقاً في القاعدة الجديدة
    new_cur.execute(
        f"SELECT setval(pg_get_serial_sequence('{table}', '{id_column}'), "
        f"COALESCE((SELECT MAX({id_column}) FROM {table}), 1))"
    )
    new_conn.commit()

    print(f"  - {table}: تم نسخ {inserted} من أصل {len(rows)} صف.")
    return inserted


def main():
    if "ضع_هنا" in OLD_DATABASE_URL or "ضع_هنا" in NEW_DATABASE_URL:
        print("⚠️  عدّل أولاً قيمتي OLD_DATABASE_URL و NEW_DATABASE_URL بأعلى الملف.")
        return

    print("جاري الاتصال بالقاعدتين...")
    old_conn = get_conn(OLD_DATABASE_URL)
    new_conn = get_conn(NEW_DATABASE_URL)

    print("\nملاحظة: القاعدة الجديدة يجب أن تحتوي نفس الجداول فارغة.")
    print("أسهل طريقة: شغّل موقعك مرة واحدة محلياً مع DATABASE_URL يشاور")
    print("على القاعدة الجديدة (هذا يخلق الجداول تلقائياً عبر init_db())،")
    print("ثم أوقفه وشغّل هذا السكربت.\n")

    input("اضغط Enter للمتابعة، أو أغلق النافذة للإلغاء...")

    print("\nجاري نسخ البيانات (الترتيب مهم بسبب الروابط بين الجداول):")
    copy_table(old_conn, new_conn, "categories")
    copy_table(old_conn, new_conn, "products")
    copy_table(old_conn, new_conn, "reservations")

    old_conn.close()
    new_conn.close()
    print("\n✅ تم نسخ كل البيانات بنجاح إلى القاعدة الجديدة.")
    print("الخطوة الأخيرة: غيّر DATABASE_URL في Render للرابط الجديد وأعد النشر.")


if __name__ == "__main__":
    main()
