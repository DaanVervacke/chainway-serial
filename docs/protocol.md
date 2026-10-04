# Chainway UR4 protocol reference

Wire protocol for the Chainway UR4 fixed UHF RFID reader, reconstructed from the vendor SDKs. Every byte layout below comes from decompiled code in those SDKs, not from observation on hardware. Items marked **unverified** need a live reader to confirm.

Sources:

- Android `DeviceAPI_ver20250209_release.aar`, decompiled with jadx. Frame builder and command set: `com/rscja/team/qcom/deviceapi/Q.java` and `T.java`. Receive state machine: `com/rscja/team/qcom/e/b.java`. Tag record parser: `com/rscja/deviceapi/b.java`.
- Java `ReaderAPI20240822.jar`, decompiled with jadx. Frame builder: `com/rscja/deviceapi/i.java`, UR4 overrides in `j.java`. Tag record parser and batch format: `com/rscja/deviceapi/b.java`. Hardcoded ready-made frames: `com/rscja/deviceapi/d.java`.
- Windows `UHFAPI.dll` interface document `RFID_API_DLL_V1.0.1.doc`, converted to text. Command semantics, parameter units and value ranges. The C header `UHFAPI.h` and import library ship in the same archive.
- `libTagReader.so`, the Linux native counterpart of the DLL, extracted from the Java archive with debug symbols intact. Its frame builder and receiver independently confirm the wire format, and the receiver also accepts the `C8 8C` header and a 4096 byte length window.

Where the Android AAR and the Java jar disagree on a payload byte, the Windows DLL document usually explains it: the byte is a save flag, 0 for settings that survive until power off and 1 for settings stored persistently. The AAR tends to send 0, the jar tends to send 1. Both are valid wire encodings.

## Transports

| Transport | Parameters |
|---|---|
| TCP | Port 8888. Default reader address 192.168.99.202 per the vendor UR4 manual, Simple Fixed Reader User Manual (UR4, UR8, UR1A), 2023-04-28. SDK demo configs use 192.168.99.200 and 192.168.99.112. Raw byte stream. |
| RS-232 | 115200 baud, 8 data bits, 1 stop bit, no parity, no flow control. Custom rates possible, 115200 is the default. |
| USB HID | Windows SDK only. Not covered. |

The vendor datasheet and manual list RS-232 (115200 bps), RJ45 and GPIO as the only UR4 interfaces. They advertise no RS-485 and no USB. The manual states that the reader in the same LAN broadcasts its IP and MAC address, matching the UDP discovery below, and that the serial link can query the device IP.

The frame format and command set are identical on TCP and RS-232. Both pure-Java SDKs feed every transport into the same frame parser, and the parser resynchronizes on the frame header, so partial reads and chunking are harmless.

## Frame format

```
Offset  Size  Field
0       2     Header: A5 5A or C8 8C, both officially valid
2       2     Length: total frame size in bytes (payload + 8), big-endian, valid 8 to 2048
4       1     Command
5       N     Payload, N = Length - 8
5+N     1     Checksum: XOR of bytes at offsets 2 through 4+N (length bytes, command, payload)
6+N     2     Tail: 0D 0A
```

The official protocol document lists `C8 8C` as equally valid next to `A5 5A`, and the vendor's native receiver hunts both. This library sends `A5 5A`, like the Android SDK and the Windows DLL, and its parser accepts both. Which header the UR4 answers with is **unverified**. The Java SDKs reject frames above 2048 bytes, the native library accepts up to 4096, so the window is **unverified** at the top end.

The Windows `UHFAPI.dll` (64-bit build identical to the Java demo copy, 32-bit build in the C# app, same 458 exports) has two receive paths. The stream framer behind the read thread, used on serial, TCP, UDP and USB, accepts `A5` or `C8` as byte 0 and `5A` or `8C` as byte 1, checked independently, so a mixed pair would pass too. It takes lengths from 8 to 4096, XORs from the length bytes through the payload, requires `0D 0A`, and resets to the header hunt on any violation without rewinding to the byte after the header. The command response helper behind the `*_RecvData` builders accepts only `A5 5A` and 8 to 2048 bytes, and rejects a response unless its command equals the request command plus one. The DLL sends `A5 5A` for every command and no `C8 8C` appears in its code. Its static frames are the stop `A5 5A 00 08 8C 84 0D 0A` and the start `A5 5A 00 0A 82 00 00 88 0D 0A`, so the `27 10` start payload is specific to the npm client. The vendor clients therefore prove what the host accepts and sends, not what the firmware answers with.

Worked examples:

| Purpose | Bytes | Checksum |
|---|---|---|
| Get version | `A5 5A 00 08 02 0A 0D 0A` | 00 ^ 08 ^ 02 = 0A |
| Start inventory | `A5 5A 00 0A 82 00 00 88 0D 0A` | 00 ^ 0A ^ 82 ^ 00 ^ 00 = 88 |
| Stop inventory | `A5 5A 00 08 8C 84 0D 0A` | 00 ^ 08 ^ 8C = 84 |
| Beep on | `A5 5A 00 0A E4 03 01 EC 0D 0A` | 00 ^ 0A ^ E4 ^ 03 ^ 01 = EC |
| Get region | `A5 5A 00 08 2E 26 0D 0A` | 00 ^ 08 ^ 2E = 26 |
| Get Gen2 parameters | `A5 5A 00 08 22 2A 0D 0A` | 00 ^ 08 ^ 22 = 2A |
| Read tag data, see 0x84 | `A5 5A 00 16 84 00 00 00 00 01 00 00 00 00 03 00 02 00 02 90 0D 0A` | XOR over length, command and payload |
| Write tag data, see 0x86 | `A5 5A 00 18 86 00 00 00 00 01 00 00 00 00 03 00 02 00 01 E2 80 FD 0D 0A` | XOR over length, command and payload |
| Lock tag, see 0x88 | `A5 5A 00 14 88 00 00 00 00 01 00 00 00 00 02 00 80 1F 0D 0A` | XOR over length, command and payload |
| Kill tag, see 0x8A | `A5 5A 00 11 8A 12 34 56 78 01 00 00 00 00 92 0D 0A` | XOR over length, command and payload |
| Set tag filter, see 0x6E | `A5 5A 00 10 6E 00 01 00 20 00 10 12 34 69 0D 0A` | XOR over length, command and payload |
| Read collected tags, see 0xE0 | `A5 5A 00 08 E0 E8 0D 0A` | 00 ^ 08 ^ E0 = E8 |
| Read full collected tags, see 0xE2 | `A5 5A 00 09 E2 01 EA 0D 0A` | 00 ^ 09 ^ E2 ^ 01 = EA |
| Get device ID | `A5 5A 00 08 04 0C 0D 0A` | 00 ^ 08 ^ 04 = 0C |
| Get fixed frequency | `A5 5A 00 08 16 1E 0D 0A` | 00 ^ 08 ^ 16 = 1E |
| Get return loss | `A5 5A 00 08 26 2E 0D 0A` | 00 ^ 08 ^ 26 = 2E |
| Software reset | `A5 5A 00 08 68 60 0D 0A` | 00 ^ 08 ^ 68 = 60 |
| Restore factory settings | `A5 5A 00 08 74 7C 0D 0A` | 00 ^ 08 ^ 74 = 7C |
| Authenticate tag, see 0x8E | `A5 5A 00 1D 8E 00 00 00 00 01 00 00 00 00 0B 00 00 01 02 03 04 05 06 07 08 09 98 0D 0A` | XOR over length, command and payload |
| Block permalock, see 0x9F | `A5 5A 00 23 9F 00 00 00 00 02 00 00 00 60 E2 00 34 14 01 33 01 00 10 38 D2 B5 00 03 00 00 00 01 62 0D 0A` | XOR over length, command and payload |

Reading a frame from a stream: read 4 bytes, take the total length from bytes 2 and 3, read `length - 4` more bytes, verify the XOR and the `0D 0A` tail. Do not hunt for the `0D 0A` tail with a delimiter read, because tag payloads can contain that byte pair.

Receiver state machine, as implemented by the SDKs: hunt for `A5`, expect `5A`, collect length, reject anything outside 8 to 2048, collect command and payload, compare the XOR, expect `0D 0A`. On any mismatch, restart the hunt. Frames longer than 2048 bytes are dropped by the parser.

## Response conventions

- A response frame carries command = request command + 1. Request 0x02, response 0x03. Request 0x8C, response 0x8D.
- Set operations answer with payload `01` on success. Set operations that report an error code answer with a non-`01` payload, exact codes **unverified**.
- Tag operations answer with payload `01 00` on success. The second byte is the error flag: `01` means the operation failed and `22` means the tag could not be recognized, per the official protocol document. Other codes are **unverified**.
- Commands in the 0xA1 configuration family carry a subcommand in payload byte 0. Set operations answer with payload `01`. Get operations echo the subcommand number in payload byte 0, followed by the requested values.
- Commands 0x06 and 0x70 carry an operation selector in payload byte 0, see the tables below.
- The SDKs wait up to 2000 ms for a response.
- While a continuous inventory is running, the reader answers no command except stop inventory (0x8C). Set configuration before starting a scan.
- Start inventory (0x82) produces no meaningful acknowledgement. The 0x83 stream simply begins. The SDK sleeps 500 ms after sending the start and treats that as success.

### Keepalive and heartbeat

Client-side policy from the SDK connection managers. Whether the reader enforces any of this is **unverified**.

The Android SDK connection managers send a heartbeat only after 5 seconds of inbound silence, at most every 3 seconds, and suspend the dead-link check while an inventory runs. Idle they send a get-version frame, during inventory a single `00` byte, and 20 seconds of inbound silence on an idle link marks it dead. The Java jar sends get-version every 2 seconds, uses a 10 second dead link, and never drops the link during inventory. This library implements a fixed `keepalive_interval` of 5 seconds, the 20 second Android dead-link value, and suspends the dead-link check while an inventory runs. All three intervals are client parameters. The bare `00` byte is not a valid frame, the parser must tolerate it.

## Command reference

### Reader status

| Command | Request payload | Response | Meaning |
|---|---|---|---|
| 0x02 | empty | 0x03, payload `maj min patch` | Firmware version, printed as V<maj>.<min>.<patch>. The Android SDK renames known majors: 3 = E310, 5 = E510, 7 = E710 |
| 0xC8 | empty | 0xC9, payload `maj min patch` | STM32 microcontroller version, digits are raw values, printed as V<maj>.<min>.<patch> |
| 0x00 | empty | 0x01, payload `maj min patch` | Hardware version of the module, printed as V<maj>.<min>.<patch>. On an Ex10 module this is the version of the Ex10 chip, per the official protocol document |
| 0x04 | empty | 0x05, payload 4 bytes | Module ID, for example `F1 F2 F3 F4` |
| 0x34 | empty | 0x35, payload `01 hi lo` | Reader temperature. Value = 16-bit big-endian / 100 in degrees C, negative numbers are two's complement, per the official protocol document. The two Java SDKs instead treat `hi >= 0xF0` as negative and compute `(raw - 65535) / 100`, which differs by 0.01 degrees. The DLL document claims Fahrenheit, the two Java SDKs parse centigrade |
| 0x4E | empty | 0x4F, payload 2 bytes | Antenna connection state, a 16-bit mask: bit 0 = ANT1 through bit 15 = ANT16, per the official protocol document |
| 0xE4 sub 01 | `01` | 0xE5, payload `01 pct` | Battery charge percentage |

### RF power

Power values on the wire are centi-dBm, big-endian, so 30 dBm = 0x0BB8.

| Command | Request payload | Response | Meaning |
|---|---|---|---|
| 0x10 | `status` then per antenna: `ant readHi readLo writeHi writeLo` | 0x11, payload `01` | Set RF power per antenna. `ant` is 1-based, read power and write power in centi-dBm each. The single-antenna call sends `02 01 hi lo hi lo`. The status byte carries the save flag in bit 1, per the official protocol document: 0x02 stores the power across a power cycle, 0x00 keeps it until power off. Read power is reserved on the module and carries no meaning |
| 0x12 | empty | 0x13, payload `00` then per antenna: `ant readHi readLo writeHi writeLo` | Get RF power for every antenna. Both SDKs read the value from bytes 2 and 3, which is the read power of the first antenna |

### RF configuration

| Command | Request payload | Response | Meaning |
|---|---|---|---|
| 0x14 | `01 f2 f1 f0` | 0x15, payload `01` | Set fixed frequency, value in kHz, 3-byte big-endian, for example 920125. The leading `01` is the number of frequency points, only one is supported |
| 0x16 | empty | 0x17, payload `count` then `count` times 3 bytes | Get the fixed frequency table, values in kHz, 3-byte big-endian |
| 0x2C | `save region` | 0x2D, payload `01` | Set frequency region. `save` 0 or 1. Region: see the table below |
| 0x2E | empty | 0x2F, payload `01 region` | Get frequency region |
| 0x24 | `on` | 0x25, payload `01` | Set continuous carrier wave, 0 off, 1 on |
| 0x26 | empty | 0x27, payload `port loss` pairs | Get the return loss of every port in dB, one port number and one loss byte per port. A loss of 0 means the port is not enabled, or has no antenna connected on a single-port module. Both Java SDKs read payload byte 0 of this response as a carrier wave on/off state, which is the port-1 number of the return loss layout, so this library follows the official protocol document. **unverified** |
| 0x20 | 4 bytes, see below | 0x21, payload `01` | Set Gen2 parameters |
| 0x22 | empty | 0x23, payload 4 bytes | Get Gen2 parameters, same packing as the request |
| 0x52 | `00 save mode` | 0x53, payload `01` | Set recommended RF link combination. Mode: see the table below. Leading `00` constant, meaning **unverified** |
| 0x54 | `00 00` | 0x55, payload `01 00 mode` | Get RF link combination |
| 0x5C | `enable 00` | 0x5D, payload `01` | Set FastID, 0 off, 1 on. Trailing `00` constant |
| 0x5E | `00 00` | 0x5F, payload `01 enable` | Get FastID state |
| 0x60 | `enable 00` | 0x61, payload `01` | Set TagFocus, 0 off, 1 on. Trailing `00` constant |
| 0x62 | `00 00` | 0x63, payload `status enable` | Get TagFocus state. The AAR parses byte 0 as `01`, the jar as `00`, both read byte 1 as the state |
| 0x06 | `00 type` | 0x07, payload `00 01` | Set protocol type. Type: 0 ISO18000-6C, 1 GB/T29768, 2 GJB7377.1 |
| 0x06 | `01 00` | 0x07, payload `01 type` | Get protocol type |
| 0x30 | `01 value` | 0x31 | Set power-on dynamic configuration, semantics **unverified**, the Android SDK ships no response parser |
| 0x64 | `save enable 00` | 0x65, payload `01` | Set fast inventory mode. `save` 0 or 1, semantics of the mode **unverified** |
| 0x66 | `00 00` | 0x67, payload `01 enable` | Get fast inventory mode |
| 0x68 | empty | 0x69, payload `01` | Software reset of the UHF module, the official protocol document's module-level reset |
| 0x74 | empty | 0x75, payload `01` | Restore factory settings. The official protocol document defines 0x74 as the factory reset, the SDKs call the same opcode the soft reset. Which behavior the UR4 firmware implements is **unverified** |

Frequency regions, from the official protocol document:

| Region | Value | Region | Value |
|---|---|---|---|
| China1 | 0x01 | Sri Lanka | 0x38 |
| China2 | 0x02 | Azerbaijan | 0x39 |
| Europe | 0x04 | Iran | 0x3A |
| USA | 0x08 | Malaysia | 0x3B |
| Korea | 0x16 | Brazil | 0x3C |
| Japan | 0x32 | ETSI_UPPER | 0x3D |
| South Africa | 0x33 | Australia | 0x3E |
| Taiwan | 0x34 | Indonesia | 0x3F |
| Vietnam | 0x35 | Israel | 0x40 |
| Peru | 0x36 | Hong Kong | 0x41 |
| Russia | 0x37 | New Zealand | 0x42 |
| Singapore | 0x44 | 880MHz-930MHz | 0x43 |
| Thailand | 0x45 | | |

RF link combinations, from the official protocol document. The DLL document names 0x00 to 0x03 differently: DSB_ASK/FM0/40kHz, PR_ASK/Miller4/250kHz, PR_ASK/Miller4/300kHz and DSB_ASK/FM0/400kHz. The values match, the names do not. Per the official document 0x01 is the best performance for R2000 modules and 0x02 for Ex10 modules, and the Gen2X combinations only support the latest Impinj tags such as M830 and M850:

| Value | Combination | Value | Combination |
|---|---|---|---|
| 0x00 | PR_ASK / Miller8 / 160kHz | 0x0A | Gen2X / Miller8 / 160kHz |
| 0x01 | PR_ASK / Miller4 / 250kHz | 0x0B | Gen2X / Miller4 / 250kHz |
| 0x02 | PR_ASK / Miller4 / 320kHz | 0x0C | Gen2X / Miller4 / 320kHz |
| 0x03 | PR_ASK / Miller4 / 640kHz | 0x0D | Gen2X / Miller4 / 640kHz |
| 0x04 | PR_ASK / Miller2 / 320kHz | 0x0E | Gen2X / Miller2 / 320kHz |
| 0x05 | PR_ASK / Miller2 / 640kHz | 0x0F | Gen2X / Miller2 / 640kHz |

Gen2 packing for 0x20 and 0x22, four payload bytes:

```
byte 0: (target & 7) << 5 | (action & 7) << 2 | (truncate & 1) << 1 | (qMode & 1)
byte 1: (startQ & 15) << 4 | (minQ & 15)
byte 2: (maxQ & 15) << 4 | (dr & 1) << 3 | (coding & 3) << 1 | (trExt & 1)
byte 3: (sel & 3) << 6 | (session & 3) << 4 | (gen2Target & 1) << 3 | (linkFreq & 7)
```

Semantics from the DLL document: target 0 to 4 for S0 to S3 and SL, action 0 to 7, truncate 0 or 1, qMode 0 fixed and 1 dynamic, startQ, minQ and maxQ 0 to 15, dr 0 for 848kHz and 1 for 64/3, coding 0 FM0, 1 Miller2, 2 Miller4, 3 Miller8, trExt 0 or 1, sel 0 to 3, session 0 to 3 for S0 to S3, gen2Target 0 for A and 1 for B, linkFreq 0 40kHz, 1 160kHz, 2 200kHz, 3 250kHz, 4 300kHz, 5 320kHz, 6 400kHz, 7 640kHz.

### Antennas

| Command | Request payload | Response | Meaning |
|---|---|---|---|
| 0x28 | `save maskHi maskLo` | 0x29, payload `01` | Set antenna enable mask, 16 bits, high byte first, bit 0 = ANT1 through bit 15 = ANT16 |
| 0x2A | empty | 0x2B, payload 2 bytes | Get antenna enable mask |
| 0x4A | `setHi ant hi lo` or `ant hi lo` | 0x4B, payload `01` | Set antenna work time. The AAR sends `0x10 | ant`, the jar sends `ant`, so the high nibble is read as the save flag. Unit **unverified**. Antenna 16 collides with the save bit, the byte is the same either way |
| 0x4C | `ant 00` | 0x4D, payload `01 ant hi lo` | Get antenna work time, 16-bit big-endian |

### Inventory control

| Command | Request payload | Response | Meaning |
|---|---|---|---|
| 0x70 | `save mode userAddr userLen` | 0x71, payload `01` | Select inventory mode. Mode 0 = EPC only, mode 1 = EPC and TID, mode 2 = EPC, TID and USER. `userAddr` is the USER start address in 16-bit words, `userLen` the USER read length in words. TID is a fixed 12 bytes when present. The parser source also knows mode 10 = EPC and RESERVED, 14 = LED tag and 15 = temperature tag, support on UR4 **unverified** |
| 0x70 | `00 00 00 00` | 0x71, payload `01` | Shorthand for mode 0 without saving |
| 0x72 | `00 00` | 0x73, payload `01 mode userAddr userLen` | Get inventory mode |
| 0x6E | `save bank ptrHi ptrLo cntHi cntLo data...` | 0x6F, payload `01` | Set tag filter. Bank 1 = EPC, 2 = TID, 3 = USER. `ptr` is the bit offset of the match, `cnt` the match length in bits, `data` the match bytes, ceil(cnt / 8) of them. A zero bit length clears the filter and carries no data bytes, 6 payload bytes total |
| 0x80 | `00 64` | 0x81, one tag record | Single inventory. Returns at most one tag record in the response, and none when no tag is found. The official protocol document calls the two payload bytes reserved and its example sends `00 00`, both SDKs send `00 64` and their demos run on real hardware, so this library keeps the SDK bytes. Semantics **unverified** |
| 0x82 | `Num1 Num0` | none, stream begins | Start continuous inventory. The official protocol document defines the two payload bytes: `00 00` for a normal scan, `FF FF` for phase reporting, where every 0x83 record carries a 2-byte phase in degrees between the EPC and the RSSI pair. The SDKs always send `00 00`. A third-party Node client sends `27 10`, meaning **unverified** |
| 0x8C | empty | 0x8D, payload `01` | Stop continuous inventory |
| 0x83 | reader to host only | n/a | One tag sighting per frame, pushed while inventory runs |

### Tag operations

All tag operation requests share one layout. `password` is 4 bytes big-endian: the access password for read, write, block write, block erase and lock, the kill password for kill. The filter selects a single tag: `bank` 1 = EPC, 2 = TID, 3 = USER, `ptr` is the bit offset of the match, `cnt` the match length in bits, `data` ceil(cnt / 8) match bytes. When `cnt` is 0 the filter is omitted: the request carries `bank = 1, ptr = 0, cnt = 0` and no data bytes, and the reader picks a tag on its own.

```
password(4) | bank(1) | ptrHi ptrLo | cntHi cntLo | data(ceil(cnt/8)) | operation tail
```

| Command | Operation tail | Response | Meaning |
|---|---|---|---|
| 0x84 | `bank addrHi addrLo lenHi lenLo` | 0x85, payload `01 00 lenHi lenLo data...` | Read from a bank. `bank` 1 = EPC, 2 = TID, 3 = USER, `addr` and `len` in 16-bit words, data is `len * 2` bytes |
| 0x86 | `bank addrHi addrLo lenHi lenLo data(len*2)` | 0x87, payload `01 00` | Write to a bank, same units as read |
| 0x93 | `bank addrHi addrLo lenHi lenLo data(len*2)` | 0x94, payload `01 00` | Block write, same layout as write |
| 0x95 | `bank addrHi addrLo lenHi lenLo` | 0x96, payload `01 00` | Block erase, `len` in words |
| 0x88 | `lockCode(3)` | 0x89, payload `01 00` | Lock tag memories, see the lock code table |
| 0x8A | none | 0x8B, payload `01 00` | Kill tag, the password is the kill password. A tag with a zero kill password ignores the command |
| 0x8E | `dl keyId challenge(10)` | 0x8F, payload `01 00 lenHi lenLo data...` | Authenticate tag, the Gen2 v2.0 Authenticate command. `dl` is the length of KeyID plus Data in bytes, fixed at 11. `keyId` defaults to 0. `challenge` is the ten-byte IChallenge_TAM1 data. The response carries 8 words (16 bytes) of data on success, no data on failure. Only tags that support the command respond |
| 0x9F | `readLock bank ptrHi ptrLo rangeHi rangeLo [maskHi maskLo]` | 0xA0, payload `01 00 [data...]` | Block permalock operation. `readLock` bit 0 is 0 for a read and 1 for a permalock. `ptr` is the block start address in windows of 16 blocks of 8 bytes, `range` the number of windows. The 16-bit mask selects which of the 16 blocks of a window to permalock. The document's worked example omits the mask for the read form, so the mask bytes on the permalock form are **unverified**. A read response carries `range` words of per-block status bits after the flags, a permalock response carries none. Only tags that support the command respond |

### Lock code

The lock code is 3 bytes, big-endian. Bits 19 down to 10 are the Gen2 lock mask field, bits 9 down to 0 the action field, two bits per memory. The SDKs compute it from a set of banks and one mode.

Modes, from the demo constant names: open, lock, permanently open, permanently lock.

Banks and their bits:

| Bank | Mask bits | Action bits |
|---|---|---|
| Kill password | 19, 18 | 9, 8 |
| Access password | 17, 16 | 7, 6 |
| EPC memory | 15, 14 | 5, 4 |
| TID memory | 13, 12 | 3, 2 |
| USER memory | 11, 10 | 1, 0 |

Bits set per bank and mode, from the SDK generator:

| Bank | Open | Lock | Permanently open | Permanently lock |
|---|---|---|---|---|
| Kill password | 80000 | 80000 200 | 80000 40000 100 | 80000 40000 200 100 |
| Access password | 20000 | 20000 80 | 20000 10000 40 | 20000 10000 80 40 |
| EPC memory | 8000 | 8000 20 | 8000 4000 10 | 8000 4000 20 10 |
| TID memory | 2000 | 2000 08 | 2000 1000 04 | 2000 1000 08 04 |
| USER memory | 800 | 800 02 | 800 400 01 | 800 400 02 01 |

Values are hex bit positions. The generator ORs one column per selected bank, then writes the 20-bit result as 3 bytes big-endian. The example frame above locks the access password in lock mode: mask 0x20000 with action bit 0x80 gives `02 00 80`.

### Collected tag storage

| Command | Request payload | Response | Meaning |
|---|---|---|---|
| 0xE0 | empty | 0xE1, see batch format | Pull tags collected in auto and trigger work mode, EPC records only |
| 0xE2 | `01 ...` | 0xE3, see batch format | Variant with full tag records. The response carries one extra byte before the index pair, the request tail is **unverified** |
| 0xE9 | `FF` | 0xEA, payload `00 00` | Delete all collected tags from flash |
| 0xE9 | `00` | 0xEA, payload `cntHi cntLo` | Get count of all collected tags |
| 0xE9 | `01` | 0xEA, payload `cntHi cntLo` | Get count of new collected tags |
| 0xEB | `FF` | 0xEC, payload `count(1) | count times: [len][record bytes]` | Pull collected tag data from flash. The layout comes from the Android demo decode, the Java jar passes the payload through raw, so it is **unverified** on the UR4 |

Presence of the flash commands on the UR4 is **unverified**, the Android SDK inherits them from the A8 product line.

### Configuration family, command 0xA1

| Sub | Request payload | Response payload | Meaning |
|---|---|---|---|
| 01 | `01 ip0 ip1 ip2 ip3 portHi portLo` | `01` | Set reader IP and port. With subnet mask and gateway: `01 ip0 ip1 ip2 ip3 portHi portLo mask0 mask1 mask2 mask3 gw0 gw1 gw2 gw3`, 15 bytes |
| 02 | `02` | `02 ip0 ip1 ip2 ip3 portHi portLo` | Get reader IP and port. Long responses also carry mask and gateway |
| 03 | `03 ip0 ip1 ip2 ip3 portHi portLo` | `01` | Set destination IP and port. Target for the UDP push in auto and trigger work modes |
| 04 | `04` | `04 ip0 ip1 ip2 ip3 portHi portLo` | Get destination IP and port |
| 05 | `05 mode` | `01` | Set work mode. 0 = command mode, 1 = auto mode, 2 = trigger mode |
| 06 | `06` | `06 mode` | Get work mode |
| 07 | `07 state` | `01` | Buzzer on or off |
| 08 | `08` | `08 state` | Get buzzer state |
| 09 | `09 gpo0 gpo1 status` | `01` | Set GPO relay outputs. Each GPO is 0 low or 1 high, status 0 open or 1 closed |
| 0A | `0A` | `0A gpo0 gpo1` | Get GPO output state |
| 0B | `0B io workHi workLo intHi intLo out 00` | `01` | Set trigger mode parameters. See below |
| 0C | `0C` | `0C io workHi workLo intHi intLo out` | Get trigger mode parameters |
| 11 | `11 volume` | `01` or `11 01` | Set buzzer volume. The Android SDK is the only source and expects the subcommand echoed back, the family convention answers `01`, so both are accepted. **Unverified** |
| 12 | `12` | `12 volume` | Get buzzer volume |

Trigger parameters for sub 0B:

- `io`: which GPI input triggers inventory, 0 = input 1, 1 = input 2
- `work`: 16-bit big-endian, how long the inventory runs per trigger, unit 10 ms
- `int`: 16-bit big-endian, minimum time since the previous trigger, unit 10 ms
- `out`: tag output routing, 00 = the serial or TCP link, 01 = UDP to the destination IP
- trailing `00` is constant

### Peripherals, command 0xE4

| Request payload | Meaning |
|---|---|
| `01` | Battery charge percentage, answered by 0xE5 with `01 pct` |
| `02` | Scan a 1D or 2D barcode, if the reader variant has an imager. Response `02` followed by the barcode bytes, the 3-byte form `02 02 00` means no read. The Android SDK defines the no-read form, the Java jar does not. **Unverified** |
| `03 01 duration` | Buzzer duration |
| `03 01` | Beep once, the hardcoded frame `A5 5A 00 0A E4 03 01 EC 0D 0A` |
| `03 00` | Buzzer off, the hardcoded frame `A5 5A 00 0A E4 03 00 ED 0D 0A` |
| `05 value` | Set the reader idle sleep time, unit **unverified**, answered by 0xE5 with `01` |
| `06` | Get the reader idle sleep time, answered by 0xE5 with `06 value` |
| `07 01 00 00 00` | LED on |
| `07 00 00 00 00` | LED off |
| `07 02 r g b` | Blink the LED with color components |

### User settings family, command 0xF0

Imager module settings with two subchannels, 118 and 119, and an ack convention of `04 00` for writes. The demo uses it for scan timeout, movement sensitivity and illumination settings. Request layout `04 sub ...` with a nested length byte, response echo `04 00 sub ...`. Reads use `05 ...` and answer `05 00 ...`. Decoded shapes, semantics **unverified**:

| Request | Meaning |
|---|---|
| `04 76 01 88` | Set scan timeout, response carries the value in units of 100 ms capped at 10000 |
| `04 76 01 2D` | Query a 118 parameter, response value 0, 1 or value + 1000 |
| `04 76 01 EE` | Query another 118 parameter |
| `04 77 03 00 2D v` | Write a 119 parameter, v = 0 or 2 |
| `04 77 03 00 9F v` | Write a 119 parameter, v = 0 or 1 |
| `05 b 00 00` | Read user settings block b |

The Windows DLL exposes four subcommands of 0xF0, with a 3000 ms timeout for upload and download and 1500 ms for the others. Sub `01` is upload user parameters, payload `01 data`, acknowledged by `01 00`. Sub `02` is download, request `02`, response `02 00 data`. Sub `03` sets BLE parameters, payload `03 data`, acknowledged by `03 00`. Sub `04` sets parameters, payload `04 data`, acknowledged by `04 00`. The DLL's `ScannerRead` sends 0xE4 subs `02` and `00` with a 16-bit field, not decoded.

### Firmware update

| Command | Request payload | Meaning |
|---|---|---|
| 0xC0 | 1 byte target selector | Jump to the bootloader of one firmware target |
| 0xC2 | empty | Start the update |
| 0xC4 | 64-byte block | Send one firmware block |
| 0xC6 | empty | Stop the update |

The 0xC0 payload selects the target. The Android AAR, the C# demo, `libTagReader.so` and the Windows DLL map a flag to a byte, and the Java jar only knows flag 1.

| Flag | Byte | Target | Version read first |
|---|---|---|---|
| 0 | `EE` | Mainboard, the reader application on the STM32 | 0xC8 |
| 1 | `CC` | UHF module | 0x02 |
| 2 | `BB` | Reader bootloader | none |
| 3 | `AA` | Ex10 SDK firmware | none |

The manual's "Motherboard Firmware" and "UHF Firmware" options most likely correspond to flags 0 and 1. The Android demo offers flags 0 and 1, the Java demo only flag 1, and the C# demo offers all four.

The vendor sequence:

1. Read the current version.
2. Send 0xC0 with the selector and wait 2000 ms.
3. For a target other than the UHF module on TCP or USB, the C# demo drops the link, waits about 1000 ms and reconnects. The Android SDK does the same for the mainboard target. The Java SDK does not.
4. Send 0xC2 and wait 2000 ms.
5. Send the image as consecutive 0xC4 blocks of 64 bytes with no sequence number, offset or per-block checksum. The C# demo pauses 5 ms between blocks and the Java SDK waits up to 5000 ms for each reply. Any failure aborts and sends 0xC6.
6. Send 0xC6, wait 2000 ms and read the version again.

The Java and Android SDKs expect the replies 0xC1, 0xC3, 0xC5 and 0xC7 with payload `01`. The native libraries do not wait for the 0xC6 reply, so whether the firmware answers it is **unverified**. The image is the raw `.bin` file with no host-side header. The only image in the vendor archives, `Ex10 V2.0.0.bin`, is 160804 bytes and looks encrypted. The vendor download URL names a four channel CM710-4 mainboard image. The Java and Android SDKs zero-pad the last block to 64 bytes, the Windows DLL export used by the C# demo sends the short tail with its real length, and both forms are **unverified** on the firmware.

Worked frames:

| Frame | Bytes |
|---|---|
| Jump to the UHF module | `A5 5A 00 09 C0 CC 05 0D 0A` |
| Jump to the mainboard | `A5 5A 00 09 C0 EE 27 0D 0A` |
| Jump to the reader bootloader | `A5 5A 00 09 C0 BB 72 0D 0A` |
| Jump to Ex10 | `A5 5A 00 09 C0 AA 63 0D 0A` |
| Start update | `A5 5A 00 08 C2 CA 0D 0A` |
| Stop update | `A5 5A 00 08 C6 CE 0D 0A` |
| Short tail block of 4 bytes | `A5 5A 00 0C C4 01 02 03 04 CC 0D 0A` |

The Ax Android readers have a separate TCP upgrade service with an APK upload, file size and MD5. It is not part of this flow.

## Other product lines

The shared SDK code bases carry commands for other Chainway products. They are decoded but not implemented in this library and have no confirmed UR4 support:

| Command | Request payload | Response | Meaning |
|---|---|---|---|
| 0xE5 | `04 mode` | 0xE6, payload `01` | R6 work mode |
| 0xF2 | HF commands | | The DLL uses it for every HF, ISO 15693 and smart card export. Another product line |

The DLL also routes an incoming 0x7F frame like 0x83 into the tag queue, with a payload of at least 4 bytes and a different type flag, and treats 0xEC specially as split content data. No export sends 0x7F and its payload is not decoded.

## Module-level protocol

The official protocol document V2.1.2 describes the UHF module protocol, one layer below the reader protocol. The frame format and the tag operation commands are shared, and this library implements the module-level command subset next to the reader protocol. The commands below appear in the document but in none of the two Java SDKs: get device ID (0x04), get fixed frequency (0x16), get return loss (0x26), software reset (0x68), authenticate tag (0x8E) and block permalock (0x9F). The vendor's native Linux library `libTagReader.so` from the UR4 Java demo builds all six, as `UHFGetDeviceID`, `UHFGetJumpFrequency`, `UHFGetCW`, `UHFSetSoftReset`, `UHFAuthenticate` and `UHFBlockPermalock`. Whether the UR4 reader firmware answers them is still **unverified**.

The deltas between the two layers:

- The document's examples all use the `C8 8C` header.
- At module level 0x68 is the software reset and 0x74 the factory reset, while the Java SDKs know only 0x74 and call it the soft reset. The Android native libraries `libDeviceAPIM.so` and `libDeviceAPIQ.so` (DeviceAPI 20250209) build 0x68 as their soft reset frame, `A5 5A 00 08 68 60 0D 0A`, and contain no 0x74 builder. The library implements both commands per the document. Which behavior the UR4 firmware implements for 0x74 is **unverified**
- Tag operation error responses carry an error flag after the success flag: 0x01 means the operation failed and 0x22 means the tag could not be recognized.
- The document defines 0x26 as get return loss. Both Java SDKs read the first payload byte of the 0x27 response as a carrier wave on/off state, which is the port-1 number of the return loss layout. The library follows the document.
- Commands 0xA1 through 0xFF are reserved at module level. The reader protocol uses them: the 0xA1 configuration family, the 0xE4 peripherals and the 0xE0 collected tag pull exist only at reader level.

## Native library command catalog

`libTagReader.so` in the Java UR4 and UR1A demo (v1.1, 2024-08-23) is the Linux counterpart of the Windows `UHFAPI.dll`. It ships with debug symbols, so parameter names come from DWARF. Every function funnels into one send and receive routine that takes the command byte, a payload length and the payload, which makes the opcode of each function readable from the disassembly. The table lists the builders for opcodes that this document did not cover before. Nothing here is verified against a UR4. The demo ships the library for the UR4 and UR1A, so the opcodes are at least intended for these readers.

Map generation: the library carries opcodes of both document revisions. It has the V2.0.8 QT commands 0x97 to 0x9D and the temperature protection pair 0x38 and 0x3A, and it also has 0x4E as antenna link status, the V2.1.2 meaning. It names 0x26 get CW, the V2.0.8 meaning. Opcode 0x74 is `UHFSetDefaultMode` next to 0x68 `UHFSetSoftReset`, which matches the V2.1.2 split into factory reset and soft reset.

In the layouts below `filter` is `bank(1) addr(2) len_bits(2) data(ceil(len_bits/8))`, multi-byte fields are big-endian, and "ok" means the first reply payload byte is `01`. Every example frame was recomputed with the XOR rule.

| Opcode | Native function | Request payload | Reply parsing | Example frame |
|---|---|---|---|---|
| 0x18 | `UHF_Set_Param` | `type(1) ID(4) data(4)` | ok | `A5 5A 00 11 18 01 00 00 00 01 00 00 00 02 0B 0D 0A` |
| 0x1A | `UHF_Get_Param` | `type(1) ID(4)` | ok, then 4 data bytes after the echoed ID, shape inferred | `A5 5A 00 0D 1A 01 00 00 00 01 17 0D 0A` |
| 0x30 | `UHF_Inventory_Bank` | `pwd(4) bank(1) ptr(2) cnt(2)` | ok | `A5 5A 00 11 30 00 00 00 00 03 00 00 00 04 26 0D 0A` |
| 0x38 | `UHFSetTemperatureProtect`, `UHFSetTempVal` | 1 byte, flag or temperature value | ok | `A5 5A 00 09 38 01 30 0D 0A` |
| 0x3A | `UHFGetTemperatureProtect`, `UHFGetTempVal` | empty | ok, then the value | `A5 5A 00 08 3A 32 0D 0A` |
| 0x3C | `UHFSetWorkTime` | `DByte4 .. DByte0`, 5 bytes | ok | `A5 5A 00 0D 3C 00 00 00 01 F4 C4 0D 0A` |
| 0x3E | `UHFGetWorkTime` | empty | ok, then 4 bytes | `A5 5A 00 08 3E 36 0D 0A` |
| 0x6A | `UHFSetDualSingelMode` | `save(1) mode(1)` | ok | `A5 5A 00 0A 6A 01 01 60 0D 0A` |
| 0x6C | `UHFGetDualSingelMode` | empty | ok, then the mode | `A5 5A 00 08 6C 64 0D 0A` |
| 0x08 | `UHFVerifyVoltage` | `01` | `01 01 value(2)`, signed | `A5 5A 00 09 08 01 00 0D 0A` |
| 0x97 | `UHFSetQT` | `pwd(4) filter QTData(1)` | ok | `A5 5A 00 14 97 00 00 00 00 01 00 20 00 10 E2 80 01 D1 0D 0A` |
| 0x99 | `UHFGetQT` | `pwd(4) filter` | ok, then QTData | `A5 5A 00 13 99 00 00 00 00 01 00 20 00 10 E2 80 D9 0D 0A` |
| 0x9B | `UHFReadQT` | `pwd(4) filter QTData(1) rbank(1) rptr(2) rcnt(2)` | `01 00 words(2) data(words*2)` | `A5 5A 00 19 9B 00 00 00 00 01 00 20 00 10 E2 80 01 03 00 00 00 02 D1 0D 0A` |
| 0x9D | `UHFWriteQT` | as 0x9B with `rcnt*2` data bytes appended | `01 00` | `A5 5A 00 1B 9D 00 00 00 00 01 00 20 00 10 E2 80 01 03 00 00 00 01 12 34 F0 0D 0A` |
| 0xB0 | `UHFDeactivate` | `cmd(2) pwd(4) filter` | ok | `A5 5A 00 15 B0 00 00 00 00 00 00 01 00 20 00 10 E2 80 F6 0D 0A` |
| 0xB2 | `UHFDwell` | `dwell(4) count(4)` | ok | `A5 5A 00 10 B2 00 00 03 E8 00 00 00 03 4A 0D 0A` |

The QT commands are the V2.0.8 Impinj Monza QT operations. The `UHF_ReadQTDataSingle` and `UHF_WriteQTDataSingle` wrappers run a single inventory (0x80 `00 64`) before the 0x9B or 0x9D frame. The native read count byte truncates above 255 bytes.

Sensor and calibration, opcode 0x7C. The request is `sub(1) EPC(16) ant(1) power(2)` with the EPC zero padded, and the reply is `01 00 words(2) data(words*2)`. The sub operations are 01 sensor code, 02 get calibration, 03 on-chip RSSI, 04 temperature code, 05 RSSI plus temperature code and 06 write calibration, which appends 8 data bytes. Example, sub 03 with antenna 1 and power 0x0BB8: `A5 5A 00 1C 7C 03 E2 80 11 60 60 00 02 05 6B 3A 5A 1E 00 00 00 00 01 0B B8 B0 0D 0A`.

Tag sensor operations, opcode 0xA3. The first payload byte selects the function and the second part is `bank(1) addr(2) len_bits(2) data` as a mask filter.

| Sub | Native function | Extra payload | Reply | Example |
|---|---|---|---|---|
| 03 | `UHFStartLogging` | `min(2) max(2) delay(2) interval(2)`, min and max are 10-bit temperature codes | ok, otherwise a nonzero error code in the second byte | `A5 5A 00 18 A3 03 01 00 20 00 10 E2 80 00 50 00 7A 00 00 00 0A CB 0D 0A` |
| 04 | `UHFStopLogging` | none | as sub 03 | `A5 5A 00 10 A3 04 01 00 20 00 10 E2 80 E4 0D 0A` |
| 05 | `UHFCheckOpMode` | none | `05 value(2)` | `A5 5A 00 10 A3 05 01 00 20 00 10 E2 80 E5 0D 0A` |
| 06 | `UHFReadTagVoltage` | none | `06 raw(2)`, volts = raw x 2.5 / 8192 | `A5 5A 00 10 A3 06 01 00 20 00 10 E2 80 E6 0D 0A` |
| 07 | `UHFReadMultiTemp` | `t_start(2) t_num(1)` | `07 total(2) returnNum(1)` then one 4-byte record per tag, with a little-endian 10-bit code in the first two bytes | `A5 5A 00 13 A3 07 01 00 20 00 10 E2 80 00 00 04 E0 0D 0A` |

The 10-bit temperature code is a signed fixed point value, 8 bits of whole degrees Celsius and 2 bits of quarter degrees, so 20.0 C is 0x050 and 30.5 C is 0x07A. The library's decoder may be off by one degree for negative fractions. The 0xA3 sub 03 layout comes from the disassembly only, and the 0x1A reply shape is inferred. The other layouts match emulated builder output. The DWARF parameter names of `UHFStartLogging` do not match the register order in the code.

The Windows DLL carries the same 0x38, 0x3C, 0x6A, 0x7C, 0x97 to 0x9D, 0xA3, 0xB0 and 0xB2 builders and lacks 0x18, 0x1A and 0x30.

## Third-party implementations

Independent implementations that corroborate the frame format against live hardware:

- jlujan2016/ur4_test_gpio, Rust: relay control, quotes the official software's 0xA1 sub 09 frames `A5 5A 00 0C A1 09 00 00 01 A5 0D 0A` and `... 09 00 00 00 A4 0D 0A`, matching the library's GPO layout.
- ready2tag/chainway-rfid, npm: UR4 over TCP, start inventory `A5 5A 00 0A 82 27 10 BF 0D 0A` and the stop frame with the `C8 8C` header.
- 01Hash10/chainway-ur4-rs232-usb, Python: single and continuous inventory over RS-232 with `C8 8C` frames, and the host of the official protocol document.
- jlujan2016/simulador_UR4_chainway, Rust: a reader simulator speaking the tag frame layout.

A cluster of Node and Tauri applications by the same author carries a second, conflicting command table, 0x87 version, 0x89 inventory, 0x93 power, on the same framing. No source explains its origin and no captured responses exist, so it is not treated as protocol evidence.

## Tag record

The payload of a 0x83 frame, and the response of a single inventory (0x81), is one tag record:

```
PC(2) | EPC(...) | TID(12, optional) | USER(..., optional) | RSSI(2) | ANT(1)
```

- EPC length comes from the Gen2 PC word: bytes = (PC[0] >> 3) * 2, where PC[0] is the first byte of the record
- TID is present as a fixed 12-byte block when the inventory mode includes TID
- USER data follows TID when the mode includes it. The SDKs treat more than 3 bytes after the TID block as the marker for a present USER block
- Without a TID block the RSSI pair and the antenna byte sit directly after the EPC, the SDKs have no short TID block
- RSSI: 16-bit big-endian two's complement of dBm times ten, so raw 0xFD6F = -65.7 dBm, matching the official document's worked example. The SDKs compute (raw - 65535) / 10 instead, which differs by 0.1 dBm. The SDKs treat values outside a 20 dBm span as invalid, and so does this library
- ANT: 1-byte antenna index, 0-based
- Phase: in phase reporting mode, started with the `FF FF` payload, a 2-byte big-endian phase in degrees, 0 to 360, sits between the body and the RSSI pair. The documented shape carries it after the EPC, the position with TID or USER blocks present is inferred. **Unverified**

The parser infers which optional blocks are present from the total record length, since the inventory mode is known by context.

Collected tag batch format, used by the 0xE0 read-tag-data command for tags collected in auto and trigger work modes:

```
indexHi indexLo count | count times: [len][record bytes]
```

- 0xE0 records are raw EPC bytes with no PC word and no RSSI or antenna
- 0xE2 records are full tag records with the PC word and RSSI but no antenna byte, and the batch carries one extra byte before the index pair
- A payload shorter than 5 bytes carries only the 16-bit index, the SDK reports it as an invalid tag marker
- The 0xEC flash response follows a different layout, one count byte then per record one length byte and raw EPC bytes, from the Android demo decode

The Windows DLL exposes a different, length-prefixed layout to applications through `UHF_GetReceived_EX`: `uiiLen | PC+EPC | tidLen | TID | RSSI(2) | ANT(1)`. The two pure-Java SDKs parse the PC-based layout directly off the wire, so the PC-based layout is the wire format and the length-prefixed layout is a DLL-side representation. **Verify against live traffic when hardware is available.**

## UDP device discovery

The reader broadcasts a 12-byte UDP packet to port 1111:

```
MAC(6) | IPv4(4) | TCP port(2, big-endian)
```

The Java SDK listens on port 1111 and reports every reader that announces itself. The C# demo binds 0.0.0.0:1111 with a 500 ms receive timeout, accepts datagrams of at least 12 bytes and drops a device after 30 seconds without a packet. Tag data pushed in auto mode over UDP arrives as the same 0x83 frames as on the serial link, read through the DLL's `BindUDP`. The Windows DLL has matching BindUDP and UnbindUDP entry points.

## Work modes

Set with 0xA1 sub 05.

| Mode | Name | Behavior |
|---|---|---|
| 0 | Command mode | The host starts and stops inventory with 0x82 and 0x8C. Default mode |
| 1 | Auto mode | The reader inventories on its own, using the trigger parameters as timing. Tag output goes to the link or UDP depending on the output routing parameter |
| 2 | Trigger mode | A signal on GPI input 1 or 2 starts an inventory run for the configured work time. Output routing applies here too |

From the vendor manual: the start and stop conditions in trigger mode must be opposite levels, for example start on a high level at input 1 and stop on a low level with a configurable delay such as 1000 ms. In auto mode the reader starts inventory on power up and sends tag data over UDP to the configured target IP and port, which is the output routing parameter. A factory reset restores the IP settings and the work mode. The factory defaults are antenna 1 enabled, 30 dBm and an EPC-only inventory mode. The manual documents the demo GUI only and gives no wire bytes.

## Open items

- 0x80 single inventory payload bytes `00 64`: first byte is likely an antenna or mode selector, 100 is likely a duration. Untested on hardware
- The Android SDK socket layer measures silence from the last inbound byte. After 5 seconds it sends the heartbeat, get-version when idle and the bare byte `00` during inventory, and repeats it about every 3 seconds while the silence lasts. It drops the link after 20 seconds of silence. Its connect timeout is 5000 ms, its read timeout 500 ms, and it sends stop inventory 100 ms after a successful connect
- The DLL has no keepalive on TCP or serial. Its only heartbeat is the USB poll `A5 5A 00 08 EB E3 0D 0A` while no inventory runs, so the 5 and 20 second maintenance intervals do not come from the vendor DLL. The DLL's stop routine resends the stop frame every 100 ms for up to 1000 ms until the 0x8D reply arrives
- Whether the reader enforces the heartbeat or keepalive intervals, or whether they are purely client-side library behavior
- Whether a 0x83 frame can carry more than one record. Both pure-Java SDKs parse exactly one record per frame, and the 0xE0 batch exists for the multi-record case
- Error payload values beyond `01`, `01 00` and the documented `01` and `22` tag error flags, no SDK decodes them
- The meaning of the leading `00` in the 0x52 RF link payload
- The 0x4A work time save flag reading, inferred from the AAR and jar disagreement
- The 0xE2 request tail
- The 0xF0 user settings semantics beyond the shapes listed above
- Antenna work time unit, the idle sleep time unit, and the inventory modes 3, 10, 14 and 15 from the parser constants
- Whether the volume set response is a bare `01` or echoes the subcommand, the only parser and the family convention disagree
- Whether the flash storage commands 0xE9 and 0xEB apply to the UR4
- Which header the reader answers with, `A5 5A` or `C8 8C`
- The 4096 versus 2048 length window: the Java SDKs and the Android native receiver cap at 2048, the Linux and Windows native library at 4096
- The phase reporting record layout with TID or USER blocks present, inferred from the documented EPC-only shape
- The `27 10` start inventory payload seen in a third-party client
- Whether the UR4 reader firmware forwards the module-level commands 0x04, 0x16, 0x26, 0x68, 0x8E and 0x9F, which appear in no Java SDK and only in the native Linux library
- Whether 0x74 factory-resets or soft-resets the UR4. The native libraries name 0x74 `UHFSetDefaultMode` and 0x68 `UHFSetSoftReset`, so a factory reset is the likely reading
- The block permalock mask bytes on the permalock form
- RS-485 variants, if the specific unit has one: half-duplex direction control is outside the protocol

## Decompiled source locations

The decompiled trees live in a temporary workspace:

- Android AAR: obfuscated class names, `Q.java` and `T.java` hold the command builders, `com/rscja/deviceapi/b.java` the tag record, batch and lock code logic
- Java jar: readable names, `i.java` and `j.java` hold the frame and command logic, `h.java` and `d.java` the record and hardcoded frames
- `api_doc.txt` inside the Windows demo: converted DLL reference with command semantics and units, `UHFAPI.h` in the same archive holds the C signatures
- C# demo with the full P/Invoke surface in `UHFAPI.cs`
- Android native libraries `libDeviceAPIM.so` and `libDeviceAPIQ.so` inside the AAR, arm64-v8a build, disassembled with radare2. The 47 `UHF*_SendData` builders emit the frames listed in this document with the `A5 5A` header, none uses `C8 8C` and none adds an opcode this library lacks. Both libraries produce identical frames. The receiver `Um7_BT_RecvData` is a nine-state machine that hunts `A5` then `5A`, reads a 16-bit length, rejects lengths below 8 or above 2048 and resets, XORs every byte from the length through the payload, compares that to the checksum byte, then requires `0D` and `0A`. It never accepts `C8 8C`. The libraries name opcode 0x26 get CW, which agrees with the V2.0.8 opcode map
