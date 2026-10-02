# Chainway UR4 protocol reference

Wire protocol for the Chainway UR4 fixed UHF RFID reader, reconstructed from the vendor SDKs. Every byte layout below comes from decompiled code in those SDKs, not from observation on hardware. Items marked **unverified** need a live reader to confirm.

Sources:

- Android `DeviceAPI_ver20250209_release.aar`, decompiled with jadx. Frame builder and command set: `com/rscja/team/qcom/deviceapi/Q.java` and `T.java`. Receive state machine: `com/rscja/team/qcom/e/b.java`. Tag record parser: `com/rscja/deviceapi/b.java`.
- Java `ReaderAPI20240822.jar`, decompiled with jadx. Frame builder: `com/rscja/deviceapi/i.java`, UR4 overrides in `j.java`. Tag record parser and batch format: `com/rscja/deviceapi/b.java`. Hardcoded ready-made frames: `com/rscja/deviceapi/d.java`.
- Windows `UHFAPI.dll` interface document `RFID_API_DLL_V1.0.1.doc`, converted to text. Command semantics, parameter units and value ranges.
- Java and C# demo applications shipped in the three RAR archives at the repository root.

Where the Android AAR and the Java jar disagree on a payload byte, the Windows DLL document usually explains it: the byte is a save flag, 0 for settings that survive until power off and 1 for settings stored persistently. The AAR tends to send 0, the jar tends to send 1. Both are valid wire encodings.

## Transports

| Transport | Parameters |
|---|---|
| TCP | Port 8888. Default reader address 192.168.99.200 (demo configs also use 192.168.99.112 and .202). Raw byte stream. |
| RS-232 | 115200 baud, 8 data bits, 1 stop bit, no parity, no flow control. Custom rates possible, 115200 is the default. |
| USB HID | Windows SDK only. Not covered. |

The frame format and command set are identical on TCP and RS-232. Both pure-Java SDKs feed every transport into the same frame parser, and the parser resynchronizes on the frame header, so partial reads and chunking are harmless.

## Frame format

```
Offset  Size  Field
0       2     Header: A5 5A
2       2     Length: total frame size in bytes (payload + 8), big-endian, valid 8 to 2048
4       1     Command
5       N     Payload, N = Length - 8
5+N     1     Checksum: XOR of bytes at offsets 2 through 4+N (length bytes, command, payload)
6+N     2     Tail: 0D 0A
```

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

Reading a frame from a stream: read 4 bytes, take the total length from bytes 2 and 3, read `length - 4` more bytes, verify the XOR and the `0D 0A` tail. Do not hunt for the `0D 0A` tail with a delimiter read, because tag payloads can contain that byte pair.

Receiver state machine, as implemented by the SDKs: hunt for `A5`, expect `5A`, collect length, reject anything outside 8 to 2048, collect command and payload, compare the XOR, expect `0D 0A`. On any mismatch, restart the hunt. Frames longer than 2048 bytes are dropped by the parser.

## Response conventions

- A response frame carries command = request command + 1. Request 0x02, response 0x03. Request 0x8C, response 0x8D.
- Set operations answer with payload `01` on success. Set operations that report an error code answer with a non-`01` payload, exact codes **unverified**.
- Tag operations answer with payload `01 00` on success. Anything else starting with `01` is a failure, exact codes **unverified**.
- Commands in the 0xA1 configuration family carry a subcommand in payload byte 0. Set operations answer with payload `01`. Get operations echo the subcommand number in payload byte 0, followed by the requested values.
- Commands 0x06 and 0x70 carry an operation selector in payload byte 0, see the tables below.
- The SDKs wait up to 2000 ms for a response.
- While a continuous inventory is running, the reader answers no command except stop inventory (0x8C). Set configuration before starting a scan.
- Start inventory (0x82) produces no meaningful acknowledgement. The 0x83 stream simply begins. The SDK sleeps 500 ms after sending the start and treats that as success.

### Keepalive and heartbeat

Client-side policy from the SDK connection managers. Whether the reader enforces any of this is **unverified**.

- Idle connection: send a get-version frame every 5 seconds. 20 seconds without any inbound data marks the connection dead and triggers a disconnect.
- During inventory: send a single `00` byte every 5 seconds. No response is expected. This bare byte is not a valid frame, the parser must tolerate it.

## Command reference

### Reader status

| Command | Request payload | Response | Meaning |
|---|---|---|---|
| 0x02 | empty | 0x03, payload `maj min patch` | Firmware version, printed as V<maj>.<min>.<patch>. The Android SDK renames known majors: 3 = E310, 5 = E510, 7 = E710 |
| 0xC8 | empty | 0xC9, payload `maj min patch` | STM32 microcontroller version, digits are raw values, printed as V<maj>.<min>.<patch> |
| 0x00 | empty | 0x01, payload `maj min patch` | SDK firmware version of the module, printed as V<maj>.<min>.<patch> |
| 0x34 | empty | 0x35, payload `01 hi lo` | Reader temperature. Value = 16-bit big-endian / 100 in degrees C. If `hi >= 0xF0` the value is negative: -(65535 - raw) / 100. The DLL document claims Fahrenheit, the two Java SDKs parse centigrade |
| 0x4E | empty | 0x4F, payload 2 bytes | Antenna connection state. Second byte is a bitmask, bit 0 = ANT1 through bit 7 = ANT8. First byte meaning **unverified** |
| 0xE4 sub 01 | `01` | 0xE5, payload `01 pct` | Battery charge percentage |

### RF power

Power values on the wire are centi-dBm, big-endian, so 30 dBm = 0x0BB8.

| Command | Request payload | Response | Meaning |
|---|---|---|---|
| 0x10 | `02` then per antenna: `ant readHi readLo writeHi writeLo` | 0x11, payload `01` | Set RF power per antenna. `ant` is 1-based, read power and write power in centi-dBm each. The single-antenna call sends `02 01 hi lo hi lo`. The leading `02` is constant, meaning **unverified** |
| 0x12 | empty | 0x13, payload `00` then per antenna: `ant readHi readLo writeHi writeLo` | Get RF power for every antenna. Both SDKs read the value from bytes 2 and 3, which is the read power of the first antenna |

### RF configuration

| Command | Request payload | Response | Meaning |
|---|---|---|---|
| 0x14 | `01 f2 f1 f0` | 0x15, payload `01` | Set fixed frequency, value in kHz, 3-byte big-endian, for example 920125 |
| 0x2C | `save region` | 0x2D, payload `01` | Set frequency region. `save` 0 or 1. Region: 0x01 China1, 0x02 China2, 0x04 Europe, 0x08 USA, 0x16 Korea, 0x32 Japan |
| 0x2E | empty | 0x2F, payload `01 region` | Get frequency region |
| 0x24 | `on` | 0x25, payload `01` | Set continuous carrier wave, 0 off, 1 on |
| 0x26 | empty | 0x27, payload `01 on` | Get continuous carrier wave state |
| 0x20 | 4 bytes, see below | 0x21, payload `01` | Set Gen2 parameters |
| 0x22 | empty | 0x23, payload 4 bytes | Get Gen2 parameters, same packing as the request |
| 0x52 | `00 save mode` | 0x53, payload `01` | Set recommended RF link combination. Mode: 0 DSB_ASK/FM0/40kHz, 1 PR_ASK/Miller4/250kHz, 2 PR_ASK/Miller4/300kHz, 3 DSB_ASK/FM0/400kHz. Leading `00` constant, meaning **unverified** |
| 0x54 | `00 00` | 0x55, payload `01 00 mode` | Get RF link combination |
| 0x5C | `enable 00` | 0x5D, payload `01` | Set FastID, 0 off, 1 on. Trailing `00` constant |
| 0x5E | `00 00` | 0x5F, payload `01 enable` | Get FastID state |
| 0x60 | `enable 00` | 0x61, payload `01` | Set TagFocus, 0 off, 1 on. Trailing `00` constant |
| 0x62 | `00 00` | 0x63, payload `status enable` | Get TagFocus state. The AAR parses byte 0 as `01`, the jar as `00`, both read byte 1 as the state |
| 0x06 | `00 type` | 0x07, payload `00 01` | Set protocol type. Type: 0 ISO18000-6C, 1 GB/T29768, 2 GJB7377.1 |
| 0x06 | `01 00` | 0x07, payload `01 type` | Get protocol type |
| 0x30 | `01 value` | 0x31 | Set power-on dynamic configuration, semantics **unverified**, the Android SDK ships no response parser |
| 0x64 | `01 enable 00` | 0x65, payload `01` | Set fast inventory mode, semantics **unverified** |
| 0x66 | `00 00` | 0x67, payload `01 enable` | Get fast inventory mode |
| 0x74 | empty | 0x75, payload `01` | Soft reset of the UHF module |

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
| 0x4A | `setHi ant hi lo` or `ant hi lo` | 0x4B, payload `01` | Set antenna work time. The AAR sends `0x10 | ant`, the jar sends `ant`, so the high nibble is read as the save flag. Unit **unverified** |
| 0x4C | `ant 00` | 0x4D, payload `01 ant hi lo` | Get antenna work time, 16-bit big-endian |

### Inventory control

| Command | Request payload | Response | Meaning |
|---|---|---|---|
| 0x70 | `save mode userAddr userLen` | 0x71, payload `01` | Select inventory mode. Mode 0 = EPC only, mode 1 = EPC and TID, mode 2 = EPC, TID and USER. `userAddr` is the USER start address in 16-bit words, `userLen` the USER read length in words. TID is a fixed 12 bytes when present. The parser source also knows mode 10 = EPC and RESERVED, 14 = LED tag and 15 = temperature tag, support on UR4 **unverified** |
| 0x70 | `00 00 00 00` | 0x71, payload `01` | Shorthand for mode 0 without saving |
| 0x72 | `00 00` | 0x73, payload `01 mode userAddr userLen` | Get inventory mode |
| 0x6E | `save bank ptrHi ptrLo cntHi cntLo data...` | 0x6F, payload `01` | Set tag filter. Bank 1 = EPC, 2 = TID, 3 = USER. `ptr` is the bit offset of the match, `cnt` the match length in bits, `data` the match bytes, ceil(cnt / 8) of them |
| 0x80 | `00 64` | 0x81, one tag record | Single inventory. Returns at most one tag record in the response. Payload bytes are parameters, semantics **unverified** |
| 0x82 | `00 00` | none, stream begins | Start continuous inventory. Tag sightings arrive as 0x83 frames |
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
| 0x8A | none | 0x8B, payload `01 00` | Kill tag, the password is the kill password |

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
| 0xE2 | `01 ...` | 0xE3, see batch format | Variant with full tag records, request tail and leading response byte **unverified** |
| 0xE9 | `FF` | 0xEA, payload `00 00` | Delete all collected tags from flash |
| 0xE9 | `00` | 0xEA, payload `cntHi cntLo` | Get count of all collected tags |
| 0xE9 | `01` | 0xEA, payload `cntHi cntLo` | Get count of new collected tags |
| 0xEB | `FF` | 0xEC, batch format | Pull collected tag data from flash |

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
| 11 | `11 volume` | `01` | Set buzzer volume |
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
| `02` | Scan a 1D or 2D barcode, if the reader variant has an imager. Response `02` followed by the barcode bytes, the 3-byte form `02 02 00` means no read. **Unverified** |
| `03 01 duration` | Buzzer duration |
| `03 01 01` | Beep once, the hardcoded frame `A5 5A 00 0A E4 03 01 EC 0D 0A` |
| `03 01 00` | Silence the buzzer |
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

### Firmware update

| Command | Request payload | Meaning |
|---|---|---|
| 0xC0 | `CC` | Jump to bootloader, the SDK passes 0xCC to reboot into the update mode |
| 0xC2 | empty | Start the update |
| 0xC4 | 64-byte block | Send one firmware block, padded with zeros past the end of the image |
| 0xC6 | empty | Stop the update |

All four answer payload `01`. Block order and image format **unverified**, the SDK sends raw 64-byte blocks.

## Tag record

The payload of a 0x83 frame, and the response of a single inventory (0x81), is one tag record:

```
PC(2) | EPC(...) | TID(12, optional) | USER(..., optional) | RSSI(2) | ANT(1)
```

- EPC length comes from the Gen2 PC word: bytes = (PC[0] >> 3) * 2, where PC[0] is the first byte of the record
- TID is present as a fixed 12-byte block when the inventory mode includes TID
- USER data follows TID when the mode includes it
- RSSI: 16-bit big-endian. dBm = (raw - 65535) / 10, so raw 0xFED6 = -29.7 dBm. The SDKs treat values where 65535 - raw >= 2000 as invalid
- ANT: 1-byte antenna index, 0-based

The parser infers which optional blocks are present from the total record length, since the inventory mode is known by context.

Collected tag batch format, used by the 0xE0 read-tag-data command for tags collected in auto and trigger work modes:

```
indexHi indexLo count | count times: [len][record bytes]
```

- 0xE0 records are raw EPC bytes with no PC word and no RSSI or antenna
- 0xE2 records are full tag records with the PC word and RSSI but no antenna byte
- A payload shorter than 5 bytes carries only the 16-bit index, the SDK reports it as an invalid tag marker
- The 0xE2 batch carries one extra byte before the index, meaning **unverified**

The Windows DLL exposes a different, length-prefixed layout to applications through `UHF_GetReceived_EX`: `uiiLen | PC+EPC | tidLen | TID | RSSI(2) | ANT(1)`. The two pure-Java SDKs parse the PC-based layout directly off the wire, so the PC-based layout is the wire format and the length-prefixed layout is a DLL-side representation. **Verify against live traffic when hardware is available.**

## UDP device discovery

The reader broadcasts a 12-byte UDP packet to port 1111:

```
MAC(6) | IPv4(4) | TCP port(2, big-endian)
```

The Java SDK listens on port 1111 and reports every reader that announces itself. The Windows DLL has matching BindUDP and UnbindUDP entry points.

## Work modes

Set with 0xA1 sub 05.

| Mode | Name | Behavior |
|---|---|---|
| 0 | Command mode | The host starts and stops inventory with 0x82 and 0x8C. Default mode |
| 1 | Auto mode | The reader inventories on its own, using the trigger parameters as timing. Tag output goes to the link or UDP depending on the output routing parameter |
| 2 | Trigger mode | A signal on GPI input 1 or 2 starts an inventory run for the configured work time. Output routing applies here too |

## Open items

- 0x80 single inventory payload bytes `00 64`: first byte is likely an antenna or mode selector, 100 is likely a duration. Untested on hardware
- Whether the reader enforces the heartbeat or keepalive intervals, or whether they are purely client-side library behavior
- Whether a 0x83 frame can carry more than one record. Both pure-Java SDKs parse exactly one record per frame, and the 0xE0 batch exists for the multi-record case
- First byte of the 0x4F antenna state response
- Error payload values beyond `01` and `01 00`, no SDK decodes them
- The meaning of the leading `02` in the 0x10 set power payload and the leading `00` in the 0x52 RF link payload
- The 0x4A work time save flag reading, inferred from the AAR and jar disagreement
- The 0xE2 request tail and the extra leading byte in its response
- The 0xF0 user settings semantics beyond the shapes listed above
- Antenna work time unit
- Whether the flash storage commands 0xE9 and 0xEB apply to the UR4
- RS-485 variants, if the specific unit has one: half-duplex direction control is outside the protocol

## Decompiled source locations

The extracted archives and decompiled trees live in a temporary workspace. Re-extract from the three RAR files at the repository root when needed:

- Android AAR: obfuscated class names, `Q.java` and `T.java` hold the command builders, `com/rscja/deviceapi/b.java` the tag record, batch and lock code logic
- Java jar: readable names, `i.java` and `j.java` hold the frame and command logic, `h.java` and `d.java` the record and hardcoded frames
- `api_doc.txt` inside the Windows demo: converted DLL reference with command semantics and units
- C# demo with the full P/Invoke surface in `UHFAPI.cs`
