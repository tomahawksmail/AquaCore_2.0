# AquaCore TDS sensor wiring (Orange Pi Zero 2W)

**Status:** wiring notes only; software integration and measurement calibration not yet implemented.

TDS analog module -> ADS1115 (4-channel I²C ADC) -> Orange Pi Zero 2W.

| Source | Destination |
| --- | --- |
| TDS analog output A | ADS1115 A3 (single-ended analog channel 3) |
| TDS GND | Common ground with ADS1115 and Orange Pi |
| ADS1115 SDA | Orange Pi physical pin 3 / PI8 / I²C1 SDA |
| ADS1115 SCL | Orange Pi physical pin 5 / PI7 / I²C1 SCL |
| ADS1115 VDD | Orange Pi physical pin 1 / 3.3V |
| ADS1115 GND | Orange Pi physical pin 6 or 9 / GND |

TDS module supply: verify exact purchased board. For DFRobot-style Gravity analog TDS transmitter, specified operating range is 3.3-5.5V, analog signal 0-2.3V, so 3.3V power is a good fit. Confirm VDD and analog output limits for the actual board before connecting. Do not put 5V into the Orange Pi GPIO, I²C signals or 3.3V-powered ADS1115 inputs.

ADS1115 ADDR must be configured: ADDR grounded typically corresponds to I²C address 0x48. Check the specific breakout for any address strap, gain, and pullup configuration. Tie all sensor grounds together. Do not assume channel A3 maps to database `tds` without a conversion/calibration function.

Test later (no relay loads involved): `ls /dev/i2c-*`, and `i2cdetect -l` to identify the bus. Check device-tree I²C enablement if the bus is missing. Avoid blindly assuming a Linux bus index, since it can vary with firmware.

**Do not enable sensor writing to MariaDB yet.** Temperature compensation and calibration are required for meaningful ppm readings. The named product link was supplied for a similar device rather than as a confirmed part number.
