"""Tests pinned to frames captured from a UR4 with an antenna and real tags.

The reader ran firmware 7.40.1 with Impinj Monza R6-P and Alien tags on
the antenna. docs/protocol.md lists the captures under live verification.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest

from chainway_serial import (
    ChainwayClient,
    ChainwayResponseError,
    ChainwayTimeoutError,
    ChainwayUnsupportedCommandError,
    LockBank,
    LockMode,
    MemoryBank,
    ReturnLoss,
    TagFilter,
)
from chainway_serial.const import Command, SensorSubcommand
from chainway_serial.frames import build_frame, parse_frame
from chainway_serial.parsers import (
    build_filter_payload,
    build_lock_code,
    build_tag_operation_payload,
    parse_return_loss,
    parse_tag_record,
)

from .fake_reader import FakeReaderLogic

RECEIVED_AT = datetime(2026, 10, 9, tzinfo=UTC)
TID = bytes.fromhex("e2801170200011cd615c0b20")
BY_TID = TagFilter(bank=MemoryBank.TID, bit_address=0, bit_length=96, data=TID)
ZERO_PASSWORD = bytes(4)


def frame_payload(frame_hex: str) -> bytes:
    _, payload = parse_frame(bytes.fromhex(frame_hex))
    return payload


def test_return_loss_with_an_antenna_on_port_one() -> None:
    payload = frame_payload("A55A0010270110020003000400230D0A")
    assert parse_return_loss(payload) == (
        ReturnLoss(port=1, loss_db=16),
        ReturnLoss(port=2, loss_db=0),
        ReturnLoss(port=3, loss_db=0),
        ReturnLoss(port=4, loss_db=0),
    )


def test_epc_and_tid_record() -> None:
    record = bytes.fromhex("3400523742303030303539353538e28011702000419f40ac0b9ffe1301")
    tag = parse_tag_record(record, with_antenna=True, received_at=RECEIVED_AT)
    assert tag.epc == b"R7B000059558"
    assert tag.tid == bytes.fromhex("e28011702000419f40ac0b9f")
    assert tag.user_data is None
    assert tag.rssi == -49.3
    assert tag.antenna == 1


def test_epc_tid_and_user_record() -> None:
    record = bytes.fromhex("3400523742303030303539353536e28011702000518f40ac0b9f00000000fdcd01")
    tag = parse_tag_record(record, with_antenna=True, received_at=RECEIVED_AT)
    assert tag.tid == bytes.fromhex("e28011702000518f40ac0b9f")
    assert tag.user_data == bytes(4)
    assert tag.rssi == -56.3


def test_phase_only_record_carries_no_tid() -> None:
    record = bytes.fromhex("34005237423030303035393535380147fe1701")
    tag = parse_tag_record(record, with_antenna=True, received_at=RECEIVED_AT, with_phase=True)
    assert tag.epc == b"R7B000059558"
    assert tag.tid is None
    assert tag.phase == 327
    assert tag.rssi == -48.9


def test_frequency_record_on_an_etsi_channel() -> None:
    record = bytes.fromhex("3400523730303030303534373634e2801170200011cd615c0b200d3a54fe8b01")
    tag = parse_tag_record(record, with_antenna=True, received_at=RECEIVED_AT, with_frequency=True)
    assert tag.tid == TID
    assert tag.frequency_khz == 866900
    assert tag.rssi == -37.3


def test_phase_and_frequency_record() -> None:
    record = bytes.fromhex("3400523742303030303539353537e2801170200041ff40ac0b9f00510d3a54fdb101")
    tag = parse_tag_record(
        record, with_antenna=True, received_at=RECEIVED_AT, with_phase=True, with_frequency=True
    )
    assert tag.tid == bytes.fromhex("e2801170200041ff40ac0b9f")
    assert tag.user_data is None
    assert tag.phase == 81
    assert tag.frequency_khz == 866900
    assert tag.rssi == -59.1
    assert tag.antenna == 1


def test_fast_id_record_appends_the_tid_in_epc_mode() -> None:
    record = bytes.fromhex("3000523730303030303534373633e28011702000037d615e0b20fdef01")
    tag = parse_tag_record(record, with_antenna=True, received_at=RECEIVED_AT)
    assert tag.pc == b"\x30\x00"
    assert tag.epc == b"R70000054763"
    assert tag.tid == bytes.fromhex("e28011702000037d615e0b20")


def test_read_reserved_bank_frame() -> None:
    tail = bytes((MemoryBank.RESERVED, 0x00, 0x00, 0x00, 0x04))
    payload = build_tag_operation_payload(ZERO_PASSWORD, BY_TID, tail)
    assert build_frame(Command.READ_TAG, payload) == bytes.fromhex(
        "A55A002284000000000200000060E2801170200011CD615C0B200000000004290D0A"
    )


@pytest.mark.parametrize(
    ("banks", "mode", "code"),
    [
        ([LockBank.USER], LockMode.LOCK, "000802"),
        ([LockBank.ACCESS_PASSWORD], LockMode.LOCK, "020080"),
        ([LockBank.USER, LockBank.ACCESS_PASSWORD], LockMode.OPEN, "020800"),
    ],
)
def test_lock_codes_the_tags_accepted(banks: list[LockBank], mode: LockMode, code: str) -> None:
    assert build_lock_code(banks, mode) == bytes.fromhex(code)


def test_lock_user_bank_frame() -> None:
    payload = build_tag_operation_payload(
        bytes.fromhex("aabbccdd"), BY_TID, build_lock_code([LockBank.USER], LockMode.LOCK)
    )
    assert build_frame(Command.LOCK_TAG, payload) == bytes.fromhex(
        "A55A002088AABBCCDD0200000060E2801170200011CD615C0B20000802290D0A"
    )


def test_epc_prefix_filter_frame() -> None:
    tag_filter = TagFilter(bank=MemoryBank.EPC, bit_address=32, bit_length=24, data=b"R7B")
    payload = build_filter_payload(tag_filter, save=False)
    assert build_frame(Command.SET_INVENTORY_FILTER, payload) == bytes.fromhex(
        "A55A00116E000100200018523742610D0A"
    )


async def test_read_reserved_bank_sends_bank_zero(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    await client.read_tag(MemoryBank.RESERVED, 0, 4, tag_filter=BY_TID)
    payload = logic.received[-1][1]
    assert payload[-5:] == b"\x00\x00\x00\x00\x04"


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (b"\x00\x22\x00\x00", r"error code 0x22: no tag answered"),
        (b"\x00\x01", r"error code 0x01: the tag rejected the operation"),
        (b"\x00\x05", r"error code 0x05$"),
        (b"\x01", r"failed with payload"),
    ],
)
async def test_tag_errors_name_the_code(
    client: ChainwayClient,
    reader_server: tuple[FakeReaderLogic, int],
    reply: bytes,
    message: str,
) -> None:
    logic, _ = reader_server
    logic.tag_error_payload = reply
    logic.failing_tag_commands = {Command.READ_TAG}
    with pytest.raises(ChainwayResponseError, match=message):
        await client.read_tag(MemoryBank.TID, 0, 12, tag_filter=BY_TID)


UNSUPPORTED_CALLS: list[tuple[Command, Callable[[ChainwayClient], Awaitable[object]]]] = [
    (Command.BLOCK_ERASE_TAG, lambda c: c.block_erase_tag(MemoryBank.USER, 0, 2)),
    (Command.READ_QT, lambda c: c.read_qt(0x00, MemoryBank.USER, 0, 2)),
    (Command.GET_QT, lambda c: c.get_qt()),
    (Command.DEACTIVATE_TAG, lambda c: c.deactivate_tag()),
    (
        Command.SENSOR_CALIBRATION,
        lambda c: c.read_tag_sensor(SensorSubcommand.SENSOR_CODE, b"R70000054764", 1, 20.0),
    ),
    (Command.TAG_SENSOR, lambda c: c.check_tag_sensor_mode(BY_TID)),
    (Command.TAG_SENSOR, lambda c: c.read_tag_sensor_voltage(BY_TID)),
    (Command.TAG_SENSOR, lambda c: c.read_tag_temperatures(BY_TID, 0, 4)),
    (Command.READ_COLLECTED_TAGS_FULL, lambda c: c.read_collected_tags_full()),
    (Command.FLASH_STORAGE, lambda c: c.get_collected_tag_count()),
    (Command.FLASH_STORAGE, lambda c: c.get_new_collected_tag_count()),
    (Command.FLASH_STORAGE, lambda c: c.delete_collected_tags()),
]


@pytest.mark.parametrize(("command", "call"), UNSUPPORTED_CALLS)
async def test_bare_zero_reply_raises_unsupported(
    client: ChainwayClient,
    reader_server: tuple[FakeReaderLogic, int],
    command: Command,
    call: Callable[[ChainwayClient], Awaitable[object]],
) -> None:
    logic, _ = reader_server
    logic._responders[command] = lambda _payload: b"\x00"
    with pytest.raises(ChainwayUnsupportedCommandError, match=f"{command:#04x}"):
        await call(client)


async def test_restore_waits_out_the_module_mute(
    client: ChainwayClient,
    reader_server: tuple[FakeReaderLogic, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logic, _ = reader_server
    logic.restore_mute = 0.2
    monkeypatch.setattr("chainway_serial.client.RESTORE_COMMIT_DELAY", 0.3)
    await client.restore_factory_settings()
    assert await client.get_version() is not None
    assert logic.dropped == []


async def test_without_the_restore_delay_the_module_drops_the_next_request(
    client: ChainwayClient, reader_server: tuple[FakeReaderLogic, int]
) -> None:
    logic, _ = reader_server
    logic.restore_mute = 0.3
    client.response_timeout = 0.1
    await client.restore_factory_settings()
    with pytest.raises(ChainwayTimeoutError):
        await client.get_version()
    assert logic.dropped == [(Command.GET_VERSION, b"")]
