"""Volume-based fertilizer dosing calculations (no GPIO or DB side effects)."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CALIBRATION_SECONDS = Decimal("10")
MAX_PULSE_SECONDS = Decimal("60")
MIN_PULSE_SECONDS = Decimal("0.25")
MAX_DOSE_ML = Decimal("100")


def calibrated_seconds(volume_ml, ml_per_second):
    """Return bounded runtime; fail closed on absent/stale-looking calibration."""
    try:
        volume = Decimal(str(volume_ml))
        rate = Decimal(str(ml_per_second))
        if not volume.is_finite() or not rate.is_finite():
            return None
        if not Decimal("0") < volume <= MAX_DOSE_ML:
            return None
        if not Decimal("0.01") <= rate <= Decimal("50"):
            return None
        duration = (volume / rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if not MIN_PULSE_SECONDS <= duration <= MAX_PULSE_SECONDS:
            return None
        return float(duration)
    except (TypeError, ValueError, ArithmeticError, InvalidOperation):
        return None


def calibrate_rate(measured_ml, duration_seconds=CALIBRATION_SECONDS):
    """Calculate flow from measured ml and the completed, measured test duration."""
    try:
        measured = Decimal(str(measured_ml))
        duration = Decimal(str(duration_seconds))
        if (not measured.is_finite() or not duration.is_finite()
                or not Decimal("0.10") <= measured <= Decimal("500")
                or not Decimal("2") <= duration <= MAX_PULSE_SECONDS):
            return None
        rate = (measured / duration).quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP)
        return rate if Decimal("0.01") <= rate <= Decimal("50") else None
    except (TypeError, ValueError, ArithmeticError, InvalidOperation):
        return None
