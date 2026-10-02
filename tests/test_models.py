"""Model validation tests."""

from datetime import UTC, datetime

import pytest

from chainway_serial.models import (
    AntennaState,
    FirmwareVersion,
    Gen2Parameters,
    LockBank,
    LockMode,
    MemoryBank,
    OutputRoute,
    ReaderAddress,
    Tag,
    TagFilter,
    TriggerConfig,
    TriggerInput,
)


def test_firmware_version_str() -> None:
    assert str(FirmwareVersion(1, 2, 3)) == "V1.2.3"


def test_tag_filter_needs_enough_data() -> None:
    with pytest.raises(ValueError, match="data carries"):
        TagFilter(bank=MemoryBank.EPC, bit_address=0x20, bit_length=16, data=b"\x12")


def test_tag_filter_accepts_exact_data() -> None:
    tag_filter = TagFilter(bank=MemoryBank.EPC, bit_address=0x20, bit_length=16, data=b"\x12\x34")
    assert tag_filter.bank is MemoryBank.EPC


def test_tag_filter_rejects_a_bad_address() -> None:
    with pytest.raises(ValueError, match="bit_address"):
        TagFilter(bank=MemoryBank.EPC, bit_address=0x10000, bit_length=16, data=b"\x12\x34")


def test_trigger_config_rejects_a_bad_work_time() -> None:
    with pytest.raises(ValueError, match="work_time_ms"):
        TriggerConfig(
            input=TriggerInput.INPUT_1,
            work_time_ms=655360,
            min_interval_ms=100,
            output=OutputRoute.LINK,
        )


def test_reader_address_rejects_a_bad_ip() -> None:
    with pytest.raises(ValueError, match="dotted quad"):
        ReaderAddress(ip="192.168.99", port=8888)


def test_reader_address_rejects_a_bad_port() -> None:
    with pytest.raises(ValueError, match="port"):
        ReaderAddress(ip="192.168.99.200", port=0)


def test_gen2_parameters_reject_a_bad_target() -> None:
    with pytest.raises(ValueError, match="target"):
        Gen2Parameters(target=5)


def test_gen2_parameters_reject_a_bad_coding() -> None:
    with pytest.raises(ValueError, match="coding"):
        Gen2Parameters(coding=4)


def test_antenna_state_needs_at_least_one_flag() -> None:
    with pytest.raises(ValueError, match="at least one antenna"):
        AntennaState(connected=(), raw=b"\x00\x00")


def test_tag_is_frozen() -> None:
    tag = Tag(
        pc=b"\x30\x00",
        epc=b"\x01\x02",
        tid=None,
        user_data=None,
        rssi=None,
        antenna=None,
        received_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    with pytest.raises(AttributeError):
        tag.epc = b"\x00"  # type: ignore[misc]


def test_lock_bank_and_mode_values_match_the_sdk() -> None:
    assert LockBank.KILL_PASSWORD.value == 16
    assert LockBank.ACCESS_PASSWORD.value == 32
    assert LockBank.EPC.value == 48
    assert LockBank.TID.value == 64
    assert LockBank.USER.value == 80
    assert LockMode.LOCK.value == 16
    assert LockMode.OPEN.value == 32
    assert LockMode.PERMANENTLY_LOCK.value == 48
    assert LockMode.PERMANENTLY_OPEN.value == 64
