"""AquaCore Telegram controller (aiogram 3, polling).

Run separately from Flask and the GPIO controller. Authorized private chats only.
Telegram requests alter MariaDB software states; scheduler.py and
relay_controller.py remain responsible for physical outputs.
"""
import asyncio
import logging
import os
from datetime import datetime, time as clock_time, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Message
from dotenv import load_dotenv

from app import SETTINGS, TIME_FIELDS, db
from scheduler import SCHEDULE_MAP, next_transition, scheduled_state

load_dotenv(os.getenv("AQUACORE_ENV", os.path.join(os.path.dirname(__file__), ".env")))
LOG = logging.getLogger("aquacore.telegram")
TOKEN = os.getenv("BOT_TOKEN", "")
OWNER = int(os.getenv("MyTGaccount", "0"))
dp = Dispatcher()

DEVICES = {
    "co2_status": "CO₂",
    "o2_status": "Oxygen",
    "UV_status": "UV",
    "MasterL_status": "Main light",
    "Backlight_status": "Backlight",
    "PlantL_status": "Plant light",
}
DEVICE_KEYS = list(DEVICES)
FIELDS = {**{name: "number" for name in SETTINGS}, **{name: "time" for name in TIME_FIELDS}}


def authorized(event):
    user = event.from_user
    chat = event.chat if isinstance(event, Message) else event.message.chat if event.message else None
    return bool(user and user.id == OWNER and chat and chat.type == "private"
                and chat.id == OWNER)


def fmt(value, digits=1):
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


MENU_LABELS = {
    "🐠 Aquarium metrics": "aqua",
    "🖥 System metrics": "system",
    "🔌 Equipment control": "equipment",
    "⚙️ Settings": "settings",
    "❔ Help": "help",
    "🏠 Main menu": "menu",
}

def reply_menu():
    """Persistent two-column keyboard available from every screen."""
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="🐠 Aquarium metrics"), KeyboardButton(text="🖥 System metrics")],
        [KeyboardButton(text="🔌 Equipment control"), KeyboardButton(text="⚙️ Settings")],
        [KeyboardButton(text="❔ Help"), KeyboardButton(text="🏠 Main menu")],
    ], resize_keyboard=True, is_persistent=True, input_field_placeholder="Choose an AquaCore action…")


def device_picker():
    rows=[]
    for index,label in enumerate(DEVICES.values()):
        rows.append([InlineKeyboardButton(text="🔌 "+label+"   ›",callback_data=f"device:{index}")])
    rows.append([InlineKeyboardButton(text="🔄 Refresh status",callback_data="view:equipment")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def device_controls(index):
    name=list(DEVICES.values())[index]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Turn ON",callback_data=f"confirm:{index}:on"),
         InlineKeyboardButton(text="🔴 Turn OFF",callback_data=f"confirm:{index}:off")],
        [InlineKeyboardButton(text="🕒 Automatic schedule",callback_data=f"confirm:{index}:auto")],
        [InlineKeyboardButton(text="‹ All equipment",callback_data="view:equipment")],
    ])


def main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐠 Aquarium", callback_data="view:aqua"),
         InlineKeyboardButton(text="🖥 System", callback_data="view:system")],
        [InlineKeyboardButton(text="🔌 Equipment", callback_data="view:equipment"),
         InlineKeyboardButton(text="⚙️ Settings", callback_data="view:settings")],
        [InlineKeyboardButton(text="📋 Help", callback_data="view:help")],
    ])


def equipment_keyboard():
    rows = []
    for index, label in enumerate(DEVICES.values()):
        rows.append([
            InlineKeyboardButton(text=f"{label} ON", callback_data=f"confirm:{index}:on"),
            InlineKeyboardButton(text="OFF", callback_data=f"confirm:{index}:off"),
            InlineKeyboardButton(text="AUTO", callback_data=f"confirm:{index}:auto"),
        ])
    rows.append([InlineKeyboardButton(text="↩ Menu", callback_data="view:menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_keyboard(index, action):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Confirm", callback_data=f"execute:{index}:{action}"),
        InlineKeyboardButton(text="Cancel", callback_data="view:equipment"),
    ]])


def read_aqua():
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT NOW() AS server_time")
            now = cur.fetchone()["server_time"]
            cur.execute("SELECT Datetime,temp,ph,tds FROM data ORDER BY Datetime DESC,Id DESC LIMIT 1")
            row = cur.fetchone()
    if row is None:
        return "🐠 Aquarium readings: no data"
    age = (now-row["Datetime"]).total_seconds() if row.get("Datetime") else None
    warning = "⚠️ STALE" if age is None or age > 120 else "⚠️ ZERO / UNVERIFIED" if all(row.get(k) == 0 for k in ("temp","ph","tds")) else "✅ Recent"
    return (f"🐠 Aquarium readings ({warning})\n"
            f"🌡 Temperature: {fmt(row['temp'])} °C\n"
            f"🧪 pH: {fmt(row['ph'],2)}\n"
            f"💧 TDS: {fmt(row['tds'],0)} ppm\n"
            f"🕒 Sample: {row['Datetime']} (server time)\n"
            "Note: zero readings may be missing-sensor placeholders.")


def read_system():
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT * FROM psutil ORDER BY Id DESC LIMIT 1")
            r = cur.fetchone()
    if not r:
        return "🖥 System metrics: no data"
    cores = " | ".join(f"{fmt(r.get('cpus_percent_'+str(n)),0)}%" for n in range(4))
    return ("🖥 System metrics (latest stored)\n"
            f"CPU frequency: {fmt(r.get('scpufreq_cur'),0)} MHz\n"
            f"Core 0–3: {cores}\n"
            f"CPU temperature: {fmt(r.get('cpu_thermal_cur'))} °C\n"
            f"DDR temperature: {fmt(r.get('ddr_thermal_cur'))} °C\n"
            f"RAM: {fmt(r.get('RAM_percent'))}% of {fmt(r.get('RAM_total'),0)} MB\n"
            f"Disk usage: {fmt(r.get('disk_usage_percent'))}%\n"
            f"Network sent/received: {fmt(r.get('net_bytes_sent'),0)} / {fmt(r.get('net_bytes_recv'),0)} bytes")


def read_equipment():
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT * FROM status")
            status = cur.fetchall()
            if len(status) != 1:
                raise ValueError("Expected one status row")
            cur.execute("SELECT device,desired,until_at FROM manual_overrides WHERE until_at > NOW()")
            overrides = {r["device"]:r for r in cur.fetchall()}
    lines = ["🔌 Equipment (requested state, not confirmed GPIO output)"]
    for field,name in DEVICES.items():
        state = "ON" if status[0].get(field) == "checked" else "OFF"
        manual = overrides.get(field)
        mode = ("MANUAL until " + str(manual["until_at"])) if manual else "AUTO"
        lines.append(f"{'🟢' if state=='ON' else '⚪'} {name}: {state} · {mode}")
    return "\n".join(lines)


def read_settings():
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT * FROM options LIMIT 1")
            settings = cur.fetchone()
    if not settings:
        return "⚠️ No settings row"
    lines = ["⚙️ Current options"]
    for field in ("min_temp","max_temp","min_ph","max_ph","min_tds","max_tds"):
        lines.append(f"{field}: {settings.get(field)}")
    for field,(start,end) in SCHEDULE_MAP.items():
        lines.append(f"{DEVICES[field]}: {settings.get(start)} → {settings.get(end)}")
    lines.append("\nChange with /set FIELD VALUE (example: /set co2_on 08:00)")
    lines.append("Supported fields: " + ", ".join(sorted(FIELDS)))
    return "\n".join(lines)


def set_device(field, action):
    if field not in DEVICES or action not in ("on","off","auto"):
        raise ValueError("Unsupported device or action")
    with db() as con:
        try:
            with con.cursor() as cur:
                cur.execute("SELECT NOW() AS t")
                now = cur.fetchone()["t"]
                cur.execute("SELECT * FROM status FOR UPDATE")
                rows = cur.fetchall()
                if len(rows) != 1:
                    raise ValueError("Expected exactly one status row")
                cur.execute("SELECT * FROM options LIMIT 1")
                options = cur.fetchone()
                if not options:
                    raise ValueError("Missing options row")
                if action == "auto":
                    desired = "checked" if scheduled_state(field,options,now) else "unchecked"
                    cur.execute("DELETE FROM manual_overrides WHERE device=%s",(field,))
                    until = None
                else:
                    until = next_transition(field,options,now)
                    desired = "checked" if action == "on" else "unchecked"
                    cur.execute(
                        "INSERT INTO manual_overrides (device,desired,until_at,created_at) "
                        "VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE "
                        "desired=VALUES(desired),until_at=VALUES(until_at),created_at=VALUES(created_at)",
                        (field,desired,until,now))
                cur.execute("UPDATE status SET `"+field+"`=%s",(desired,))
                cur.execute("INSERT INTO loging (`User`,`Event`,`Datetime`) VALUES (%s,%s,%s)",
                            ("Telegram:"+str(OWNER),f"{field} {action} => {desired}",now))
            con.commit()
        except Exception:
            con.rollback()
            raise
    return f"✅ {DEVICES[field]}: {action.upper()} requested" + (f" until {until} (server time)" if until else " (schedule mode)") + "\nPhysical relay state is not independently verified."


def set_option(field, raw):
    if field not in FIELDS:
        raise ValueError("Unknown field; see /settings")
    if field in SETTINGS:
        cast,low,high=SETTINGS[field]
        parsed=cast(raw)
        import math
        if not math.isfinite(parsed) or not low<=parsed<=high:
            raise ValueError(f"{field} must be between {low} and {high}")
    else:
        parsed = datetime.strptime(raw,"%H:%M").strftime("%H:%M:%S")
    with db() as con:
        try:
            with con.cursor() as cur:
                cur.execute("SELECT * FROM options FOR UPDATE")
                rows=cur.fetchall()
                if len(rows)!=1:
                    raise ValueError("Expected exactly one options row")
                vals=dict(rows[0]);vals[field]=parsed
                for lo,hi in (("min_temp","max_temp"),("min_ph","max_ph"),("min_tds","max_tds")):
                    if vals.get(lo) is not None and vals.get(hi) is not None and float(vals[lo])>=float(vals[hi]):
                        raise ValueError(f"{lo} must be below {hi}")
                cur.execute("UPDATE options SET `"+field+"`=%s",(parsed,))
                cur.execute("SELECT NOW() AS t")
                now=cur.fetchone()["t"]
                cur.execute("INSERT INTO loging (`User`,`Event`,`Datetime`) VALUES (%s,%s,%s)",
                            ("Telegram:"+str(OWNER),f"Setting {field} = {parsed}",now))
            con.commit()
        except Exception:
            con.rollback()
            raise
    return f"✅ Updated {field} = {parsed}"


HELP = ("AquaCore Telegram\n"
        "/start — menu\n/aqua — latest water readings\n/system — latest system metrics\n"
        "/equipment — six devices and control buttons\n/settings — thresholds and schedules\n"
        "/set FIELD VALUE — update one validated setting\n"
        "Examples: /set max_tds 500, /set co2_on 08:00\n"
        "ON/OFF lasts until the next scheduled transition; AUTO returns to schedule. "
        "Changes are recorded in MariaDB.")

VIEWS = {"aqua":read_aqua,"system":read_system,"equipment":read_equipment,"settings":read_settings}


async def show_view(message, view):
    if view=="menu":
        await message.answer("🌊 AquaCore 2.0  •  Control Center\n\n🐠 Aquarium monitoring\n🖥 System health\n🔌 Equipment and schedules\n\nSelect a button below to continue.",reply_markup=reply_menu())
    elif view=="help":
        await message.answer(HELP+"\n\nUse the persistent buttons below to navigate.",reply_markup=reply_menu())
    else:
        result=await asyncio.to_thread(VIEWS[view])
        await message.answer(result,reply_markup=device_picker() if view=="equipment" else main_keyboard())


@dp.message(CommandStart())
async def start(message:Message):
    if not authorized(message):return
    await show_view(message,"menu")


@dp.message(Command("aqua","system","equipment","settings","help"))
async def commands(message:Message):
    if not authorized(message):return
    name=message.text.split()[0][1:].split("@")[0].lower()
    try:
        await show_view(message,name)
    except Exception:
        LOG.exception("Failed to retrieve %s",name)
        await message.answer("⚠️ Database is unavailable; check server logs.")


@dp.message(Command("set"))
async def set_command(message:Message):
    if not authorized(message):return
    parts=(message.text or "").split()
    if len(parts)!=3:
        await message.answer("Usage: /set FIELD VALUE\nExample: /set co2_on 08:00")
        return
    try:
        result=await asyncio.to_thread(set_option,parts[1],parts[2])
    except ValueError as exc:
        await message.answer(f"⚠️ {exc}")
        return
    except Exception:
        LOG.exception("Failed to save setting")
        await message.answer("⚠️ Database write failed; check server logs.")
        return
    await message.answer(result,reply_markup=main_keyboard())


@dp.callback_query(F.data.startswith("view:"))
async def view_callback(query:CallbackQuery):
    if not authorized(query):return
    view=query.data.split(":",1)[1]
    if view not in (*VIEWS,"menu","help"):
        await query.answer("Unknown menu",show_alert=True)
        return
    await query.answer()
    try:
        await show_view(query.message,view)
    except Exception:
        LOG.exception("Failed Telegram view")
        await query.message.answer("⚠️ Database is unavailable.")


@dp.callback_query(F.data.startswith("device:"))
async def device_page(query:CallbackQuery):
    if not authorized(query):return
    try:
        index=int(query.data.split(":",1)[1])
        if index<0 or index>=len(DEVICE_KEYS):
            raise ValueError
    except (ValueError,AttributeError):
        await query.answer("Unknown device",show_alert=True)
        return
    await query.answer()
    field=DEVICE_KEYS[index]
    try:
        summary=await asyncio.to_thread(read_equipment)
        entry=next((line for line in summary.splitlines() if DEVICES[field]+":" in line),"")
    except Exception:
        LOG.exception("Unable to load equipment status")
        await query.message.answer("⚠️ Could not retrieve equipment state.")
        return
    await query.message.answer("🔌 "+DEVICES[field]+"\n\n"+entry+"\n\nChoose an action:",reply_markup=device_controls(index))


@dp.callback_query(F.data.startswith("confirm:"))
async def confirm_action(query:CallbackQuery):
    if not authorized(query):return
    try:
        _,index,action=query.data.split(":")
        index=int(index)
        if not 0<=index<len(DEVICE_KEYS) or action not in ("on","off","auto"):
            raise ValueError
    except (ValueError,AttributeError):
        await query.answer("Invalid command",show_alert=True)
        return
    field=DEVICE_KEYS[index]
    await query.answer()
    await query.message.answer(
        f"Confirm {DEVICES[field]} → {action.upper()}?\n"
        +("This changes a software request; no physical relay feedback." if action!="auto" else "Return to automatic schedule."),
        reply_markup=confirm_keyboard(index,action))


@dp.callback_query(F.data.startswith("execute:"))
async def execute_action(query:CallbackQuery):
    if not authorized(query):return
    try:
        _,index,action=query.data.split(":")
        index=int(index)
        if not 0<=index<len(DEVICE_KEYS) or action not in ("on","off","auto"):
            raise ValueError
    except (ValueError,AttributeError):
        await query.answer("Invalid command",show_alert=True)
        return
    await query.answer("Processing")
    try:
        result=await asyncio.to_thread(set_device,DEVICE_KEYS[index],action)
    except ValueError as exc:
        await query.message.answer(f"⚠️ {exc}")
        return
    except Exception:
        LOG.exception("Telegram device action failed")
        await query.message.answer("⚠️ Write failed. No success was confirmed.")
        return
    # Remove the confirmation buttons to prevent accidental duplicate actions.
    try:await query.message.edit_reply_markup(reply_markup=None)
    except Exception:pass
    await query.message.answer(result,reply_markup=device_controls(index))


@dp.message(F.text.in_(tuple(MENU_LABELS)))
async def menu_buttons(message:Message):
    if not authorized(message):return
    view=MENU_LABELS[message.text]
    try:
        await show_view(message,view)
    except Exception:
        LOG.exception("Telegram menu failed")
        await message.answer("⚠️ Could not load this view; check server logs.")


@dp.message()
async def unknown_message(message:Message):
    if authorized(message):
        await message.answer("Choose one of the menu buttons below.",reply_markup=reply_menu())


async def main():
    if not TOKEN or OWNER<=0:
        raise RuntimeError("BOT_TOKEN and numeric MyTGaccount must be set in .env")
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    bot=Bot(token=TOKEN)
    # Private message/callback traffic only. Explicit auth remains in every handler.
    await dp.start_polling(bot,allowed_updates=["message","callback_query"],
                           handle_as_tasks=False)


if __name__=="__main__":
    asyncio.run(main())
