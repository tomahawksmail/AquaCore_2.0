"""Pure system-chart data helpers for Telegram; no GPIO, database or plotting imports."""
from datetime import datetime
import math


def split_system_samples(rows, max_gap_seconds=1200):
    """Keep valid dated samples; break lines across outages or clock reversals."""
    groups = []
    current = []
    for row in rows:
        date = row.get("Datetime")
        if isinstance(date, str):
            try:
                date = datetime.fromisoformat(date)
            except ValueError:
                continue
        if not isinstance(date, datetime):
            continue
        try:
            total = float(row.get("RAM_total"))
        except (ValueError, TypeError):
            continue
        if not math.isfinite(total) or total <= 0:
            continue
        item = dict(row)
        item["Datetime"] = date
        if current:
            try:
                elapsed = (date - current[-1]["Datetime"]).total_seconds()
            except TypeError:
                continue
            if elapsed < 0:
                continue  # Refuse out-of-order points.
            if elapsed > max_gap_seconds:
                groups.append(current)
                current = []
        current.append(item)
    if current:
        groups.append(current)
    return groups


def trailing_mean(rows, field, window=3, minimum=None, maximum=None):
    """Create a true connected line from a bounded rolling average; gaps stay NaN."""
    if window < 1:
        raise ValueError("Window must be positive")
    history = []
    output = []
    for row in rows:
        try:
            value = float(row.get(field))
        except (TypeError, ValueError):
            value = math.nan
        if (not math.isfinite(value)
                or minimum is not None and value < minimum
                or maximum is not None and value > maximum):
            history = []
            output.append(math.nan)
            continue
        history.append(value)
        if len(history) > window:
            history.pop(0)
        output.append(sum(history) / len(history))
    return output
