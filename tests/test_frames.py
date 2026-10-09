"""Frame codec tests pinned to the worked examples in docs/protocol.md."""

import pytest

from chainway_serial.exceptions import ChainwayProtocolError
from chainway_serial.frames import build_frame, compute_checksum, parse_frame


def test_checksum_xor() -> None:
    assert compute_checksum(b"\x00\x08\x02") == 0x0A
    assert compute_checksum(b"") == 0


def test_get_version_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0x02) == bytes.fromhex("A55A0008020A0D0A")


def test_start_inventory_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0x82, b"\x00\x00") == bytes.fromhex("A55A000A820000880D0A")


def test_start_inventory_frequency_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0x82, b"\xff\xfe") == bytes.fromhex("A55A000A82FFFE890D0A")


def test_start_inventory_phase_and_frequency_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0x82, b"\xff\xfd") == bytes.fromhex("A55A000A82FFFD8A0D0A")


def test_stop_inventory_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0x8C) == bytes.fromhex("A55A00088C840D0A")


def test_beep_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0xE4, b"\x03\x01\x01") == bytes.fromhex("A55A000BE4030101EC0D0A")


def test_get_region_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0x2E) == bytes.fromhex("A55A00082E260D0A")


def test_get_gen2_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0x22) == bytes.fromhex("A55A0008222A0D0A")


def test_set_uart_baudrate_frame_matches_the_captured_reference() -> None:
    assert build_frame(0x1C, b"\x02") == bytes.fromhex("A55A00091C02170D0A")


def test_get_uart_baudrate_frame_matches_the_captured_reference() -> None:
    assert build_frame(0x1E) == bytes.fromhex("A55A00081E160D0A")


def test_read_tag_frame_matches_the_protocol_reference() -> None:
    payload = bytes.fromhex("0000000001000000000300020002")
    assert build_frame(0x84, payload) == bytes.fromhex(
        "A55A0016840000000001000000000300020002900D0A"
    )


def test_write_tag_frame_matches_the_protocol_reference() -> None:
    payload = bytes.fromhex("0000000001000000000300020001E280")
    assert build_frame(0x86, payload) == bytes.fromhex(
        "A55A0018860000000001000000000300020001E280FD0D0A"
    )


def test_lock_tag_frame_matches_the_protocol_reference() -> None:
    payload = bytes.fromhex("000000000100000000020080")
    assert build_frame(0x88, payload) == bytes.fromhex("A55A0014880000000001000000000200801F0D0A")


def test_kill_tag_frame_matches_the_protocol_reference() -> None:
    payload = bytes.fromhex("123456780100000000")
    assert build_frame(0x8A, payload) == bytes.fromhex("A55A00118A123456780100000000920D0A")


def test_filter_frame_matches_the_protocol_reference() -> None:
    payload = bytes.fromhex("0001002000101234")
    assert build_frame(0x6E, payload) == bytes.fromhex("A55A00106E0001002000101234690D0A")


def test_collected_tags_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0xE0) == bytes.fromhex("A55A0008E0E80D0A")


def test_collected_tags_full_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0xE2, b"\x01") == bytes.fromhex("A55A0009E201EA0D0A")


def test_get_device_id_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0x04) == bytes.fromhex("A55A0008040C0D0A")


def test_get_fixed_frequency_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0x16) == bytes.fromhex("A55A0008161E0D0A")


def test_get_return_loss_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0x26) == bytes.fromhex("A55A0008262E0D0A")


def test_software_reset_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0x68) == bytes.fromhex("A55A000868600D0A")


def test_restore_factory_settings_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0x74) == bytes.fromhex("A55A0008747C0D0A")


def test_authenticate_tag_frame_matches_the_protocol_reference() -> None:
    payload = bytes.fromhex("0000000001000000000B0000010203040506070809")
    assert build_frame(0x8E, payload) == bytes.fromhex(
        "A55A001D8E0000000001000000000B0000010203040506070809980D0A"
    )


def test_set_protected_mode_frame_matches_the_protocol_reference() -> None:
    payload = bytes.fromhex("000000000100200010E2800100")
    assert build_frame(0x90, payload) == bytes.fromhex("A55A001590000000000100200010E2800100D70D0A")


def test_block_permalock_frame_matches_the_protocol_reference() -> None:
    payload = bytes.fromhex("000000000200000060E2003414013301001038D2B5000300000001")
    assert build_frame(0x9F, payload) == bytes.fromhex(
        "A55A00239F000000000200000060E2003414013301001038D2B5000300000001620D0A"
    )


def test_buzzer_off_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0xE4, b"\x03\x00") == bytes.fromhex("A55A000AE40300ED0D0A")


def test_verify_voltage_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0x08, b"\x01") == bytes.fromhex("A55A00090801000D0A")


def test_set_module_parameter_frame_matches_the_protocol_reference() -> None:
    payload = bytes.fromhex("010000000100000002")
    assert build_frame(0x18, payload) == bytes.fromhex("A55A0011180100000001000000020B0D0A")


def test_get_module_parameter_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0x1A, bytes.fromhex("0100000001")) == bytes.fromhex(
        "A55A000D1A0100000001170D0A"
    )


def test_set_temperature_protect_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0x38, b"\x01") == bytes.fromhex("A55A00093801300D0A")


def test_get_temperature_protect_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0x3A) == bytes.fromhex("A55A00083A320D0A")


def test_set_work_time_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0x3C, bytes.fromhex("00000001F4")) == bytes.fromhex(
        "A55A000D3C00000001F4C40D0A"
    )


def test_get_work_time_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0x3E) == bytes.fromhex("A55A00083E360D0A")


def test_set_dual_single_mode_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0x6A, b"\x01\x01") == bytes.fromhex("A55A000A6A0101600D0A")


def test_get_dual_single_mode_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0x6C) == bytes.fromhex("A55A00086C640D0A")


def test_sensor_calibration_frame_matches_the_protocol_reference() -> None:
    payload = bytes.fromhex("03E2801160600002056B3A5A1E00000000010BB8")
    assert build_frame(0x7C, payload) == bytes.fromhex(
        "A55A001C7C03E2801160600002056B3A5A1E00000000010BB8B00D0A"
    )


def test_set_qt_frame_matches_the_protocol_reference() -> None:
    payload = bytes.fromhex("000000000100200010E28001")
    assert build_frame(0x97, payload) == bytes.fromhex("A55A001497000000000100200010E28001D10D0A")


def test_get_qt_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0x99, bytes.fromhex("000000000100200010E280")) == bytes.fromhex(
        "A55A001399000000000100200010E280D90D0A"
    )


def test_read_qt_frame_matches_the_protocol_reference() -> None:
    payload = bytes.fromhex("000000000100200010E280010300000002")
    assert build_frame(0x9B, payload) == bytes.fromhex(
        "A55A00199B000000000100200010E280010300000002D10D0A"
    )


def test_write_qt_frame_matches_the_protocol_reference() -> None:
    payload = bytes.fromhex("000000000100200010E2800103000000011234")
    assert build_frame(0x9D, payload) == bytes.fromhex(
        "A55A001B9D000000000100200010E2800103000000011234F00D0A"
    )


def test_deactivate_frame_matches_the_protocol_reference() -> None:
    payload = bytes.fromhex("0000000000000100200010E280")
    assert build_frame(0xB0, payload) == bytes.fromhex("A55A0015B00000000000000100200010E280F60D0A")


def test_dwell_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0xB2, bytes.fromhex("000003E800000003")) == bytes.fromhex(
        "A55A0010B2000003E8000000034A0D0A"
    )


def test_start_tag_logging_frame_matches_the_protocol_reference() -> None:
    payload = bytes.fromhex("030100200010E2800050007A0000000A")
    assert build_frame(0xA3, payload) == bytes.fromhex(
        "A55A0018A3030100200010E2800050007A0000000ACB0D0A"
    )


def test_stop_tag_logging_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0xA3, bytes.fromhex("040100200010E280")) == bytes.fromhex(
        "A55A0010A3040100200010E280E40D0A"
    )


def test_check_tag_sensor_mode_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0xA3, bytes.fromhex("050100200010E280")) == bytes.fromhex(
        "A55A0010A3050100200010E280E50D0A"
    )


def test_read_tag_voltage_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0xA3, bytes.fromhex("060100200010E280")) == bytes.fromhex(
        "A55A0010A3060100200010E280E60D0A"
    )


def test_read_tag_temperatures_frame_matches_the_protocol_reference() -> None:
    assert build_frame(0xA3, bytes.fromhex("070100200010E280000004")) == bytes.fromhex(
        "A55A0013A3070100200010E280000004E00D0A"
    )


def test_bootloader_jump_frames_match_the_protocol_reference() -> None:
    assert build_frame(0xC0, b"\xcc") == bytes.fromhex("A55A0009C0CC050D0A")
    assert build_frame(0xC0, b"\xee") == bytes.fromhex("A55A0009C0EE270D0A")
    assert build_frame(0xC0, b"\xbb") == bytes.fromhex("A55A0009C0BB720D0A")
    assert build_frame(0xC0, b"\xaa") == bytes.fromhex("A55A0009C0AA630D0A")


def test_roundtrip() -> None:
    frame = build_frame(0x70, b"\x00\x02\x00\x04")
    assert parse_frame(frame) == (0x70, b"\x00\x02\x00\x04")


def test_payload_too_long() -> None:
    with pytest.raises(ChainwayProtocolError, match="outside 8 to 2048"):
        build_frame(0x02, b"\x00" * 3000)


def test_parse_rejects_bad_header() -> None:
    frame = bytearray(build_frame(0x02))
    frame[0] = 0x00
    with pytest.raises(ChainwayProtocolError, match="header"):
        parse_frame(bytes(frame))


def test_parse_rejects_bad_tail() -> None:
    frame = bytearray(build_frame(0x02))
    frame[-1] = 0x00
    with pytest.raises(ChainwayProtocolError, match="tail"):
        parse_frame(bytes(frame))


def test_parse_rejects_bad_checksum() -> None:
    frame = bytearray(build_frame(0x02))
    frame[-3] ^= 0xFF
    with pytest.raises(ChainwayProtocolError, match="checksum"):
        parse_frame(bytes(frame))


def test_parse_rejects_short_frame() -> None:
    with pytest.raises(ChainwayProtocolError, match="outside 8 to 2048"):
        parse_frame(b"\xa5\x5a\x00\x04")


def test_payload_with_tail_bytes_roundtrips() -> None:
    payload = b"\x30\x00" + b"\r\n" * 3
    command, parsed = parse_frame(build_frame(0x83, payload))
    assert command == 0x83
    assert parsed == payload


def test_parse_accepts_the_alternate_header() -> None:
    frame = bytearray(build_frame(0x02))
    frame[0] = 0xC8
    frame[1] = 0x8C
    assert parse_frame(bytes(frame)) == (0x02, b"")
