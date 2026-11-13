#!/usr/bin/env python3
"""Read-only AquaCore sensor diagnostics for Orange Pi Zero 2W.

Configured hardware: ADS1115 A0=pH, A1=optional NTC10K B3950, A3=TDS.
No GPIO, relay, MariaDB or equipment output is modified.
pH defaults to measured pH 6.86/4.01 buffer voltages; NTC requires divider.
"""
import argparse
import glob
import os
import sys
import time
from sensor_conversion import calibrated_ph, calibrated_ph_from_points, ntc_celsius


def adc_read(bus, address, channel, pga=4.096):
    """ADS1115 single-ended conversion, configurable full-scale PGA, 128 SPS.

    Note: PGA +/-6.144 V does NOT permit input above ADS1115 VDD.
    """
    from smbus2 import SMBus
    pga_bits = {6.144: 0, 4.096: 1, 2.048: 2, 1.024: 3, 0.512: 4, 0.256: 5}
    if pga not in pga_bits:
        raise ValueError("Unsupported ADS1115 PGA")
    mux = 4 + channel
    config = (1 << 15) | (mux << 12) | (pga_bits[pga] << 9) | (1 << 8) | (4 << 5) | 3
    # The ADS1115 has one shared mux/config register. The 500 ms web preview,
    # background TDS collector and operator calibration must not change channels
    # while another process is converting. /run/lock is shared despite PrivateTmp.
    import fcntl
    lock_path = f"/run/lock/aquacore-ads1115-{bus}-{address:02x}.lock"
    lock_fd = os.open(lock_path, os.O_RDONLY | os.O_CREAT |
                      getattr(os, "O_NOFOLLOW", 0), 0o644)
    try:
        try:
            os.fchmod(lock_fd, 0o644)  # also allow a manual root test first
        except PermissionError:
            pass
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        with SMBus(bus) as device:
            device.write_i2c_block_data(address, 0x01, [config >> 8, config & 0xff])
            time.sleep(0.012)
            data = device.read_i2c_block_data(address, 0x00, 2)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
    raw = (data[0] << 8) | data[1]
    if raw >= 32768:
        raw -= 65536
    return raw, raw * pga / 32768.0


def estimate_tds_ppm(voltage, temperature_c):
    """DFRobot-style approximation, not a measured calibration."""
    corrected = max(0.0, voltage) / (1.0 + 0.02 * (temperature_c - 25.0))
    return max(0.0, (133.42 * corrected**3 - 255.86 * corrected**2
                     + 857.39 * corrected) * 0.5)


# PROVISIONAL adjustment: assumed 13 ppm for boiled Primo water at ~22 C,
# compared with a prior estimated ~49.5 ppm. NOT certified calibration.
DEFAULT_TDS_FACTOR = 0.2626


def main():
    p = argparse.ArgumentParser(description="Read-only AquaCore sensor tester (ADS1115 TDS A3)")
    p.add_argument("--bus", type=int, help="Linux I2C bus number; e.g. 1 for /dev/i2c-1")
    p.add_argument("--address", type=lambda x: int(x, 0), default=0x48,
                   help="ADS1115 7-bit address (default 0x48)")
    p.add_argument("--interval", type=float, default=2.0)
    p.add_argument("--once", action="store_true")
    p.add_argument("--all-channels", action="store_true",
                   help="Read A0 pH, A1 raw/optional NTC and adjusted TDS on A3")
    p.add_argument("--ntc", action="store_true",
                   help="Convert A1 as 10k B3950 NTC using 10k pull-up to 3.3V")
    p.add_argument("--ntc-supply", type=float, default=3.3,
                   help="Measured divider supply voltage, nominally 3.3V")
    p.add_argument("--pga", type=float, choices=(4.096, 6.144), default=4.096,
                   help="ADS1115 full-scale range (+/- volts); default 4.096")
    p.add_argument("--ph-high", type=float, default=6.86,
                   help="Higher reference buffer pH (default 6.86)")
    p.add_argument("--ph-high-voltage", type=float, default=2.54,
                   help="Voltage measured in higher pH buffer (default 2.54 V)")
    p.add_argument("--ph-low", type=float, default=4.01,
                   help="Lower reference buffer pH (default 4.01)")
    p.add_argument("--ph-low-voltage", type=float, default=3.04,
                   help="Voltage measured in lower pH buffer (default 3.04 V)")
    p.add_argument("--ph7-voltage", type=float, default=None,
                   help="A0 volts measured in pH 7.00 buffer")
    p.add_argument("--ph4-voltage", type=float, default=None,
                   help="A0 volts measured in pH 4.00 buffer")
    p.add_argument("--tds-factor", type=float, default=DEFAULT_TDS_FACTOR,
                   help="Provisional multiplier (default 0.2626); use 1 for unadjusted")
    p.add_argument("--temperature", type=float, default=25.0,
                   help="Measured water temperature C for estimate (default 25)")
    args = p.parse_args()
    if args.interval < 0.05 or args.bus is not None and args.bus < 0:
        p.error("Invalid bus or interval")
    if not (0 < args.tds_factor <= 10):
        p.error("--tds-factor must be greater than 0 and at most 10")
    if (args.ph7_voltage is None) != (args.ph4_voltage is None):
        p.error('Supply both --ph7-voltage and --ph4-voltage or neither')
    try:
        if args.ph7_voltage is not None:
            calibrated_ph(args.ph7_voltage, args.ph7_voltage, args.ph4_voltage)
        else:
            calibrated_ph_from_points(args.ph_high_voltage, args.ph_high,
                                      args.ph_high_voltage, args.ph_low,
                                      args.ph_low_voltage)
    except ValueError as exc:
        p.error(str(exc))
    if not (3.0 <= args.ntc_supply <= 3.6):
        p.error('--ntc-supply must be 3.0-3.6 V')
    if not (-2 <= args.temperature <= 55):
        p.error("--temperature must be between -2 and 55 C")

    print("AquaCore SENSOR TEST — read-only, no DB writes or relay changes", flush=True)
    if args.ph7_voltage is not None:
        print(f"A0 pH:       legacy buffers pH 7.00={args.ph7_voltage:.3f} V, pH 4.00={args.ph4_voltage:.3f} V")
    else:
        print(f"A0 pH:       buffers pH {args.ph_high:.2f}={args.ph_high_voltage:.3f} V, pH {args.ph_low:.2f}={args.ph_low_voltage:.3f} V")
    print(f"ADS1115 PGA: +/-{args.pga:.3f} V (input must not exceed chip supply limits)")
    print("A1:          NTC B3950 via 10k pull-up to 5.0V" if args.ntc else "A1:          raw voltage only (use --ntc after re-wiring)")
    print(f"TDS:         ADS1115 A3; temperature {args.temperature:.1f} C; provisional factor {args.tds_factor:.4f} (NOT calibrated)")
    buses = glob.glob("/dev/i2c-*")
    print("Detected I2C bus devices:", ", ".join(sorted(buses)) or "none")
    if args.bus is None:
        print("Choose the ADS1115 bus using: i2cdetect -l; i2cdetect -y BUS")
        print("Then run: python sensorstest.py --bus BUS --once")
        return 0
    path = f"/dev/i2c-{args.bus}"
    if path not in buses:
        print(f"ERROR: {path} not found. Enable the correct I2C interface in Armbian.", file=sys.stderr)
        return 2
    try:
        import smbus2
    except ImportError:
        print("ERROR: install smbus2 in the project venv: pip install smbus2", file=sys.stderr)
        return 2
    print(f"Reading ADS1115 0x{args.address:02x} on {path}, "+("A0/A1/A3" if args.all_channels else "A3")+"; Ctrl+C to quit")
    try:
        while True:
            try:
                raw, volts = adc_read(args.bus, args.address, 3, pga=args.pga)
                prefix = time.strftime('%Y-%m-%d %H:%M:%S')
                temperature = args.temperature
                if args.all_channels:
                    raw0, voltage0 = adc_read(args.bus, args.address, 0, pga=args.pga)
                    raw1, voltage1 = adc_read(args.bus, args.address, 1, pga=args.pga)
                    channels = [f"A0={voltage0:.5f} V (raw={raw0})",
                                f"A1={voltage1:.5f} V (raw={raw1})"]
                    if raw1 >= 32767:
                        channels.append("A1 SATURATED (actual voltage unknown)")
                    if args.ntc:
                        try:
                            if raw1 >= 32767:
                                raise ValueError("ADC saturation")
                            temperature = ntc_celsius(voltage1, supply_v=args.ntc_supply)
                            channels.append(f"water_temp={temperature:.2f} C (NTC B3950)")
                        except ValueError as exc:
                            channels.append(f"water_temp=INVALID ({exc}); TDS uses fallback {args.temperature:.1f} C")
                    try:
                        if raw0 >= 32767:
                            raise ValueError("ADC saturation")
                        if args.ph7_voltage is not None:
                            ph = calibrated_ph(voltage0, args.ph7_voltage, args.ph4_voltage)
                        else:
                            ph = calibrated_ph_from_points(
                                voltage0, args.ph_high, args.ph_high_voltage,
                                args.ph_low, args.ph_low_voltage)
                        channels.append(f"pH={ph:.2f} (2-buffer)")
                    except ValueError as exc:
                        channels.append(f"pH=INVALID ({exc})")
                    adjusted = estimate_tds_ppm(volts, temperature) * args.tds_factor
                    print(f"{prefix}  {'  '.join(channels)}  A3 TDS={adjusted:.1f} ppm (PROVISIONAL)", flush=True)
                else:
                    ppm = estimate_tds_ppm(volts, temperature)
                    adjusted = ppm * args.tds_factor
                    print(f"{prefix}  TDS A3: {volts:.5f} V  raw={raw}  base={ppm:.1f} ppm  adjusted={adjusted:.1f} ppm ({temperature:.1f} C, PROVISIONAL)", flush=True)
            except (OSError, ValueError) as exc:
                print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  SENSOR ERROR: {exc}", flush=True)
                if args.once:
                    return 1
            if args.once:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
