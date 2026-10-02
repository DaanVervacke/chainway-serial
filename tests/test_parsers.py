"""Parser and builder tests pinned to the decoded SDK logic."""

from datetime import UTC, datetime

import pytest

from chainway_serial.exceptions import ChainwayResponseError
from chainway_serial.models import (
    CollectedTags,
    Gen2Parameters,
    InventoryMode,
    InventoryModeConfig,
    LockBank,
    LockMode,
    MemoryBank,
    ReaderAddress,
    TagFilter,
)
from chainway_serial.parsers import (
    build_filter_payload,
    build_lock_code,
    build_power_payload,
    build_reader_address_payload,
    build_tag_operation_payload,
    pack_gen2_parameters,
    parse_antenna_connection_state,
    parse_collected_tags,
    parse_power_records,
    parse_reader_address,
    parse_tag_record,
    parse_temperature,
    parse_version,
    unpack_gen2_parameters,
    validate_word_window,
)

RECEIVED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def test_parse_version() -> None:
    assert parse_version(b"\x01\x02\x03").__str__() == "V1.2.3"


def test_parse_temperature_positive() -> None:
    assert parse_temperature(b"\x01\x10\x0e") == 41.1


def test_parse_temperature_negative() -> None:
    assert parse_temperature(b"\x01\xff\x38") == -1.99


def test_parse_temperature_rejects_a_foreign_payload() -> None:
    with pytest.raises(ChainwayResponseError, match="temperature"):
        parse_temperature(b"\x00\x10\x0e")


def test_parse_antenna_connection_state() -> None:
    state = parse_antenna_connection_state(b"\x00\x05")
    assert state == (True, False, True, False, False, False, False, False)


def test_parse_power_records() -> None:
    records = parse_power_records(b"\x00\x01\x0b\xb8\x0b\xb8\x02\x07\xd0\x07\xd0")
    assert len(records) == 2
    assert records[0].antenna == 1
    assert records[0].read_power_dbm == 30.0
    assert records[1].antenna == 2
    assert records[1].write_power_dbm == 20.0


def test_parse_power_records_rejects_a_partial_record() -> None:
    with pytest.raises(ChainwayResponseError, match="power"):
        parse_power_records(b"\x00\x01\x0b\xb8")


def test_build_power_payload() -> None:
    assert build_power_payload(1, 30.0, 30.0) == b"\x02\x01\x0b\xb8\x0b\xb8"
    assert build_power_payload(2, 20.0, 25.5) == b"\x02\x02\x07\xd0\x09\xf6"


def test_build_power_payload_rejects_a_bad_antenna() -> None:
    with pytest.raises(ValueError, match="antenna"):
        build_power_payload(0, 30.0, 30.0)


def test_parse_tag_record_epc_only() -> None:
    record = b"\x30\x00" + bytes(range(1, 13)) + b"\xfe\xd6\x02"
    tag = parse_tag_record(record, with_antenna=True, received_at=RECEIVED_AT)
    assert tag.pc == b"\x30\x00"
    assert tag.epc == bytes(range(1, 13))
    assert tag.tid is None
    assert tag.user_data is None
    assert tag.rssi == -29.7
    assert tag.antenna == 2
    assert tag.received_at == RECEIVED_AT


def test_parse_tag_record_with_tid_and_user() -> None:
    record = (
        b"\x30\x00"
        + bytes(range(1, 13))
        + bytes(range(13, 25))
        + b"\xaa\xbb"
        + b"\xfe\xd6"
        + b"\x00"
    )
    tag = parse_tag_record(record, with_antenna=True, received_at=RECEIVED_AT)
    assert tag.tid == bytes(range(13, 25))
    assert tag.user_data == b"\xaa\xbb"
    assert tag.rssi == -29.7
    assert tag.antenna == 0


def test_parse_tag_record_without_antenna() -> None:
    record = b"\x30\x00" + bytes(range(1, 13)) + b"\xfe\xd6"
    tag = parse_tag_record(record, with_antenna=False, received_at=RECEIVED_AT)
    assert tag.antenna is None
    assert tag.rssi == -29.7


def test_parse_tag_record_short_tid_block() -> None:
    record = b"\x30\x00" + bytes(range(1, 13)) + b"\x01\x02\xfe\xd6\x00"
    tag = parse_tag_record(record, with_antenna=True, received_at=RECEIVED_AT)
    assert tag.tid == b"\x01\x02"
    assert tag.user_data is None


def test_parse_tag_record_tid_without_user_data() -> None:
    record = b"\x30\x00" + bytes(range(1, 13)) + bytes(range(13, 25)) + b"\xfe\xd6\x00"
    tag = parse_tag_record(record, with_antenna=True, received_at=RECEIVED_AT)
    assert tag.tid == bytes(range(13, 25))
    assert tag.user_data is None


def test_parse_tag_record_without_rssi_or_antenna() -> None:
    record = b"\x30\x00" + bytes(range(1, 13))
    tag = parse_tag_record(record, with_antenna=True, received_at=RECEIVED_AT)
    assert tag.tid is None
    assert tag.rssi is None
    assert tag.antenna is None


def test_parse_tag_record_invalid_rssi_is_none() -> None:
    record = b"\x30\x00" + bytes(range(1, 13)) + b"\x00\x05\x00"
    tag = parse_tag_record(record, with_antenna=True, received_at=RECEIVED_AT)
    assert tag.rssi is None


def test_parse_tag_record_rejects_a_short_record() -> None:
    with pytest.raises(ChainwayResponseError, match="at least 3 bytes"):
        parse_tag_record(b"\x30\x00", with_antenna=True, received_at=RECEIVED_AT)


def test_parse_tag_record_rejects_a_truncated_epc() -> None:
    record = b"\x30\x00" + b"\x01\x02"
    with pytest.raises(ChainwayResponseError, match="PC and EPC"):
        parse_tag_record(record, with_antenna=True, received_at=RECEIVED_AT)


def test_parse_collected_tags() -> None:
    payload = b"\x00\x05\x02\x06\x11\x22\x33\x44\x55\x66\x04\xaa\xbb\xcc\xdd"
    collected = parse_collected_tags(payload)
    assert collected == CollectedTags(
        index=5, tags=(b"\x11\x22\x33\x44\x55\x66", b"\xaa\xbb\xcc\xdd")
    )


def test_parse_collected_tags_invalid_marker() -> None:
    assert parse_collected_tags(b"\x00\x07") == CollectedTags(index=7, tags=())


def test_parse_collected_tags_stops_at_a_truncated_record() -> None:
    payload = b"\x00\x05\x02\x06\x11\x22\x33"
    collected = parse_collected_tags(payload)
    assert collected.tags == ()


def test_parse_collected_tags_stops_when_the_count_overruns() -> None:
    payload = b"\x00\x00\x02\x02\x11\x22"
    collected = parse_collected_tags(payload)
    assert collected.tags == (b"\x11\x22",)


def test_parse_collected_tags_rejects_a_short_payload() -> None:
    with pytest.raises(ChainwayResponseError, match="at least 2 bytes"):
        parse_collected_tags(b"\x00")


def test_lock_code_kill_bank_lock() -> None:
    assert build_lock_code([LockBank.KILL_PASSWORD], LockMode.LOCK) == b"\x08\x02\x00"


def test_lock_code_access_bank_lock() -> None:
    assert build_lock_code([LockBank.ACCESS_PASSWORD], LockMode.LOCK) == b"\x02\x00\x80"


def test_lock_code_epc_bank_permanently_lock() -> None:
    assert build_lock_code([LockBank.EPC], LockMode.PERMANENTLY_LOCK) == b"\x00\xc0\x30"


def test_lock_code_tid_bank_permanently_open() -> None:
    assert build_lock_code([LockBank.TID], LockMode.PERMANENTLY_OPEN) == b"\x00\x30\x04"


def test_lock_code_user_bank_open() -> None:
    assert build_lock_code([LockBank.USER], LockMode.OPEN) == b"\x00\x08\x00"


def test_lock_code_combines_banks() -> None:
    code = build_lock_code(
        [LockBank.KILL_PASSWORD, LockBank.ACCESS_PASSWORD], LockMode.PERMANENTLY_LOCK
    )
    assert code == b"\x0f\x03\xc0"


def test_gen2_roundtrip() -> None:
    parameters = Gen2Parameters(
        target=0x03,
        action=0x05,
        truncate=True,
        dynamic_q=False,
        start_q=0x09,
        min_q=0x02,
        max_q=0x0E,
        divider_ratio=0x01,
        coding=0x03,
        tr_ext=False,
        sel=0x02,
        session=0x03,
        gen2_target=True,
        link_frequency=0x07,
    )
    assert unpack_gen2_parameters(pack_gen2_parameters(parameters)) == parameters


def test_unpack_gen2_rejects_a_short_payload() -> None:
    with pytest.raises(ChainwayResponseError, match="Gen2"):
        unpack_gen2_parameters(b"\x00\x00\x00")


def test_parse_reader_address_short_form() -> None:
    address = parse_reader_address(b"\x02\xc0\xa8\x63\xc8\x22\xb8", 0x02)
    assert address == ReaderAddress(ip="192.168.99.200", port=8888)


def test_parse_reader_address_with_mask_and_gateway() -> None:
    payload = b"\x02\xc0\xa8\x63\xc8\x22\xb8\xff\xff\xff\x00\xc0\xa8\x63\x01"
    address = parse_reader_address(payload, 0x02)
    assert address.ip == "192.168.99.200"
    assert address.port == 8888
    assert address.subnet_mask == "255.255.255.0"
    assert address.gateway == "192.168.99.1"


def test_build_reader_address_payload_roundtrip() -> None:
    address = ReaderAddress(ip="10.0.0.7", port=5010)
    payload = build_reader_address_payload(0x01, address)
    assert payload == b"\x01\x0a\x00\x00\x07\x13\x92"
    assert parse_reader_address(b"\x02" + payload[1:], 0x02) == address


def test_build_reader_address_payload_with_mask_and_gateway() -> None:
    address = ReaderAddress(ip="10.0.0.7", port=5010, subnet_mask="255.255.0.0", gateway="10.0.0.1")
    payload = build_reader_address_payload(0x01, address)
    assert len(payload) == 15


def test_build_tag_operation_payload_without_filter() -> None:
    payload = build_tag_operation_payload(b"\x00\x00\x00\x00", None, b"\x03\x00\x02\x00\x02")
    assert payload == b"\x00\x00\x00\x00\x01\x00\x00\x00\x00\x03\x00\x02\x00\x02"


def test_build_tag_operation_payload_with_filter() -> None:
    tag_filter = TagFilter(bank=MemoryBank.EPC, bit_address=0x20, bit_length=16, data=b"\x12\x34")
    payload = build_tag_operation_payload(b"\x12\x34\x56\x78", tag_filter, b"\x03\x00\x02\x00\x02")
    assert payload == (b"\x12\x34\x56\x78\x01\x00\x20\x00\x10\x12\x34\x03\x00\x02\x00\x02")


def test_build_tag_operation_payload_rejects_a_bad_password() -> None:
    with pytest.raises(ValueError, match="password"):
        build_tag_operation_payload(b"\x00", None, b"")


def test_build_filter_payload() -> None:
    tag_filter = TagFilter(bank=MemoryBank.TID, bit_address=0x20, bit_length=16, data=b"\xab\xcd")
    payload = build_filter_payload(tag_filter, save=True)
    assert payload == b"\x01\x02\x00\x20\x00\x10\xab\xcd"


def test_build_filter_payload_clear_form() -> None:
    assert build_filter_payload(None, save=False) == b"\x00\x01\x00\x00\x00\x00\x00"


def test_validate_word_window() -> None:
    validate_word_window(0, 1)
    validate_word_window(0xFFFF, 0xFFFF)
    with pytest.raises(ValueError, match="word address"):
        validate_word_window(-1, 1)
    with pytest.raises(ValueError, match="word count"):
        validate_word_window(0, 0)


def test_inventory_mode_config_validation() -> None:
    config = InventoryModeConfig(
        mode=InventoryMode.EPC_TID_USER,
        user_address=2,
        user_length=4,
    )
    assert config.mode is InventoryMode.EPC_TID_USER
    with pytest.raises(ValueError, match="user_address"):
        InventoryModeConfig(mode=InventoryMode.EPC, user_address=256, user_length=0)
