"""AquaCore ADS1115 sensor conversions.

A0: pH electrode with measured 6.86 / 4.01 two-buffer calibration.
A1: 10k NTC B3950 with a fixed 10k resistor from 3.3 V to A1.
A3: TDS; its temperature correction is handled by sensorstest.py.

The pair 2.54 V / pH 6.86 and 3.04 V / pH 4.01 is assumed to have
been measured at 25 C unless buffer temperatures are recaptured.
"""
import math

NTC_R0_OHMS = 10000.0
NTC_REFERENCE_C = 25.0
NTC_BETA = 3950.0
NTC_FIXED_OHMS = 10000.0
NTC_SUPPLY_V = 3.3

DEFAULT_PH686_V = 2.54
DEFAULT_PH401_V = 3.04
DEFAULT_PH_CALIBRATION_C = 25.0

# Buffer chemistry varies with temperature. These are pH 4.01 and 6.86
# buffer-family reference points at the stated temperatures, NOT a table
# of aquarium-water pH or an adjustment to sample chemistry.
PH_BUFFER_TABLE = {
    "ph401": ((0,4.01),(5,4.00),(10,4.00),(15,4.00),(20,4.00),
              (25,4.01),(30,4.02),(35,4.03),(40,4.04),(45,4.05),(50,4.06)),
    "ph686": ((0,6.98),(5,6.95),(10,6.92),(15,6.90),(20,6.88),
              (25,6.86),(30,6.85),(35,6.84),(40,6.84),(45,6.83),(50,6.83)),
}


def ntc_celsius(volts, *, supply_v=NTC_SUPPLY_V,
                fixed_ohms=NTC_FIXED_OHMS, r0_ohms=NTC_R0_OHMS,
                beta=NTC_BETA):
    """Convert 3.3V -> 10k pullup -> A1 -> NTC -> GND to degrees Celsius."""
    if not all(math.isfinite(v) and v > 0 for v in
               (supply_v, fixed_ohms, r0_ohms, beta)):
        raise ValueError("Invalid NTC circuit parameters")
    if not math.isfinite(volts) or volts <= 0.02 or volts >= supply_v - 0.02:
        raise ValueError("NTC input disconnected or outside divider range")
    resistance = fixed_ohms * volts / (supply_v - volts)
    temp = (1.0 / (1.0 / (NTC_REFERENCE_C + 273.15)
                   + math.log(resistance / r0_ohms) / beta)) - 273.15
    if not -10 <= temp <= 60:
        raise ValueError("NTC reading outside expected aquarium range")
    return temp


def buffer_reference_ph(kind, temperature_c):
    """Return the expected pH of the *actual matching buffer* at its temperature."""
    points = PH_BUFFER_TABLE.get(kind)
    if points is None:
        raise ValueError("Unsupported buffer (use pH 4.01 or 6.86)")
    if not math.isfinite(temperature_c) or not points[0][0] <= temperature_c <= points[-1][0]:
        raise ValueError("Buffer temperature outside reference chart")
    for (t0, p0), (t1, p1) in zip(points, points[1:]):
        if t0 <= temperature_c <= t1:
            return p0 + (p1 - p0) * (temperature_c - t0) / (t1 - t0)
    raise ValueError("No buffer pH reference for temperature")


def calibrated_ph_from_points(volts, ph_a, volts_a, ph_b, volts_b):
    """Linear pH from two valid calibration pairs, no invented neutral anchor."""
    values = (volts, ph_a, volts_a, ph_b, volts_b)
    if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in values):
        raise ValueError("Invalid pH calibration")
    if not 0 <= ph_a <= 14 or not 0 <= ph_b <= 14 or ph_a == ph_b:
        raise ValueError("Invalid buffer pH")
    if not 0.02 < volts_a < 4.096 or not 0.02 < volts_b < 4.096:
        raise ValueError("Invalid buffer voltage")
    if abs(volts_b - volts_a) < 0.03:
        raise ValueError("pH calibration voltages too close")
    ph = ph_a + (volts - volts_a) * (ph_b - ph_a) / (volts_b - volts_a)
    if not 0 <= ph <= 14:
        raise ValueError("pH outside physical range 0-14")
    return ph


def temperature_compensated_ph_two_points(volts, v686, v401,
                                           t686_c, t401_c, water_c):
    """Compensate measured two-buffer electrode slope using calibrated A1 water temp.

    Assumes electrode/amplifier slope approximately follows absolute temperature
    (Nernst); this does not adjust aquarium chemistry to 25 C. The reference
    solution pH values are looked up using the *buffer* temperatures.
    """
    temps = (t686_c, t401_c, water_c)
    if not all(isinstance(t, (int, float)) and math.isfinite(t)
               and 0 <= t <= 50 for t in temps):
        raise ValueError("Calibrated A1 and valid 0-50 C buffer temperatures required")
    p686 = buffer_reference_ph("ph686", t686_c)
    p401 = buffer_reference_ph("ph401", t401_c)
    base = calibrated_ph_from_points(volts, p686, v686, p401, v401)
    calibration_kelvin = (t686_c + t401_c) / 2.0 + 273.15
    water_kelvin = water_c + 273.15
    ph = p686 + (base - p686) * calibration_kelvin / water_kelvin
    if not 0 <= ph <= 14:
        raise ValueError("Temperature-compensated pH outside 0-14")
    return ph
