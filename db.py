import sqlite3
import os
from datetime import datetime, timedelta
from contextlib import contextmanager

DB_PATH = "kino_bot.db"

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS movies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                description TEXT,
                quality TEXT,
                year TEXT,
                language TEXT,
                rating TEXT,
                file_id TEXT NOT NULL,
                request_count INTEGER DEFAULT 0,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_blocked INTEGER DEFAULT 0,
                failed_sends INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                start_date TIMESTAMP NOT NULL,
                end_date TIMESTAMP NOT NULL,
                months INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS pending_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT,
                months INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                check_file_id TEXT,
                check_type TEXT,
                status TEXT DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS movie_code_counter (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                last_code INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS promo_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT UNIQUE NOT NULL,
                discount_type TEXT NOT NULL,
                discount_value INTEGER NOT NULL,
                duration_days INTEGER DEFAULT 0,
                max_uses INTEGER DEFAULT 0,
                used_count INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS promo_uses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                promo_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(promo_id, user_id),
                FOREIGN KEY (promo_id) REFERENCES promo_codes(id)
            );
            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                movie_code TEXT NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, movie_code)
            );
            CREATE TABLE IF NOT EXISTS movie_ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                movie_code TEXT NOT NULL,
                rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
                rated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, movie_code)
            );
            CREATE TABLE IF NOT EXISTS user_watch_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                movie_code TEXT NOT NULL,
                watched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT,
                message TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS admin_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                full_name TEXT,
                message TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                handled_by INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS bot_version (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                version TEXT DEFAULT '1.2.9',
                changelog TEXT DEFAULT '',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

        # Migrations
        migrations = [
            "ALTER TABLE movies ADD COLUMN request_count INTEGER DEFAULT 0",
        ]
        for m in migrations:
            try:
                conn.execute(m)
            except Exception:
                pass

        # movie_code_counter boshlang'ich qiymati
        conn.execute("INSERT OR IGNORE INTO movie_code_counter (id, last_code) VALUES (1, 0)")

        # Agar eski bazada kinolar bo'lsa, counter ni sinxronlaymiz
        row = conn.execute(
            "SELECT MAX(CAST(code AS INTEGER)) as mx FROM movies"
        ).fetchone()
        if row and row["mx"]:
            conn.execute(
                "UPDATE movie_code_counter SET last_code = MAX(last_code, ?) WHERE id = 1",
                (row["mx"],)
            )

        # Bot versiyasi
        conn.execute("INSERT OR IGNORE INTO bot_version (id, version, changelog) VALUES (1, '1.2.9', '')")

        # Default settings
        defaults = {
            "monthly_price": "50000",
            "card_number": "9800000000001234",
            "card_owner": "SOLEJON ADASHOV ISROILOVICH",
        }
        for k, v in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v)
            )

# ─── SETTINGS ────────────────────────────────────────────────────────────────

def get_setting(key: str) -> str | None:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
        )

# ─── ADMINS ──────────────────────────────────────────────────────────────────

def add_admin(user_id: int):
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,)
        )

def remove_admin(user_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM admins WHERE user_id=?", (user_id,))

def get_admins() -> list[int]:
    with get_conn() as conn:
        rows = conn.execute("SELECT user_id FROM admins").fetchall()
        return [r["user_id"] for r in rows]

def is_admin(user_id: int, main_admin: int) -> bool:
    if user_id == main_admin:
        return True
    return user_id in get_admins()

# ─── USERS ───────────────────────────────────────────────────────────────────

def upsert_user(user_id: int, username: str | None, full_name: str) -> bool:
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM users WHERE id=?", (user_id,)
        ).fetchone()
        conn.execute(
            """INSERT INTO users (id, username, full_name)
               VALUES (?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   username=excluded.username,
                   full_name=excluded.full_name""",
            (user_id, username, full_name),
        )
        return existing is None

def get_user(user_id: int):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

def get_all_users() -> list:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM users").fetchall()

def get_total_users() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]

def mark_blocked(user_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE users SET is_blocked=1 WHERE id=?", (user_id,))

def unblock_user(user_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE users SET is_blocked=0, failed_sends=0 WHERE id=?", (user_id,))

def increment_failed(user_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET failed_sends = failed_sends + 1 WHERE id=?", (user_id,)
        )
        row = conn.execute(
            "SELECT failed_sends FROM users WHERE id=?", (user_id,)
        ).fetchone()
        if row and row["failed_sends"] >= 2:
            conn.execute("UPDATE users SET is_blocked=1 WHERE id=?", (user_id,))

def reset_failed(user_id: int):
    with get_conn() as conn:
        conn.execute("UPDATE users SET failed_sends=0 WHERE id=?", (user_id,))

# ─── SUBSCRIPTIONS ───────────────────────────────────────────────────────────

def add_subscription(user_id: int, months: int):
    now = datetime.now()
    with get_conn() as conn:
        active = conn.execute(
            "SELECT end_date FROM subscriptions WHERE user_id=? AND end_date > ? ORDER BY end_date DESC LIMIT 1",
            (user_id, now.isoformat()),
        ).fetchone()
        if active:
            start = now
            end = datetime.fromisoformat(active["end_date"]) + timedelta(days=30 * months)
        else:
            start = now
            end = now + timedelta(days=30 * months)
        conn.execute(
            "INSERT INTO subscriptions (user_id, start_date, end_date, months) VALUES (?, ?, ?, ?)",
            (user_id, start.isoformat(), end.isoformat(), months),
        )

def has_active_subscription(user_id: int) -> bool:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM subscriptions WHERE user_id=? AND end_date > ?",
            (user_id, now),
        ).fetchone()
        return row is not None

def get_subscription_end(user_id: int) -> datetime | None:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT end_date FROM subscriptions WHERE user_id=? AND end_date > ? ORDER BY end_date DESC LIMIT 1",
            (user_id, now),
        ).fetchone()
        return datetime.fromisoformat(row["end_date"]) if row else None

def get_subscription_history(user_id: int) -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM subscriptions WHERE user_id=? ORDER BY start_date DESC",
            (user_id,)
        ).fetchall()

def extend_subscription(user_id: int, months: int):
    """Obunani uzaytirish (admin tomonidan)"""
    add_subscription(user_id, months)

def reduce_subscription(user_id: int, days: int):
    """Obunani qisqartirish (admin tomonidan)"""
    now = datetime.now()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, end_date FROM subscriptions WHERE user_id=? AND end_date > ? ORDER BY end_date DESC LIMIT 1",
            (user_id, now.isoformat())
        ).fetchone()
        if row:
            new_end = datetime.fromisoformat(row["end_date"]) - timedelta(days=days)
            if new_end < now:
                new_end = now
            conn.execute(
                "UPDATE subscriptions SET end_date=? WHERE id=?",
                (new_end.isoformat(), row["id"])
            )

# ─── MOVIES ──────────────────────────────────────────────────────────────────

def add_movie(code: str, name: str, description: str, quality: str,
              year: str, language: str, rating: str, file_id: str):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO movies (code, name, description, quality, year, language, rating, file_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (code, name, description, quality, year, language, rating, file_id),
        )

def get_movie_by_code(code: str):
    with get_conn() as conn:
        return conn.execute("SELECT * FROM movies WHERE code=?", (code,)).fetchone()

def search_movies_by_name(name: str) -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM movies WHERE name LIKE ?", (f"%{name}%",)
        ).fetchall()

def delete_movie(code: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM movies WHERE code=?", (code,))
        return cur.rowcount > 0

def get_all_movies() -> list:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM movies ORDER BY id DESC").fetchall()

def get_next_movie_code() -> str:
    with get_conn() as conn:
        conn.execute(
            "UPDATE movie_code_counter SET last_code = last_code + 1 WHERE id = 1"
        )
        row = conn.execute(
            "SELECT last_code FROM movie_code_counter WHERE id = 1"
        ).fetchone()
        return str(row["last_code"])

def increment_movie_requests(code: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE movies SET request_count = COALESCE(request_count, 0) + 1 WHERE code=?",
            (code,)
        )

def get_top_movies(limit: int = 10) -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM movies ORDER BY request_count DESC LIMIT ?", (limit,)
        ).fetchall()

# ─── MOVIE RATINGS ───────────────────────────────────────────────────────────

def rate_movie(user_id: int, movie_code: str, rating: int):
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO movie_ratings (user_id, movie_code, rating)
               VALUES (?, ?, ?)
               ON CONFLICT(user_id, movie_code) DO UPDATE SET rating=excluded.rating, rated_at=CURRENT_TIMESTAMP""",
            (user_id, movie_code, rating)
        )

def get_movie_avg_rating(movie_code: str) -> tuple[float, int]:
    """(o'rtacha reyting, ovozlar soni)"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT AVG(rating) as avg, COUNT(*) as cnt FROM movie_ratings WHERE movie_code=?",
            (movie_code,)
        ).fetchone()
        avg = round(row["avg"], 1) if row["avg"] else 0.0
        return avg, row["cnt"]

def get_user_rating(user_id: int, movie_code: str) -> int | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT rating FROM movie_ratings WHERE user_id=? AND movie_code=?",
            (user_id, movie_code)
        ).fetchone()
        return row["rating"] if row else None

# ─── FAVORITES ───────────────────────────────────────────────────────────────

def add_favorite(user_id: int, movie_code: str) -> bool:
    """True = qo'shildi, False = allaqachon bor"""
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO favorites (user_id, movie_code) VALUES (?, ?)",
                (user_id, movie_code)
            )
            return True
        except Exception:
            return False

def remove_favorite(user_id: int, movie_code: str):
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM favorites WHERE user_id=? AND movie_code=?",
            (user_id, movie_code)
        )

def get_favorites(user_id: int) -> list:
    with get_conn() as conn:
        return conn.execute(
            """SELECT m.* FROM movies m
               JOIN favorites f ON f.movie_code = m.code
               WHERE f.user_id=? ORDER BY f.added_at DESC""",
            (user_id,)
        ).fetchall()

def is_favorite(user_id: int, movie_code: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM favorites WHERE user_id=? AND movie_code=?",
            (user_id, movie_code)
        ).fetchone()
        return row is not None

# ─── WATCH HISTORY ───────────────────────────────────────────────────────────

def add_watch_history(user_id: int, movie_code: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO user_watch_history (user_id, movie_code) VALUES (?, ?)",
            (user_id, movie_code)
        )

def get_watch_count(user_id: int) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as c FROM user_watch_history WHERE user_id=?", (user_id,)
        ).fetchone()
        return row["c"]

def get_user_watched_movies(user_id: int, limit: int = 10) -> list:
    with get_conn() as conn:
        return conn.execute(
            """SELECT m.name, m.code, MAX(h.watched_at) as last_watched
               FROM user_watch_history h
               JOIN movies m ON m.code = h.movie_code
               WHERE h.user_id=?
               GROUP BY m.code ORDER BY last_watched DESC LIMIT ?""",
            (user_id, limit)
        ).fetchall()

# ─── PROMO CODES ─────────────────────────────────────────────────────────────

def create_promo(code: str, discount_type: str, discount_value: int,
                 duration_days: int = 0, max_uses: int = 0) -> bool:
    """
    discount_type: 'free_days' | 'percent'
    duration_days: bepul kunlar (free_days uchun)
    max_uses: 0 = cheksiz
    """
    with get_conn() as conn:
        try:
            conn.execute(
                """INSERT INTO promo_codes (code, discount_type, discount_value, duration_days, max_uses)
                   VALUES (?, ?, ?, ?, ?)""",
                (code, discount_type, discount_value, duration_days, max_uses)
            )
            return True
        except Exception:
            return False

def get_promo(code: str):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM promo_codes WHERE code=? AND is_active=1", (code,)
        ).fetchone()

def get_all_promos() -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM promo_codes ORDER BY created_at DESC"
        ).fetchall()

def use_promo(promo_id: int, user_id: int) -> bool:
    """True = muvaffaqiyatli, False = allaqachon ishlatilgan"""
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO promo_uses (promo_id, user_id) VALUES (?, ?)",
                (promo_id, user_id)
            )
            conn.execute(
                "UPDATE promo_codes SET used_count = used_count + 1 WHERE id=?",
                (promo_id,)
            )
            # max_uses tekshirish
            row = conn.execute(
                "SELECT max_uses, used_count FROM promo_codes WHERE id=?", (promo_id,)
            ).fetchone()
            if row and row["max_uses"] > 0 and row["used_count"] >= row["max_uses"]:
                conn.execute("UPDATE promo_codes SET is_active=0 WHERE id=?", (promo_id,))
            return True
        except Exception:
            return False

def has_used_promo(promo_id: int, user_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM promo_uses WHERE promo_id=? AND user_id=?",
            (promo_id, user_id)
        ).fetchone()
        return row is not None

def delete_promo(code: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM promo_codes WHERE code=?", (code,))

def toggle_promo(code: str, active: bool):
    with get_conn() as conn:
        conn.execute(
            "UPDATE promo_codes SET is_active=? WHERE code=?",
            (1 if active else 0, code)
        )

# ─── OFFERS ──────────────────────────────────────────────────────────────────

def add_offer(user_id: int, username: str | None, full_name: str, message: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO offers (user_id, username, full_name, message) VALUES (?, ?, ?, ?)",
            (user_id, username, full_name, message)
        )
        return cur.lastrowid

def get_all_offers() -> list:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM offers ORDER BY created_at DESC").fetchall()

# ─── ADMIN REQUESTS ──────────────────────────────────────────────────────────

def add_admin_request(user_id: int, username: str | None, full_name: str, message: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO admin_requests (user_id, username, full_name, message) VALUES (?, ?, ?, ?)",
            (user_id, username, full_name, message)
        )
        return cur.lastrowid

def mark_request_handled(request_id: int, admin_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE admin_requests SET status='handled', handled_by=? WHERE id=?",
            (admin_id, request_id)
        )

# ─── BOT VERSION ─────────────────────────────────────────────────────────────

def get_bot_version() -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM bot_version WHERE id=1").fetchone()
        return dict(row) if row else None

def set_bot_version(version: str, changelog: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE bot_version SET version=?, changelog=?, updated_at=CURRENT_TIMESTAMP WHERE id=1",
            (version, changelog)
        )

# ─── PENDING PAYMENTS ────────────────────────────────────────────────────────

def create_payment(user_id: int, username: str | None, full_name: str,
                   months: int, amount: int) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO pending_payments (user_id, username, full_name, months, amount)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, username, full_name, months, amount),
        )
        return cur.lastrowid

def update_payment_check(payment_id: int, file_id: str, file_type: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE pending_payments SET check_file_id=?, check_type=? WHERE id=?",
            (file_id, file_type, payment_id),
        )

def get_payment(payment_id: int):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM pending_payments WHERE id=?", (payment_id,)
        ).fetchone()

def get_payment_history(user_id: int) -> list:
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM pending_payments WHERE user_id=? ORDER BY created_at DESC",
            (user_id,)
        ).fetchall()

def approve_payment(payment_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE pending_payments SET status='approved' WHERE id=?", (payment_id,)
        )

def reject_payment(payment_id: int):
    with get_conn() as conn:
        conn.execute(
            "UPDATE pending_payments SET status='rejected' WHERE id=?", (payment_id,)
        )

# ─── STATS ───────────────────────────────────────────────────────────────────

def get_stats() -> dict:
    now = datetime.now().isoformat()
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
        blocked = conn.execute(
            "SELECT COUNT(*) as c FROM users WHERE is_blocked=1"
        ).fetchone()["c"]
        active_subs = conn.execute(
            """SELECT COUNT(DISTINCT u.id) as c FROM users u
               JOIN subscriptions s ON s.user_id=u.id
               WHERE s.end_date > ? AND u.is_blocked=0""",
            (now,),
        ).fetchone()["c"]
        ordinary = total - active_subs - blocked
        total_movies = conn.execute("SELECT COUNT(*) as c FROM movies").fetchone()["c"]
        total_offers = conn.execute("SELECT COUNT(*) as c FROM offers").fetchone()["c"]
        return {
            "total": total,
            "active_subs": active_subs,
            "ordinary": max(ordinary, 0),
            "blocked": blocked,
            "total_movies": total_movies,
            "total_offers": total_offers,
        }
