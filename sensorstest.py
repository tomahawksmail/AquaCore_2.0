#!/usr/bin/env python3
"""Read-only AquaCore sensor diagnostics for Orange Pi Zero 2W.

Configured hardware: analog TDS transmitter -> ADS1115 input A3 over I2C.
No GPIO, relay, MariaDB or equipment output is modified.
Unconfigured temperature and pH sensors are reported, never fabricated.
"""
import argparse
import glob
import os
import sys
import time


def adc_read(bus, address, channel):
    """ADS1115 one-shot single-ended conversion at +/-4.096V, 128 SPS."""
    from smbus2 import SMBus
    mux = 4 + channel
    config = (1 << 15) | (mux << 12) | (1 << 9) | (1 << 8) | (4 << 5) | 3
    with SMBus(bus) as device:
        device.write_i2c_block_data(address, 0x01, [config >> 8, config & 0xff])
        time.sleep(0.012)
        data = device.read_i2c_block_data(address, 0x00, 2)
    raw = (data[0] << 8) | data[1]
    if raw >= 32768:
        raw -= 65536
    return raw, raw * 4.096 / 32768.0


def estimate_tds_ppm(voltage, temperature_c):
    """DFRobot-style approximation, not a measured calibration."""
    corrected = max(0.0, voltage) / (1.0 + 0.02 * (temperature_c - 25.0))
    return max(0.0, (133.42 * corrected**3 - 255.86 * corrected**2
                     + 857.39 * corrected) * 0.5)


def main():
    p = argparse.ArgumentParser(description="Read-only AquaCore sensor tester (ADS1115 TDS A3)")
    p.add_argument("--bus", type=int, help="Linux I2C bus number; e.g. 1 for /dev/i2c-1")
    p.add_argument("--address", type=lambda x: int(x, 0), default=0x48,
                   help="ADS1115 7-bit address (default 0x48)")
    p.add_argument("--interval", type=float, default=2.0)
    p.add_argument("--once", action="store_true")
    p.add_argument("--temperature", type=float, default=25.0,
                   help="Measured water temperature C for estimate (default 25)")
    args = p.parse_args()
    if args.interval < 0.05 or args.bus is not None and args.bus < 0:
        p.error("Invalid bus or interval")
    if not (-2 <= args.temperature <= 55):
        p.error("--temperature must be between -2 and 55 C")

    print("AquaCore SENSOR TEST — read-only, no DB writes or relay changes", flush=True)
    print("Temperature: not configured in project; no hardware reader available")
    print("pH:          not configured in project; no hardware reader available")
    print(f"TDS:         ADS1115 A3; estimated ppm at {args.temperature:.1f} C (NOT calibrated)")
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
    print(f"Reading ADS1115 0x{args.address:02x} on {path}, A3; Ctrl+C to quit")
    try:
        while True:
            try:
                raw, volts = adc_read(args.bus, args.address, 3)
                ppm = estimate_tds_ppm(volts, args.temperature)
                print(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  TDS A3: {volts:.5f} V  raw={raw}  estimated={ppm:.1f} ppm ({args.temperature:.1f} C, UNCALIBRATED)", flush=True)
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
