#!/usr/bin/env python3
"""AquaCore host metrics sampler; writes only to MariaDB psutil table."""
import argparse
import logging
import os
import time
import psutil
import pymysql
from dotenv import load_dotenv

LOG = logging.getLogger("aquacore.system")
def db():
    return pymysql.connect(host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")), user=os.getenv("DB_USER", "aquacore_web"),
        password=os.getenv("DB_PASSWORD",""), database=os.getenv("DB_NAME","_AquaCore_"),
        autocommit=True, connect_timeout=5)

def thermal(prefixes):
    root="/sys/class/thermal"
    try:
        for name in sorted(os.listdir(root)):
            if not name.startswith("thermal_zone"): continue
            directory=os.path.join(root,name)
            try:
                with open(os.path.join(directory,"type")) as f: kind=f.read().strip().lower()
                if not any(p in kind for p in prefixes): continue
                with open(os.path.join(directory,"temp")) as f: val=float(f.read().strip())/1000.0
                if -20 <= val <= 130: return val
            except (OSError, ValueError): continue
    except OSError: pass
    return None

def values():
    per_cpu=psutil.cpu_percent(interval=0.3, percpu=True)
    memory=psutil.virtual_memory()
    mb = 1024 * 1024  # Existing AquaCore dashboard stores and displays RAM in MB.
    disk=psutil.disk_usage("/")
    net=psutil.net_io_counters()
    io=psutil.disk_io_counters()
    freq=psutil.cpu_freq()
    d={
        "scpufreq_cur":freq.current if freq else None,
        "RAM_total":round(memory.total / mb, 2), "RAM_available":round(memory.available / mb, 2),
        "RAM_percent":memory.percent, "RAM_used":round(memory.used / mb, 2), "RAM_free":round(memory.free / mb, 2),
        "RAM_active":round(getattr(memory,"active") / mb, 2) if getattr(memory,"active",None) is not None else None,
        "RAM_inactive":round(getattr(memory,"inactive") / mb, 2) if getattr(memory,"inactive",None) is not None else None,
        "RAM_buffers":round(getattr(memory,"buffers") / mb, 2) if getattr(memory,"buffers",None) is not None else None,
        "RAM_cached":round(getattr(memory,"cached") / mb, 2) if getattr(memory,"cached",None) is not None else None,
        "RAM_shared":round(getattr(memory,"shared") / mb, 2) if getattr(memory,"shared",None) is not None else None,
        "RAM_slab":round(getattr(memory,"slab") / mb, 2) if getattr(memory,"slab",None) is not None else None,
        "cpu_thermal_cur":thermal(("cpu","soc","sunxi")),
        "ddr_thermal_cur":thermal(("ddr","dram")),
        "disk_usage_total":disk.total, "disk_usage_used":disk.used,
        "disk_usage_free":disk.free, "disk_usage_percent":disk.percent,
    }
    for i in range(4): d[f"cpus_percent_{i}"]=per_cpu[i] if i<len(per_cpu) else None
    for name in ("bytes_sent","bytes_recv","packets_sent","packets_recv",
                 "errin","errout","dropin","dropout"):
        d["net_"+name]=getattr(net,name,None)
    if io:
        for name in ("read_count","write_count","read_bytes","write_bytes",
                     "read_time","write_time","busy_time"):
            d["disk_"+name]=getattr(io,name,None)
    return d

def main():
    p=argparse.ArgumentParser(description="Collect AquaCore system metrics into psutil DB table")
    p.add_argument("--interval",type=float,default=600)
    p.add_argument("--once",action="store_true")
    args=p.parse_args()
    if args.interval < 1:p.error("--interval must be at least 1s")
    load_dotenv(os.getenv("AQUACORE_ENV",os.path.join(os.path.dirname(__file__),".env")))
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    while True:
        try:
            data=values()
            with db() as con:
                with con.cursor() as cur:
                    cur.execute("SHOW COLUMNS FROM `psutil`")
                    columns={row[0]:row for row in cur.fetchall()}
                    insert={name:value for name,value in data.items() if name in columns}
                    for timestamp in ("Datetime","datetime","Timestamp","timestamp"):
                        if timestamp in columns:
                            insert[timestamp]=None  # replaced with SQL NOW()
                            break
                    if not insert:raise RuntimeError("No compatible psutil metric columns")
                    fields=list(insert)
                    quotes=",".join("`"+name+"`" for name in fields)
                    values_sql=",".join("NOW()" if name in ("Datetime","datetime","Timestamp","timestamp") else "%s" for name in fields)
                    params=[insert[name] for name in fields if name not in ("Datetime","datetime","Timestamp","timestamp")]
                    cur.execute("INSERT INTO `psutil` ("+quotes+") VALUES ("+values_sql+")",params)
            LOG.info("System sample saved: CPU=%s C, CPU load=%s, RAM=%s%%",
                 data["cpu_thermal_cur"],[round(x,1) for x in psutil.cpu_percent(percpu=True)],
                 data["RAM_percent"])
        except (OSError,ValueError,RuntimeError,pymysql.MySQLError):
            LOG.exception("System metrics sample failed")
            if args.once:return 1
        if args.once:return 0
        time.sleep(args.interval)

if __name__=="__main__":
    raise SystemExit(main())
