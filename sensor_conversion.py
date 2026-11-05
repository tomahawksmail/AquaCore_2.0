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
