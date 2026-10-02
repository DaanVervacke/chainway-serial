"""State machine tests for the framing protocol."""

from chainway_serial.frames import build_frame
from chainway_serial.protocol import ChainwayProtocol


def make_protocol() -> tuple[ChainwayProtocol, list[tuple[int, bytes]]]:
    frames: list[tuple[int, bytes]] = []

    def on_frame(command: int, payload: bytes) -> None:
        frames.append((command, payload))

    protocol = ChainwayProtocol(on_frame, lambda _exc: None)
    return protocol, frames


def test_single_frame() -> None:
    protocol, frames = make_protocol()
    protocol.data_received(build_frame(0x02, b"\x01\x02\x03"))
    assert frames == [(0x02, b"\x01\x02\x03")]


def test_frame_delivered_byte_by_byte() -> None:
    protocol, frames = make_protocol()
    for byte in build_frame(0x02, b"\x01\x02\x03"):
        protocol.data_received(bytes((byte,)))
    assert frames == [(0x02, b"\x01\x02\x03")]


def test_frames_split_at_random_chunk_boundaries() -> None:
    protocol, frames = make_protocol()
    stream = build_frame(0x02) + build_frame(0x34) + build_frame(0x8C)
    protocol.data_received(stream[:5])
    protocol.data_received(stream[5:9])
    protocol.data_received(stream[9:20])
    protocol.data_received(stream[20:])
    assert [command for command, _ in frames] == [0x02, 0x34, 0x8C]


def test_junk_between_frames_is_skipped() -> None:
    protocol, frames = make_protocol()
    stream = b"\x00\xff garbage" + build_frame(0x02) + b"\x7f" + build_frame(0x34)
    protocol.data_received(stream)
    assert [command for command, _ in frames] == [0x02, 0x34]


def test_bare_keepalive_byte_is_tolerated() -> None:
    protocol, frames = make_protocol()
    protocol.data_received(b"\x00")
    protocol.data_received(build_frame(0x02))
    assert frames == [(0x02, b"")]


def test_bad_checksum_resyncs_to_the_next_header() -> None:
    protocol, frames = make_protocol()
    broken = bytearray(build_frame(0x02))
    broken[-3] ^= 0xFF
    protocol.data_received(bytes(broken) + build_frame(0x02, b"\x09"))
    assert frames == [(0x02, b"\x09")]


def test_invalid_length_resyncs_to_the_next_header() -> None:
    protocol, frames = make_protocol()
    protocol.data_received(b"\xa5\x5a\xff\xff\x00\x00\x00\x00" + build_frame(0x02))
    assert frames == [(0x02, b"")]


def test_split_header_hunt_survives_a_lone_a5() -> None:
    protocol, frames = make_protocol()
    protocol.data_received(b"\xa5")
    protocol.data_received(b"\x5a\x00\x08\x02\x0a\x0d\x0a")
    assert frames == [(0x02, b"")]


def test_bad_tail_resyncs() -> None:
    protocol, frames = make_protocol()
    broken = bytearray(build_frame(0x02))
    broken[-2] = 0x00
    protocol.data_received(bytes(broken) + build_frame(0x02))
    assert frames == [(0x02, b"")]


def test_payload_containing_the_tail_pair_is_not_split() -> None:
    protocol, frames = make_protocol()
    payload = b"\x30\x00" + b"\r\n\r\n"
    protocol.data_received(build_frame(0x83, payload))
    assert frames == [(0x83, payload)]


def test_last_activity_is_updated_on_any_data() -> None:
    protocol, _ = make_protocol()
    before = protocol.last_activity
    protocol.data_received(b"\x00")
    assert protocol.last_activity >= before


def test_connection_lost_forwards_to_the_callback() -> None:
    lost: list[Exception | None] = []
    protocol = ChainwayProtocol(lambda _c, _p: None, lost.append)
    sample = OSError("gone")
    protocol.connection_lost(sample)
    assert lost == [sample]


def test_alternate_header_frame_is_delivered() -> None:
    protocol, frames = make_protocol()
    frame = bytearray(build_frame(0x02, b"\x09"))
    frame[0] = 0xC8
    frame[1] = 0x8C
    protocol.data_received(bytes(frame))
    assert frames == [(0x02, b"\x09")]


def test_mixed_headers_are_both_parsed() -> None:
    protocol, frames = make_protocol()
    alt = bytearray(build_frame(0x02))
    alt[0] = 0xC8
    alt[1] = 0x8C
    protocol.data_received(bytes(alt) + build_frame(0x34))
    assert [command for command, _ in frames] == [0x02, 0x34]


def test_lone_alternate_header_byte_is_retained() -> None:
    protocol, frames = make_protocol()
    alt = bytearray(build_frame(0x02))
    alt[0] = 0xC8
    alt[1] = 0x8C
    protocol.data_received(b"\xc8")
    protocol.data_received(bytes(alt)[1:])
    assert frames == [(0x02, b"")]
