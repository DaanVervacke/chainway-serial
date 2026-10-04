"""Parser and builder tests pinned to the decoded SDK logic."""

from datetime import UTC, datetime

import pytest

from chainway_serial.const import SensorSubcommand, TagSensorSubcommand
from chainway_serial.exceptions import ChainwayResponseError
from chainway_serial.models import (
    CollectedTags,
    CollectedTagsFull,
    Gen2Parameters,
    InventoryMode,
    InventoryModeConfig,
    LockBank,
    LockMode,
    MemoryBank,
    ReaderAddress,
    ReturnLoss,
    TagFilter,
)
from chainway_serial.parsers import (
    build_deactivate_payload,
    build_filter_payload,
    build_lock_code,
    build_module_parameter_payload,
    build_power_payload,
    build_reader_address_payload,
    build_sensor_payload,
    build_tag_operation_payload,
    build_tag_sensor_payload,
    pack_gen2_parameters,
    parse_antenna_connection_state,
    parse_collected_tags,
    parse_collected_tags_full,
    parse_device_id,
    parse_fixed_frequency,
    parse_flash_tags,
    parse_module_parameter,
    parse_power_records,
    parse_reader_address,
    parse_return_loss,
    parse_tag_record,
    parse_tag_sensor_value,
    parse_tag_temperatures,
    parse_temperature,
    parse_version,
    parse_voltage,
    parse_word_data,
    unpack_gen2_parameters,
    validate_block_window,
    validate_word_window,
)

RECEIVED_AT = datetime(2026, 1, 1, tzinfo=UTC)


def test_parse_version() -> None:
    assert parse_version(b"\x01\x02\x03").__str__() == "V1.2.3"


def test_parse_temperature_positive() -> None:
    assert parse_temperature(b"\x01\x10\x0e") == 41.1


def test_parse_temperature_negative() -> None:
    assert parse_temperature(b"\x01\xff\x38") == -2.0


def test_parse_temperature_rejects_a_foreign_payload() -> None:
    with pytest.raises(ChainwayResponseError, match="temperature"):
        parse_temperature(b"\x00\x10\x0e")


def test_parse_antenna_connection_state() -> None:
    state = parse_antenna_connection_state(b"\x00\x05")
    assert state == (True, False, True, False, False, False, False, False) + (False,) * 8


def test_parse_antenna_connection_state_high_byte() -> None:
    state = parse_antenna_connection_state(b"\x20\x00")
    assert state == (False,) * 13 + (True,) + (False,) * 2


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
    assert build_power_payload(1, 30.0, 30.0, save=False) == b"\x00\x01\x0b\xb8\x0b\xb8"


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
    assert tag.rssi == -29.8
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
    assert tag.rssi == -29.8
    assert tag.antenna == 0


def test_parse_tag_record_without_antenna() -> None:
    record = b"\x30\x00" + bytes(range(1, 13)) + b"\xfe\xd6"
    tag = parse_tag_record(record, with_antenna=False, received_at=RECEIVED_AT)
    assert tag.antenna is None
    assert tag.rssi == -29.8


def test_parse_tag_record_without_tid_reads_rssi_after_the_epc() -> None:
    record = b"\x30\x00" + bytes(range(1, 13)) + b"\x01\x02\xfe\xd6\x00"
    tag = parse_tag_record(record, with_antenna=True, received_at=RECEIVED_AT)
    assert tag.tid is None
    assert tag.user_data is None
    assert tag.rssi is None
    assert tag.antenna == 0xFE


def test_parse_tag_record_tid_without_user_data() -> None:
    record = b"\x30\x00" + bytes(range(1, 13)) + bytes(range(13, 25)) + b"\xfe\xd6\x00"
    tag = parse_tag_record(record, with_antenna=True, received_at=RECEIVED_AT)
    assert tag.tid == bytes(range(13, 25))
    assert tag.user_data is None


def test_parse_tag_record_tid_only_without_rssi() -> None:
    record = b"\x30\x00" + bytes(range(1, 13)) + bytes(range(13, 25))
    tag = parse_tag_record(record, with_antenna=True, received_at=RECEIVED_AT)
    assert tag.tid == bytes(range(13, 25))
    assert tag.rssi is None
    assert tag.antenna is None


def test_parse_tag_record_tid_and_rssi_without_antenna() -> None:
    record = b"\x30\x00" + bytes(range(1, 13)) + bytes(range(13, 25)) + b"\xfe\xd6"
    tag = parse_tag_record(record, with_antenna=True, received_at=RECEIVED_AT)
    assert tag.tid == bytes(range(13, 25))
    assert tag.user_data is None
    assert tag.rssi == -29.8
    assert tag.antenna is None


def test_parse_tag_record_batch_user_without_antenna() -> None:
    record = b"\x30\x00" + bytes(range(1, 13)) + bytes(range(13, 25)) + b"\xaa\xbb" + b"\xfe\xd6"
    tag = parse_tag_record(record, with_antenna=False, received_at=RECEIVED_AT)
    assert tag.tid == bytes(range(13, 25))
    assert tag.user_data == b"\xaa\xbb"
    assert tag.rssi == -29.8
    assert tag.antenna is None


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


def test_parse_tag_record_rssi_outside_the_validity_window_is_none() -> None:
    record = b"\x30\x00" + bytes(range(1, 13)) + b"\x90\x00\x02"
    tag = parse_tag_record(record, with_antenna=True, received_at=RECEIVED_AT)
    assert tag.rssi is None


def test_parse_tag_record_rssi_matches_the_documented_example() -> None:
    record = b"\x30\x00" + bytes(range(1, 13)) + b"\xfd\x6f\x02"
    tag = parse_tag_record(record, with_antenna=True, received_at=RECEIVED_AT)
    assert tag.rssi == -65.7


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


def test_lock_code_rejects_an_empty_bank_selection() -> None:
    with pytest.raises(ValueError, match="at least one memory"):
        build_lock_code([], LockMode.LOCK)


def test_parse_tag_record_phase_mode_epc_only() -> None:
    record = b"\x34\x00" + bytes.fromhex("e2c45566a5030060705db2c7") + b"\x00\x3b\xfe\xc8\x01"
    tag = parse_tag_record(record, with_antenna=True, received_at=RECEIVED_AT, with_phase=True)
    assert tag.epc == bytes.fromhex("e2c45566a5030060705db2c7")
    assert tag.phase == 59
    assert tag.rssi == -31.2
    assert tag.antenna == 1


def test_parse_tag_record_phase_mode_without_antenna() -> None:
    record = b"\x34\x00" + bytes.fromhex("e2c45566a5030060705db2c7") + b"\x00\x3b\xfe\xc8"
    tag = parse_tag_record(record, with_antenna=False, received_at=RECEIVED_AT, with_phase=True)
    assert tag.phase == 59
    assert tag.rssi == -31.2
    assert tag.antenna is None


def test_parse_tag_record_phase_mode_with_tid_and_user() -> None:
    record = (
        b"\x30\x00"
        + bytes(range(1, 13))
        + bytes(range(13, 25))
        + b"\xaa\xbb"
        + b"\x00\x3b"
        + b"\xfe\xd6"
        + b"\x00"
    )
    tag = parse_tag_record(record, with_antenna=True, received_at=RECEIVED_AT, with_phase=True)
    assert tag.tid == bytes(range(13, 25))
    assert tag.user_data == b"\xaa\xbb"
    assert tag.phase == 59
    assert tag.rssi == -29.8
    assert tag.antenna == 0


def test_parse_tag_record_phase_absent_without_the_mode() -> None:
    record = b"\x34\x00" + bytes.fromhex("e2c45566a5030060705db2c7") + b"\x00\x3b\xfe\xc8\x01"
    tag = parse_tag_record(record, with_antenna=True, received_at=RECEIVED_AT)
    assert tag.phase is None
    assert tag.rssi is None
    assert tag.antenna == 0xFE


def test_parse_tag_record_frequency_mode_epc_only() -> None:
    record = b"\x30\x00" + bytes(range(1, 13)) + bytes.fromhex("0DF4C8") + b"\xfd\x6f\x01"
    tag = parse_tag_record(record, with_antenna=True, received_at=RECEIVED_AT, with_frequency=True)
    assert tag.phase is None
    assert tag.frequency_khz == 914632
    assert tag.rssi == -65.7
    assert tag.antenna == 1


def test_parse_tag_record_phase_and_frequency_mode_epc_only() -> None:
    record = b"\x30\x00" + bytes(range(1, 13)) + bytes.fromhex("2A8C0DF4C8") + b"\xfd\x6f\x01"
    tag = parse_tag_record(
        record,
        with_antenna=True,
        received_at=RECEIVED_AT,
        with_phase=True,
        with_frequency=True,
    )
    assert tag.phase == 0x2A8C
    assert tag.frequency_khz == 914632
    assert tag.rssi == -65.7
    assert tag.antenna == 1


def test_parse_tag_record_phase_and_frequency_without_antenna() -> None:
    record = b"\x30\x00" + bytes(range(1, 13)) + bytes.fromhex("2A8C0DF4C8") + b"\xfd\x6f"
    tag = parse_tag_record(
        record,
        with_antenna=False,
        received_at=RECEIVED_AT,
        with_phase=True,
        with_frequency=True,
    )
    assert tag.phase == 0x2A8C
    assert tag.frequency_khz == 914632
    assert tag.rssi == -65.7
    assert tag.antenna is None


def test_parse_tag_record_phase_and_frequency_with_tid_and_user() -> None:
    record = (
        b"\x30\x00"
        + bytes(range(1, 13))
        + bytes(range(13, 25))
        + b"\xaa\xbb"
        + bytes.fromhex("2A8C0DF4C8")
        + b"\xfd\x6f\x00"
    )
    tag = parse_tag_record(
        record,
        with_antenna=True,
        received_at=RECEIVED_AT,
        with_phase=True,
        with_frequency=True,
    )
    assert tag.tid == bytes(range(13, 25))
    assert tag.user_data == b"\xaa\xbb"
    assert tag.phase == 0x2A8C
    assert tag.frequency_khz == 914632
    assert tag.rssi == -65.7
    assert tag.antenna == 0


def test_parse_flash_tags() -> None:
    payload = b"\x02\x06\x11\x22\x33\x44\x55\x66\x04\xaa\xbb\xcc\xdd"
    assert parse_flash_tags(payload) == (b"\x11\x22\x33\x44\x55\x66", b"\xaa\xbb\xcc\xdd")


def test_parse_flash_tags_stops_at_a_truncated_record() -> None:
    assert parse_flash_tags(b"\x02\x06\x11\x22\x33") == ()


def test_parse_flash_tags_stops_when_the_count_overruns() -> None:
    assert parse_flash_tags(b"\x02\x02\x11\x22") == (b"\x11\x22",)


def test_parse_flash_tags_empty_count() -> None:
    assert parse_flash_tags(b"\x00") == ()


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
    assert build_filter_payload(None, save=False) == b"\x00\x01\x00\x00\x00\x00"
    assert build_filter_payload(None, save=True) == b"\x01\x01\x00\x00\x00\x00"


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


def test_parse_device_id() -> None:
    assert parse_device_id(b"\xf1\xf2\xf3\xf4") == b"\xf1\xf2\xf3\xf4"


def test_parse_device_id_rejects_a_foreign_length() -> None:
    with pytest.raises(ChainwayResponseError, match="device ID"):
        parse_device_id(b"\xf1\xf2\xf3")


def test_parse_fixed_frequency() -> None:
    assert parse_fixed_frequency(b"\x01\x0e\x0a\x3d") == (920125,)


def test_parse_fixed_frequency_multiple_points() -> None:
    assert parse_fixed_frequency(b"\x02\x0e\x0a\x3d\x0e\x0a\x63") == (920125, 920163)


def test_parse_fixed_frequency_rejects_a_count_mismatch() -> None:
    with pytest.raises(ChainwayResponseError, match="fixed frequency"):
        parse_fixed_frequency(b"\x02\x0e\x0a\x3d")


def test_parse_fixed_frequency_rejects_an_empty_payload() -> None:
    with pytest.raises(ChainwayResponseError, match="fixed frequency"):
        parse_fixed_frequency(b"")


def test_parse_return_loss() -> None:
    assert parse_return_loss(b"\x01\x12\x02\x01\x03\x00\x04\x00") == (
        ReturnLoss(port=1, loss_db=18),
        ReturnLoss(port=2, loss_db=1),
        ReturnLoss(port=3, loss_db=0),
        ReturnLoss(port=4, loss_db=0),
    )


def test_parse_return_loss_empty_payload() -> None:
    assert parse_return_loss(b"") == ()


def test_parse_return_loss_rejects_an_odd_payload() -> None:
    with pytest.raises(ChainwayResponseError, match="return loss"):
        parse_return_loss(b"\x01\x12\x02")


def test_parse_word_data() -> None:
    assert parse_word_data(b"\x01\x00\x00\x02\x11\x22\x33\x44", "read") == b"\x11\x22\x33\x44"


def test_parse_word_data_rejects_a_short_payload() -> None:
    with pytest.raises(ChainwayResponseError, match="at least 4 bytes"):
        parse_word_data(b"\x01\x00\x00", "read")


def test_parse_word_data_rejects_truncated_data() -> None:
    with pytest.raises(ChainwayResponseError, match="promised"):
        parse_word_data(b"\x01\x00\x00\x04\x11\x22", "read")


def test_validate_block_window() -> None:
    validate_block_window(0, 1)
    validate_block_window(0xFFFF, 0xFFFF)
    with pytest.raises(ValueError, match="block pointer"):
        validate_block_window(-1, 1)
    with pytest.raises(ValueError, match="block range"):
        validate_block_window(0, 0)


def qt_filter() -> TagFilter:
    return TagFilter(bank=MemoryBank.EPC, bit_address=0x20, bit_length=16, data=b"\xe2\x80")


def test_parse_voltage_positive() -> None:
    assert parse_voltage(b"\x01\x01\x0b\xb8") == 3000


def test_parse_voltage_negative() -> None:
    assert parse_voltage(b"\x01\x01\xff\x38") == -200


def test_parse_voltage_rejects_a_short_payload() -> None:
    with pytest.raises(ChainwayResponseError, match="voltage"):
        parse_voltage(b"\x01\x01\x0b")


def test_build_module_parameter_payload_set_form() -> None:
    payload = build_module_parameter_payload(0x01, 0x01020304, b"\x00\x00\x00\x02")
    assert payload == bytes.fromhex("010102030400000002")


def test_build_module_parameter_payload_get_form() -> None:
    assert build_module_parameter_payload(0x01, 0x01020304, None) == bytes.fromhex("0101020304")


def test_build_module_parameter_payload_rejects_a_bad_type() -> None:
    with pytest.raises(ValueError, match="parameter type"):
        build_module_parameter_payload(256, 0, b"\x00" * 4)


def test_build_module_parameter_payload_rejects_a_bad_id() -> None:
    with pytest.raises(ValueError, match="parameter ID"):
        build_module_parameter_payload(0, 1 << 32, b"\x00" * 4)


def test_build_module_parameter_payload_rejects_bad_data() -> None:
    with pytest.raises(ValueError, match="parameter data"):
        build_module_parameter_payload(0, 0, b"\x00")


def test_parse_module_parameter() -> None:
    payload = bytes.fromhex("0101020304aabbccdd")
    assert parse_module_parameter(payload, 0x01020304) == b"\xaa\xbb\xcc\xdd"


def test_parse_module_parameter_rejects_a_foreign_echo() -> None:
    with pytest.raises(ChainwayResponseError, match="echoed"):
        parse_module_parameter(bytes.fromhex("010000000055667788"), 0x01020304)


def test_parse_module_parameter_rejects_a_short_payload() -> None:
    with pytest.raises(ChainwayResponseError, match="module parameter"):
        parse_module_parameter(b"\x01\x01", 0x01020304)


def test_build_deactivate_payload_with_filter() -> None:
    payload = build_deactivate_payload(b"\x00\x00", b"\x00\x00\x00\x00", qt_filter())
    assert payload == bytes.fromhex("0000000000000100200010E280")


def test_build_deactivate_payload_without_filter() -> None:
    payload = build_deactivate_payload(b"\x00\x00", b"\x12\x34\x56\x78", None)
    assert payload == bytes.fromhex("0000123456780100000000")


def test_build_deactivate_payload_rejects_a_bad_command() -> None:
    with pytest.raises(ValueError, match="command"):
        build_deactivate_payload(b"\x00", b"\x00\x00\x00\x00", None)


def test_build_deactivate_payload_rejects_a_bad_password() -> None:
    with pytest.raises(ValueError, match="password"):
        build_deactivate_payload(b"\x00\x00", b"\x00", None)


def test_build_sensor_payload_pads_the_epc() -> None:
    epc = bytes.fromhex("E2801160600002056B3A5A1E")
    payload = build_sensor_payload(SensorSubcommand.ON_CHIP_RSSI, epc, 1, 30.0)
    assert payload == b"\x03" + epc + b"\x00\x00\x00\x00" + b"\x01\x0b\xb8"


def test_build_sensor_payload_write_calibration() -> None:
    payload = build_sensor_payload(SensorSubcommand.WRITE_CALIBRATION, b"\x01", 1, 30.0, bytes(8))
    assert payload == b"\x06\x01" + b"\x00" * 15 + b"\x01\x0b\xb8" + bytes(8)


def test_build_sensor_payload_rejects_a_long_epc() -> None:
    with pytest.raises(ValueError, match="EPC"):
        build_sensor_payload(SensorSubcommand.SENSOR_CODE, bytes(17), 1, 30.0)


def test_build_sensor_payload_rejects_a_bad_antenna() -> None:
    with pytest.raises(ValueError, match="antenna"):
        build_sensor_payload(SensorSubcommand.SENSOR_CODE, b"", 0, 30.0)


def test_build_sensor_payload_rejects_a_bad_power() -> None:
    with pytest.raises(ValueError, match="power"):
        build_sensor_payload(SensorSubcommand.SENSOR_CODE, b"", 1, 40.0)


def test_build_sensor_payload_rejects_a_wrong_data_length() -> None:
    with pytest.raises(ValueError, match="calibration data"):
        build_sensor_payload(SensorSubcommand.WRITE_CALIBRATION, b"", 1, 30.0, b"\x00")
    with pytest.raises(ValueError, match="calibration data"):
        build_sensor_payload(SensorSubcommand.SENSOR_CODE, b"", 1, 30.0, b"\x00")


def test_build_tag_sensor_payload_start_logging() -> None:
    extra = bytes.fromhex("0050007A0000000A")
    payload = build_tag_sensor_payload(TagSensorSubcommand.START_LOGGING, qt_filter(), extra)
    assert payload == bytes.fromhex("030100200010E2800050007A0000000A")


def test_build_tag_sensor_payload_stop_logging() -> None:
    payload = build_tag_sensor_payload(TagSensorSubcommand.STOP_LOGGING, qt_filter(), b"")
    assert payload == bytes.fromhex("040100200010E280")


def test_parse_tag_sensor_value() -> None:
    value = parse_tag_sensor_value(b"\x05\x00\x01", TagSensorSubcommand.CHECK_OP_MODE, "mode")
    assert value == 1


def test_parse_tag_sensor_value_rejects_a_foreign_echo() -> None:
    with pytest.raises(ChainwayResponseError, match="echo"):
        parse_tag_sensor_value(b"\x06\x00\x01", TagSensorSubcommand.CHECK_OP_MODE, "mode")


def test_parse_tag_sensor_value_rejects_a_short_payload() -> None:
    with pytest.raises(ChainwayResponseError, match="at least 3 bytes"):
        parse_tag_sensor_value(b"\x05\x00", TagSensorSubcommand.CHECK_OP_MODE, "mode")


def test_parse_tag_temperatures() -> None:
    assert parse_tag_temperatures(bytes.fromhex("07000202500000007A000000")) == (20.0, 30.5)


def test_parse_tag_temperatures_decodes_negative_codes() -> None:
    payload = bytes.fromhex("07000202D7030000FC030000")
    assert parse_tag_temperatures(payload) == (-10.25, -1.0)


def test_parse_tag_temperatures_rejects_truncated_records() -> None:
    with pytest.raises(ChainwayResponseError, match="promised"):
        parse_tag_temperatures(bytes.fromhex("07000202D7030000"))


def test_parse_tag_temperatures_rejects_a_foreign_echo() -> None:
    with pytest.raises(ChainwayResponseError, match="echo"):
        parse_tag_temperatures(bytes.fromhex("05000200"))


def test_parse_tag_temperatures_rejects_a_short_payload() -> None:
    with pytest.raises(ChainwayResponseError, match="at least 4 bytes"):
        parse_tag_temperatures(b"\x07\x00\x02")


def test_parse_collected_tags_full() -> None:
    record = b"\x30\x00" + bytes(range(1, 13)) + b"\xfe\xd6"
    payload = b"\x00\x00\x05\x02\x10" + record + b"\x10" + record
    collected = parse_collected_tags_full(payload)
    assert isinstance(collected, CollectedTagsFull)
    assert collected.index == 5
    assert len(collected.tags) == 2
    assert collected.tags[0].epc == bytes(range(1, 13))
    assert collected.tags[0].rssi == -29.8
    assert collected.tags[0].antenna is None


def test_parse_collected_tags_full_invalid_marker() -> None:
    collected = parse_collected_tags_full(b"\x00\x00\x07")
    assert collected.index == 7
    assert collected.tags == ()


def test_parse_collected_tags_full_stops_at_a_truncated_record() -> None:
    record = b"\x30\x00" + bytes(range(1, 13)) + b"\xfe\xd6"
    payload = b"\x00\x00\x05\x02\x10" + record + b"\x10\x11\x22"
    collected = parse_collected_tags_full(payload)
    assert len(collected.tags) == 1


def test_parse_collected_tags_full_stops_when_the_count_overruns() -> None:
    record = b"\x30\x00" + bytes(range(1, 13)) + b"\xfe\xd6"
    payload = b"\x00\x00\x05\x02\x10" + record
    collected = parse_collected_tags_full(payload)
    assert len(collected.tags) == 1


def test_parse_collected_tags_full_rejects_a_short_payload() -> None:
    with pytest.raises(ChainwayResponseError, match="at least 3 bytes"):
        parse_collected_tags_full(b"\x00\x05")
