"""AquaCore helper for rendering MariaDB TIME fields as valid HTML HH:MM."""
import re
from datetime import datetime, time, timedelta


def html_time(value):
    """Return valid HH:MM for MySQL TIME/timedelta, time, datetime and strings.

    MariaDB TIME 08:00 is decoded by PyMySQL as timedelta(hours=8),
    whose string is '8:00:00'. Taking the first five characters would produce
    the invalid HTML time value '8:00:' and make the browser show --:--.
    """
    if value is None:
        return ""
    if isinstance(value, timedelta):
        total = value.total_seconds()
        if not 0 <= total < 86400:
            return ""
        hours, minutes = divmod(int(total) // 60, 60)
        return f"{hours:02d}:{minutes:02d}"
    if isinstance(value, (datetime, time)):
        return value.strftime("%H:%M")
    if isinstance(value, str):
        match = re.fullmatch(
            r"\s*(\d{1,2}):([0-5]\d)(?::[0-5]\d(?:\.\d+)?)?\s*",
            value,
        )
        if match and int(match.group(1)) < 24:
            return f"{int(match.group(1)):02d}:{int(match.group(2)):02d}"
    return ""
