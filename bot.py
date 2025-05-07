import logging
import asyncio
import json
import os
import re
import nest_asyncio
from datetime import datetime, timedelta
from telegram import Update, Message, ChatMember
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)
from telegram.error import TelegramError

nest_asyncio.apply()
logging.basicConfig(level=logging.WARNING)

BOT_TOKEN = "8087324556:AAHA3be2HtQ1P3thT2JPdu-49YKDV9C9TgQ"
OWNER_ID = 1420080384  # Replace with your Telegram user ID
SETTINGS_FILE = "group_settings.json"
BACKUP_CHANNEL_ID = -1002427674407  # Your backup channel ID

# === CONFIG FUNCTIONS ===
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)

group_settings = load_settings()

def get_group_config(group_id: str):
    if group_id not in group_settings:
        group_settings[group_id] = {
            "admin_delete_time": None,
            "whitelist": [],
            "scheduled_time": None,
            "scheduled_duration": None,
            "scheduled_off_time": None
        }
        save_settings(group_settings)
    return group_settings[group_id]

# === UTILITIES ===
def parse_time_from_caption(caption: str) -> int | None:
    match = re.search(r"(\d+)([smh])", caption.lower())
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    return value * {"s": 1, "m": 60, "h": 3600}.get(unit, 0)

async def is_admin(update: Update, user_id: int) -> bool:
    try:
        member: ChatMember = await update.effective_chat.get_member(user_id)
        return member.status in ("administrator", "creator")
    except Exception as e:
        logging.warning(f"Admin check failed: {e}")
        return False

# === DELETE + SCHEDULE ===
async def delete_after_delay(context, chat_id, message_id, delay):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id, message_id)
    except Exception as e:
        logging.warning(f"Delete failed: {e}")

async def schedule_loop(app):
    while True:
        now = datetime.utcnow() + timedelta(hours=6)  # Bangladesh time (UTC+6)
        now_str = now.strftime("%H:%M")
        for group_id, config in group_settings.items():
            if config.get("scheduled_time") == now_str:
                config["admin_delete_time"] = config["scheduled_duration"]
                try:
                    await app.bot.send_message(chat_id=int(group_id),
                        text=f"⏱ Auto-delete timer set to {config['scheduled_duration'] // 60} minutes by schedule.\nUse /scheduleoff HH:MM to stop schedule.")
                except:
                    pass
            if config.get("scheduled_off_time") == now_str:
                config["admin_delete_time"] = None
                try:
                    await app.bot.send_message(chat_id=int(group_id),
                        text="⏹ Scheduled timer turned off. Timer restored to group default.")
                except:
                    pass
        save_settings(group_settings)
        await asyncio.sleep(60)

# === MEDIA HANDLER ===
async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message: Message = update.message
    if not message or not message.from_user:
        return

    user = message.from_user
    user_id = user.id
    username = f"@{user.username}" if user.username else user.full_name
    chat_id = str(message.chat_id)
    caption = message.caption or ""
    message_id = message.message_id
    config = get_group_config(chat_id)
    whitelist = config["whitelist"]
    delete_time = config["admin_delete_time"]

    # === BACKUP TO CHANNEL ===
    try:
        group_title = update.effective_chat.title or "Unnamed Group"
        user_tag = (
            f"🆔 Group: {group_title}\n"
            f"👤 User ID: {user_id}\n"
            f"🙋 Name: {username}"
        )
        if message.photo:
            await context.bot.send_photo(
                chat_id=BACKUP_CHANNEL_ID,
                photo=message.photo[-1].file_id,
                caption=user_tag
            )
        elif message.video:
            await context.bot.send_video(
                chat_id=BACKUP_CHANNEL_ID,
                video=message.video.file_id,
                caption=user_tag
            )
    except Exception as e:
        logging.warning(f"Backup failed: {e}")

# === DELETE TIMER LOGIC ===
    try:
        custom_time = parse_time_from_caption(caption)
        is_group_admin = await is_admin(update, user_id)
        is_whitelisted = user_id in whitelist or is_group_admin

        if is_whitelisted:
            if custom_time:
                delay = custom_time
            else:
                return
        else:
            if custom_time and (delete_time is None or custom_time <= delete_time):
                delay = custom_time
            elif delete_time is not None:
                delay = delete_time
            else:
                return

        asyncio.create_task(delete_after_delay(context, message.chat_id, message_id, delay))
    except Exception as e:
        logging.warning(f"Timer logic failed: {e}")

# === COMMAND HANDLERS ===
async def set_timer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user_id = update.effective_user.id
    if not await is_admin(update, user_id):
        return await update.message.reply_text("Only admins can set the timer.")
    if not context.args:
        return await update.message.reply_text("Usage: /settimer <duration like 30s, 5m, 1h or 'off'>")
    
    config = get_group_config(chat_id)
    arg = context.args[0].lower()
    
    if arg == "off":
        config["admin_delete_time"] = None
        await update.message.reply_text("⏸ Auto-delete timer is now OFF.")
    else:
        try:
            duration = 0
            if 'h' in arg:
                duration += int(arg.replace("h", "")) * 3600
            elif 'm' in arg:
                duration += int(arg.replace("m", "")) * 60
            elif 's' in arg:
                duration += int(arg.replace("s", ""))
            else:
                duration += int(arg) * 60  # Default fallback to minutes if no unit

            config["admin_delete_time"] = duration

            hours = duration // 3600
            minutes = (duration % 3600) // 60
            seconds = duration % 60

            msg_parts = []
            if hours:
                msg_parts.append(f"{hours} hours")
            if minutes:
                msg_parts.append(f"{minutes} minutes")
            if seconds:
                msg_parts.append(f"{seconds} seconds")

            await update.message.reply_text(f"✅ Timer set to {', '.join(msg_parts)}.")
        except ValueError:
            await update.message.reply_text("❌ Invalid time format. Use formats like 30s, 5m, 1h.")
    
    save_settings(group_settings)

async def schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user_id = update.effective_user.id
    if not await is_admin(update, user_id):
        return await update.message.reply_text("Only admins can schedule.")
    if len(context.args) != 2:
        return await update.message.reply_text("Usage: /schedule HH:MM <duration>")
    time_str, duration_str = context.args
    if not re.match(r"^\d{2}:\d{2}$", time_str):
        return await update.message.reply_text("Time must be in HH:MM format.")
    duration = parse_time_from_caption(duration_str)
    if duration is None:
        return await update.message.reply_text("Invalid duration. Use 5m, 10s, 1h.")
    config = get_group_config(chat_id)
    config["scheduled_time"] = time_str
    config["scheduled_duration"] = duration
    config["scheduled_off_time"] = None
    save_settings(group_settings)
    await update.message.reply_text(f"✅ Schedule set daily at {time_str} to {duration_str}.\nUse /scheduleoff HH:MM to stop it. (GMT+6) ")

async def scheduleoff(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user_id = update.effective_user.id
    if not await is_admin(update, user_id):
        return await update.message.reply_text("Only admins can stop schedule.")
    if len(context.args) != 1:
        return await update.message.reply_text("Usage: /scheduleoff HH:MM")
    time_str = context.args[0]
    if not re.match(r"^\d{2}:\d{2}$", time_str):
        return await update.message.reply_text("Time must be in HH:MM format.")
    config = get_group_config(chat_id)
    config["scheduled_off_time"] = time_str
    save_settings(group_settings)
    await update.message.reply_text(f"⏹ Schedule will stop daily at {time_str} and revert to default.")

async def whitelist_him(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to a message to whitelist user.")
    chat_id = str(update.effective_chat.id)
    user_id = update.effective_user.id
    if not await is_admin(update, user_id):
        return await update.message.reply_text("Only admins can whitelist.")
    target_id = update.message.reply_to_message.from_user.id
    config = get_group_config(chat_id)
    if target_id not in config["whitelist"]:
        config["whitelist"].append(target_id)
        save_settings(group_settings)
    await update.message.reply_text(f"✅ User {target_id} whitelisted.")

async def remove_him(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to a message to remove user.")
    chat_id = str(update.effective_chat.id)
    user_id = update.effective_user.id
    if not await is_admin(update, user_id):
        return await update.message.reply_text("Only admins can remove from whitelist.")
    target_id = update.message.reply_to_message.from_user.id
    config = get_group_config(chat_id)
    if target_id in config["whitelist"]:
        config["whitelist"].remove(target_id)
        save_settings(group_settings)
    await update.message.reply_text(f"✅ User {target_id} removed from whitelist.")

def format_duration(seconds):
    if seconds is None:
        return "OFF"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    parts = []
    if h:
        parts.append(f"{h} hr")
    if m:
        parts.append(f"{m} min")
    if s or not parts:
        parts.append(f"{s} sec")
    return " ".join(parts)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    config = get_group_config(chat_id)

    timer = config.get("admin_delete_time")
    timer_str = format_duration(timer)

    scheduled = config.get("scheduled_time", "None")
    scheduled_off = config.get("scheduled_off_time", "None")
    whitelist = config.get("whitelist", [])

    await update.message.reply_text(
        f"🛠 Timer: {timer_str}\n"
        f"⏰ Schedule: {scheduled} (GMT+6)\n"
        f"⛔ Off Time: {scheduled_off} (GMT+6)\n"
        f"👥 Whitelist: {whitelist}"
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat.type == "private":
        await update.message.reply_text(
            "👋 Welcome to the Auto-Delete Media Bot!\n\n"
            "📌 To use this bot:\n"
            "1. Add it to your group.\n"
            "2. Make it admin with delete permissions.\n"
            "3. Use /settimer 15m or /settimer off\n"
            "4. Use /status to view settings\n"
            "⚙️ Commands:\n"
            "/settimer <minutes|off> – Set auto-delete timer\n"
            "/schedule 22:00 5m – Schedule timer (GMT+6)\n"
            "/scheduleoff 08:00 – Schedule timer off (GMT+6) \n"
            "/whitelist_him – Reply to whitelist a user\n"
            "/remove_him – Reply to remove from whitelist\n"
            "/status – Show current config\n"
            "📸 Media deletes after the specified time (e.g., caption '6s' for 6 seconds, '10m' for 10 minutes)."
        )

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return
    if not context.args:
        return await update.message.reply_text("Usage: /broadcast your message | Button Text | Button URL")

    # Combine all arguments into a single string
    full_text = update.message.text.partition(" ")[2]
    parts = [part.strip() for part in full_text.split("|")]

    message = parts[0]
    button_text = parts[1] if len(parts) > 1 else None
    button_url = parts[2] if len(parts) > 2 else None

    reply_markup = None
    if button_text and button_url:
        keyboard = [[InlineKeyboardButton(button_text, url=button_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)

    for group_id in group_settings:
        try:
            await context.bot.send_message(
                chat_id=int(group_id),
                text=message,
                reply_markup=reply_markup
            )
        except Exception as e:
            logging.warning(f"Broadcast to {group_id} failed: {e}")

    await update.message.reply_text("✅ Broadcast sent.")

async def list_groups(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != OWNER_ID:
        return await update.message.reply_text("Only the bot owner can use this command.")
    
    lines = []
    for group_id in group_settings:
        try:
            chat = await context.bot.get_chat(int(group_id))
            title = chat.title or "Unnamed Group"
            lines.append(f"- {title} ({group_id})")
        except Exception as e:
            lines.append(f"- [Failed to fetch name] ({group_id})")
            logging.warning(f"Failed to fetch group {group_id}: {e}")
    
    if lines:
        await update.message.reply_text("📋 Groups using the bot:\n" + "\n".join(lines))
    else:
        await update.message.reply_text("No groups registered.")
        
# === MAIN ===
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("settimer", set_timer))
    app.add_handler(CommandHandler("schedule", schedule))
    app.add_handler(CommandHandler("scheduleoff", scheduleoff))
    app.add_handler(CommandHandler("whitelist_him", whitelist_him))
    app.add_handler(CommandHandler("remove_him", remove_him))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CommandHandler("listgroups", list_groups))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, handle_media))
    asyncio.create_task(schedule_loop(app))
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
