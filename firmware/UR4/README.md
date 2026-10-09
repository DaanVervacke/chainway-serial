# UR4 firmware dumps

Dumped on October 9, 2026 from the development unit, after a 0x74 factory reset and a 0x68 reboot. Mainboard firmware 7.0.9, bootloader 1.2.1, UHF module firmware 7.40.1, hardware 2.2.0. Checksums are in `mainboard-stm32f2/SHA256SUMS`.

## mainboard-stm32f2

STM32F2, device ID 0x411, 512 KiB flash, 128 KiB SRAM, read protection level 0. Read over SWD with a Tigard on the mainboard header `3V3 DIO CLK RST GND`, OpenOCD with the `ftdi` driver in SWD mode. The core was halted during the reads and resumed afterwards. Nothing was written.

| File | Address | Size | Content |
|---|---|---|---|
| `ur4-mainboard-flash-full-v7.0.9.bin` | 0x08000000 | 512 KiB | Whole flash. Read twice with identical results, and identical to a dump taken before the factory reset. The three files below are slices of it |
| `ur4-mainboard-bootloader-v1.2.1.bin` | 0x08000000 | 32 KiB | Flash sectors 0 to 2. Chainway bootloader, prints the boot console and the network block, jumps to 0x08010000 |
| `ur4-mainboard-settings.bin` | 0x0800C000 | 16 KiB | Flash sector 3. 31 bytes of stored settings, the rest erased |
| `ur4-mainboard-application-v7.0.9.bin` | 0x08010000 | 64 KiB | Flash sector 4. Application, vector table at the start, reset handler 0x080144CD. Sectors 5 to 7 are erased |
| `ur4-mainboard-sram-running-v7.0.9.bin` | 0x20000000 | 128 KiB | RAM of the running application with the module connected. 0x20000014 holds the module baud rate (115200), 0x20000009 the boot probe result (0x07) |
| `stm32f2-st-system-bootloader.bin` | 0x1FFF0000 | 30 KiB | ST system bootloader in ROM, not Chainway code |
| `ur4-mainboard-otp.bin` | 0x1FFF7800 | 528 B | One-time programmable area and its lock bytes, blank (all FF) |
| `ur4-mainboard-uid-flashsize.bin` | 0x1FFF7A10 | 20 B | 96-bit unique ID and the flash size register |
| `ur4-mainboard-option-bytes.bin` | 0x1FFFC000 | 16 B | RDP 0xAA (level 0), no write protection |
| `ur4-mainboard-backup-sram.bin` | 0x40024000 | 4 KiB | Backup SRAM. The firmware never enables its clock, so the content is power-on noise |
| `ur4-mainboard-rtc-backup-registers.bin` | 0x40002850 | 80 B | RTC backup registers, all zero |

Disassemble the application with `r2 -a arm -b 16 -m 0x08010000 ur4-mainboard-application-v7.0.9.bin`, or the full image with `-m 0x08000000`. The protocol reference describes what is known about the internals, see "Mainboard internals" in `docs/protocol.md`.

## uhf-module

Not dumped. The module is only reachable from the mainboard over its UART, and the protocol has no memory read command. A dump needs the module's own debug pads under its shield.

## settings

Every read command through the library over RS-232, before and after the factory reset. Both files are identical, so the unit was already at factory defaults.
