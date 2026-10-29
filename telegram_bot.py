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


MENU_LABELS={"🐠 Aquarium metrics":"aqua","🖥 System metrics":"system","📈 Aquarium chart":"chart_aqua","📉 System chart":"chart_system","🔌 Equipment control":"equipment","🕒 Timings":"timings","⚙️ Settings":"settings","❔ Help":"help","🏠 Main menu":"menu"}
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
    return keyboard([labels[i:i+2] for i in range(0,len(labels),2)]+[["🏠 Main menu"]])

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
            f"🕒 Server time: {row['Datetime']}\n")


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
            cur.execute("SELECT * FROM psutil ORDER BY Id DESC LIMIT 1")
            r = cur.fetchone()
    if not r:
        return "🖥 System metrics: no data"
    cores = "  |  ".join(f"{fmt(r.get('cpus_percent_'+str(n)),0)}%" for n in range(4))
    return (
        "🖥 SYSTEM METRICS\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"⚡ CPU frequency: {fmt(r.get('scpufreq_cur'),0)} MHz\n"
        f"🧩 CPU cores 0–3: {cores}\n"
        f"🌡 CPU temperature: {fmt(r.get('cpu_thermal_cur'))} °C\n"
        f"🌡 DDR temperature: {fmt(r.get('ddr_thermal_cur'))} °C\n"
        f"🧠 RAM usage: {fmt(r.get('RAM_percent'))}%\n"
        f"💾 RAM total: {fmt(r.get('RAM_total'),0)} MB\n"
        f"🗄 Disk usage: {fmt(r.get('disk_usage_percent'))}%\n"
        "\n🌐 NETWORK TRAFFIC\n"
        f"⬆️ Sent: {readable_bytes(r.get('net_bytes_sent'))}\n"
        f"⬇️ Received: {readable_bytes(r.get('net_bytes_recv'))}\n"
        "ℹ️ Network values are cumulative totals, not current speed."
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

VIEWS={"aqua":read_aqua,"system":read_system,"equipment":read_equipment,"settings":read_settings,"timings":read_timings}

async def show_view(message,view):
    if view=="menu":
        STATE.clear()
        await message.answer("🌊 Welcome to AquaCore 2.0",reply_markup=reply_menu())
    elif view=="help":
        await message.answer(HELP+"\n\nUse the bottom keyboard to navigate.",reply_markup=reply_menu())
    elif view.startswith("chart_"):
        kind=view.split("_",1)[1]
        image=await asyncio.to_thread(chart_image,kind)
        if image:await message.answer_photo(BufferedInputFile(image,filename=kind+".png"),caption="📈 "+kind.title()+" metrics",reply_markup=reply_menu())
        else:await message.answer("No timestamped metrics available.",reply_markup=reply_menu())
    elif view=="equipment":
        STATE.clear()
        await message.answer(await asyncio.to_thread(read_equipment),reply_markup=devices_menu())
    elif view=="timings":
        STATE.clear()
        await message.answer(await asyncio.to_thread(read_timings),reply_markup=timings_menu())
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
    parts=(message.text or "").split()
    if len(parts)!=3:
        await message.answer("Use /set FIELD VALUE, e.g. /set co2_on 08:00")
        return
    try:result=await asyncio.to_thread(set_option,parts[1],parts[2])
    except ValueError as err:await message.answer("⚠️ "+str(err));return
    except Exception:LOG.exception("Setting failed");await message.answer("⚠️ Save failed");return
    await message.answer(result,reply_markup=reply_menu())

@dp.message()
async def menu_handler(message:Message):
    if not authorized(message) or not message.text:return
    value=message.text.strip()
    try:
        if value in MENU_LABELS:
            await show_view(message,MENU_LABELS[value]);return
        if value in DEVICE_CHOICES:
            STATE[OWNER]={"type":"device","field":DEVICE_CHOICES[value]}
            await message.answer(value+"\nChoose a mode:",reply_markup=keyboard([["🟢 ON","🔴 OFF"],["🔄 AUTO"],["🏠 Main menu"]]))
            return
        if value in TIMING_CHOICES:
            STATE[OWNER]={"type":"time","field":TIMING_CHOICES[value]}
            await message.answer("Send new time for "+TIMING_CHOICES[value]+" (HH:MM), or select Main menu.",reply_markup=keyboard([["🏠 Main menu"]]))
            return
        pending=STATE.get(OWNER)
        if pending and pending["type"]=="device" and value in ACTIONS:
            pending["type"]="confirm";pending["action"]=ACTIONS[value]
            await message.answer("Confirm "+DEVICES[pending["field"]]+" "+pending["action"].upper()+"? (software request)",reply_markup=keyboard([["✅ Confirm","❌ Cancel"],["🏠 Main menu"]]))
            return
        if pending and pending["type"]=="confirm":
            if value=="❌ Cancel":
                await show_view(message,"equipment");return
            if value=="✅ Confirm":
                STATE.clear()
                result=await asyncio.to_thread(set_device,pending["field"],pending["action"])
                await message.answer(result,reply_markup=devices_menu());return
        if pending and pending["type"]=="time":
            try:datetime.strptime(value,"%H:%M")
            except ValueError:
                await message.answer("Please enter HH:MM, e.g. 18:30");return
            result=await asyncio.to_thread(set_option,pending["field"],value)
            STATE.clear()
            await message.answer(result,reply_markup=timings_menu());return
        await message.answer("Use the menu buttons below.",reply_markup=reply_menu())
    except ValueError as err:await message.answer("⚠️ "+str(err))
    except Exception:LOG.exception("Telegram menu failure");await message.answer("⚠️ Action failed; see logs")

async def main():
    if not TOKEN or OWNER<=0:
        raise RuntimeError("BOT_TOKEN and numeric MyTGaccount must be set in .env")
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    bot=Bot(token=TOKEN)
    # Private message/callback traffic only. Explicit auth remains in every handler.
    await dp.start_polling(bot,allowed_updates=["message"],
                           handle_as_tasks=False)


if __name__=="__main__":
    asyncio.run(main())
