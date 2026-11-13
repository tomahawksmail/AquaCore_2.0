"""AquaCore analog sensor conversion helpers.

A1: 10k NTC B3950 connected from ADC A1 to GND with an external
10k resistor from A1 to 3.3 V. Never connect the old pH module T1/T2
to this input at the same time.
A0: pH voltage, requires two measured buffer reference voltages.
"""
import math

NTC_R0_OHMS = 10000.0
NTC_REFERENCE_C = 25.0
NTC_BETA = 3950.0
NTC_FIXED_OHMS = 10000.0
NTC_SUPPLY_V = 3.3


def ntc_celsius(volts, *, supply_v=NTC_SUPPLY_V,
                fixed_ohms=NTC_FIXED_OHMS, r0_ohms=NTC_R0_OHMS,
                beta=NTC_BETA):
    """Convert a 10k/B3950 thermistor voltage into degrees Celsius.

    Divider: 3.3V -> 10k fixed resistor -> ADS1115 A1 -> NTC -> GND.
    Raise ValueError on open/short/saturated/implausible voltages.
    """
    if not all(math.isfinite(v) and v > 0 for v in
               (supply_v, fixed_ohms, r0_ohms, beta)):
        raise ValueError("Invalid NTC circuit parameters")
    if not math.isfinite(volts) or volts <= 0.02 or volts >= supply_v - 0.02:
        raise ValueError("NTC input is disconnected, shorted, or outside the divider range")
    resistance = fixed_ohms * volts / (supply_v - volts)
    kelvin = 1.0 / (1.0 / (NTC_REFERENCE_C + 273.15)
                    + math.log(resistance / r0_ohms) / beta)
    temp = kelvin - 273.15
    if not -10 <= temp <= 60:
        raise ValueError("NTC reading outside the expected aquarium range")
    return temp


def calibrated_ph(volts, ph7_voltage, ph4_voltage):
    """Linear pH estimate from actual pH 7 and pH 4 buffer voltages.

    This is NOT a substitute for real two-buffer calibration.
    No invented zero offset or generic mV-per-pH slope is assumed.
    """
    if not all(math.isfinite(v) for v in (volts, ph7_voltage, ph4_voltage)):
        raise ValueError("Invalid pH voltages")
    delta = ph4_voltage - ph7_voltage
    if abs(delta) < 0.03:
        raise ValueError("pH calibration voltages are too close")
    result = 7.0 - 3.0 * (volts - ph7_voltage) / delta
    if not 0 <= result <= 14:
        raise ValueError("pH estimate outside physical 0-14 range")
    return result


def calibrated_ph_from_points(volts, ph_a, volts_a, ph_b, volts_b):
    """Calculate pH using two measured buffer points (pH, volts).

    Unlike calibrated_ph(), reference pH values need not be exactly 4 and 7.
    """
    values = (volts, ph_a, volts_a, ph_b, volts_b)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Invalid pH calibration values")
    if not 0 <= ph_a <= 14 or not 0 <= ph_b <= 14 or ph_a == ph_b:
        raise ValueError("Invalid reference buffer pH values")
    if abs(volts_b - volts_a) < 0.03:
        raise ValueError("pH calibration voltages are too close")
    result = ph_a + (volts - volts_a) * (ph_b - ph_a) / (volts_b - volts_a)
    if not 0 <= result <= 14:
        raise ValueError("pH estimate outside physical 0-14 range")
    return result


# Typical NIST-compatible pH buffer temperature tables for 4.01, 6.86 and 9.18.
# The nominal label is specified at 25 C. For other manufacturers use their
# buffer temperature chart if it differs. See Hanna Instruments HI510 annex.
PH_BUFFER_TABLE = {
    "ph401": ((0,4.01),(5,4.00),(10,4.00),(15,4.00),(20,4.00),
              (25,4.01),(30,4.02),(35,4.03),(40,4.04),(45,4.05),(50,4.06)),
    "ph686": ((0,6.98),(5,6.95),(10,6.92),(15,6.90),(20,6.88),
              (25,6.86),(30,6.85),(35,6.84),(40,6.84),(45,6.83),(50,6.83)),
    "ph918": ((0,9.46),(5,9.39),(10,9.33),(15,9.27),(20,9.22),
              (25,9.18),(30,9.14),(35,9.11),(40,9.07),(45,9.04),(50,9.01)),
}


def buffer_reference_ph(kind, temperature_c):
    """Interpolate the expected pH of a named calibration buffer at liquid temp."""
    if kind not in PH_BUFFER_TABLE:
        raise ValueError("Unsupported pH buffer")
    if not math.isfinite(temperature_c) or not 0 <= temperature_c <= 50:
        raise ValueError("Buffer temperature must be 0–50 °C")
    points = PH_BUFFER_TABLE[kind]
    for (t0, p0), (t1, p1) in zip(points, points[1:]):
        if t0 <= temperature_c <= t1:
            return p0 + (p1 - p0) * (temperature_c - t0) / (t1 - t0)
    raise ValueError("No buffer reference for this temperature")


def validate_ph_three_points(v401, v686, v918, p401, p686, p918):
    """Reject crossed, saturated, non-monotonic, or near-identical references."""
    values = (v401, v686, v918, p401, p686, p918)
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
        raise ValueError("Three finite buffer readings are required")
    if not all(0.02 < v < 4.095 for v in (v401, v686, v918)):
        raise ValueError("Buffer voltages outside safe ADC range")
    if not (3.5 < p401 < 4.5 and 6.5 < p686 < 7.2 and 8.7 < p918 < 9.6):
        raise ValueError("Invalid buffer reference pH")
    d1 = v686 - v401
    d2 = v918 - v686
    if abs(d1) < 0.03 or abs(d2) < 0.03 or d1 * d2 <= 0:
        raise ValueError("pH electrode response must be monotonic with >=0.03 V per interval")


def calibrated_ph_three_points(volts, v401, v686, v918,
                                p401, p686, p918):
    """Three measured buffers, piecewise linear between bracketing references.

    Extrapolate from the nearest segment outside 4.01..9.18.
    Values outside pH 0–14 are rejected, not artificially clipped.
    """
    validate_ph_three_points(v401, v686, v918, p401, p686, p918)
    if not math.isfinite(volts):
        raise ValueError("Invalid pH ADC voltage")
    fraction = (volts - v401) / (v686 - v401)
    if fraction <= 1.0:
        result = p401 + fraction * (p686 - p401)
    else:
        result = p686 + (volts - v686) / (v918 - v686) * (p918 - p686)
    if not 0 <= result <= 14:
        raise ValueError("pH estimate outside physical 0-14 range")
    return result


def temperature_compensated_ph_three_points(volts, v401, v686, v918,
                                             p401, p686, p918,
                                             t401, t686, t918, sample_temp_c):
    """Approximate pH electrode Nernst slope correction using live water temp.

    Uses the measured slope of the applicable calibration segment, scaled
    by absolute temperature (Kelvin). The pH 6.86 reference is the anchor.
    The PH-4502C board's amplifier gain is already included in each measured
    voltage difference; do not apply a generic mV/pH multiplier.

    Buffer pH values must already be evaluated at each buffer's calibration
    temperature. Temperature compensation does NOT adjust the actual sample
    chemistry to an arbitrary reference temperature such as 25 C.
    """
    validate_ph_three_points(v401, v686, v918, p401, p686, p918)
    temperatures = (t401, t686, t918, sample_temp_c)
    if not all(isinstance(t, (int, float)) and math.isfinite(t)
               and 0 <= t <= 50 for t in temperatures):
        raise ValueError("pH temperature compensation requires valid 0-50 C readings")
    if not math.isfinite(volts):
        raise ValueError("Invalid pH ADC voltage")
    # Choose the bracketing segment relative to the near-neutral pH buffer.
    # This works whether the amplifier voltage rises or falls with pH.
    on_acid_side = (volts - v686) * (v401 - v686) >= 0
    if on_acid_side:
        reference_voltage, reference_ph = v401, p401
        calibration_temp = (t401 + t686) / 2.0
    else:
        reference_voltage, reference_ph = v918, p918
        calibration_temp = (t918 + t686) / 2.0
    relative = (volts - v686) / (reference_voltage - v686)
    # dE/dpH is proportional to absolute temperature in the Nernst equation.
    ph = p686 + relative * (reference_ph - p686) * (
        (calibration_temp + 273.15) / (sample_temp_c + 273.15))
    if not 0 <= ph <= 14:
        raise ValueError("Temperature-compensated pH outside physical 0-14 range")
    return ph
