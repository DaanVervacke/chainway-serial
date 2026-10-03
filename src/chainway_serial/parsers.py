"""Payload parsers and builders shared by the client and the fake reader."""

from __future__ import annotations

import math
from collections.abc import Collection, Iterable
from datetime import UTC, datetime

from .const import (
    ACCESS_PASSWORD_SIZE,
    ANTENNA_COUNT,
    BATCH_MIN_PAYLOAD,
    DEVICE_ID_SIZE,
    FREQUENCY_BYTES,
    INVALID_RSSI_SPAN,
    MAX_ANTENNA,
    MAX_WORD_ADDRESS,
    MAX_WORD_COUNT,
    MIN_ANTENNA,
    MIN_TAG_RECORD_SIZE,
    MIN_WORD_ADDRESS,
    PHASE_SIZE,
    POWER_RECORD_SIZE,
    READER_ADDRESS_LONG_SIZE,
    READER_ADDRESS_SIZE,
    RETURN_LOSS_RECORD_SIZE,
    STATUS_OK,
    TID_SIZE,
    USER_BLOCK_MARGIN,
    WORD_MODULUS,
    WORD_SIGN_BIT,
)
from .exceptions import ChainwayResponseError
from .models import (
    AntennaPower,
    CollectedTags,
    FirmwareVersion,
    Gen2Parameters,
    LockBank,
    LockMode,
    MemoryBank,
    ReaderAddress,
    ReturnLoss,
    Tag,
    TagFilter,
)

_LOCK_BANK_BITS: dict[LockBank, tuple[int, int, int, int]] = {
    LockBank.KILL_PASSWORD: (0x80000, 0x40000, 0x200, 0x100),
    LockBank.ACCESS_PASSWORD: (0x20000, 0x10000, 0x80, 0x40),
    LockBank.EPC: (0x8000, 0x4000, 0x20, 0x10),
    LockBank.TID: (0x2000, 0x1000, 0x08, 0x04),
    LockBank.USER: (0x800, 0x400, 0x02, 0x01),
}


def _require(condition: bool, message: str) -> None:  # noqa: FBT001
    if not condition:
        raise ChainwayResponseError(message)


def require_exact_length(payload: bytes, size: int, name: str) -> None:
    """Require a payload of exactly ``size`` bytes.

    Raises:
        ChainwayResponseError: The payload length differs.
    """
    _require(len(payload) == size, f"{name} payload must carry {size} bytes, got {len(payload)}")


def require_minimum_length(payload: bytes, size: int, name: str) -> None:
    """Require a payload of at least ``size`` bytes.

    Raises:
        ChainwayResponseError: The payload is too short.
    """
    _require(
        len(payload) >= size, f"{name} payload must carry at least {size} bytes, got {len(payload)}"
    )


def require_status_header(payload: bytes, size: int, status: int, name: str) -> None:
    """Require a minimum payload length and a status byte in front.

    Raises:
        ChainwayResponseError: The payload is too short or starts with
            a different byte.
    """
    _require(
        len(payload) >= size and payload[0] == status,
        f"{name} payload must start with {status:#04x} and carry at least {size} bytes,"
        f" got {payload!r}",
    )


def parse_version(payload: bytes) -> FirmwareVersion:
    """Parse the three version bytes of a 0x03, 0x01 or 0xC9 response."""
    require_exact_length(payload, 3, "version")
    return FirmwareVersion(payload[0], payload[1], payload[2])


def parse_device_id(payload: bytes) -> bytes:
    """Return the four module ID bytes of a 0x05 response.

    Raises:
        ChainwayResponseError: The payload is not four bytes.
    """
    require_exact_length(payload, DEVICE_ID_SIZE, "device ID")
    return bytes(payload)


def parse_temperature(payload: bytes) -> float:
    """Parse the temperature payload of a 0x35 response in degrees C.

    The value is hundredths of a degree, negative numbers are two's
    complement, as the official protocol document defines them.

    Raises:
        ChainwayResponseError: The payload does not start with the
            status byte.
    """
    require_status_header(payload, 3, STATUS_OK, "temperature")
    raw = payload[1] << 8 | payload[2]
    if raw >= WORD_SIGN_BIT:
        return (raw - WORD_MODULUS) / 100
    return raw / 100


def parse_antenna_connection_state(payload: bytes) -> tuple[bool, ...]:
    """Parse the 16-bit mask of a 0x4F response into per-antenna flags.

    Bit 0 of the low byte is antenna 1, bit 15 of the high byte is
    antenna 16.

    Raises:
        ChainwayResponseError: The payload is not two bytes.
    """
    require_exact_length(payload, 2, "antenna state")
    mask = payload[0] << 8 | payload[1]
    return tuple(mask & 1 << index != 0 for index in range(ANTENNA_COUNT))


def parse_power_records(payload: bytes) -> tuple[AntennaPower, ...]:
    """Parse the per-antenna records of a 0x13 response."""
    require_minimum_length(payload, 1, "power")
    _require(
        payload[0] == 0x00 and (len(payload) - 1) % POWER_RECORD_SIZE == 0,
        f"power payload must start with 00 and carry {POWER_RECORD_SIZE} bytes per antenna,"
        f" got {payload!r}",
    )
    records = []
    for offset in range(1, len(payload), POWER_RECORD_SIZE):
        read_power = payload[offset + 1] << 8 | payload[offset + 2]
        write_power = payload[offset + 3] << 8 | payload[offset + 4]
        records.append(
            AntennaPower(
                antenna=payload[offset],
                read_power_dbm=read_power / 100,
                write_power_dbm=write_power / 100,
            )
        )
    return tuple(records)


def build_power_payload(
    antenna: int,
    read_power_dbm: float,
    write_power_dbm: float,
    *,
    save: bool = True,
) -> bytes:
    """Build the 0x10 payload: status byte, then one antenna record.

    The status byte carries the save flag in bit 1, per the official
    protocol document. Bit 1 set stores the power across a power
    cycle, clear keeps it until power off.

    Raises:
        ValueError: The antenna number or a power value is out of range.
    """
    if not MIN_ANTENNA <= antenna <= MAX_ANTENNA:
        msg = f"antenna must be between 1 and 16, got {antenna}"
        raise ValueError(msg)
    read_centi = round(read_power_dbm * 100)
    write_centi = round(write_power_dbm * 100)
    status = 0x02 if save else 0x00
    return bytes(
        (
            status,
            antenna,
            read_centi >> 8 & 0xFF,
            read_centi & 0xFF,
            write_centi >> 8 & 0xFF,
            write_centi & 0xFF,
        )
    )


def _decode_rssi(rssi_bytes: bytes) -> float | None:
    raw = rssi_bytes[0] << 8 | rssi_bytes[1]
    if raw < WORD_SIGN_BIT:
        return None
    span = WORD_MODULUS - raw
    if span >= INVALID_RSSI_SPAN:
        return None
    return -span / 10


def parse_fixed_frequency(payload: bytes) -> tuple[int, ...]:
    """Parse the frequency table of a 0x17 response in kHz.

    The payload carries one count byte, then three big-endian bytes
    per frequency point.

    Raises:
        ChainwayResponseError: The payload is empty or does not
            match the count byte.
    """
    require_minimum_length(payload, 1, "fixed frequency")
    count = payload[0]
    _require(
        len(payload) == 1 + count * FREQUENCY_BYTES,
        f"fixed frequency payload must carry {count} three byte values,"
        f" got {len(payload) - 1} bytes",
    )
    return tuple(
        int.from_bytes(payload[1 + index * FREQUENCY_BYTES : (index + 1) * FREQUENCY_BYTES + 1])
        for index in range(count)
    )


def parse_return_loss(payload: bytes) -> tuple[ReturnLoss, ...]:
    """Parse the port and loss pairs of a 0x27 response in dB.

    Raises:
        ChainwayResponseError: The payload does not carry two bytes
            per port.
    """
    _require(
        len(payload) % RETURN_LOSS_RECORD_SIZE == 0,
        f"return loss payload must carry {RETURN_LOSS_RECORD_SIZE} bytes per port,"
        f" got {len(payload)}",
    )
    return tuple(
        ReturnLoss(port=payload[offset], loss_db=payload[offset + 1])
        for offset in range(0, len(payload), RETURN_LOSS_RECORD_SIZE)
    )


def parse_word_data(payload: bytes, name: str) -> bytes:
    """Parse the data tail shared by the 0x85 and 0x8F responses.

    The tail carries a success flag, an error flag, a word count
    and the data.

    Raises:
        ChainwayResponseError: The payload is truncated.
    """
    require_minimum_length(payload, 4, name)
    words = payload[2] << 8 | payload[3]
    data = payload[4:]
    if len(data) < words * 2:
        msg = f"{name} response promised {words * 2} data bytes, got {len(data)}"
        raise ChainwayResponseError(msg)
    return data[: words * 2]


def parse_tag_record(
    record: bytes,
    *,
    with_antenna: bool,
    received_at: datetime,
    with_phase: bool = False,
) -> Tag:
    """Parse one tag record of a 0x83, 0x81 or batch response.

    The blocks follow the SDK parsers exactly. With a TID block
    present, USER data fills the space between the TID and the
    trailing block, and more than three bytes after the TID mark
    the USER block as present, a margin the SDKs hardcode. Without a
    TID block the trailing block sits directly after the EPC. With
    ``with_phase`` the trailing block starts with a 2-byte phase in
    degrees, a layout the official protocol document defines for the
    phase reporting inventory mode. The RSSI pair is a 16-bit
    two's complement of dBm times ten, as the official protocol
    document defines it, and values outside the SDK validity window
    of 20 dBm span parse as None.

    Args:
        record: The raw record bytes: PC, then EPC, then the optional
            TID and USER blocks, then the optional phase, the RSSI
            pair and the optional antenna byte.
        with_antenna: Whether the record ends with one antenna byte
            after the RSSI pair. Inventory records carry it, collected
            tag records do not.
        received_at: Reception timestamp stored on the tag.
        with_phase: Whether the record carries a 2-byte phase in
            degrees between the body and the RSSI pair.

    Raises:
        ChainwayResponseError: The record is too short or carries no
            EPC.
    """
    require_minimum_length(record, MIN_TAG_RECORD_SIZE, "tag record")
    epc_length = (record[0] >> 3) * 2 + 2
    _require(
        len(record) >= epc_length,
        f"tag record needs {epc_length} bytes of PC and EPC, got {len(record)}",
    )
    phase_offset = PHASE_SIZE if with_phase else 0
    trailing = 3 if with_antenna else 2
    phase: int | None = None
    rssi_bytes: bytes | None = None
    antenna: int | None = None
    tid: bytes | None = None
    user_data: bytes | None = None
    if len(record) >= epc_length + TID_SIZE:
        tid = record[epc_length : epc_length + TID_SIZE]
        tail_start = epc_length + TID_SIZE
        if len(record) - USER_BLOCK_MARGIN > epc_length + TID_SIZE:
            tail_start = len(record) - trailing - phase_offset
            user_data = record[epc_length + TID_SIZE : tail_start]
    else:
        tail_start = epc_length
    rssi_start = tail_start + phase_offset
    if len(record) >= tail_start + PHASE_SIZE + 2:
        if with_phase:
            phase = record[tail_start] << 8 | record[tail_start + 1]
        rssi_bytes = record[rssi_start : rssi_start + 2]
        if len(record) >= rssi_start + 3:
            antenna = record[rssi_start + 2]
    elif len(record) >= tail_start + phase_offset + 2:
        rssi_bytes = record[rssi_start : rssi_start + 2]
        if len(record) >= rssi_start + 3:
            antenna = record[rssi_start + 2]
    rssi: float | None = None
    if rssi_bytes is not None:
        rssi = _decode_rssi(rssi_bytes)
    return Tag(
        pc=record[:2],
        epc=record[2:epc_length],
        tid=tid,
        user_data=user_data,
        rssi=rssi,
        antenna=antenna,
        received_at=received_at,
        phase=phase,
    )


def parse_collected_tags(payload: bytes) -> CollectedTags:
    """Parse the collected tag batch of a 0xE1 or 0xEC response.

    A payload shorter than five bytes carries only the 16-bit storage
    index and marks the read as invalid, so the tags tuple comes back
    empty.
    """
    require_minimum_length(payload, 2, "collected")
    if len(payload) < BATCH_MIN_PAYLOAD:
        return CollectedTags(index=payload[0] << 8 | payload[1], tags=())
    index = payload[0] << 8 | payload[1]
    count = payload[2]
    tags: list[bytes] = []
    offset = 3
    for _ in range(count):
        if offset >= len(payload):
            break
        length = payload[offset]
        end = offset + 1 + length
        if end > len(payload):
            break
        tags.append(payload[offset + 1 : end])
        offset = end
    return CollectedTags(index=index, tags=tuple(tags))


def parse_flash_tags(payload: bytes) -> tuple[bytes, ...]:
    """Parse the flash storage payload of a 0xEC response.

    The payload carries a one byte record count, then per record one
    length byte and the record bytes, which are raw EPC data. This
    layout comes from the Android demo decode, the Java jar passes
    the payload through raw, so the shape is unverified on the UR4.
    """
    require_minimum_length(payload, 1, "flash")
    count = payload[0]
    tags: list[bytes] = []
    offset = 1
    for _ in range(count):
        if offset >= len(payload):
            break
        length = payload[offset]
        end = offset + 1 + length
        if end > len(payload):
            break
        tags.append(payload[offset + 1 : end])
        offset = end
    return tuple(tags)


def build_lock_code(banks: Iterable[LockBank], mode: LockMode) -> bytes:
    """Build the 3-byte lock code from the selected banks and one mode.

    The code packs the Gen2 lock mask into bits 19 down to 10 and the
    action into bits 9 down to 0, two bits per memory bank.

    Raises:
        ValueError: No bank was selected.
    """
    selected = tuple(banks)
    if not selected:
        msg = "banks must select at least one memory"
        raise ValueError(msg)
    code = 0
    for bank in selected:
        mask_bit, mask_flag, action_high, action_low = _LOCK_BANK_BITS[bank]
        code |= mask_bit
        if mode in (LockMode.LOCK, LockMode.PERMANENTLY_LOCK):
            code |= action_high
        if mode in (LockMode.PERMANENTLY_OPEN, LockMode.PERMANENTLY_LOCK):
            code |= mask_flag
        if mode in (LockMode.PERMANENTLY_OPEN, LockMode.PERMANENTLY_LOCK):
            code |= action_low
    return code.to_bytes(3)


def pack_gen2_parameters(parameters: Gen2Parameters) -> bytes:
    """Pack the Gen2 parameters into the four payload bytes of command 0x20."""
    return bytes(
        (
            (parameters.target & 7) << 5
            | (parameters.action & 7) << 2
            | int(parameters.truncate) << 1
            | int(parameters.dynamic_q),
            (parameters.start_q & 15) << 4 | parameters.min_q & 15,
            (parameters.max_q & 15) << 4
            | (parameters.divider_ratio & 1) << 3
            | (parameters.coding & 3) << 1
            | int(parameters.tr_ext),
            (parameters.sel & 3) << 6
            | (parameters.session & 3) << 4
            | int(parameters.gen2_target) << 3
            | parameters.link_frequency & 7,
        )
    )


def unpack_gen2_parameters(payload: bytes) -> Gen2Parameters:
    """Unpack the four bytes of a 0x23 response into Gen2 parameters.

    Raises:
        ChainwayResponseError: The payload is not four bytes.
    """
    require_exact_length(payload, 4, "Gen2")
    return Gen2Parameters(
        target=payload[0] >> 5 & 7,
        action=payload[0] >> 2 & 7,
        truncate=bool(payload[0] >> 1 & 1),
        dynamic_q=bool(payload[0] & 1),
        start_q=payload[1] >> 4 & 15,
        min_q=payload[1] & 15,
        max_q=payload[2] >> 4 & 15,
        divider_ratio=payload[2] >> 3 & 1,
        coding=payload[2] >> 1 & 3,
        tr_ext=bool(payload[2] & 1),
        sel=payload[3] >> 6 & 3,
        session=payload[3] >> 4 & 3,
        gen2_target=bool(payload[3] >> 3 & 1),
        link_frequency=payload[3] & 7,
    )


def parse_reader_address(payload: bytes, subcommand: int) -> ReaderAddress:
    """Parse the address payload of a 0xA2 response."""
    require_status_header(payload, READER_ADDRESS_SIZE, subcommand, "address")
    long_form = len(payload) >= READER_ADDRESS_LONG_SIZE
    return ReaderAddress(
        ip=".".join(str(byte) for byte in payload[1:5]),
        port=payload[5] << 8 | payload[6],
        subnet_mask=".".join(str(byte) for byte in payload[7:11]) if long_form else None,
        gateway=".".join(str(byte) for byte in payload[11:15]) if long_form else None,
    )


def build_reader_address_payload(subcommand: int, address: ReaderAddress) -> bytes:
    """Build the payload for the 0xA1 address subcommands.

    A payload with a subnet mask and gateway carries 15 bytes, one
    without carries 7.
    """
    octets = bytes(int(part) for part in address.ip.split("."))
    if address.subnet_mask is None or address.gateway is None:
        return (
            bytes((subcommand,)) + octets + bytes((address.port >> 8 & 0xFF, address.port & 0xFF))
        )
    mask = bytes(int(part) for part in address.subnet_mask.split("."))
    gateway = bytes(int(part) for part in address.gateway.split("."))
    return (
        bytes((subcommand,))
        + octets
        + bytes((address.port >> 8 & 0xFF, address.port & 0xFF))
        + mask
        + gateway
    )


def build_tag_operation_payload(
    password: bytes,
    tag_filter: TagFilter | None,
    tail: bytes,
) -> bytes:
    """Build the shared prefix of every tag operation request.

    The prefix carries the password, the optional filter, and the
    operation specific tail. Without a filter the request carries
    bank 1, address 0, length 0 and no data bytes, so the reader picks
    the tag on its own.

    Raises:
        ValueError: The password is not four bytes.
    """
    if len(password) != ACCESS_PASSWORD_SIZE:
        msg = f"password must be {ACCESS_PASSWORD_SIZE} bytes, got {len(password)}"
        raise ValueError(msg)
    if tag_filter is None:
        return password + b"\x01\x00\x00\x00\x00" + tail
    data_length = math.ceil(tag_filter.bit_length / 8)
    return (
        password
        + bytes(
            (
                tag_filter.bank,
                tag_filter.bit_address >> 8 & 0xFF,
                tag_filter.bit_address & 0xFF,
                tag_filter.bit_length >> 8 & 0xFF,
                tag_filter.bit_length & 0xFF,
            )
        )
        + tag_filter.data[:data_length]
        + tail
    )


def build_filter_payload(tag_filter: TagFilter | None, *, save: bool) -> bytes:
    """Build the 0x6E payload, or the clear-filter form without a filter.

    A filter with a zero bit length clears the active filter and
    carries no data bytes, matching both SDKs.
    """
    if tag_filter is None or tag_filter.bit_length == 0:
        return bytes((int(save), MemoryBank.EPC, 0, 0, 0, 0))
    data_length = math.ceil(tag_filter.bit_length / 8)
    return (
        bytes((int(save),))
        + bytes(
            (
                tag_filter.bank,
                tag_filter.bit_address >> 8 & 0xFF,
                tag_filter.bit_address & 0xFF,
                tag_filter.bit_length >> 8 & 0xFF,
                tag_filter.bit_length & 0xFF,
            )
        )
        + tag_filter.data[:data_length]
    )


def validate_word_window(word_address: int, word_count: int) -> None:
    """Validate a tag memory window in 16-bit words.

    Raises:
        ValueError: The address or count is out of range.
    """
    if not MIN_WORD_ADDRESS <= word_address <= MAX_WORD_ADDRESS:
        msg = f"word address must be within 0 to {MAX_WORD_ADDRESS}, got {word_address}"
        raise ValueError(msg)
    if not 1 <= word_count <= MAX_WORD_COUNT:
        msg = f"word count must be between 1 and {MAX_WORD_COUNT}, got {word_count}"
        raise ValueError(msg)


def validate_block_window(block_ptr: int, block_range: int) -> None:
    """Validate a block permalock window in 16-block windows.

    Raises:
        ValueError: The pointer or range is out of range.
    """
    if not MIN_WORD_ADDRESS <= block_ptr <= MAX_WORD_ADDRESS:
        msg = f"block pointer must be within 0 to {MAX_WORD_ADDRESS}, got {block_ptr}"
        raise ValueError(msg)
    if not 1 <= block_range <= MAX_WORD_COUNT:
        msg = f"block range must be between 1 and {MAX_WORD_COUNT}, got {block_range}"
        raise ValueError(msg)


def banks_tuple(banks: Collection[LockBank]) -> tuple[LockBank, ...]:
    """Return the unique banks of a lock selection in wire order."""
    return tuple(sorted(set(banks), key=lambda bank: bank.value))


def now_utc() -> datetime:
    """Return the current UTC timestamp used for tag sightings."""
    return datetime.now(UTC)
