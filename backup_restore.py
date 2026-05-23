"""
backup_restore.py — Kino Bot uchun avtomatik backup va merge-restore tizimi
==========================================================================

Backup:
  - Barcha jadvallarni alohida JSON fayllar sifatida eksport qiladi
  - ZIP arxivga joylaydi va admin'ga Telegram orqali yuboradi
  - Haftalik avtomatik + /backup buyrug'i bilan qo'lda ishlatiladi

Restore (merge rejimi):
  - Mavjud ma'lumotlarni saqlab qoladi
  - Backup'dagi faqat yangi (bazada yo'q) ma'lumotlarni qo'shadi
  - Kalit asosida: user_id, movie code, (user_id, movie_code) va boshqalar
"""

import os
import io
import json
import zipfile
import logging
from datetime import datetime

import db

logger = logging.getLogger(__name__)

BACKUP_DIR = "backups"


# ─── EKSPORT ─────────────────────────────────────────────────────────────────

def _rows_to_list(rows) -> list[dict]:
    """sqlite3.Row ro'yxatini dict ro'yxatiga o'giradi."""
    return [dict(r) for r in rows]


def export_all() -> dict[str, list[dict]]:
    """
    Barcha jadvallarni dict ko'rinishida qaytaradi.
    Kalit — fayl nomi (jadval nomi), qiymat — qatorlar ro'yxati.
    """
    data: dict[str, list[dict]] = {}

    with db.get_conn() as conn:
        tables = [
            "users",
            "movies",
            "subscriptions",
            "admins",
            "settings",
            "promo_codes",
            "promo_uses",
            "favorites",
            "movie_ratings",
            "user_watch_history",
            "movie_code_counter",
            "bot_version",
            "pending_payments",
            "offers",
            "admin_requests",
        ]
        for table in tables:
            try:
                rows = conn.execute(f"SELECT * FROM {table}").fetchall()
                data[table] = _rows_to_list(rows)
            except Exception as e:
                logger.warning(f"Jadval eksport qilinmadi [{table}]: {e}")
                data[table] = []

    return data


def create_backup_zip() -> bytes:
    """
    Barcha jadvallarni alohida JSON fayllar sifatida ZIP arxivga joylashtiradi.
    ZIP fayli xotirada (bytes) saqlanadi — diskka yozilmaydi.
    """
    all_data = export_all()
    meta = {
        "created_at": datetime.now().isoformat(),
        "version": "1.2.9",
        "tables": list(all_data.keys()),
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Metadata
        zf.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))

        # Har bir jadval alohida fayl
        for table_name, rows in all_data.items():
            content = json.dumps(rows, ensure_ascii=False, indent=2, default=str)
            zf.writestr(f"{table_name}.json", content)

    buf.seek(0)
    return buf.read()


# ─── RESTORE (MERGE REJIMI) ──────────────────────────────────────────────────

def _load_zip(zip_bytes: bytes) -> dict[str, list[dict]]:
    """ZIP baytlardan JSON fayllarni o'qib dict qaytaradi."""
    data: dict[str, list[dict]] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            if name == "meta.json" or not name.endswith(".json"):
                continue
            table = name.replace(".json", "")
            try:
                content = zf.read(name).decode("utf-8")
                data[table] = json.loads(content)
            except Exception as e:
                logger.warning(f"ZIP ichidagi fayl o'qilmadi [{name}]: {e}")
    return data


def merge_restore(zip_bytes: bytes) -> dict[str, int]:
    """
    ZIP fayldagi backup'ni mavjud baza bilan merge qiladi.
    Mavjud ma'lumotlar o'ZGARTIRILMAYDI — faqat yangilari qo'shiladi.

    Qaytaradi: {jadval_nomi: qo'shilgan_qatorlar_soni}
    """
    backup = _load_zip(zip_bytes)
    stats: dict[str, int] = {}

    with db.get_conn() as conn:

        # ── users ─────────────────────────────────────────────────────────────
        added = 0
        for row in backup.get("users", []):
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO users
                       (id, username, full_name, join_date, is_blocked, failed_sends)
                       VALUES (:id, :username, :full_name, :join_date, :is_blocked, :failed_sends)""",
                    row,
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    added += 1
            except Exception as e:
                logger.warning(f"users merge xato: {e} | {row}")
        stats["users"] = added

        # ── movies ────────────────────────────────────────────────────────────
        added = 0
        for row in backup.get("movies", []):
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO movies
                       (code, name, description, quality, year, language, rating, file_id,
                        request_count, added_date)
                       VALUES (:code, :name, :description, :quality, :year, :language,
                               :rating, :file_id, :request_count, :added_date)""",
                    row,
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    added += 1
            except Exception as e:
                logger.warning(f"movies merge xato: {e} | {row}")
        stats["movies"] = added

        # movie_code_counter ni sinxronlash (MAX qiymatni olish)
        try:
            row_max = conn.execute(
                "SELECT MAX(CAST(code AS INTEGER)) as mx FROM movies"
            ).fetchone()
            if row_max and row_max["mx"]:
                conn.execute(
                    "UPDATE movie_code_counter SET last_code = MAX(last_code, ?) WHERE id=1",
                    (row_max["mx"],),
                )
        except Exception as e:
            logger.warning(f"movie_code_counter yangilanmadi: {e}")

        # ── subscriptions ─────────────────────────────────────────────────────
        added = 0
        for row in backup.get("subscriptions", []):
            try:
                # (user_id, start_date, end_date) unique bo'ladi
                exists = conn.execute(
                    """SELECT id FROM subscriptions
                       WHERE user_id=? AND start_date=? AND end_date=?""",
                    (row["user_id"], row["start_date"], row["end_date"]),
                ).fetchone()
                if not exists:
                    conn.execute(
                        """INSERT INTO subscriptions (user_id, start_date, end_date, months)
                           VALUES (:user_id, :start_date, :end_date, :months)""",
                        row,
                    )
                    added += 1
            except Exception as e:
                logger.warning(f"subscriptions merge xato: {e} | {row}")
        stats["subscriptions"] = added

        # ── admins ────────────────────────────────────────────────────────────
        added = 0
        for row in backup.get("admins", []):
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO admins (user_id, added_date) VALUES (:user_id, :added_date)",
                    row,
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    added += 1
            except Exception as e:
                logger.warning(f"admins merge xato: {e} | {row}")
        stats["admins"] = added

        # ── settings ──────────────────────────────────────────────────────────
        # Mavjud sozlamalarni o'zgartirmaymiz — faqat yo'qlarini qo'shamiz
        added = 0
        for row in backup.get("settings", []):
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO settings (key, value) VALUES (:key, :value)",
                    row,
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    added += 1
            except Exception as e:
                logger.warning(f"settings merge xato: {e} | {row}")
        stats["settings"] = added

        # ── promo_codes ───────────────────────────────────────────────────────
        # Eski promo ID'larini qayta mapping uchun saqlaymiz
        promo_id_map: dict[int, int] = {}  # old_id -> new_id
        added = 0
        for row in backup.get("promo_codes", []):
            old_id = row.get("id")
            try:
                exists = conn.execute(
                    "SELECT id FROM promo_codes WHERE code=?", (row["code"],)
                ).fetchone()
                if exists:
                    promo_id_map[old_id] = exists["id"]
                else:
                    cur = conn.execute(
                        """INSERT INTO promo_codes
                           (code, discount_type, discount_value, duration_days,
                            max_uses, used_count, is_active, created_at)
                           VALUES (:code, :discount_type, :discount_value, :duration_days,
                                   :max_uses, :used_count, :is_active, :created_at)""",
                        row,
                    )
                    promo_id_map[old_id] = cur.lastrowid
                    added += 1
            except Exception as e:
                logger.warning(f"promo_codes merge xato: {e} | {row}")
        stats["promo_codes"] = added

        # ── promo_uses ────────────────────────────────────────────────────────
        added = 0
        for row in backup.get("promo_uses", []):
            old_promo_id = row.get("promo_id")
            new_promo_id = promo_id_map.get(old_promo_id, old_promo_id)
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO promo_uses (promo_id, user_id, used_at)
                       VALUES (?, :user_id, :used_at)""",
                    (new_promo_id, row["user_id"], row.get("used_at")),
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    added += 1
            except Exception as e:
                logger.warning(f"promo_uses merge xato: {e} | {row}")
        stats["promo_uses"] = added

        # ── favorites ─────────────────────────────────────────────────────────
        added = 0
        for row in backup.get("favorites", []):
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO favorites (user_id, movie_code, added_at)
                       VALUES (:user_id, :movie_code, :added_at)""",
                    row,
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    added += 1
            except Exception as e:
                logger.warning(f"favorites merge xato: {e} | {row}")
        stats["favorites"] = added

        # ── movie_ratings ─────────────────────────────────────────────────────
        added = 0
        for row in backup.get("movie_ratings", []):
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO movie_ratings (user_id, movie_code, rating, rated_at)
                       VALUES (:user_id, :movie_code, :rating, :rated_at)""",
                    row,
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    added += 1
            except Exception as e:
                logger.warning(f"movie_ratings merge xato: {e} | {row}")
        stats["movie_ratings"] = added

        # ── user_watch_history ────────────────────────────────────────────────
        # (user_id, movie_code, watched_at) kombinatsiyasini takrorlamaymiz
        added = 0
        for row in backup.get("user_watch_history", []):
            try:
                exists = conn.execute(
                    """SELECT id FROM user_watch_history
                       WHERE user_id=? AND movie_code=? AND watched_at=?""",
                    (row["user_id"], row["movie_code"], row.get("watched_at")),
                ).fetchone()
                if not exists:
                    conn.execute(
                        """INSERT INTO user_watch_history (user_id, movie_code, watched_at)
                           VALUES (:user_id, :movie_code, :watched_at)""",
                        row,
                    )
                    added += 1
            except Exception as e:
                logger.warning(f"user_watch_history merge xato: {e} | {row}")
        stats["user_watch_history"] = added

        # ── bot_version ───────────────────────────────────────────────────────
        # Joriy versiyani saqlab qolamiz — restore qilib yozmaymiz
        stats["bot_version"] = 0

        # ── pending_payments ──────────────────────────────────────────────────
        # Faqat yangi paymentlarni qo'shamiz (user_id + created_at asosida)
        added = 0
        for row in backup.get("pending_payments", []):
            try:
                exists = conn.execute(
                    """SELECT id FROM pending_payments
                       WHERE user_id=? AND created_at=?""",
                    (row["user_id"], row.get("created_at")),
                ).fetchone()
                if not exists:
                    conn.execute(
                        """INSERT INTO pending_payments
                           (user_id, username, full_name, months, amount,
                            check_file_id, check_type, status, created_at)
                           VALUES (:user_id, :username, :full_name, :months, :amount,
                                   :check_file_id, :check_type, :status, :created_at)""",
                        row,
                    )
                    added += 1
            except Exception as e:
                logger.warning(f"pending_payments merge xato: {e} | {row}")
        stats["pending_payments"] = added

        # ── offers ────────────────────────────────────────────────────────────
        added = 0
        for row in backup.get("offers", []):
            try:
                exists = conn.execute(
                    "SELECT id FROM offers WHERE user_id=? AND created_at=?",
                    (row["user_id"], row.get("created_at")),
                ).fetchone()
                if not exists:
                    conn.execute(
                        """INSERT INTO offers (user_id, username, full_name, message, created_at)
                           VALUES (:user_id, :username, :full_name, :message, :created_at)""",
                        row,
                    )
                    added += 1
            except Exception as e:
                logger.warning(f"offers merge xato: {e} | {row}")
        stats["offers"] = added

        # ── admin_requests ────────────────────────────────────────────────────
        added = 0
        for row in backup.get("admin_requests", []):
            try:
                exists = conn.execute(
                    "SELECT id FROM admin_requests WHERE user_id=? AND created_at=?",
                    (row["user_id"], row.get("created_at")),
                ).fetchone()
                if not exists:
                    conn.execute(
                        """INSERT INTO admin_requests
                           (user_id, username, full_name, message, status, handled_by, created_at)
                           VALUES (:user_id, :username, :full_name, :message,
                                   :status, :handled_by, :created_at)""",
                        row,
                    )
                    added += 1
            except Exception as e:
                logger.warning(f"admin_requests merge xato: {e} | {row}")
        stats["admin_requests"] = added

    return stats


# ─── YORDAMCHI: XABAR MATNI ──────────────────────────────────────────────────

def backup_filename() -> str:
    now = datetime.now().strftime("%Y-%m-%d_%H-%M")
    return f"kino_bot_backup_{now}.zip"


def restore_stats_text(stats: dict[str, int]) -> str:
    lines = ["📦 <b>Restore yakunlandi (merge rejimi)</b>\n"]
    total = 0
    for table, count in stats.items():
        if count > 0:
            lines.append(f"  ✅ <b>{table}</b>: +{count} ta yangi qator")
        else:
            lines.append(f"  ✔️ {table}: o'zgartirish yo'q")
        total += count
    lines.append(f"\n🔢 Jami qo'shildi: <b>{total}</b> ta qator")
    lines.append("⚠️ Mavjud ma'lumotlar o'zgartirilmadi.")
    return "\n".join(lines)
