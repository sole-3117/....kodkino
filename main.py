import os
import io
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)
from telegram.error import Forbidden, BadRequest
import db
import backup_restore

# XAVFSIZLIK: BOT_TOKEN ni .env fayldan o'qiymiz
BOT_TOKEN  = "8922191640:AAG0jseLXI7ZR2TKLB-o2AYMsribcH2XRu4"
MAIN_ADMIN = 6887251996

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── STATES ──────────────────────────────────────────────────────────────────
(
    PAY_CHOOSE_PLAN, PAY_WAIT_CHECK,
    ADD_VIDEO, ADD_NAME, ADD_QUALITY, ADD_YEAR, ADD_LANG, ADD_RATING, ADD_CODE,
    BROADCAST_MSG,
    DELETE_CODE,
    ADD_ADMIN_ID,
    REMOVE_ADMIN_ID,
    PROMO_ENTER,
    OFFERS_ENTER,
    ADMIN_REQUEST_ENTER,
    PROMO_ADMIN_ADD,
    USER_SEND_ID, USER_SEND_MSG,
    BOT_VERSION_SET,
    BLOCK_USER_ID,
    SUB_MANAGE_ID, SUB_MANAGE_ACTION,
    RESTORE_WAIT,           # ← YANGI: restore fayl kutish holati
) = range(24)

# ─── HELPERS ─────────────────────────────────────────────────────────────────

def fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ")

def is_admin(uid: int) -> bool:
    return db.is_admin(uid, MAIN_ADMIN)

def stars(n: int) -> str:
    return "⭐" * n + "☆" * (5 - n)

def plans_keyboard(monthly: int):
    return [
        [InlineKeyboardButton(f"1️⃣  1 oylik — {fmt(monthly)} so'm",    callback_data="plan_1")],
        [InlineKeyboardButton(f"3️⃣  3 oylik — {fmt(monthly*3)} so'm",  callback_data="plan_3")],
        [InlineKeyboardButton(f"6️⃣  6 oylik — {fmt(monthly*6)} so'm",  callback_data="plan_6")],
        [InlineKeyboardButton(f"🔄 12 oylik — {fmt(monthly*12)} so'm", callback_data="plan_12")],
    ]

async def show_pay_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    monthly = int(db.get_setting("monthly_price") or 50000)
    card    = db.get_setting("card_number") or "9800000000001234"
    owner   = db.get_setting("card_owner")  or "SOLEJON ADASHOV ISROILOVICH"
    daily   = int(monthly / 30)
    text = (
        "🎬 <b>KINO BOT</b> — Oylik obuna tizimi\n\n"
        "Bu bot <b>oylik to'lov</b> asosida ishlaydi.\n"
        f"🗓 Kunlik: <b>{fmt(daily)} so'm</b>\n\n"
        "⚠️ <b>OGOHLANTIRISH!</b> Kartaga ko'p ham, kam ham "
        "pul tashlanmasin. <b>Chek talab qilinadi!</b>\n\n"
        f"💳 <code>{card}</code>\n"
        f"👤 <b>{owner}</b>\n\n"
        "🎯 Obuna muddatini tanlang:"
    )
    kb = plans_keyboard(monthly)
    kb.append([InlineKeyboardButton("🎬 Kodim bor — filmni ko'rish", callback_data="has_code")])
    kb.append([InlineKeyboardButton("🎟 Promo-kod bor", callback_data="enter_promo")])
    if update.callback_query:
        try:
            await update.callback_query.message.edit_text(
                text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML"
            )
            return PAY_CHOOSE_PLAN
        except Exception:
            pass
    await update.effective_message.reply_text(
        text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML"
    )
    return PAY_CHOOSE_PLAN

# ─── /start ──────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user   = update.effective_user
    is_new = db.upsert_user(user.id, user.username, user.full_name)
    context.user_data.clear()

    if is_new and not is_admin(user.id):
        total = db.get_total_users()
        uname = f"@{user.username}" if user.username else "—"
        notif = (
            f"🆕 <b>Yangi Foydalanuvchi!</b>\n\n"
            f"👥 Umumiy: <b>[{total}]</b>\n"
            f"👤 Ismi: <b>{user.full_name}</b>\n"
            f"📌 User: {uname}\n"
            f"🆔 Id: <code>#{user.id}</code>"
        )
        for aid in set([MAIN_ADMIN] + db.get_admins()):
            try:
                await context.bot.send_message(aid, notif, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Yangi user xabari {aid} ga yuborilmadi: {e}")

    if is_admin(user.id):
        await update.message.reply_text(
            f"👋 Xush kelibsiz, Admin <b>{user.full_name}</b>!\n\n"
            "🎬 <b>KINO BOT</b> boshqaruv paneli:\n\n"
            "/add — Yangi kino qo'shish\n"
            "/delete — Kinoni o'chirish\n"
            "/broadcast — Barcha foydalanuvchilarga xabar\n"
            "/user_send — Bitta foydalanuvchiga xabar\n"
            "/user_sends — Faol obunachilar\n"
            "/stats — Statistika\n"
            "/settings — Sozlamalar\n"
            "/promo_admin — Promo-kodlar\n"
            "/block — Foydalanuvchini bloklash\n"
            "/unblock — Blokni ochish\n"
            "/sub_manage — Obunani boshqarish\n"
            "/setversion — Bot versiyasini yangilash\n"
            "/addadmin — Admin qo'shish\n"
            "/removeadmin — Adminni o'chirish\n"
            "/admins — Adminlar ro'yxati\n"
            "/backup — Backup yaratish\n"
            "/restore — Backup'dan tiklash\n"
            "/list — Buyruqlar ro'yxati",
            parse_mode="HTML"
        )
        return ConversationHandler.END

    if db.has_active_subscription(user.id):
        end = db.get_subscription_end(user.id)
        await update.message.reply_text(
            f"🎬 <b>KINO BOT</b>ga xush kelibsiz, {user.first_name}!\n\n"
            f"✅ Obunangiz faol: <b>{end.strftime('%d.%m.%Y')}</b> gacha\n\n"
            "🔍 Kino kodi yoki nomini yozing\n"
            "📋 /list — barcha buyruqlar",
            parse_mode="HTML"
        )
        return ConversationHandler.END

    return await show_pay_menu(update, context)

# ─── /list ───────────────────────────────────────────────────────────────────

async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if is_admin(user.id):
        await update.message.reply_text(
            "📋 <b>Admin buyruqlari:</b>\n\n"
            "🎬 <b>Kino:</b>\n"
            "/add — Kino qo'shish\n"
            "/delete — Kinoni o'chirish\n\n"
            "📢 <b>Xabar:</b>\n"
            "/broadcast — Hammaga xabar\n"
            "/user_send — Bitta foydalanuvchiga\n"
            "/user_sends — Faol obunachilar\n\n"
            "👤 <b>Foydalanuvchi:</b>\n"
            "/block — Bloklash\n"
            "/unblock — Blokni ochish\n"
            "/sub_manage — Obunani boshqarish\n\n"
            "🎟 <b>Promo:</b>\n"
            "/promo_admin — Promo-kodlar\n\n"
            "💾 <b>Backup:</b>\n"
            "/backup — Backup yaratish va yuborish\n"
            "/restore — Backup fayldan tiklash\n\n"
            "⚙️ <b>Boshqaruv:</b>\n"
            "/stats — Statistika\n"
            "/settings — Sozlamalar\n"
            "/setversion — Versiya yangilash\n"
            "/addadmin — Admin qo'shish\n"
            "/removeadmin — Adminni o'chirish\n"
            "/admins — Adminlar ro'yxati",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            "📋 <b>Buyruqlar ro'yxati:</b>\n\n"
            "/start — Botni qayta ishga tushirish\n"
            "/profile — Profilim\n"
            "/sub — Obuna ma'lumoti\n"
            "/promo — Promo-kod kiritish\n"
            "/offers — Taklif va g'oya yuborish\n"
            "/admin_send — Adminga murojaat\n"
            "/bot — Bot versiyasi\n"
            "/list — Buyruqlar ro'yxati\n\n"
            "🎬 Kino kodi yoki nomini yuboring!",
            parse_mode="HTML"
        )

# ─── /profile ────────────────────────────────────────────────────────────────

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.username, user.full_name)

    uname = f"@{user.username}" if user.username else "—"
    watch_count = db.get_watch_count(user.id)
    fav_count = len(db.get_favorites(user.id))
    pay_history = db.get_payment_history(user.id)
    approved = [p for p in pay_history if p["status"] == "approved"]

    if db.has_active_subscription(user.id):
        end = db.get_subscription_end(user.id)
        days_left = (end - datetime.now()).days
        sub_text = (
            f"✅ <b>Faol</b>\n"
            f"📅 Tugash: <b>{end.strftime('%d.%m.%Y')}</b>\n"
            f"⏳ Qoldi: <b>{days_left} kun</b>"
        )
        if days_left == 1:
            sub_text += "\n\n⚠️ <b>Ertaga obunangiz tugaydi!</b>"
    else:
        sub_text = "❌ <b>Faol emas</b>"

    await update.message.reply_text(
        f"👤 <b>Mening profilim</b>\n\n"
        f"🆔 ID: <code>{user.id}</code>\n"
        f"👤 Ism: <b>{user.full_name}</b>\n"
        f"📌 Username: {uname}\n\n"
        f"📡 <b>Obuna holati:</b>\n{sub_text}\n\n"
        f"🎬 Ko'rilgan kinolar: <b>{watch_count}</b>\n"
        f"🔖 Sevimlilar: <b>{fav_count}</b>\n"
        f"💳 Tasdiqlangan to'lovlar: <b>{len(approved)}</b>",
        parse_mode="HTML"
    )

# ─── /sub ────────────────────────────────────────────────────────────────────

async def sub_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    monthly = int(db.get_setting("monthly_price") or 50000)

    if db.has_active_subscription(user.id):
        end = db.get_subscription_end(user.id)
        days_left = (end - datetime.now()).days
        history = db.get_subscription_history(user.id)

        hist_text = ""
        for s in history[:5]:
            start_d = datetime.fromisoformat(s["start_date"]).strftime("%d.%m.%Y")
            end_d   = datetime.fromisoformat(s["end_date"]).strftime("%d.%m.%Y")
            hist_text += f"  • {s['months']} oy: {start_d} → {end_d}\n"

        await update.message.reply_text(
            f"📡 <b>Obuna ma'lumoti</b>\n\n"
            f"✅ Holat: <b>Faol</b>\n"
            f"📅 Tugaydi: <b>{end.strftime('%d.%m.%Y')}</b>\n"
            f"⏳ Qolgan kunlar: <b>{days_left}</b>\n\n"
            f"💰 Oylik narx: <b>{fmt(monthly)} so'm</b>\n\n"
            f"📜 <b>Obuna tarixi:</b>\n{hist_text}\n"
            "Muddatni uzaytirish uchun admin bilan bog'laning: /admin_send",
            parse_mode="HTML"
        )
    else:
        kb = InlineKeyboardMarkup(plans_keyboard(monthly) + [
            [InlineKeyboardButton("🎟 Promo-kod bor", callback_data="enter_promo")]
        ])
        await update.message.reply_text(
            f"📡 <b>Obuna ma'lumoti</b>\n\n"
            f"❌ Holat: <b>Faol emas</b>\n\n"
            f"💰 Oylik narx: <b>{fmt(monthly)} so'm</b>\n"
            f"🗓 Kunlik: <b>{fmt(monthly // 30)} so'm</b>\n\n"
            "Obuna xarid qiling:",
            reply_markup=kb, parse_mode="HTML"
        )

# ─── /bot — versiya ──────────────────────────────────────────────────────────

async def bot_version(update: Update, context: ContextTypes.DEFAULT_TYPE):
    v = db.get_bot_version()
    if v:
        changelog = v["changelog"] or "—"
        updated = v.get("updated_at", "")[:10] if v.get("updated_at") else ""
        await update.message.reply_text(
            f"🤖 <b>KINO BOT</b>\n\n"
            f"📦 Versiya: <b>v{v['version']}</b>\n"
            f"🗓 Yangilangan: <b>{updated}</b>\n\n"
            f"📝 <b>Yangilanishlar:</b>\n{changelog}",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text("ℹ️ Versiya ma'lumoti topilmadi.")

async def setversion_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "📦 Yangi versiya raqamini yozing (masalan: <code>1.3.0</code>):\n\n/cancel — bekor",
        parse_mode="HTML"
    )
    return BOT_VERSION_SET

async def setversion_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if "\n" in text:
        parts = text.split("\n", 1)
        version = parts[0].strip()
        changelog = parts[1].strip()
    else:
        version = text
        changelog = ""
    db.set_bot_version(version, changelog)
    await update.message.reply_text(
        f"✅ Bot versiyasi yangilandi: <b>v{version}</b>\n\n"
        f"📝 {changelog or '—'}",
        parse_mode="HTML"
    )
    return ConversationHandler.END

# ─── /promo — foydalanuvchi ──────────────────────────────────────────────────

async def promo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.username, user.full_name)
    await update.message.reply_text(
        "🎟 <b>Promo-kod</b>\n\nPromo-kodingizni yuboring:\n\n/cancel — bekor",
        parse_mode="HTML"
    )
    return PROMO_ENTER

async def promo_enter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    code = update.message.text.strip().upper()
    promo = db.get_promo(code)

    if not promo:
        await update.message.reply_text(
            "❌ Promo-kod topilmadi yoki faol emas.\nQayta kiriting yoki /cancel."
        )
        return PROMO_ENTER

    if db.has_used_promo(promo["id"], user.id):
        await update.message.reply_text(
            "⚠️ Siz bu promo-kodni allaqachon ishlatgansiz."
        )
        return ConversationHandler.END

    if promo["max_uses"] > 0 and promo["used_count"] >= promo["max_uses"]:
        await update.message.reply_text("❌ Bu promo-kodning limiti tugagan.")
        return ConversationHandler.END

    db.use_promo(promo["id"], user.id)

    if promo["discount_type"] == "free_days":
        days = promo["duration_days"]
        now = datetime.now()
        with db.get_conn() as conn:
            active = conn.execute(
                "SELECT end_date FROM subscriptions WHERE user_id=? AND end_date > ? ORDER BY end_date DESC LIMIT 1",
                (user.id, now.isoformat())
            ).fetchone()
            if active:
                new_end = datetime.fromisoformat(active["end_date"]) + timedelta(days=days)
                conn.execute(
                    "UPDATE subscriptions SET end_date=? WHERE user_id=? AND end_date=?",
                    (new_end.isoformat(), user.id, active["end_date"])
                )
            else:
                new_end = now + timedelta(days=days)
                conn.execute(
                    "INSERT INTO subscriptions (user_id, start_date, end_date, months) VALUES (?, ?, ?, ?)",
                    (user.id, now.isoformat(), new_end.isoformat(), 0)
                )
        await update.message.reply_text(
            f"🎉 <b>Promo-kod qabul qilindi!</b>\n\n"
            f"✅ <b>{days} kunlik</b> bepul sinov muddati berildi.\n"
            f"📅 Obuna: <b>{new_end.strftime('%d.%m.%Y')}</b> gacha\n\n"
            "🎬 Kino kodi yozing!",
            parse_mode="HTML"
        )
    elif promo["discount_type"] == "percent":
        pct = promo["discount_value"]
        monthly = int(db.get_setting("monthly_price") or 50000)
        discounted = int(monthly * (1 - pct / 100))
        await update.message.reply_text(
            f"🎉 <b>Promo-kod qabul qilindi!</b>\n\n"
            f"💰 Sizga <b>{pct}% chegirma</b> berildi!\n"
            f"Oylik narx: ~~{fmt(monthly)}~~ → <b>{fmt(discounted)} so'm</b>\n\n"
            "To'lov qilish uchun /sub ga bosing.",
            parse_mode="HTML"
        )

    return ConversationHandler.END

# ─── /promo_admin ─────────────────────────────────────────────────────────────

async def promo_admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    promos = db.get_all_promos()
    if promos:
        lines = []
        for p in promos:
            status = "✅" if p["is_active"] else "❌"
            if p["discount_type"] == "free_days":
                desc = f"{p['duration_days']} kun bepul"
            else:
                desc = f"{p['discount_value']}% chegirma"
            uses = f"{p['used_count']}/{p['max_uses']}" if p["max_uses"] > 0 else f"{p['used_count']}/∞"
            lines.append(f"{status} <code>{p['code']}</code> — {desc} | {uses}")
        promo_list = "\n".join(lines)
    else:
        promo_list = "Hozircha promo-kodlar yo'q."

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Yangi promo qo'shish", callback_data="promo_add")],
        [InlineKeyboardButton("🗑 Promo o'chirish", callback_data="promo_delete")],
    ])
    await update.message.reply_text(
        f"🎟 <b>Promo-kodlar</b>\n\n{promo_list}",
        reply_markup=kb, parse_mode="HTML"
    )

async def promo_admin_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return

    if query.data == "promo_add":
        await query.message.reply_text(
            "➕ <b>Yangi promo-kod qo'shish</b>\n\n"
            "Quyidagi formatda yuboring:\n"
            "<code>KOD TUR QIYMAT KUNLAR MAX_FOYDALANISH</code>\n\n"
            "<b>Tur:</b> <code>days</code> (bepul kun) yoki <code>percent</code> (chegirma)\n\n"
            "<b>Misol (bepul kun):</b>\n"
            "<code>PROMO2024 days 0 7 100</code>\n"
            "→ 7 kun bepul, 100 ta foydalanuvchi\n\n"
            "<b>Misol (chegirma):</b>\n"
            "<code>SALE50 percent 50 0 0</code>\n"
            "→ 50% chegirma, cheksiz\n\n"
            "/cancel — bekor",
            parse_mode="HTML"
        )
        context.user_data["promo_action"] = "add"
        return

    if query.data == "promo_delete":
        await query.message.reply_text(
            "🗑 O'chirmoqchi bo'lgan promo-kod nomini yuboring:\n\n/cancel — bekor"
        )
        context.user_data["promo_action"] = "delete"

async def promo_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    action = context.user_data.get("promo_action")
    text = update.message.text.strip()

    if action == "add":
        parts = text.split()
        if len(parts) < 5:
            await update.message.reply_text(
                "❌ Noto'g'ri format. Qaytadan:\n"
                "<code>KOD TUR QIYMAT KUNLAR MAX_FOYDALANISH</code>",
                parse_mode="HTML"
            )
            return
        code = parts[0].upper()
        tur  = parts[1]
        if tur == "days":
            discount_type  = "free_days"
            discount_value = 0
            duration_days  = int(parts[2]) if parts[2].isdigit() else int(parts[3])
        else:
            discount_type  = "percent"
            discount_value = int(parts[2])
            duration_days  = 0
        max_uses = int(parts[4]) if parts[4].isdigit() else 0

        ok = db.create_promo(code, discount_type, discount_value, duration_days, max_uses)
        if ok:
            await update.message.reply_text(
                f"✅ Promo-kod <code>{code}</code> qo'shildi!", parse_mode="HTML"
            )
        else:
            await update.message.reply_text(f"❌ <code>{code}</code> allaqachon mavjud!", parse_mode="HTML")
        context.user_data.pop("promo_action", None)

    elif action == "delete":
        db.delete_promo(text.upper())
        await update.message.reply_text(
            f"✅ <code>{text.upper()}</code> o'chirildi.", parse_mode="HTML"
        )
        context.user_data.pop("promo_action", None)

# ─── /offers ─────────────────────────────────────────────────────────────────

async def offers_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.username, user.full_name)
    await update.message.reply_text(
        "💡 <b>Taklif va g'oyalar</b>\n\n"
        "Kino qo'shish, yangi funksiyalar yoki boshqa takliflaringizni yuboring:\n\n"
        "/cancel — bekor",
        parse_mode="HTML"
    )
    return OFFERS_ENTER

async def offers_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    oid  = db.add_offer(user.id, user.username, user.full_name, text)
    uname = f"@{user.username}" if user.username else "—"

    await update.message.reply_text("✅ Taklifingiz adminga yuborildi. Rahmat!")
    notif = (
        f"💡 <b>Yangi taklif #{oid}</b>\n\n"
        f"👤 {user.full_name} | {uname}\n"
        f"🆔 <code>{user.id}</code>\n\n"
        f"📝 {text}"
    )
    for aid in set([MAIN_ADMIN] + db.get_admins()):
        try:
            await context.bot.send_message(aid, notif, parse_mode="HTML")
        except Exception:
            pass
    return ConversationHandler.END

# ─── /admin_send ─────────────────────────────────────────────────────────────

async def admin_send_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.username, user.full_name)
    await update.message.reply_text(
        "📩 <b>Adminga murojaat</b>\n\n"
        "Savolingizni yoki murojaatingizni yuboring:\n\n"
        "/cancel — bekor",
        parse_mode="HTML"
    )
    return ADMIN_REQUEST_ENTER

async def admin_send_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user  = update.effective_user
    text  = update.message.text.strip()
    rid   = db.add_admin_request(user.id, user.username, user.full_name, text)
    uname = f"@{user.username}" if user.username else "—"

    await update.message.reply_text(
        "✅ Murojaatingiz adminga yuborildi.\nTez orada javob beriladi."
    )
    notif = (
        f"📩 <b>Murojaat #{rid}</b>\n\n"
        f"👤 {user.full_name} | {uname}\n"
        f"🆔 <code>{user.id}</code>\n\n"
        f"📝 {text}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Qabul qilindi", callback_data=f"req_accept_{rid}_{user.id}"),
    ]])
    for aid in set([MAIN_ADMIN] + db.get_admins()):
        try:
            await context.bot.send_message(aid, notif, reply_markup=kb, parse_mode="HTML")
        except Exception:
            pass
    return ConversationHandler.END

async def admin_request_accept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    parts = query.data.split("_")
    rid = int(parts[2])
    uid = int(parts[3])
    db.mark_request_handled(rid, query.from_user.id)
    try:
        old = query.message.text or ""
        await query.edit_message_text(
            old + f"\n\n✅ Qabul qildi: <b>{query.from_user.full_name}</b>",
            parse_mode="HTML"
        )
    except Exception:
        pass
    try:
        await context.bot.send_message(
            uid,
            f"✅ Murojaatingiz <b>{query.from_user.full_name}</b> tomonidan qabul qilindi.",
            parse_mode="HTML"
        )
    except Exception:
        pass

# ─── PAYMENT FLOW ─────────────────────────────────────────────────────────────

async def plan_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "has_code":
        await query.message.edit_text("🔑 Kino kodini yuboring:")
        return ConversationHandler.END
    if query.data == "enter_promo":
        await query.message.edit_text(
            "🎟 Promo-kodingizni yuboring:\n\n/cancel — bekor"
        )
        context.user_data["from_pay"] = True
        return PAY_WAIT_CHECK
    months  = int(query.data.split("_")[1])
    monthly = int(db.get_setting("monthly_price") or 50000)
    amount  = monthly * months
    card    = db.get_setting("card_number") or "9800000000001234"
    owner   = db.get_setting("card_owner")  or "SOLEJON ADASHOV ISROILOVICH"
    user    = update.effective_user
    pid     = db.create_payment(user.id, user.username, user.full_name, months, amount)
    context.user_data["payment_id"] = pid
    await query.message.edit_text(
        f"✅ <b>{months} oylik</b> obuna tanlandi\n\n"
        f"💰 To'lov miqdori: <b>{fmt(amount)} so'm</b>\n\n"
        "⚠️ <b>OGOHLANTIRISH!</b>\n"
        "Kartaga aynan shu summani o'tkazing — ko'p ham kam ham bo'lmasin!\n\n"
        f"💳 <code>{card}</code>\n"
        f"👤 <b>{owner}</b>\n\n"
        "🧾 Pul o'tkazgach <b>chekni</b> yuboring (rasm yoki fayl).",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Pul o'tkazildi — Chek yuborish", callback_data="send_check")],
            [InlineKeyboardButton("🔙 Orqaga", callback_data="back_to_plans")],
        ]),
        parse_mode="HTML"
    )
    return PAY_CHOOSE_PLAN

async def prompt_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text(
        "🧾 <b>Chekni yuboring</b>\n\nRasm yoki fayl (PDF) bo'lishi mumkin.",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Bekor", callback_data="back_to_plans")]
        ]),
        parse_mode="HTML"
    )
    return PAY_WAIT_CHECK

async def receive_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pid = context.user_data.get("payment_id")
    if not pid:
        await update.message.reply_text("❌ Xatolik. /start ga bosing.")
        return ConversationHandler.END
    msg = update.message
    if msg.photo:
        fid, ftype = msg.photo[-1].file_id, "photo"
    elif msg.document:
        fid, ftype = msg.document.file_id, "document"
    else:
        await msg.reply_text("❌ Rasm yoki fayl yuboring.")
        return PAY_WAIT_CHECK
    db.update_payment_check(pid, fid, ftype)
    payment = db.get_payment(pid)
    user    = update.effective_user
    uname   = f"@{user.username}" if user.username else "—"
    await msg.reply_text(
        "⏳ Chekingiz adminga yuborildi.\n"
        "✅ Tasdiqlangandan so'ng obuna faollashtiriladi."
    )
    caption = (
        f"💳 <b>Yangi to'lov so'rovi</b>\n\n"
        f"👤 {user.full_name}\n"
        f"📌 {uname}\n"
        f"🆔 <code>{user.id}</code>\n\n"
        f"🗓 Muddat: <b>{payment['months']} oy</b>\n"
        f"💰 Summa: <b>{fmt(payment['amount'])} so'm</b>\n\n"
        "Tasdiqlaysizmi?"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Ha",   callback_data=f"approve_{pid}"),
        InlineKeyboardButton("❌ Yo'q", callback_data=f"reject_{pid}"),
    ]])
    for aid in set([MAIN_ADMIN] + db.get_admins()):
        try:
            if ftype == "photo":
                await context.bot.send_photo(aid, fid, caption=caption, reply_markup=kb, parse_mode="HTML")
            else:
                await context.bot.send_document(aid, fid, caption=caption, reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Admin {aid} ga yuborib bo'lmadi: {e}")
    return ConversationHandler.END

async def payment_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    action, pid = query.data.split("_", 1)
    pid     = int(pid)
    payment = db.get_payment(pid)
    if not payment or payment["status"] != "pending":
        await query.answer("⚠️ Allaqachon ko'rib chiqilgan.", show_alert=True)
        return
    uid    = payment["user_id"]
    months = payment["months"]
    if action == "approve":
        db.approve_payment(pid)
        db.add_subscription(uid, months)
        end_str = (datetime.now() + timedelta(days=30 * months)).strftime("%d.%m.%Y")
        try:
            old = query.message.caption or ""
            await query.edit_message_caption(
                old + f"\n\n✅ TASDIQLANDI — {query.from_user.full_name}", parse_mode="HTML"
            )
        except Exception:
            pass
        try:
            await context.bot.send_message(
                uid,
                f"🎉 <b>Tabriklaymiz!</b>\n\n"
                f"✅ {months} oylik obunangiz faollashtirildi!\n"
                f"🗓 <b>{end_str}</b> gacha amal qiladi.\n\n"
                "🎬 Kino kodini yuboring!",
                parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        db.reject_payment(pid)
        try:
            old = query.message.caption or ""
            await query.edit_message_caption(
                old + f"\n\n❌ RAD ETILDI — {query.from_user.full_name}", parse_mode="HTML"
            )
        except Exception:
            pass
        monthly = int(db.get_setting("monthly_price") or 50000)
        card    = db.get_setting("card_number") or "9800000000001234"
        owner   = db.get_setting("card_owner")  or "SOLEJON ADASHOV ISROILOVICH"
        try:
            await context.bot.send_message(
                uid,
                f"❌ <b>Chekda yoki to'lovda xatolik bor.</b>\n\n"
                "Qayta tekshirib, to'g'ri summani o'tkazing.\n\n"
                f"💳 <code>{card}</code>\n"
                f"👤 <b>{owner}</b>",
                reply_markup=InlineKeyboardMarkup(plans_keyboard(monthly)),
                parse_mode="HTML"
            )
        except Exception:
            pass

# ─── KINO RATING ─────────────────────────────────────────────────────────────

def rating_keyboard(movie_code: str, current: int = 0):
    buttons = []
    for i in range(1, 6):
        label = f"{'⭐' if i <= current else '☆'}{i}"
        # TUZATISH: movie_code ichida '_' bo'lsa ham ishlaydi
        buttons.append(InlineKeyboardButton(label, callback_data=f"rate_{movie_code}_{i}"))
    return [buttons]

async def rate_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # TUZATISH: rsplit bilan oxirgi elementni ajratamiz — movie_code ichida '_' bo'lsa ham xato yo'q
    # format: "rate_{movie_code}_{star}"
    data      = query.data          # "rate_avatar2_3"  yoki  "rate_star_wars_3"
    remainder = data[5:]            # "avatar2_3"       yoki  "star_wars_3"
    movie_code, star_str = remainder.rsplit("_", 1)
    star = int(star_str)

    db.rate_movie(query.from_user.id, movie_code, star)
    avg, cnt = db.get_movie_avg_rating(movie_code)
    await query.edit_message_reply_markup(
        reply_markup=InlineKeyboardMarkup(rating_keyboard(movie_code, star))
    )
    await query.answer(f"✅ {star}⭐ qo'ydingiz! O'rtacha: {avg}⭐ ({cnt} ta)", show_alert=True)

# ─── SEVIMLILAR ──────────────────────────────────────────────────────────────

async def favorites_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    parts   = query.data.split("_", 2)
    action  = parts[1]   # add / remove / list
    user_id = query.from_user.id

    if action == "add":
        movie_code = parts[2]
        added = db.add_favorite(user_id, movie_code)
        if added:
            movie = db.get_movie_by_code(movie_code)
            await query.answer(f"🔖 '{movie['name']}' sevimlilarga qo'shildi!", show_alert=True)
        else:
            await query.answer("⚠️ Allaqachon sevimlilarda bor.", show_alert=True)

    elif action == "remove":
        movie_code = parts[2]
        db.remove_favorite(user_id, movie_code)
        await query.answer("🗑 Sevimlidan o'chirildi.", show_alert=True)
        await show_favorites(query.message, user_id, edit=True)

    elif action == "list":
        await show_favorites(query.message, user_id, edit=True)

async def show_favorites(message, user_id: int, edit: bool = False):
    favs = db.get_favorites(user_id)
    if not favs:
        text = "🔖 <b>Sevimlilar ro'yxati bo'sh</b>\n\nKino ko'rganingizda ❤️ tugmasini bosing."
        kb   = None
    else:
        text    = "🔖 <b>Sevimlilar ro'yxati:</b>\n\n"
        buttons = []
        for m in favs[:15]:
            text += f"🎬 <b>{m['name']}</b> — <code>{m['code']}</code>\n"
            buttons.append([InlineKeyboardButton(
                f"🗑 {m['name']}", callback_data=f"fav_remove_{m['code']}"
            )])
        kb = InlineKeyboardMarkup(buttons)
    if edit:
        try:
            await message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        except Exception:
            await message.reply_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await message.reply_text(text, reply_markup=kb, parse_mode="HTML")

async def cmd_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.username, user.full_name)
    await show_favorites(update.message, user.id)

# ─── MENING STATISTIKAM ──────────────────────────────────────────────────────

async def my_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.upsert_user(user.id, user.username, user.full_name)

    watch_count = db.get_watch_count(user.id)
    fav_count   = len(db.get_favorites(user.id))
    watched     = db.get_user_watched_movies(user.id, 5)
    pay_history = db.get_payment_history(user.id)
    approved    = [p for p in pay_history if p["status"] == "approved"]

    hist_text = ""
    for m in watched:
        last = m["last_watched"][:10]
        hist_text += f"  🎬 <b>{m['name']}</b> — {last}\n"
    if not hist_text:
        hist_text = "  Hali kino ko'rilmagan."

    sub_text = "❌ Faol emas"
    if db.has_active_subscription(user.id):
        end = db.get_subscription_end(user.id)
        sub_text = f"✅ {end.strftime('%d.%m.%Y')} gacha"

    await update.message.reply_text(
        f"📊 <b>Mening statistikam</b>\n\n"
        f"🎬 Ko'rilgan kinolar: <b>{watch_count}</b>\n"
        f"🔖 Sevimlilar: <b>{fav_count}</b>\n"
        f"💳 Tasdiqlangan to'lovlar: <b>{len(approved)}</b>\n"
        f"📡 Obuna: {sub_text}\n\n"
        f"🕐 <b>So'nggi ko'rilganlar:</b>\n{hist_text}",
        parse_mode="HTML"
    )

# ─── GENERAL TEXT HANDLER ─────────────────────────────────────────────────────

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()
    db.upsert_user(user.id, user.username, user.full_name)

    if context.user_data.get("from_pay"):
        context.user_data.pop("from_pay", None)
        return await promo_enter(update, context)

    if is_admin(user.id) and context.user_data.get("setting_mode"):
        mode  = context.user_data.pop("setting_mode")
        value = text
        if mode == "price":
            if not value.isdigit():
                await update.message.reply_text("❌ Faqat raqam kiriting!")
                context.user_data["setting_mode"] = "price"
                return
            db.set_setting("monthly_price", value)
            await update.message.reply_text(
                f"✅ Oylik narx: <b>{fmt(int(value))} so'm</b>", parse_mode="HTML"
            )
        elif mode == "card":
            db.set_setting("card_number", value)
            await update.message.reply_text(
                f"✅ Karta raqami: <code>{value}</code>", parse_mode="HTML"
            )
        elif mode == "owner":
            db.set_setting("card_owner", value)
            await update.message.reply_text(
                f"✅ Karta egasi: <b>{value}</b>", parse_mode="HTML"
            )
        await settings_cmd(update, context)
        return

    if is_admin(user.id) and context.user_data.get("promo_action"):
        await promo_admin_input(update, context)
        return

    if is_admin(user.id):
        await update.message.reply_text(
            "❓ Buyruqlardan foydalaning:\n"
            "/add /delete /broadcast /stats /settings /list"
        )
        return

    if not db.has_active_subscription(user.id):
        await show_pay_menu(update, context)
        return

    movie = db.get_movie_by_code(text)
    if movie:
        db.increment_movie_requests(text)
        db.add_watch_history(user.id, text)
        req    = db.get_movie_by_code(text)["request_count"]
        avg, cnt = db.get_movie_avg_rating(text)
        is_fav  = db.is_favorite(user.id, text)
        fav_btn    = "💔 Sevimlidan o'chirish" if is_fav else "🔖 Sevimlilarga qo'shish"
        fav_action = f"fav_remove_{text}" if is_fav else f"fav_add_{text}"
        caption = (
            f"🎬 <b>{movie['name']}</b>\n\n"
            f"🎞 Sifat: <b>{movie['quality'] or '—'}</b>\n"
            f"🗓 Yil: <b>{movie['year'] or '—'}</b>\n"
            f"🌐 Til: <b>{movie['language'] or '—'}</b>\n"
            f"⭐ Reyting: <b>{movie['rating'] or '—'}/10</b>\n"
            f"👥 Foydalanuvchi reytingi: <b>{avg}⭐</b> ({cnt} ta)\n\n"
            f"🗂 Yuklash: <b>{req}</b> ta"
        )
        user_star = db.get_user_rating(user.id, text) or 0
        kb = InlineKeyboardMarkup(
            rating_keyboard(text, user_star) +
            [[InlineKeyboardButton(fav_btn, callback_data=fav_action)]]
        )
        await update.message.reply_video(
            movie["file_id"], caption=caption, reply_markup=kb, parse_mode="HTML"
        )
        return

    results = db.search_movies_by_name(text)
    if results:
        if len(results) == 1:
            m = results[0]
            db.increment_movie_requests(m["code"])
            db.add_watch_history(user.id, m["code"])
            req    = db.get_movie_by_code(m["code"])["request_count"]
            avg, cnt = db.get_movie_avg_rating(m["code"])
            is_fav  = db.is_favorite(user.id, m["code"])
            fav_btn    = "💔 Sevimlidan o'chirish" if is_fav else "🔖 Sevimlilarga qo'shish"
            fav_action = f"fav_remove_{m['code']}" if is_fav else f"fav_add_{m['code']}"
            caption = (
                f"🎬 <b>{m['name']}</b>\n\n"
                f"🎞 Sifat: <b>{m['quality'] or '—'}</b>\n"
                f"🗓 Yil: <b>{m['year'] or '—'}</b>\n"
                f"🌐 Til: <b>{m['language'] or '—'}</b>\n"
                f"⭐ Reyting: <b>{m['rating'] or '—'}/10</b>\n"
                f"👥 Foydalanuvchi reytingi: <b>{avg}⭐</b> ({cnt} ta)\n\n"
                f"🗂 Yuklash: <b>{req}</b> ta"
            )
            user_star = db.get_user_rating(user.id, m["code"]) or 0
            kb = InlineKeyboardMarkup(
                rating_keyboard(m["code"], user_star) +
                [[InlineKeyboardButton(fav_btn, callback_data=fav_action)]]
            )
            await update.message.reply_video(
                m["file_id"], caption=caption, reply_markup=kb, parse_mode="HTML"
            )
        else:
            lines = "\n".join(
                f"🎬 <b>{m['name']}</b> — Kod: <code>{m['code']}</code>"
                for m in results[:10]
            )
            await update.message.reply_text(
                f"🔍 <b>Qidiruv natijalari:</b>\n\n{lines}\n\n"
                "🎯 Kino kodini yuboring.",
                parse_mode="HTML"
            )
    else:
        await update.message.reply_text(
            "❌ Kino topilmadi.\nKodni yoki nomni to'g'ri kiriting."
        )

# ─── ADMIN: ADD MOVIE ─────────────────────────────────────────────────────────

async def add_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    context.user_data.clear()
    await update.message.reply_text(
        "🎬 <b>Yangi kino qo'shish</b>\n\n"
        "1️⃣ <b>Kino faylini</b> (video) yuboring:\n\n"
        "/cancel — bekor qilish",
        parse_mode="HTML"
    )
    return ADD_VIDEO

async def add_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.video:
        context.user_data["file_id"] = update.message.video.file_id
    elif update.message.document:
        context.user_data["file_id"] = update.message.document.file_id
    else:
        await update.message.reply_text("❌ Video fayl yuboring.")
        return ADD_VIDEO
    await update.message.reply_text("2️⃣ 🎬 <b>Kino nomini</b> yozing:", parse_mode="HTML")
    return ADD_NAME

async def add_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text(
        "3️⃣ 🎞 <b>Sifati:</b>\n<code>4K</code> / <code>Full HD 1080p</code> / <code>720p</code>",
        parse_mode="HTML"
    )
    return ADD_QUALITY

async def add_quality(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["quality"] = update.message.text.strip()
    await update.message.reply_text("4️⃣ 🗓 <b>Chiqarilgan yili:</b>", parse_mode="HTML")
    return ADD_YEAR

async def add_year(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["year"] = update.message.text.strip()
    await update.message.reply_text(
        "5️⃣ 🌐 <b>Tili:</b>\nMasalan: O'zbek, Rus, Ingliz",
        parse_mode="HTML"
    )
    return ADD_LANG

async def add_lang(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["language"] = update.message.text.strip()
    await update.message.reply_text(
        "6️⃣ ⭐ <b>Reytingi</b> (10 dan):\nMasalan: <code>8.5</code>",
        parse_mode="HTML"
    )
    return ADD_RATING

async def add_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["rating"] = update.message.text.strip()
    await update.message.reply_text(
        "7️⃣ 🔑 <b>Kino kodini kiriting:</b>\n\n"
        "Raqam yoki harflar bo'lishi mumkin.\n"
        "Masalan: <code>42</code> yoki <code>avatar2</code>\n\n"
        "/cancel — bekor qilish",
        parse_mode="HTML"
    )
    return ADD_CODE

async def add_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip()
    if not code or code.startswith("/"):
        await update.message.reply_text("❌ Noto'g'ri kod. Qaytadan kiriting:")
        return ADD_CODE
    existing = db.get_movie_by_code(code)
    if existing:
        await update.message.reply_text(
            f"⚠️ <b><code>{code}</code> kodi allaqachon mavjud!</b>\n\n"
            f"📌 Bu kod: <b>{existing['name']}</b> filmiga tegishli.\n\n"
            "Boshqa kod kiriting:",
            parse_mode="HTML"
        )
        return ADD_CODE
    context.user_data["code"] = code
    d = context.user_data
    await update.message.reply_text(
        f"✅ <b>Tasdiqlang:</b>\n\n"
        f"🔑 Kod: <code>{code}</code>\n"
        f"🎬 Nom: <b>{d['name']}</b>\n"
        f"🎞 Sifat: <b>{d['quality']}</b>\n"
        f"🗓 Yil: <b>{d['year']}</b>\n"
        f"🌐 Til: <b>{d['language']}</b>\n"
        f"⭐ Reyting: <b>{d['rating']}/10</b>",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Saqlash", callback_data="movie_save"),
            InlineKeyboardButton("❌ Bekor",   callback_data="movie_cancel"),
        ]]),
        parse_mode="HTML"
    )
    return ADD_CODE

async def movie_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "movie_cancel":
        await query.edit_message_text("❌ Bekor qilindi.")
        context.user_data.clear()
        return ConversationHandler.END
    d    = context.user_data
    code = d["code"]
    db.add_movie(
        code=code, name=d["name"], description="",
        quality=d.get("quality", ""), year=d.get("year", ""),
        language=d.get("language", ""), rating=d.get("rating", ""),
        file_id=d["file_id"],
    )
    await query.edit_message_text(
        f"✅ <b>Kino qo'shildi!</b>\n\n"
        f"🔑 Kod: <code>{code}</code>\n"
        f"🎬 Nom: <b>{d['name']}</b>\n\n"
        "Bu kodni foydalanuvchilarga bering.",
        parse_mode="HTML"
    )
    context.user_data.clear()
    return ConversationHandler.END

# ─── ADMIN: DELETE ───────────────────────────────────────────────────────────

async def delete_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "🗑 <b>Kinoni o'chirish</b>\n\nKino <b>kodini</b> yuboring:\n\n/cancel — bekor",
        parse_mode="HTML"
    )
    return DELETE_CODE

async def delete_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code  = update.message.text.strip()
    movie = db.get_movie_by_code(code)
    if not movie:
        await update.message.reply_text(
            f"❌ <code>{code}</code> topilmadi.", parse_mode="HTML"
        )
        return DELETE_CODE
    db.delete_movie(code)
    await update.message.reply_text(
        f"✅ <b>{movie['name']}</b> (kod: <code>{code}</code>) o'chirildi.",
        parse_mode="HTML"
    )
    return ConversationHandler.END

# ─── ADMIN: BROADCAST ────────────────────────────────────────────────────────

async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "📢 <b>Xabar yuborish</b>\n\n"
        "Barcha foydalanuvchilarga yuboriladigan xabarni yozing:\n\n"
        "/cancel — bekor",
        parse_mode="HTML"
    )
    return BROADCAST_MSG

async def broadcast_send(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = db.get_all_users()
    sent = failed = blocked = 0
    for u in users:
        if u["is_blocked"]:
            blocked += 1
            continue
        try:
            await context.bot.copy_message(
                chat_id=u["id"],
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id,
            )
            db.reset_failed(u["id"])
            sent += 1
        except (Forbidden, BadRequest):
            db.increment_failed(u["id"])
            failed += 1
        except Exception as e:
            logger.error(f"Broadcast xatosi {u['id']}: {e}")
            failed += 1
    await update.message.reply_text(
        f"📢 <b>Yuborish yakunlandi</b>\n\n"
        f"✅ Yuborildi: <b>{sent}</b>\n"
        f"❌ Yuborilmadi: <b>{failed}</b>\n"
        f"🚫 Bloklangan: <b>{blocked}</b>",
        parse_mode="HTML"
    )
    return ConversationHandler.END

# ─── ADMIN: USER_SEND ────────────────────────────────────────────────────────

async def user_send_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "👤 <b>Foydalanuvchiga xabar yuborish</b>\n\n"
        "Foydalanuvchi <b>Telegram ID</b>sini yuboring:\n\n/cancel — bekor",
        parse_mode="HTML"
    )
    return USER_SEND_ID

async def user_send_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    if not t.lstrip("-").isdigit():
        await update.message.reply_text("❌ Faqat raqam kiriting.")
        return USER_SEND_ID
    context.user_data["send_to_id"] = int(t)
    await update.message.reply_text(
        f"✅ ID: <code>{t}</code>\n\nYuboriladigan xabarni yuboring:\n\n/cancel — bekor",
        parse_mode="HTML"
    )
    return USER_SEND_MSG

async def user_send_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = context.user_data.get("send_to_id")
    try:
        await context.bot.copy_message(
            chat_id=target,
            from_chat_id=update.effective_chat.id,
            message_id=update.message.message_id,
        )
        await update.message.reply_text(f"✅ Xabar <code>{target}</code> ga yuborildi.", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Yuborib bo'lmadi: {e}")
    return ConversationHandler.END

# ─── ADMIN: USER_SENDS ───────────────────────────────────────────────────────

async def user_sends_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Faol obunachilar",      callback_data="sends_active")],
        [InlineKeyboardButton("👥 Barcha foydalanuvchilar", callback_data="sends_all")],
    ])
    await update.message.reply_text(
        "📤 <b>Guruhli xabar</b>\n\nKimga yuborilsin?",
        reply_markup=kb, parse_mode="HTML"
    )

async def user_sends_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    context.user_data["sends_target"] = query.data
    await query.message.reply_text(
        "📝 Yuboriladigan xabarni yuboring:\n\n/cancel — bekor"
    )
    return BROADCAST_MSG

async def user_sends_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = context.user_data.get("sends_target", "sends_all")
    users  = db.get_all_users()
    sent = failed = skipped = 0

    for u in users:
        if u["is_blocked"]:
            skipped += 1
            continue
        if target == "sends_active" and not db.has_active_subscription(u["id"]):
            skipped += 1
            continue
        try:
            await context.bot.copy_message(
                chat_id=u["id"],
                from_chat_id=update.effective_chat.id,
                message_id=update.message.message_id,
            )
            db.reset_failed(u["id"])
            sent += 1
        except (Forbidden, BadRequest):
            db.increment_failed(u["id"])
            failed += 1
        except Exception:
            failed += 1

    label = "Faol obunachilar" if target == "sends_active" else "Barcha foydalanuvchilar"
    await update.message.reply_text(
        f"📤 <b>{label}ga yuborildi</b>\n\n"
        f"✅ Yuborildi: <b>{sent}</b>\n"
        f"❌ Yuborilmadi: <b>{failed}</b>\n"
        f"⏭ O'tkazib yuborildi: <b>{skipped}</b>",
        parse_mode="HTML"
    )
    return ConversationHandler.END

# ─── ADMIN: BLOCK / UNBLOCK ──────────────────────────────────────────────────

async def block_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "🚫 <b>Foydalanuvchini bloklash</b>\n\nUser ID yuboring:\n\n/cancel — bekor",
        parse_mode="HTML"
    )
    return BLOCK_USER_ID

async def block_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    if not t.lstrip("-").isdigit():
        await update.message.reply_text("❌ Faqat raqam kiriting.")
        return BLOCK_USER_ID
    db.mark_blocked(int(t))
    await update.message.reply_text(f"🚫 <code>{t}</code> bloklandi.", parse_mode="HTML")
    return ConversationHandler.END

async def unblock_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "✅ <b>Blokni ochish</b>\n\nUser ID yuboring:\n\n/cancel — bekor",
        parse_mode="HTML"
    )
    return BLOCK_USER_ID

async def unblock_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    if not t.lstrip("-").isdigit():
        await update.message.reply_text("❌ Faqat raqam kiriting.")
        return BLOCK_USER_ID
    db.unblock_user(int(t))
    await update.message.reply_text(f"✅ <code>{t}</code> blokdan chiqarildi.", parse_mode="HTML")
    return ConversationHandler.END

# ─── ADMIN: OBUNA BOSHQARISH ─────────────────────────────────────────────────

async def sub_manage_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "📅 <b>Obuna boshqarish</b>\n\nFoydalanuvchi ID yuboring:\n\n/cancel — bekor",
        parse_mode="HTML"
    )
    return SUB_MANAGE_ID

async def sub_manage_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    if not t.lstrip("-").isdigit():
        await update.message.reply_text("❌ Faqat raqam kiriting.")
        return SUB_MANAGE_ID
    uid = int(t)
    context.user_data["sub_uid"] = uid
    has_sub = db.has_active_subscription(uid)
    end     = db.get_subscription_end(uid)
    end_str = end.strftime("%d.%m.%Y") if end else "—"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Uzaytirish (oy)",    callback_data="sub_extend")],
        [InlineKeyboardButton("➖ Qisqartirish (kun)", callback_data="sub_reduce")],
    ])
    await update.message.reply_text(
        f"👤 ID: <code>{uid}</code>\n"
        f"📡 Obuna: {'✅ Faol' if has_sub else '❌ Faol emas'}\n"
        f"📅 Tugash: <b>{end_str}</b>\n\n"
        "Amalni tanlang:",
        reply_markup=kb, parse_mode="HTML"
    )
    return SUB_MANAGE_ACTION

async def sub_manage_action_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    action = query.data
    context.user_data["sub_action"] = action
    if action == "sub_extend":
        await query.message.reply_text("➕ Necha oy uzaytirilsin? (raqam):\n\n/cancel — bekor")
    else:
        await query.message.reply_text("➖ Necha kun qisqartirilsin? (raqam):\n\n/cancel — bekor")
    return SUB_MANAGE_ACTION

async def sub_manage_action_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    if not t.isdigit():
        await update.message.reply_text("❌ Faqat raqam kiriting.")
        return SUB_MANAGE_ACTION
    n      = int(t)
    uid    = context.user_data.get("sub_uid")
    action = context.user_data.get("sub_action")
    if action == "sub_extend":
        db.extend_subscription(uid, n)
        await update.message.reply_text(
            f"✅ <code>{uid}</code> obunasi <b>{n} oy</b> uzaytirildi.", parse_mode="HTML"
        )
        try:
            end = db.get_subscription_end(uid)
            await context.bot.send_message(
                uid,
                f"✅ Obunangiz <b>{n} oy</b> uzaytirildi!\n"
                f"📅 Yangi muddat: <b>{end.strftime('%d.%m.%Y')}</b>",
                parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        db.reduce_subscription(uid, n)
        await update.message.reply_text(
            f"✅ <code>{uid}</code> obunasi <b>{n} kun</b> qisqartirildi.", parse_mode="HTML"
        )
    return ConversationHandler.END

# ─── ADMIN: STATS ────────────────────────────────────────────────────────────

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    s   = db.get_stats()
    top = db.get_top_movies(5)
    top_text = ""
    for i, m in enumerate(top, 1):
        top_text += f"  {i}. <b>{m['name']}</b> — {m['request_count']} ta\n"
    if not top_text:
        top_text = "  Hali kino so'ralmagan."

    await update.message.reply_text(
        f"📊 <b>Bot statistikasi</b>\n\n"
        f"1️⃣ 🟢 Faol obunachilar: <b>{s['active_subs']}</b>\n"
        f"2️⃣ 👤 Oddiy foydalanuvchilar: <b>{s['ordinary']}</b>\n"
        f"3️⃣ 🚫 Bloklangan: <b>{s['blocked']}</b>\n"
        f"4️⃣ 👥 Jami: <b>{s['total']}</b>\n\n"
        f"🎬 Filmlar: <b>{s['total_movies']}</b>\n"
        f"💡 Takliflar: <b>{s['total_offers']}</b>\n\n"
        f"📈 <b>Top 5 kino:</b>\n{top_text}",
        parse_mode="HTML"
    )

# ─── ADMIN: SETTINGS ─────────────────────────────────────────────────────────

async def settings_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    price = db.get_setting("monthly_price") or "50000"
    card  = db.get_setting("card_number")   or "—"
    owner = db.get_setting("card_owner")    or "—"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 Oylik narx",   callback_data="set_price")],
        [InlineKeyboardButton("💳 Karta raqami", callback_data="set_card")],
        [InlineKeyboardButton("👤 Karta egasi",  callback_data="set_owner")],
    ])
    await update.message.reply_text(
        f"⚙️ <b>Sozlamalar</b>\n\n"
        f"💰 Oylik narx: <b>{fmt(int(price))} so'm</b>\n"
        f"💳 Karta: <code>{card}</code>\n"
        f"👤 Egasi: <b>{owner}</b>\n\n"
        "O'zgartirmoqchi bo'lgan narsani tanlang:",
        reply_markup=kb, parse_mode="HTML"
    )

async def settings_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    prompts = {
        "set_price": ("💰 Yangi oylik narxni yozing (faqat raqam):\nMasalan: <code>50000</code>",  "price"),
        "set_card":  ("💳 Yangi karta raqamini yozing:\nMasalan: <code>9800123412341234</code>",   "card"),
        "set_owner": ("👤 Karta egasining to'liq ismini yozing:\nMasalan: <code>ALISHER VALIYEV</code>", "owner"),
    }
    if query.data in prompts:
        text, mode = prompts[query.data]
        context.user_data["setting_mode"] = mode
        await query.message.reply_text(text + "\n\n/cancel — bekor qilish", parse_mode="HTML")

# ─── ADMIN MANAGEMENT ────────────────────────────────────────────────────────

async def addadmin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MAIN_ADMIN:
        await update.message.reply_text("❌ Faqat bosh admin uchun!")
        return ConversationHandler.END
    await update.message.reply_text(
        "👤 Yangi adminning <b>Telegram ID</b>sini yuboring:\n\n/cancel — bekor",
        parse_mode="HTML"
    )
    return ADD_ADMIN_ID

async def addadmin_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    if not t.lstrip("-").isdigit():
        await update.message.reply_text("❌ Faqat raqam kiriting.")
        return ADD_ADMIN_ID
    db.add_admin(int(t))
    await update.message.reply_text(f"✅ <code>{t}</code> — Admin qo'shildi!", parse_mode="HTML")
    return ConversationHandler.END

async def removeadmin_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != MAIN_ADMIN:
        await update.message.reply_text("❌ Faqat bosh admin uchun!")
        return ConversationHandler.END
    admins = db.get_admins()
    if not admins:
        await update.message.reply_text("⚠️ Qo'shimcha adminlar yo'q.")
        return ConversationHandler.END
    lines = "\n".join(f"• <code>{a}</code>" for a in admins)
    await update.message.reply_text(
        f"🚫 <b>Admin o'chirish</b>\n\nAdminlar:\n{lines}\n\nID yuboring:\n/cancel — bekor",
        parse_mode="HTML"
    )
    return REMOVE_ADMIN_ID

async def removeadmin_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t = update.message.text.strip()
    if not t.lstrip("-").isdigit():
        await update.message.reply_text("❌ Faqat raqam kiriting.")
        return REMOVE_ADMIN_ID
    aid = int(t)
    if aid == MAIN_ADMIN:
        await update.message.reply_text("❌ Bosh adminni o'chirib bo'lmaydi!")
        return REMOVE_ADMIN_ID
    db.remove_admin(aid)
    await update.message.reply_text(f"✅ <code>{aid}</code> — Admin o'chirildi!", parse_mode="HTML")
    return ConversationHandler.END

async def list_admins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    admins = db.get_admins()
    lines  = [f"👑 <code>{MAIN_ADMIN}</code> — Bosh admin"]
    lines += [f"👤 <code>{a}</code>" for a in admins]
    await update.message.reply_text(
        "<b>Adminlar ro'yxati:</b>\n\n" + "\n".join(lines), parse_mode="HTML"
    )

# ─── BACKUP & RESTORE ─────────────────────────────────────────────────────────

async def _send_backup_to_admin(bot, chat_id: int) -> bool:
    """ZIP backup yaratib berilgan chat_id ga yuboradi. True = muvaffaqiyat."""
    try:
        zip_bytes = backup_restore.create_backup_zip()
        filename  = backup_restore.backup_filename()
        await bot.send_document(
            chat_id=chat_id,
            document=io.BytesIO(zip_bytes),
            filename=filename,
            caption=(
                f"💾 <b>Kino Bot Backup</b>\n\n"
                f"🗓 Sana: <code>{datetime.now().strftime('%d.%m.%Y %H:%M')}</code>\n"
                f"📦 Fayl: <code>{filename}</code>\n\n"
                "Restore qilish uchun: /restore buyrug'ini yuboring va shu ZIP faylni jo'nating."
            ),
            parse_mode="HTML",
        )
        return True
    except Exception as e:
        logger.error(f"Backup yuborib bo'lmadi [{chat_id}]: {e}")
        return False

async def backup_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin tomonidan qo'lda backup yaratish."""
    if not is_admin(update.effective_user.id):
        return
    msg = await update.message.reply_text("⏳ Backup tayyorlanmoqda...")
    ok  = await _send_backup_to_admin(context.bot, update.effective_chat.id)
    if ok:
        await msg.edit_text("✅ Backup muvaffaqiyatli yuborildi!")
    else:
        await msg.edit_text("❌ Backup yaratishda xatolik. Log faylini tekshiring.")

async def restore_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Restore jarayonini boshlaydi — admin ZIP faylini yuborishi kutiladi."""
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text(
        "📥 <b>Backup'dan tiklash (Merge rejimi)</b>\n\n"
        "Backup ZIP faylini yuboring.\n\n"
        "⚠️ Faqat <code>.zip</code> fayl qabul qilinadi.\n"
        "ℹ️ Mavjud ma'lumotlar o'ZGARTIRILMAYDI — faqat yangilari qo'shiladi.\n\n"
        "/cancel — bekor",
        parse_mode="HTML"
    )
    return RESTORE_WAIT

async def restore_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin yuborgan ZIP faylni qabul qilib merge-restore bajaradi."""
    if not is_admin(update.effective_user.id):
        return ConversationHandler.END

    doc = update.message.document
    if not doc:
        await update.message.reply_text("❌ Fayl yuboring (ZIP format).")
        return RESTORE_WAIT

    if not doc.file_name.lower().endswith(".zip"):
        await update.message.reply_text(
            "❌ Faqat <code>.zip</code> fayl qabul qilinadi.\n\nQayta yuboring yoki /cancel.",
            parse_mode="HTML"
        )
        return RESTORE_WAIT

    msg = await update.message.reply_text("⏳ Restore jarayoni boshlandi, kuting...")

    try:
        tg_file   = await context.bot.get_file(doc.file_id)
        zip_bytes = await tg_file.download_as_bytearray()
        zip_bytes = bytes(zip_bytes)
    except Exception as e:
        await msg.edit_text(f"❌ Fayl yuklab olinmadi: {e}")
        return ConversationHandler.END

    try:
        result_stats = backup_restore.merge_restore(zip_bytes)
    except Exception as e:
        logger.error(f"Restore xatosi: {e}")
        await msg.edit_text(f"❌ Restore jarayonida xatolik:\n<code>{e}</code>", parse_mode="HTML")
        return ConversationHandler.END

    report = backup_restore.restore_stats_text(result_stats)
    await msg.edit_text(report, parse_mode="HTML")
    return ConversationHandler.END

# ─── AVTOMATIK HAFTALIK BACKUP (JobQueue) ────────────────────────────────────

async def auto_backup_job(context: ContextTypes.DEFAULT_TYPE):
    """Haftalik avtomatik backup — barcha adminlarga yuboriladi."""
    logger.info("⏰ Avtomatik haftalik backup boshlandi...")
    all_admins = set([MAIN_ADMIN] + db.get_admins())
    for aid in all_admins:
        ok = await _send_backup_to_admin(context.bot, aid)
        if ok:
            logger.info(f"✅ Backup {aid} ga yuborildi")
        else:
            logger.warning(f"⚠️ Backup {aid} ga yuborilmadi")

# ─── CANCEL ──────────────────────────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("setting_mode", None)
    context.user_data.pop("promo_action", None)
    context.user_data.pop("sends_target", None)
    context.user_data.pop("from_pay", None)
    await update.message.reply_text("❌ Bekor qilindi.")
    return ConversationHandler.END

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    db.init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    # ── /start + payment flow ────────────────────────────────────────────────
    payment_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            PAY_CHOOSE_PLAN: [
                CallbackQueryHandler(plan_chosen,   pattern=r"^plan_\d+$"),
                CallbackQueryHandler(prompt_check,  pattern="^send_check$"),
                CallbackQueryHandler(show_pay_menu, pattern="^back_to_plans$"),
                CallbackQueryHandler(plan_chosen,   pattern="^has_code$"),
                CallbackQueryHandler(plan_chosen,   pattern="^enter_promo$"),
            ],
            PAY_WAIT_CHECK: [
                MessageHandler(filters.PHOTO | filters.Document.ALL, receive_check),
                MessageHandler(filters.TEXT & ~filters.COMMAND, promo_enter),
                CallbackQueryHandler(show_pay_menu, pattern="^back_to_plans$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ── /add movie ───────────────────────────────────────────────────────────
    add_conv = ConversationHandler(
        entry_points=[CommandHandler("add", add_start)],
        states={
            ADD_VIDEO:   [MessageHandler(filters.VIDEO | filters.Document.ALL, add_video)],
            ADD_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, add_name)],
            ADD_QUALITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_quality)],
            ADD_YEAR:    [MessageHandler(filters.TEXT & ~filters.COMMAND, add_year)],
            ADD_LANG:    [MessageHandler(filters.TEXT & ~filters.COMMAND, add_lang)],
            ADD_RATING:  [MessageHandler(filters.TEXT & ~filters.COMMAND, add_rating)],
            ADD_CODE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_code),
                CallbackQueryHandler(movie_confirm, pattern="^movie_(save|cancel)$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ── /delete ──────────────────────────────────────────────────────────────
    delete_conv = ConversationHandler(
        entry_points=[CommandHandler("delete", delete_start)],
        states={DELETE_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_code)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ── /broadcast ───────────────────────────────────────────────────────────
    broadcast_conv = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_start)],
        states={BROADCAST_MSG: [MessageHandler(~filters.COMMAND, broadcast_send)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ── /addadmin ────────────────────────────────────────────────────────────
    addadmin_conv = ConversationHandler(
        entry_points=[CommandHandler("addadmin", addadmin_start)],
        states={ADD_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, addadmin_id)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ── /removeadmin ─────────────────────────────────────────────────────────
    removeadmin_conv = ConversationHandler(
        entry_points=[CommandHandler("removeadmin", removeadmin_start)],
        states={REMOVE_ADMIN_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, removeadmin_id)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ── /promo (foydalanuvchi) ───────────────────────────────────────────────
    promo_conv = ConversationHandler(
        entry_points=[CommandHandler("promo", promo_start)],
        states={PROMO_ENTER: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_enter)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ── /offers ──────────────────────────────────────────────────────────────
    offers_conv = ConversationHandler(
        entry_points=[CommandHandler("offers", offers_start)],
        states={OFFERS_ENTER: [MessageHandler(filters.TEXT & ~filters.COMMAND, offers_receive)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ── /admin_send ──────────────────────────────────────────────────────────
    admin_send_conv = ConversationHandler(
        entry_points=[CommandHandler("admin_send", admin_send_start)],
        states={ADMIN_REQUEST_ENTER: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_send_receive)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ── /user_send (admin) ───────────────────────────────────────────────────
    user_send_conv = ConversationHandler(
        entry_points=[CommandHandler("user_send", user_send_start)],
        states={
            USER_SEND_ID:  [MessageHandler(filters.TEXT & ~filters.COMMAND, user_send_id)],
            USER_SEND_MSG: [MessageHandler(~filters.COMMAND, user_send_msg)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ── /block ───────────────────────────────────────────────────────────────
    block_conv = ConversationHandler(
        entry_points=[CommandHandler("block", block_start)],
        states={BLOCK_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, block_receive)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ── /unblock ─────────────────────────────────────────────────────────────
    unblock_conv = ConversationHandler(
        entry_points=[CommandHandler("unblock", unblock_start)],
        states={BLOCK_USER_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, unblock_receive)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ── /sub_manage ──────────────────────────────────────────────────────────
    sub_manage_conv = ConversationHandler(
        entry_points=[CommandHandler("sub_manage", sub_manage_start)],
        states={
            SUB_MANAGE_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, sub_manage_id)],
            SUB_MANAGE_ACTION: [
                CallbackQueryHandler(sub_manage_action_cb, pattern="^sub_(extend|reduce)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, sub_manage_action_msg),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ── /setversion ──────────────────────────────────────────────────────────
    setversion_conv = ConversationHandler(
        entry_points=[CommandHandler("setversion", setversion_start)],
        states={BOT_VERSION_SET: [MessageHandler(filters.TEXT & ~filters.COMMAND, setversion_receive)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ── /user_sends (admin) ──────────────────────────────────────────────────
    user_sends_broadcast = ConversationHandler(
        entry_points=[CommandHandler("user_sends", user_sends_start)],
        states={BROADCAST_MSG: [MessageHandler(~filters.COMMAND, user_sends_msg)]},
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # ── /restore ─────────────────────────────────────────────────────────────
    restore_conv = ConversationHandler(
        entry_points=[CommandHandler("restore", restore_start)],
        states={
            RESTORE_WAIT: [
                MessageHandler(filters.Document.ALL, restore_receive),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    # Barcha conversation handler'larni qo'shamiz
    for conv in [
        payment_conv, add_conv, delete_conv, broadcast_conv,
        addadmin_conv, removeadmin_conv, promo_conv, offers_conv,
        admin_send_conv, user_send_conv, block_conv, unblock_conv,
        sub_manage_conv, setversion_conv, user_sends_broadcast,
        restore_conv,   # ← YANGI
    ]:
        app.add_handler(conv)

    # Standalone commands
    app.add_handler(CommandHandler("stats",       stats))
    app.add_handler(CommandHandler("settings",    settings_cmd))
    app.add_handler(CommandHandler("admins",      list_admins))
    app.add_handler(CommandHandler("cancel",      cancel))
    app.add_handler(CommandHandler("profile",     profile))
    app.add_handler(CommandHandler("sub",         sub_info))
    app.add_handler(CommandHandler("bot",         bot_version))
    app.add_handler(CommandHandler("list",        cmd_list))
    app.add_handler(CommandHandler("favorites",   cmd_favorites))
    app.add_handler(CommandHandler("mystats",     my_stats))
    app.add_handler(CommandHandler("promo_admin", promo_admin_start))
    app.add_handler(CommandHandler("backup",      backup_cmd))   # ← YANGI

    # Callbacks
    app.add_handler(CallbackQueryHandler(payment_decision,     pattern=r"^(approve|reject)_\d+$"))
    app.add_handler(CallbackQueryHandler(settings_cb,          pattern=r"^set_(price|card|owner)$"))
    app.add_handler(CallbackQueryHandler(rate_cb,              pattern=r"^rate_"))
    app.add_handler(CallbackQueryHandler(favorites_cb,         pattern=r"^fav_"))
    app.add_handler(CallbackQueryHandler(promo_admin_cb,       pattern=r"^promo_(add|delete)$"))
    app.add_handler(CallbackQueryHandler(admin_request_accept, pattern=r"^req_accept_"))
    app.add_handler(CallbackQueryHandler(user_sends_cb,        pattern=r"^sends_(active|all)$"))

    # Umumiy matn
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    #app.add_handler(group_listener)

    # ── Haftalik avtomatik backup (har Dushanba soat 03:00 da) ───────────────
    job_queue = app.job_queue
    if job_queue is not None:
        job_queue.run_repeating(
            callback=auto_backup_job,
            interval=timedelta(weeks=1),    # har hafta
            first=timedelta(seconds=60),    # botni ishga tushirgandan 60 soniya keyin birinchi marta
            name="weekly_backup",
        )
        logger.info("✅ Haftalik backup job queue ga qo'shildi (interval: 7 kun)")
    else:
        logger.warning(
            "⚠️ JobQueue ishlamayapti! "
            "'pip install python-telegram-bot[job-queue]' buyrug'ini bajaring."
        )

    logger.info("🎬 Kino Bot v1.2.9 ishga tushdi!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
