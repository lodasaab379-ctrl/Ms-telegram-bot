# main.py
# DailyEarnBot – PTB v20+, SQLite, Render keep_alive

import os
import asyncio
import logging
import sqlite3
from datetime import datetime, date
from typing import Optional, Tuple
from threading import Thread

from flask import Flask
from telegram import (
    Update,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler,
    ContextTypes, filters,
)

# -------------------- KEEP-ALIVE (Render) --------------------
_flask = Flask("keep_alive")

@_flask.route("/")
def _home():
    return "✅ Bot server is alive!"

def keep_alive():
    port = int(os.environ.get("PORT", 8080))   # Render injects PORT
    Thread(target=lambda: _flask.run(host="0.0.0.0", port=port)).start()

# -------------------- CONFIG --------------------
TOKEN = os.getenv("")  # <-- set this in Render dashboard
if not TOKEN:
    raise RuntimeErro8208891679:AAE6j5aVkxE8SsAJyLnM_Uhy823qFSR7SoEr("BOT_TOKEN env var not set!")

ADMIN_IDS = [5567349252]               # add more if needed

GOAL_USERS = 10_000
FIRST_N_CAN_WITHDRAW = 10_000

JOIN_BONUS_COINS = 25
REFERRAL_BONUS_COINS = 25
DAILY_BONUS_COINS = 5

SLABS = [(1000, 10), (5000, 50), (10000, 100)]  # (coins -> INR)

TASKS = [
    ("👍 Join our updates channel", 10),
    ("💬 Say hi in the group", 10),
    ("📢 Share your referral link with a friend", 15),
]

DB_PATH = "bot.db"

# Withdraw conversation states
CHOOSE_SLAB, CHOOSE_METHOD, ENTER_UPI, CONFIRM = range(4)

# -------------------- LOGGING --------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("DailyEarnBot")

# -------------------- DB HELPERS --------------------
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as conn:
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
              user_id INTEGER PRIMARY KEY,
              first_name TEXT,
              coins INTEGER DEFAULT 0,
              referrals INTEGER DEFAULT 0,
              joined_at TEXT,
              referred_by INTEGER,
              last_daily TEXT,
              upi_method TEXT,
              upi_address TEXT,
              reg_index INTEGER
            );
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS withdrawals (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER,
              coins INTEGER,
              amount INTEGER,
              method TEXT,
              address TEXT,
              status TEXT,
              created_at TEXT,
              decided_at TEXT,
              admin_id INTEGER
            );
            """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              title TEXT,
              coins INTEGER
            );
            """
        )
        # seed tasks
        cur = c.execute("SELECT COUNT(*) AS n FROM tasks").fetchone()
        if cur["n"] == 0:
            c.executemany("INSERT INTO tasks(title, coins) VALUES(?,?)", TASKS)
        conn.commit()

def get_user(conn: sqlite3.Connection, user_id: int) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()

def total_users(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()
    return row["n"] if row else 0

def eligible_to_withdraw(conn: sqlite3.Connection, user_id: int) -> Tuple[bool, str]:
    t = total_users(conn)
    if t < GOAL_USERS:
        return (
            False,
            f"⏳ Withdrawals open after {GOAL_USERS:,} users join.\n"
            f"Current: {t:,}/{GOAL_USERS:,}. Share your link to reach the goal faster!"
        )
    row = conn.execute("SELECT reg_index FROM users WHERE user_id=?", (user_id,)).fetchone()
    if not row:
        return False, "Please /start again."
    if row["reg_index"] > FIRST_N_CAN_WITHDRAW:
        return False, f"❌ Only the first {FIRST_N_CAN_WITHDRAW:,} registered users can withdraw."
    return True, "OK"

def add_coins(conn: sqlite3.Connection, user_id: int, amount: int):
    conn.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (amount, user_id))
    conn.commit()

# -------------------- UI HELPERS --------------------
def main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("💰 Balance"), KeyboardButton("🎯 Daily Bonus")],
            [KeyboardButton("🧩 Tasks"), KeyboardButton("👥 Referral")],
            [KeyboardButton("💳 Withdraw"), KeyboardButton("🏆 Leaderboard")],
            [KeyboardButton("📜 History"), KeyboardButton("📈 Stats")],
            [KeyboardButton("❓ FAQ")],
        ],
        resize_keyboard=True,
    )

def withdraw_slab_kb(user_coins: int) -> InlineKeyboardMarkup:
    buttons = []
    for coins, amount in SLABS:
        if user_coins >= coins:
            buttons.append([InlineKeyboardButton(f"{coins} coins → ₹{amount}", callback_data=f"slab:{coins}:{amount}")])
    if not buttons:
        buttons = [[InlineKeyboardButton("Not enough coins", callback_data="noop")]]
    return InlineKeyboardMarkup(buttons)

def withdraw_method_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("UPI (GPay)", callback_data="method:GPay")],
            [InlineKeyboardButton("UPI (PhonePe)", callback_data="method:PhonePe")],
            [InlineKeyboardButton("Paytm UPI", callback_data="method:Paytm")],
        ]
    )

# -------------------- USER COMMANDS --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    init_db()
    user = update.effective_user
    ref_id = None
    if context.args:
        try:
            ref_id = int(context.args[0])
        except Exception:
            ref_id = None

    with db() as conn:
        row = get_user(conn, user.id)
        if not row:
            idx = total_users(conn) + 1
            conn.execute(
                """
                INSERT INTO users(user_id, first_name, coins, referrals, joined_at, referred_by, reg_index)
                VALUES(?,?,?,?,?,?,?)
                """,
                (
                    user.id, user.first_name or "", 0, 0,
                    datetime.utcnow().isoformat(),
                    ref_id if ref_id and ref_id != user.id else None,
                    idx,
                ),
            )
            conn.commit()

            add_coins(conn, user.id, JOIN_BONUS_COINS)

            if ref_id and ref_id != user.id and get_user(conn, ref_id):
                add_coins(conn, ref_id, REFERRAL_BONUS_COINS)
                conn.execute("UPDATE users SET referrals = referrals + 1 WHERE user_id=?", (ref_id,))
                conn.commit()
                try:
                    await context.bot.send_message(
                        ref_id,
                        f"🎉 New referral joined: {user.first_name or user.id}\n"
                        f"+{REFERRAL_BONUS_COINS} coins added to your balance!",
                    )
                except Exception:
                    pass

    text = (
        "🚀 *Welcome to DailyEarnBot!*\n\n"
        f"• Joining bonus: *{JOIN_BONUS_COINS} coins*\n"
        f"• Referral bonus: *{REFERRAL_BONUS_COINS} coins*\n"
        "• Claim daily bonus & complete tasks.\n\n"
        f"💡 *Withdraw rule:* After *{GOAL_USERS:,}* total users join, "
        f"and only the *first {FIRST_N_CAN_WITHDRAW:,}* registered users can withdraw.\n\n"
        "Use the menu below 👇"
    )
    await update.message.reply_text(text, reply_markup=main_menu_kb(), parse_mode="Markdown")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Commands:\n"
        "/start – open menu\n"
        "/balance – show coins\n"
        "/tasks – daily tasks\n"
        "/daily – claim daily bonus\n"
        "/withdraw – request payout\n"
        "/refer – your referral link\n"
        "/leaderboard – top referrers\n"
        "/history – your withdrawals\n"
        "/stats – bot stats\n"
        "/faq – common questions\n"
        "/admin – admin panel (admins only)"
    )

async def faq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "❓ *FAQ*\n\n"
        f"• When can I withdraw?\n"
        f"  ➜ After *{GOAL_USERS:,}* total users, and only first *{FIRST_N_CAN_WITHDRAW:,}* users.\n\n"
        "• Slabs?\n"
        "  ➜ 1000→₹10, 5000→₹50, 10000→₹100.\n\n"
        "• How to earn?\n"
        "  ➜ Daily bonus, tasks, referrals.\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as conn:
        u = get_user(conn, update.effective_user.id)
        if not u:
            await update.message.reply_text("Please /start first.")
            return
        t = total_users(conn)
        text = (
            f"💰 Your Balance: *{u['coins']}* coins\n"
            f"👥 Referrals: *{u['referrals']}*\n\n"
            f"📊 Progress: *{t:,}* / *{GOAL_USERS:,}* joined\n"
            f"⚡ Spots left for withdraw eligibility: *{max(FIRST_N_CAN_WITHDRAW - t, 0):,}*\n\n"
            "Keep inviting to open withdrawals sooner!"
        )
        await update.message.reply_text(text, parse_mode="Markdown")

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as conn:
        u = get_user(conn, update.effective_user.id)
        if not u:
            await update.message.reply_text("Please /start first.")
            return
        today = date.today().isoformat()
        if u["last_daily"] == today:
            await update.message.reply_text("✅ You already claimed today’s daily bonus. Come back tomorrow!")
            return
        add_coins(conn, u["user_id"], DAILY_BONUS_COINS)
        conn.execute("UPDATE users SET last_daily=? WHERE user_id=?", (today, u["user_id"]))
        conn.commit()
    await update.message.reply_text(f"🎁 Daily bonus claimed: +{DAILY_BONUS_COINS} coins!")

async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as conn:
        rows = conn.execute("SELECT id, title, coins FROM tasks ORDER BY id").fetchall()
    if not rows:
        await update.message.reply_text("No tasks right now. Check later!")
        return
    lines = ["🧩 *Daily Tasks*\n"]
    for r in rows:
        lines.append(f"• {r['title']} – *+{r['coins']} coins* (reply: `done {r['id']}`)")
    lines.append("\nExample: `done 1` after you finish task 1.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def task_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parts = (update.message.text or "").strip().split()
    if len(parts) != 2 or parts[0].lower() != "done":
        return
    try:
        task_id = int(parts[1])
    except Exception:
        return

    with db() as conn:
        t = conn.execute("SELECT id, coins FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not t:
            await update.message.reply_text("Task not found.")
            return
        key = f"task:{task_id}:{date.today().isoformat()}"
        context.user_data.setdefault("done", set())
        if key in context.user_data["done"]:
            await update.message.reply_text("You already claimed this task today.")
            return
        context.user_data["done"].add(key)
        add_coins(conn, update.effective_user.id, t["coins"])
        coins_added = t["coins"]
    await update.message.reply_text(f"✅ Task {task_id} verified. +{coins_added} coins added!")

async def refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start={uid}"
    await update.message.reply_text(
        "👥 *Invite & Earn*\n"
        f"Share your link:\n{link}\n\n"
        f"Earn *{REFERRAL_BONUS_COINS}* coins per friend.\n"
        f"Only first {FIRST_N_CAN_WITHDRAW:,} users can withdraw once total users reach {GOAL_USERS:,}.",
        parse_mode="Markdown",
    )

async def history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as conn:
        rows = conn.execute(
            "SELECT id, coins, amount, method, address, status, created_at "
            "FROM withdrawals WHERE user_id=? ORDER BY id DESC LIMIT 10",
            (update.effective_user.id,),
        ).fetchall()
    if not rows:
        await update.message.reply_text("No withdrawals yet.")
        return
    lines = ["📜 *Your last withdrawals:*"]
    for r in rows:
        lines.append(
            f"• #{r['id']} – {r['coins']} coins → ₹{r['amount']} via {r['method']} ({r['status']})"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as conn:
        t = total_users(conn)
        pend = conn.execute("SELECT COUNT(*) AS n FROM withdrawals WHERE status='PENDING'").fetchone()["n"]
        paid = conn.execute("SELECT COUNT(*) AS n FROM withdrawals WHERE status='APPROVED'").fetchone()["n"]
    await update.message.reply_text(
        f"📈 *Live Stats*\n"
        f"Total users: *{t:,}*\n"
        f"Pending withdrawals: *{pend}*\n"
        f"Approved withdrawals: *{paid}*",
        parse_mode="Markdown",
    )

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as conn:
        rows = conn.execute(
            "SELECT first_name, referrals FROM users ORDER BY referrals DESC, user_id ASC LIMIT 10"
        ).fetchall()
    if not rows:
        await update.message.reply_text("No data yet.")
        return
    lines = ["🏆 *Top Referrers*"]
    for i, r in enumerate(rows, 1):
        name = r["first_name"] or "User"
        lines.append(f"{i}. {name} – {r['referrals']} refs")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

# -------------------- WITHDRAW FLOW --------------------
async def withdraw_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as conn:
        ok, reason = eligible_to_withdraw(conn, update.effective_user.id)
        if not ok:
            await update.message.reply_text(reason)
            return ConversationHandler.END
        u = get_user(conn, update.effective_user.id)
        coins = u["coins"]

    await update.message.reply_text(
        "Select a withdrawal slab you qualify for:",
        reply_markup=withdraw_slab_kb(coins),
    )
    return CHOOSE_SLAB

async def choose_slab_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()

    if q.data == "noop":
        await q.edit_message_text("You don't have enough coins for any slab yet.")
        return ConversationHandler.END

    _, coins, amount = q.data.split(":")
    context.user_data["withdraw"] = {"coins": int(coins), "amount": int(amount)}
    await q.edit_message_text(
        f"Selected: {coins} coins → ₹{amount}\n\nChoose payment method:",
        reply_markup=withdraw_method_kb(),
    )
    return CHOOSE_METHOD

async def choose_method_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    _, method = q.data.split(":")
    context.user_data["withdraw"]["method"] = method
    await q.edit_message_text(
        f"Payment method: {method}\n\nPlease send your *UPI ID* (e.g., name@okaxis).",
        parse_mode="Markdown",
    )
    return ENTER_UPI

async def enter_upi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upi = (update.message.text or "").strip()
    if "@" not in upi or len(upi) < 6:
        await update.message.reply_text("Please send a valid UPI ID.")
        return ENTER_UPI
    context.user_data["withdraw"]["upi"] = upi
    w = context.user_data["withdraw"]
    await update.message.reply_text(
        "Confirm your request:\n"
        f"• Coins: {w['coins']}\n"
        f"• Amount: ₹{w['amount']}\n"
        f"• Method: {w['method']}\n"
        f"• UPI: {w['upi']}\n\n"
        "Type *yes* to confirm or *no* to cancel.",
        parse_mode="Markdown",
    )
    return CONFIRM

async def confirm_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if (update.message.text or "").strip().lower() != "yes":
        await update.message.reply_text("Cancelled.")
        return ConversationHandler.END

    w = context.user_data.get("withdraw")
    if not w:
        await update.message.reply_text("Something went wrong. Try again.")
        return ConversationHandler.END

    uid = update.effective_user.id
    with db() as conn:
        u = get_user(conn, uid)
        if not u or u["coins"] < w["coins"]:
            await update.message.reply_text("Not enough coins now. Try again.")
            return ConversationHandler.END

        # deduct & create request
        conn.execute(
            "UPDATE users SET coins = coins - ?, upi_method=?, upi_address=? WHERE user_id=?",
            (w["coins"], w["method"], w["upi"], uid),
        )
        conn.execute(
            "INSERT INTO withdrawals(user_id, coins, amount, method, address, status, created_at) "
            "VALUES(?,?,?,?,?,'PENDING',?)",
            (uid, w["coins"], w["amount"], w["method"], w["upi"], datetime.utcnow().isoformat()),
        )
        conn.commit()

    await update.message.reply_text("🔄 Your withdrawal request is submitted for admin approval.")
    for admin in ADMIN_IDS:
        try:
            await context.bot.send_message(
                admin,
                f"🆕 Withdrawal Request\n"
                f"User: {uid}\n"
                f"Coins: {w['coins']} → ₹{w['amount']}\n"
                f"Method: {w['method']}\n"
                f"UPI: {w['upi']}\n"
                f"Approve: /approve {uid}\nReject: /reject {uid}",
            )
        except Exception:
            pass

    return ConversationHandler.END

async def cancel_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END

# -------------------- ADMIN --------------------
def admin_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else 0
        if uid not in ADMIN_IDS:
            await update.message.reply_text("Admins only.")
            return
        return await func(update, context)
    return wrapper

@admin_only
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👮 Admin panel:\n"
        "/redeems – list pending withdrawals\n"
        "/approve <user_id> – approve latest pending of user\n"
        "/reject <user_id> – reject latest pending (refund)\n"
        "/addcoins <user_id> <coins> – add coins to user\n"
        "/broadcast <text> – send message to all users\n"
        "/stats – overall stats"
    )

@admin_only
async def redeems(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with db() as conn:
        rows = conn.execute(
            "SELECT id, user_id, coins, amount, method, address, created_at "
            "FROM withdrawals WHERE status='PENDING' ORDER BY id ASC LIMIT 20"
        ).fetchall()
    if not rows:
        await update.message.reply_text("No pending withdrawals.")
        return
    lines = ["🟡 *Pending withdrawals:*"]
    for r in rows:
        lines.append(
            f"• #{r['id']} | user {r['user_id']} | {r['coins']}→₹{r['amount']} | {r['method']} {r['address']}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

@admin_only
async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /approve <user_id>")
        return
    uid = int(context.args[0])
    with db() as conn:
        r = conn.execute(
            "SELECT id FROM withdrawals WHERE user_id=? AND status='PENDING' ORDER BY id DESC LIMIT 1",
            (uid,),
        ).fetchone()
        if not r:
            await update.message.reply_text("No pending request for that user.")
            return
        conn.execute(
            "UPDATE withdrawals SET status='APPROVED', decided_at=?, admin_id=? WHERE id=?",
            (datetime.utcnow().isoformat(), update.effective_user.id, r["id"]),
        )
        conn.commit()
    await update.message.reply_text(f"✅ Approved withdrawal for user {uid}.")
    try:
        await context.bot.send_message(uid, "✅ Your withdrawal was *approved*. Expect funds soon.")
    except Exception:
        pass

@admin_only
async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /reject <user_id>")
        return
    uid = int(context.args[0])
    with db() as conn:
        r = conn.execute(
            "SELECT id, coins FROM withdrawals WHERE user_id=? AND status='PENDING' ORDER BY id DESC LIMIT 1",
            (uid,),
        ).fetchone()
        if not r:
            await update.message.reply_text("No pending request for that user.")
            return
        conn.execute("UPDATE users SET coins = coins + ? WHERE user_id=?", (r["coins"], uid))
        conn.execute(
            "UPDATE withdrawals SET status='REJECTED', decided_at=?, admin_id=? WHERE id=?",
            (datetime.utcnow().isoformat(), update.effective_user.id, r["id"]),
        )
        conn.commit()
    await update.message.reply_text(f"❌ Rejected withdrawal for user {uid}. Refunded coins.")
    try:
        await context.bot.send_message(uid, "❌ Your withdrawal was *rejected*. Coins refunded.")
    except Exception:
        pass

@admin_only
async def addcoins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /addcoins <user_id> <coins>")
        return
    uid = int(context.args[0])
    amt = int(context.args[1])
    with db() as conn:
        add_coins(conn, uid, amt)
    await update.message.reply_text(f"✅ Added {amt} coins to user {uid}.")

@admin_only
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    text = " ".join(context.args)
    sent = 0
    with db() as conn:
        ids = [r["user_id"] for r in conn.execute("SELECT user_id FROM users").fetchall()]
    for uid in ids:
        try:
            await context.bot.send_message(uid, f"📢 {text}")
            sent += 1
            await asyncio.sleep(0.03)
        except Exception:
            pass
    await update.message.reply_text(f"Broadcast sent to {sent} users.")

# -------------------- TEXT BUTTON HANDLER --------------------
async def text_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (update.message.text or "").strip().lower()
    if "balance" in txt:
        await balance(update, context)
    elif "daily" in txt:
        await daily(update, context)
    elif "tasks" in txt:
        await tasks(update, context)
    elif "referral" in txt or "refer" in txt:
        await refer(update, context)
    elif "withdraw" in txt:
        await withdraw_entry(update, context)
    elif "leaderboard" in txt:
        await leaderboard(update, context)
    elif "history" in txt:
        await history(update, context)
    elif "stats" in txt:
        await stats(update, context)
    elif "faq" in txt:
        await faq(update, context)
    else:
        await help_cmd(update, context)

# -------------------- WIRING --------------------
def build_app() -> Application:
    app = Application.builder().token(TOKEN).build()

    # Core commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("faq", faq))
    app.add_handler(CommandHandler("balance", balance))
    app.add_handler(CommandHandler("daily", daily))
    app.add_handler(CommandHandler("tasks", tasks))
    app.add_handler(CommandHandler("refer", refer))
    app.add_handler(CommandHandler("history", history))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("leaderboard", leaderboard))

    # Admin commands
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("redeems", redeems))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject", reject))
    app.add_handler(CommandHandler("addcoins", addcoins))
    app.add_handler(CommandHandler("broadcast", broadcast))

    # Task completion (user types: done 1)
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex(r"^done\s+\d+$"), task_done))

    # Withdraw conversation
    conv = ConversationHandler(
        entry_points=[CommandHandler("withdraw", withdraw_entry)],
        states={
            CHOOSE_SLAB: [CallbackQueryHandler(choose_slab_cb, pattern=r"^(slab:|noop$)")],
            CHOOSE_METHOD: [CallbackQueryHandler(choose_method_cb, pattern=r"^method:")],
            ENTER_UPI: [MessageHandler(filters.TEXT & ~filters.COMMAND, enter_upi)],
            CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_withdraw)],
        },
        fallbacks=[CommandHandler("cancel", cancel_withdraw)],
        allow_reentry=True,
    )
    app.add_handler(conv)

    # Reply-keyboard buttons (must be last)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_buttons))
    return app

def main():
    init_db()
    application = build_app()
    log.info("Bot is running…")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

# -------------------- ENTRYPOINT --------------------
if __name__ == "__main__":
    keep_alive()  # keeps Render dyno alive, binds PORT
    main()
