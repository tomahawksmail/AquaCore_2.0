"""Shared water-history contract for web SVG and Telegram PNG charts.

Both consumers receive identical time-bucketed records, limits and pH history
calibration boundaries. Web renders with SVG; Telegram uses Matplotlib.
"""
PERIODS = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}
LIMITS_SQL = (
    "SELECT min_temp,max_temp,min_ph,max_ph,min_tds,max_tds "
    "FROM options LIMIT 1"
)


def history_sql(period):
    if period not in PERIODS:
        raise ValueError("Unsupported chart period")
    days = PERIODS[period]
    seconds = max(60, days * 86400 // 300)
    sql = """
        SELECT FROM_UNIXTIME(FLOOR(UNIX_TIMESTAMP(`Datetime`) / %s) * %s) AS time,
               ROUND(AVG(temp), 2) AS temp,
               ROUND(AVG(CASE
                    WHEN `Datetime` >= COALESCE(
                      (SELECT ph_updated_at FROM sensor_calibration WHERE id=1),
                      '1000-01-01 00:00:00')
                    THEN ph ELSE NULL END), 3) AS ph,
               ROUND(AVG(tds), 2) AS tds,
               COUNT(*) AS samples
          FROM data
         WHERE `Datetime` >= NOW() - INTERVAL %s DAY
           AND `Datetime` <= NOW()
           AND NOT (`temp` <=> 0 AND `ph` <=> 0 AND `tds` <=> 0)
         GROUP BY FLOOR(UNIX_TIMESTAMP(`Datetime`) / %s)
         ORDER BY time ASC
    """
    return sql, (seconds, seconds, days, seconds)


def serialize_history(rows, limits, period):
    """Normalize number types and dates; preserve null missing intervals."""
    return {
        "period": period,
        "limits": {k: float(v) if v is not None else None
                   for k, v in (limits or {}).items()},
        "points": [
            {"time": r["time"].isoformat() if hasattr(r.get("time"), "isoformat")
                      else str(r["time"]) if r.get("time") is not None else None,
             "temp": float(r["temp"]) if r.get("temp") is not None else None,
             "ph": float(r["ph"]) if r.get("ph") is not None else None,
             "tds": float(r["tds"]) if r.get("tds") is not None else None,
             "samples": r["samples"]}
            for r in rows
        ],
    }
