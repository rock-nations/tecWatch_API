"""
Minimal reader for pcapng and classic pcap capture files, plus Ethernet/IPv4/UDP/ICMP decoding.
Frames are numbered like Wireshark does (every packet block counts), so frame numbers in findings
match what an engineer sees when opening the same file in Wireshark.
"""
import ipaddress
import struct
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple


class CaptureFormatError(ValueError):
    """Raised when the uploaded file is not a readable pcapng/pcap capture."""


@dataclass
class Packet:
    number: int
    timestamp: float  # seconds since the Unix epoch (UTC)
    link_type: int
    data: bytes


@dataclass
class UdpDatagram:
    src: str
    dst: str
    src_port: int
    dst_port: int
    payload: bytes


@dataclass
class IcmpUnreachable:
    src: str
    dst: str
    code: int


PCAPNG_MAGIC = b"\x0a\x0d\x0d\x0a"
PCAP_MAGICS = {
    b"\xd4\xc3\xb2\xa1": ("<", 1e6),
    b"\xa1\xb2\xc3\xd4": (">", 1e6),
    b"\x4d\x3c\xb2\xa1": ("<", 1e9),
    b"\xa1\xb2\x3c\x4d": (">", 1e9),
}
CUSTOM_BLOCK_TYPES = (0x00000BAD, 0x40000BAD)
LINKTYPE_ETHERNET = 1
LINKTYPE_RAW = (101, 228, 229)  # raw IP, IPv4, IPv6
LINKTYPE_LINUX_SLL = 113
ETHERTYPE_IPV4, ETHERTYPE_IPV6 = 0x0800, 0x86DD


def is_capture(data: bytes) -> bool:
    return data[:4] == PCAPNG_MAGIC or data[:4] in PCAP_MAGICS


def read_packets(data: bytes) -> List[Packet]:
    if len(data) < 24:
        raise CaptureFormatError("The file is too short to be a capture file.")
    try:
        if data[:4] == PCAPNG_MAGIC:
            return list(_read_pcapng(data))
        if data[:4] in PCAP_MAGICS:
            return list(_read_pcap(data))
    except (struct.error, IndexError) as e:
        raise CaptureFormatError(f"The capture file is damaged ({e}).") from e
    raise CaptureFormatError("The file is not a pcapng or pcap capture.")


def _read_pcapng(data: bytes) -> Iterator[Packet]:
    offset = 0
    endian = "<"
    interfaces: List[tuple] = []  # (link_type, timestamp divisor)
    number = 0
    while offset + 12 <= len(data):
        if data[offset:offset + 4] == PCAPNG_MAGIC:
            byte_order = data[offset + 8:offset + 12]
            if byte_order == b"\x4d\x3c\x2b\x1a":
                endian = "<"
            elif byte_order == b"\x1a\x2b\x3c\x4d":
                endian = ">"
            else:
                raise CaptureFormatError("Invalid pcapng byte-order magic.")
            interfaces = []
        block_type, block_length = struct.unpack_from(endian + "II", data, offset)
        if block_length < 12 or block_length % 4 or offset + block_length > len(data):
            raise CaptureFormatError(f"Corrupt pcapng block at byte {offset}.")
        body = data[offset + 8:offset + block_length - 4]

        if block_type == 0x00000001:  # Interface Description Block
            link_type = struct.unpack_from(endian + "H", body, 0)[0]
            interfaces.append((link_type, _timestamp_divisor(body, endian)))
        elif block_type == 0x00000006:  # Enhanced Packet Block
            interface_id, ts_high, ts_low, captured_length = struct.unpack_from(endian + "IIII", body, 0)
            link_type, divisor = interfaces[interface_id] if interface_id < len(interfaces) else (LINKTYPE_ETHERNET, 1e6)
            number += 1
            yield Packet(number, ((ts_high << 32) | ts_low) / divisor, link_type, body[20:20 + captured_length])
        elif block_type == 0x00000003:  # Simple Packet Block (no timestamp)
            original_length = struct.unpack_from(endian + "I", body, 0)[0]
            link_type = interfaces[0][0] if interfaces else LINKTYPE_ETHERNET
            number += 1
            yield Packet(number, 0.0, link_type, body[4:4 + original_length])
        elif block_type == 0x00000002:  # obsolete Packet Block
            interface_id, _drops, ts_high, ts_low, captured_length = struct.unpack_from(endian + "HHIII", body, 0)
            link_type, divisor = interfaces[interface_id] if interface_id < len(interfaces) else (LINKTYPE_ETHERNET, 1e6)
            number += 1
            yield Packet(number, ((ts_high << 32) | ts_low) / divisor, link_type, body[20:20 + captured_length])
        elif block_type in CUSTOM_BLOCK_TYPES:
            # Wireshark lists Custom Blocks (e.g. CANoe pcaplog XML metadata) as frames without packet data
            number += 1
        offset += block_length


def _timestamp_divisor(idb_body: bytes, endian: str) -> float:
    """Reads the if_tsresol option of an Interface Description Block (default: microseconds)."""
    offset = 8
    while offset + 4 <= len(idb_body):
        code, length = struct.unpack_from(endian + "HH", idb_body, offset)
        if code == 0:
            break
        if code == 9 and length >= 1:
            resolution = idb_body[offset + 4]
            return float(2 ** (resolution & 0x7F)) if resolution & 0x80 else float(10 ** resolution)
        offset += 4 + ((length + 3) & ~3)
    return 1e6


def _read_pcap(data: bytes) -> Iterator[Packet]:
    endian, divisor = PCAP_MAGICS[data[:4]]
    link_type = struct.unpack_from(endian + "I", data, 20)[0]
    offset = 24
    number = 0
    while offset + 16 <= len(data):
        ts_seconds, ts_fraction, captured_length, _original_length = struct.unpack_from(endian + "IIII", data, offset)
        offset += 16
        if offset + captured_length > len(data):
            raise CaptureFormatError(f"Truncated pcap record at byte {offset}.")
        number += 1
        yield Packet(number, ts_seconds + ts_fraction / divisor, link_type, data[offset:offset + captured_length])
        offset += captured_length


def _network_layer(packet: Packet) -> Optional[Tuple[int, bytes]]:
    """Returns (EtherType, network-layer bytes) of Ethernet (with VLAN tags), raw IP and Linux SLL frames."""
    data = packet.data
    if packet.link_type == LINKTYPE_ETHERNET:
        if len(data) < 14:
            return None
        ether_type = struct.unpack_from("!H", data, 12)[0]
        offset = 14
        while ether_type in (0x8100, 0x88A8, 0x9100):  # VLAN tags (e.g. VLAN 1201 on the test bench)
            if len(data) < offset + 4:
                return None
            ether_type = struct.unpack_from("!H", data, offset + 2)[0]
            offset += 4
        return ether_type, data[offset:]
    if packet.link_type in LINKTYPE_RAW:
        version = data[0] >> 4 if data else 0
        return {4: ETHERTYPE_IPV4, 6: ETHERTYPE_IPV6}.get(version, 0), data
    if packet.link_type == LINKTYPE_LINUX_SLL:
        if len(data) < 16:
            return None
        return struct.unpack_from("!H", data, 14)[0], data[16:]
    return None


def ip_addresses(packet: Packet) -> Optional[Tuple[str, str]]:
    """(source, destination) address of IPv4 and IPv6 packets, fragments included; None for other frames."""
    layer = _network_layer(packet)
    if layer is None:
        return None
    ether_type, ip = layer
    if ether_type == ETHERTYPE_IPV4 and len(ip) >= 20 and ip[0] >> 4 == 4:
        return _ip(ip[12:16]), _ip(ip[16:20])
    if ether_type == ETHERTYPE_IPV6 and len(ip) >= 40 and ip[0] >> 4 == 6:
        return str(ipaddress.IPv6Address(ip[8:24])), str(ipaddress.IPv6Address(ip[24:40]))
    return None


def decode_ipv4(packet: Packet) -> Optional[tuple]:
    """Returns (protocol, source IP, destination IP, payload) for IPv4 packets, else None."""
    layer = _network_layer(packet)
    if layer is None or layer[0] != ETHERTYPE_IPV4:
        return None
    ip = layer[1]
    if len(ip) < 20 or ip[0] >> 4 != 4:
        return None
    header_length = (ip[0] & 0x0F) * 4
    total_length = struct.unpack_from("!H", ip, 2)[0]
    flags_fragment = struct.unpack_from("!H", ip, 6)[0]
    if flags_fragment & 0x3FFF:  # fragmented datagrams are not reassembled
        return None
    end = total_length if header_length <= total_length <= len(ip) else len(ip)
    return ip[9], _ip(ip[12:16]), _ip(ip[16:20]), ip[header_length:end]


def decode_udp(packet: Packet) -> Optional[UdpDatagram]:
    decoded = decode_ipv4(packet)
    if decoded is None or decoded[0] != 17 or len(decoded[3]) < 8:
        return None
    _, src, dst, segment = decoded
    src_port, dst_port, length = struct.unpack_from("!HHH", segment, 0)
    end = length if 8 <= length <= len(segment) else len(segment)
    return UdpDatagram(src, dst, src_port, dst_port, segment[8:end])


def decode_icmp_unreachable(packet: Packet) -> Optional[IcmpUnreachable]:
    decoded = decode_ipv4(packet)
    if decoded is None or decoded[0] != 1 or len(decoded[3]) < 2 or decoded[3][0] != 3:
        return None
    return IcmpUnreachable(decoded[1], decoded[2], decoded[3][1])


def _ip(raw: bytes) -> str:
    return ".".join(str(byte) for byte in raw)
