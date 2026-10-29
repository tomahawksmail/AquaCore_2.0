"""AquaCore Telegram controller (aiogram 3, polling).

Run separately from Flask and the GPIO controller. Authorized private chats only.
Telegram requests alter MariaDB software states; scheduler.py and
relay_controller.py remain responsible for physical outputs.
"""
import asyncio
import logging
import os
import io
from datetime import datetime, time as clock_time, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, Message, BufferedInputFile
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


def init_users_table():
    """Persistent access list. The environment owner always remains administrator."""
    with db() as con:
        with con.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS telegram_users (
                telegram_id BIGINT UNSIGNED NOT NULL PRIMARY KEY,
                role VARCHAR(16) NOT NULL DEFAULT 'viewer',
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""")
        con.commit()


def user_role(user_id):
    if user_id == OWNER:
        return "admin"
    try:
        with db() as con:
            with con.cursor() as cur:
                cur.execute("SELECT role FROM telegram_users WHERE telegram_id=%s", (user_id,))
                row=cur.fetchone()
        return row["role"] if row and row["role"] in ("viewer","operator") else None
    except Exception:
        LOG.exception("Cannot verify Telegram authorization")
        return None


def authorized(event):
    user = event.from_user
    chat = event.chat if isinstance(event, Message) else None
    return bool(user and chat and chat.type == "private" and chat.id == user.id
                and user_role(user.id) is not None)


def can_manage(user_id):
    return user_role(user_id) in ("admin", "operator")


def is_owner(user_id):
    return user_id == OWNER


def list_users():
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT telegram_id,role FROM telegram_users ORDER BY telegram_id")
            rows=cur.fetchall()
    return rows


def change_user(user_id,role=None):
    if user_id<=0 or user_id==OWNER:
        raise ValueError("Enter another user's positive numeric Telegram ID")
    with db() as con:
        try:
            with con.cursor() as cur:
                if role is None:
                    cur.execute("DELETE FROM telegram_users WHERE telegram_id=%s",(user_id,))
                elif role in ("viewer","operator"):
                    cur.execute("INSERT INTO telegram_users (telegram_id,role) VALUES (%s,%s) "
                                "ON DUPLICATE KEY UPDATE role=VALUES(role)",(user_id,role))
                else:
                    raise ValueError("Invalid user role")
            con.commit()
        except Exception:
            con.rollback()
            raise


def users_report():
    lines=["👥 TELEGRAM ACCESS","━━━━━━━━━━━━━━━━━━",
           f"👑 Owner: {OWNER} · admin"]
    for entry in list_users():
        icon="👁" if entry["role"]=="viewer" else "🎛"
        lines.append(f"{icon} {entry['telegram_id']} · {entry['role']}")
    lines.extend(["","Viewer: metrics only","Operator: metrics and equipment/settings",
                  "Only owner can add or remove users."])
    return "\\n".join(lines)


def fmt(value, digits=1):
    if value is None:
        return "—"
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return str(value)


MENU_LABELS={"🐠 Aquarium metrics":"aqua","🖥 System metrics":"system","📈 Aquarium chart":"chart_aqua","📉 System chart":"chart_system","🔌 Equipment control":"equipment","🕒 Timings":"timings","⚙️ Settings":"settings","👥 Telegram users":"users","💧 Water limits":"limits","❔ Help":"help","🏠 Main menu":"menu"}
STATE={}
DEVICE_CHOICES={"🔌 "+name:field for field,name in DEVICES.items()}
TIMING_CHOICES={"🕒 "+DEVICES[field]+" "+kind:column for field,(on,off) in SCHEDULE_MAP.items() for kind,column in (("ON",on),("OFF",off))}
ACTIONS={"🟢 ON":"on","🔴 OFF":"off","🔄 AUTO":"auto"}
def keyboard(rows):
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=x) for x in row] for row in rows],resize_keyboard=True,is_persistent=True)
def reply_menu():
    return keyboard([["🐠 Aquarium metrics","🖥 System metrics"],["📈 Aquarium chart","📉 System chart"],["🔌 Equipment control","🕒 Timings"],["⚙️ Settings","❔ Help"],["🏠 Main menu"]])
def devices_menu():
    labels=list(DEVICE_CHOICES)
    return keyboard([labels[i:i+2] for i in range(0,len(labels),2)]+[["🏠 Main menu"]])
def timings_menu():
    labels=list(TIMING_CHOICES)
    return keyboard([labels[i:i+2] for i in range(0,len(labels),2)]+[["⚙️ Settings","🏠 Main menu"]])


LIMIT_CHOICES = {
    "🌡 Minimum temperature": "min_temp", "🌡 Maximum temperature": "max_temp",
    "🧪 Minimum pH": "min_ph", "🧪 Maximum pH": "max_ph",
    "💧 Minimum TDS": "min_tds", "💧 Maximum TDS": "max_tds",
}


def settings_menu(owner=False):
    rows=[["💧 Water limits","🕒 Timings"]]
    if owner:
        rows.append(["👥 Telegram users"])
    rows.append(["🏠 Main menu"])
    return keyboard(rows)


def limits_menu():
    keys=list(LIMIT_CHOICES)
    return keyboard([keys[i:i+2] for i in range(0,len(keys),2)]+[["⚙️ Settings","🏠 Main menu"]])


def users_menu():
    return keyboard([
        ["➕ Add viewer","➕ Add operator"],
        ["🗑 Remove user","👥 Telegram users"],
        ["⚙️ Settings","🏠 Main menu"],
    ])


def freshness(recorded, now):
    """60-second sampling: 0–90s current, 90–180s delayed, older stale."""
    if not isinstance(recorded, datetime):
        try:
            recorded=datetime.fromisoformat(str(recorded))
        except (TypeError,ValueError):
            return "🔴 Timestamp unavailable"
    seconds=(now-recorded).total_seconds()
    if seconds < -15:
        return "🟡 Clock mismatch"
    if seconds <= 90:
        return "🟢 Current"
    if seconds <= 180:
        return "🟡 Delayed"
    return "🔴 Old"


def metric_header(title, stamp, now, all_zero=False):
    """Shared Telegram layout for both metric reports."""
    status = "🔴 Old — no valid readings" if all_zero else (freshness(stamp, now) if stamp is not None else "🔴 No data")
    when = str(stamp) if stamp is not None else "Unknown"
    return f"{title}\n{status}\n🕒 Sample: {when}\n━━━━━━━━━━━━━━━━━━\n"


def read_aqua():
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT NOW() AS server_time")
            now = cur.fetchone()["server_time"]
            cur.execute("SELECT Datetime,temp,ph,tds FROM data ORDER BY Datetime DESC,Id DESC LIMIT 1")
            row = cur.fetchone()
    if row is None:
        return metric_header("🐠 AQUARIUM METRICS", None, now) + "No readings available."
    zero = all(row.get(k) == 0 for k in ("temp","ph","tds"))
    return (metric_header("🐠 AQUARIUM METRICS", row.get("Datetime"), now, all_zero=zero)
            + "💧 WATER QUALITY\n"
            + f"🌡 Temperature: {fmt(row['temp'])} °C\n"
            + f"🧪 pH: {fmt(row['ph'],2)}\n"
            + f"💦 TDS: {fmt(row['tds'],0)} ppm"
            + ("\n\n⚠️ Zero readings — sensor data unverified." if zero else ""))


def readable_bytes(value):
    """Convert cumulative byte counters to binary-sized MB/GB display."""
    if value is None:
        return "—"
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return "—"
    if amount < 0:
        return "—"
    if amount >= 1024 ** 3:
        return f"{amount / (1024 ** 3):,.2f} GB"
    return f"{amount / (1024 ** 2):,.2f} MB"


def read_system():
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT NOW() AS server_time")
            now=cur.fetchone()["server_time"]
            cur.execute("SELECT * FROM psutil ORDER BY Id DESC LIMIT 1")
            r = cur.fetchone()
    if not r:
        return metric_header("🖥 SYSTEM METRICS", None, now) + "No readings available."
    stamp=next((r.get(k) for k in ("Datetime","datetime","Timestamp","timestamp","created_at","CreatedAt","date_time") if r.get(k) is not None),None)
    # A fresh synthetic zero row indicates missing collection, not healthy metrics.
    zero_fields=("scpufreq_cur","RAM_total","cpu_thermal_cur","net_bytes_sent","net_bytes_recv")
    # Evaluate before building the report; synthetic zero samples are never fresh.
    try:
        is_zero=all(r.get(key) is not None and float(r[key]) == 0 for key in zero_fields)
    except (ValueError, TypeError):
        is_zero=False
    cores = "  |  ".join(f"{fmt(r.get('cpus_percent_'+str(n)),0)}%" for n in range(4))
    return (
        metric_header("🖥 SYSTEM METRICS", stamp, now, all_zero=is_zero)
        + "⚙️ PROCESSOR\n"
        + f"⚡ CPU frequency: {fmt(r.get('scpufreq_cur'),0)} MHz\n"
        f"🧩 CPU cores 0–3: {cores}\n"
        f"🌡 CPU temperature: {fmt(r.get('cpu_thermal_cur'))} °C\n"
        f"🌡 DDR temperature: {fmt(r.get('ddr_thermal_cur'))} °C\n"
        "\n🧠 MEMORY & STORAGE\n"
        f"🧠 RAM usage: {fmt(r.get('RAM_percent'))}%\n"
        f"💾 RAM total: {fmt(r.get('RAM_total'),0)} MB\n"
        f"🗄 Disk usage: {fmt(r.get('disk_usage_percent'))}%\n"
        "\n🌐 NETWORK TRAFFIC\n"
        f"⬆️ Sent: {readable_bytes(r.get('net_bytes_sent'))}\n"
        f"⬇️ Received: {readable_bytes(r.get('net_bytes_recv'))}\n"
        "ℹ️ Network values are cumulative totals, not current speed."
        + ("\n\n⚠️ Zero readings — system collector data unverified." if is_zero else "")
    )


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


def read_limits():
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT * FROM options LIMIT 1")
            options=cur.fetchone()
    if not options:
        return "⚠️ No settings found"
    return ("💧 WATER QUALITY LIMITS\\n━━━━━━━━━━━━━━━━━━\\n"
            + "\\n".join(f"{label}: {options.get(field)}" for label,field in LIMIT_CHOICES.items())
            + "\\n\\nSelect a parameter below to change it.")


def read_timings():
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT * FROM options LIMIT 1")
            opts=cur.fetchone()
    if not opts:return "No settings found"
    return "🕒 Equipment schedule (server time)\n"+ "\n".join(f"{DEVICES[field]}: {str(opts.get(on))[:5]}–{str(opts.get(off))[:5]}" for field,(on,off) in SCHEDULE_MAP.items())

def chart_image(which):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.dates import AutoDateLocator,DateFormatter
    with db() as con:
        with con.cursor() as cur:
            if which=="aqua":
                cur.execute("SELECT Datetime,temp,ph,tds FROM data WHERE Datetime>=NOW()-INTERVAL 24 HOUR ORDER BY Datetime ASC LIMIT 2000")
                rows=cur.fetchall()
                fields=[("temp","Temperature °C"),("ph","pH"),("tds","TDS ppm")]
            else:
                cur.execute("SELECT * FROM psutil ORDER BY Id DESC LIMIT 300")
                rows=list(reversed(cur.fetchall()))
                fields=[("cpus_percent_0","CPU core 0 %"),("RAM_percent","RAM %"),("cpu_thermal_cur","CPU °C")]
    if not rows:return None
    dates=[next((r.get(k) for k in ("Datetime","datetime","Timestamp","timestamp","created_at") if r.get(k) is not None),None) for r in rows]
    dates=[datetime.fromisoformat(d) if isinstance(d,str) else d for d in dates]
    if not all(isinstance(d,datetime) for d in dates):return None
    fig,axes=plt.subplots(3,1,figsize=(9,7),sharex=True)
    fig.patch.set_facecolor("#142536")
    for ax,(field,label),color in zip(axes,fields,("#58dfc0","#84a7ff","#f3bc80")):
        ax.set_facecolor("#1d3548")
        ax.plot(dates,[float(r[field]) if r.get(field) is not None else float("nan") for r in rows],color=color,linewidth=1.6)
        ax.set_ylabel(label,color="#d7e4ec")
        ax.tick_params(colors="#cad9e4")
        ax.grid(alpha=.18)
    axes[-1].xaxis.set_major_locator(AutoDateLocator(maxticks=7))
    axes[-1].xaxis.set_major_formatter(DateFormatter("%H:%M"))
    fig.suptitle("AquaCore · "+which.title()+" metrics",color="white")
    fig.autofmt_xdate()
    fig.tight_layout()
    out=io.BytesIO()
    fig.savefig(out,format="png",dpi=130,facecolor=fig.get_facecolor())
    plt.close(fig)
    return out.getvalue()

def set_device(field, action, actor=None):
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
                            ("Telegram:"+str(actor if actor is not None else OWNER),f"{field} {action} => {desired}",now))
            con.commit()
        except Exception:
            con.rollback()
            raise
    return f"✅ {DEVICES[field]}: {action.upper()} requested" + (f" until {until} (server time)" if until else " (schedule mode)") + "\nPhysical relay state is not independently verified."


def set_option(field, raw, actor=None):
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
                            ("Telegram:"+str(actor if actor is not None else OWNER),f"Setting {field} = {parsed}",now))
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

VIEWS={"aqua":read_aqua,"system":read_system,"equipment":read_equipment,
       "settings":read_settings,"timings":read_timings,"limits":read_limits,
       "users":users_report}


async def show_view(message,view):
    uid=message.from_user.id
    if view=="menu":
        STATE.pop(uid,None)
        await message.answer("🌊 AquaCore 2.0\\nChoose an option using the keyboard below.",reply_markup=reply_menu())
    elif view=="help":
        await message.answer(HELP+"\\n\\nUse the bottom keyboard to navigate.",reply_markup=reply_menu())
    elif view.startswith("chart_"):
        kind=view.split("_",1)[1]
        image=await asyncio.to_thread(chart_image,kind)
        if image:await message.answer_photo(BufferedInputFile(image,filename=kind+".png"),caption="📈 "+kind.title()+" metrics",reply_markup=reply_menu())
        else:await message.answer("No timestamped metrics available.",reply_markup=reply_menu())
    elif view=="equipment":
        STATE.pop(uid,None)
        await message.answer(await asyncio.to_thread(read_equipment),reply_markup=devices_menu() if can_manage(uid) else reply_menu())
    elif view=="settings":
        STATE.pop(uid,None)
        await message.answer("⚙️ AQUACORE SETTINGS\\n━━━━━━━━━━━━━━━━━━\\n💧 Water quality thresholds\\n🕒 Equipment schedules"
                             + ("\\n👥 Authorized Telegram users" if is_owner(uid) else ""),
                             reply_markup=settings_menu(is_owner(uid)))
    elif view=="users":
        if not is_owner(uid):
            await message.answer("⛔ Only the owner can manage users.");return
        STATE.pop(uid,None)
        await message.answer(await asyncio.to_thread(users_report),reply_markup=users_menu())
    elif view=="timings":
        STATE.pop(uid,None)
        await message.answer(await asyncio.to_thread(read_timings),reply_markup=timings_menu() if can_manage(uid) else settings_menu(is_owner(uid)))
    elif view=="limits":
        STATE.pop(uid,None)
        await message.answer(await asyncio.to_thread(read_limits),reply_markup=limits_menu() if can_manage(uid) else settings_menu(is_owner(uid)))
    else:
        await message.answer(await asyncio.to_thread(VIEWS[view]),reply_markup=reply_menu())


@dp.message(CommandStart())
async def start(message:Message):
    if authorized(message):await show_view(message,"menu")


@dp.message(Command("aqua","system","equipment","settings","help"))
async def commands(message:Message):
    if not authorized(message):return
    try:await show_view(message,message.text.split()[0][1:].split("@")[0])
    except Exception:LOG.exception("Command error");await message.answer("⚠️ Could not load data")


@dp.message(Command("set"))
async def set_command(message:Message):
    if not authorized(message):return
    if not can_manage(message.from_user.id):
        await message.answer("⛔ Read-only account.");return
    parts=(message.text or "").split()
    if len(parts)!=3:
        await message.answer("Use /set FIELD VALUE, e.g. /set co2_on 08:00")
        return
    try:result=await asyncio.to_thread(set_option,parts[1],parts[2],message.from_user.id)
    except ValueError as err:await message.answer("⚠️ "+str(err));return
    except Exception:LOG.exception("Setting failed");await message.answer("⚠️ Save failed");return
    await message.answer(result,reply_markup=reply_menu())


@dp.message()
async def menu_handler(message:Message):
    if not authorized(message) or not message.text:return
    uid=message.from_user.id
    value=message.text.strip()
    try:
        if value in MENU_LABELS:
            await show_view(message,MENU_LABELS[value]);return
        if value in DEVICE_CHOICES:
            if not can_manage(uid):
                await message.answer("⛔ Read-only account.");return
            STATE[uid]={"type":"device","field":DEVICE_CHOICES[value]}
            await message.answer(value+"\\nChoose a mode:",reply_markup=keyboard([["🟢 ON","🔴 OFF"],["🔄 AUTO"],["🔌 Equipment control","🏠 Main menu"]]))
            return
        if value in TIMING_CHOICES or value in LIMIT_CHOICES:
            if not can_manage(uid):
                await message.answer("⛔ Read-only account.");return
            field=TIMING_CHOICES[value] if value in TIMING_CHOICES else LIMIT_CHOICES[value]
            STATE[uid]={"type":"setting","field":field}
            example="08:30" if field in TIME_FIELDS else "25.5"
            await message.answer(f"✏️ Update {value}\\n\\nSend the new value (example: {example}).",reply_markup=keyboard([["⚙️ Settings","🏠 Main menu"]]))
            return
        if value in ("➕ Add viewer","➕ Add operator","🗑 Remove user"):
            if not is_owner(uid):
                await message.answer("⛔ Owner access required.");return
            mode={"➕ Add viewer":"viewer","➕ Add operator":"operator","🗑 Remove user":"remove"}[value]
            STATE[uid]={"type":"user_id","mode":mode}
            await message.answer("👥 Send the numeric Telegram user ID.\\nThe person must open a private chat with this bot and send /start.",
                                 reply_markup=users_menu())
            return
        pending=STATE.get(uid)
        if pending and pending["type"]=="device" and value in ACTIONS:
            pending["type"]="confirm";pending["action"]=ACTIONS[value]
            await message.answer("Confirm "+DEVICES[pending["field"]]+" "+pending["action"].upper()+"? (software request)",reply_markup=keyboard([["✅ Confirm","❌ Cancel"],["🏠 Main menu"]]))
            return
        if pending and pending["type"]=="confirm":
            if value=="❌ Cancel":
                await show_view(message,"equipment");return
            if value=="✅ Confirm":
                STATE.pop(uid,None)
                if not can_manage(uid):
                    await message.answer("⛔ Access revoked.");return
                result=await asyncio.to_thread(set_device,pending["field"],pending["action"],uid)
                await message.answer(result,reply_markup=devices_menu());return
        if pending and pending["type"]=="setting":
            if not can_manage(uid):
                STATE.pop(uid,None)
                await message.answer("⛔ Read-only account.");return
            field=pending["field"]
            if field in TIME_FIELDS:
                try:datetime.strptime(value,"%H:%M")
                except ValueError:
                    await message.answer("Enter 24-hour time HH:MM, e.g. 18:30");return
            result=await asyncio.to_thread(set_option,field,value,uid)
            STATE.pop(uid,None)
            await message.answer(result,reply_markup=timings_menu() if field in TIME_FIELDS else limits_menu());return
        if pending and pending["type"]=="user_id":
            if not is_owner(uid):
                STATE.pop(uid,None);return
            if not value.isdecimal() or int(value)<=0:
                await message.answer("⚠️ Please send a positive numeric Telegram user ID.");return
            target=int(value)
            if target==OWNER:
                await message.answer("⚠️ Owner account cannot be modified.");return
            pending["type"]="user_confirm"
            pending["target"]=target
            await message.answer(f"Confirm {pending['mode']} for Telegram ID {target}?",
                                 reply_markup=keyboard([["✅ Confirm","❌ Cancel"],["👥 Telegram users"]]))
            return
        if pending and pending["type"]=="user_confirm":
            if value=="❌ Cancel":
                await show_view(message,"users");return
            if value=="✅ Confirm":
                if not is_owner(uid):
                    STATE.pop(uid,None);return
                target=pending["target"]
                role=None if pending["mode"]=="remove" else pending["mode"]
                await asyncio.to_thread(change_user,target,role)
                STATE.pop(uid,None)
                await message.answer("✅ Access updated.\\n"+await asyncio.to_thread(users_report),reply_markup=users_menu())
                return
        await message.answer("Use the menu buttons below.",reply_markup=reply_menu())
    except ValueError as err:await message.answer("⚠️ "+str(err))
    except Exception:LOG.exception("Telegram menu failure");await message.answer("⚠️ Action failed; see logs")


async def main():
    if not TOKEN or OWNER<=0:
        raise RuntimeError("BOT_TOKEN and numeric MyTGaccount must be set in .env")
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    await asyncio.to_thread(init_users_table)\n    bot=Bot(token=TOKEN)
    # Private message/callback traffic only. Explicit auth remains in every handler.
    await dp.start_polling(bot,allowed_updates=["message"],
                           handle_as_tasks=False)


if __name__=="__main__":
    asyncio.run(main())
