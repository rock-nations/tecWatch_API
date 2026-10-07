"""
Builders for small synthetic SCI-TDS captures (pcapng with RaSTA/SCI telegrams) and CANoe report text,
so the analyzer can be tested without the real test-bench files.
"""
import socket
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

ZE_IP, OC_IP = "1.208.188.16", "10.129.15.2"
ZE_ID, OC_ID, SECTION = "DETHMM ZE 35##0001", "DETHMM AZA34##0001", "34W1"
CANOE_OFFSET_S = 3.5  # CANoe measurement time = capture time + 3.5 s
CAPTURE_START = datetime(2026, 10, 2, 10, 24, 0, tzinfo=timezone.utc).timestamp()  # 12:24:00 local time (+02:00)
FREI, BELEGT, GESTOERT = 1, 2, 3

# Real test-bench files; tests that need them are skipped when they are not available
SAMPLE_DIR = Path(__file__).resolve().parents[2] / "TDS_Task" / "TDS_Task"
REAL_CAPTURE = SAMPLE_DIR / "RealOCWorking_TDS_21026.pcapng"
REAL_REPORT = SAMPLE_DIR / "Real_SCI-TDS_2026-10-02_12-24-11.pdf"


# --- pcapng -----------------------------------------------------------------------------------------

def _block(block_type: int, body: bytes) -> bytes:
    body += b"\x00" * (-len(body) % 4)
    length = 12 + len(body)
    return struct.pack("<II", block_type, length) + body + struct.pack("<I", length)


def pcapng(packets: Iterable[Tuple[float, bytes]], custom_block: Optional[bytes] = None) -> bytes:
    """pcapng with one Ethernet interface (µs timestamps); an optional Custom Block precedes the packets."""
    data = _block(0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1))
    data += _block(0x00000001, struct.pack("<HHI", 1, 0, 0))
    if custom_block is not None:
        data += _block(0x00000BAD, struct.pack("<I", 46254) + custom_block)
    for timestamp, frame in packets:
        micros = int(round(timestamp * 1e6))
        data += _block(0x00000006, struct.pack("<IIIII", 0, micros >> 32, micros & 0xFFFFFFFF, len(frame), len(frame)) + frame)
    return data


def pcap(packets: Iterable[Tuple[float, bytes]]) -> bytes:
    """Classic little-endian pcap with microsecond timestamps."""
    data = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    for timestamp, frame in packets:
        seconds = int(timestamp)
        data += struct.pack("<IIII", seconds, int(round((timestamp - seconds) * 1e6)), len(frame), len(frame)) + frame
    return data


def udp_frame(src: str, dst: str, payload: bytes, port: int = 24001, vlan: Optional[int] = 1201,
              flags_fragment: int = 0x4000) -> bytes:
    udp = struct.pack("!HHHH", port, port, 8 + len(payload), 0) + payload
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(udp), 0, flags_fragment, 64, 17, 0,
                     socket.inet_aton(src), socket.inet_aton(dst)) + udp
    ethernet = b"\x02\x00\x00\x00\x00\x01" + b"\x02\x00\x00\x00\x00\x02"
    if vlan is not None:
        ethernet += struct.pack("!HH", 0x8100, vlan)
    return ethernet + struct.pack("!H", 0x0800) + ip


def ipv6_udp_frame(src: str, dst: str, payload: bytes) -> bytes:
    udp = struct.pack("!HHHH", 5000, 5000, 8 + len(payload), 0) + payload
    ip = struct.pack("!IHBB", 6 << 28, len(udp), 17, 64) + socket.inet_pton(socket.AF_INET6, src) \
        + socket.inet_pton(socket.AF_INET6, dst) + udp
    return b"\x02" * 6 + b"\x04" * 6 + struct.pack("!H", 0x86DD) + ip


def arp_frame() -> bytes:
    return b"\xff" * 6 + b"\x02" * 6 + struct.pack("!H", 0x0806) + b"\x00" * 28


def icmp_port_unreachable(src: str, dst: str) -> bytes:
    icmp = bytes([3, 3, 0, 0]) + b"\x00" * 4
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(icmp), 0, 0, 64, 1, 0,
                     socket.inet_aton(src), socket.inet_aton(dst)) + icmp
    return b"\x02" * 6 + b"\x04" * 6 + struct.pack("!H", 0x0800) + ip


# --- RaSTA / SCI ------------------------------------------------------------------------------------

def rasta(pdu_type: int, seq: int, timestamp: int, body: bytes = b"", messages: Sequence[bytes] = ()) -> bytes:
    """RaSTA redundancy layer + safety layer PDU with an 8-byte safety code."""
    if messages:
        body = b"".join(struct.pack("<H", len(m)) + m for m in messages)
    safety = struct.pack("<HHIIIIII", 0, pdu_type, 0x61, 0x62, seq, 0, timestamp & 0xFFFFFFFF, 0) + body + b"\x00" * 8
    safety = struct.pack("<H", len(safety)) + safety[2:]
    return struct.pack("<HHI", 8 + len(safety), 0, seq) + safety


def sci(message_type: int, sender: str, receiver: str, payload: bytes = b"", protocol: int = 0x20) -> bytes:
    def identifier(text: str) -> bytes:
        return text.encode("latin-1").ljust(20, b"_")

    return bytes([protocol]) + struct.pack("<H", message_type) + identifier(sender) + identifier(receiver) + payload


def gfma_state(occupancy: int, resettable: int, axle_count: int) -> bytes:
    return sci(0x0007, SECTION, ZE_ID, bytes([occupancy, resettable]) + struct.pack("<H", axle_count))


def azgh() -> bytes:
    return sci(0x0003, ZE_ID, SECTION)


class CaptureBuilder:
    """Collects the RaSTA traffic of ESTW-ZE (CANoe) and OC with consistent sequence numbers and timestamps."""

    def __init__(self, offset_s: float = CANOE_OFFSET_S):
        self.offset_s = offset_s
        self.packets: List[Tuple[float, bytes]] = []
        self.seq = {"ze": 0, "oc": 0}

    def pdu(self, t: float, side: str, pdu_type: int, body: bytes = b"", messages: Sequence[bytes] = (),
            seq: Optional[int] = None) -> None:
        if seq is None:
            seq = self.seq[side]
            self.seq[side] += 1
        # CANoe (the ZE) stamps its PDUs with the measurement time in µs; the OC uses its own clock
        timestamp = int(round((t + self.offset_s) * 1e6)) if side == "ze" else int(t * 1000) + 777
        src, dst = (ZE_IP, OC_IP) if side == "ze" else (OC_IP, ZE_IP)
        self.packets.append((t, udp_frame(src, dst, rasta(pdu_type, seq, timestamp, body, messages))))

    def session(self, start: float, end: float, events: Sequence[Tuple[float, str, Sequence[bytes]]],
                initial_state: Tuple[int, int, int] = (FREI, 0, 0), disconnect_reason: int = 0) -> None:
        """Connection setup, BTP version check, Aufrüstung, heartbeats every 0.3 s, data events, disconnect."""
        self.seq = {"ze": 100, "oc": 500}
        self.pdu(start, "ze", 6200, b"0303" + b"\x00" * 10)
        self.pdu(start + 0.1, "oc", 6201, b"0303" + b"\x00" * 10)
        self.pdu(start + 0.2, "ze", 6240, messages=[sci(0x0024, ZE_ID, OC_ID, b"\x01", protocol=0x20)])
        self.pdu(start + 0.3, "oc", 6240, messages=[sci(0x0025, OC_ID, ZE_ID, b"\x02\x01", protocol=0x20)])
        self.pdu(start + 0.4, "oc", 6240, messages=[sci(0x0022, OC_ID, ZE_ID), gfma_state(*initial_state),
                                                     sci(0x0023, OC_ID, ZE_ID)])
        timeline = [(t, side, 6240, list(messages)) for t, side, messages in events]
        t = start + 0.5
        while t < end:
            timeline.append((round(t, 3), "ze", 6220, []))
            timeline.append((round(t + 0.01, 3), "oc", 6220, []))
            t += 0.3
        for t, side, pdu_type, messages in sorted(timeline, key=lambda item: item[0]):
            self.pdu(t, side, pdu_type, messages=messages)
        self.pdu(end, "ze", 6216, struct.pack("<HH", 0, disconnect_reason))
        self.pdu(end + 0.01, "oc", 6220)  # heartbeat still in flight after the disconnect

    def build(self, custom_block: Optional[bytes] = None) -> bytes:
        packets = sorted(self.packets, key=lambda packet: packet[0])
        return pcapng([(CAPTURE_START + t, frame) for t, frame in packets], custom_block)


def disturbed_capture(custom_block: Optional[bytes] = None) -> bytes:
    """
    One session (capture time 0-20 s): GFM-A occupied with axle count 0x0000 at 5.0 s, 'gestört' 100 ms later,
    an AZGH at 8.0 s while not 'grundstellbar' gets no reaction.
    """
    builder = CaptureBuilder()
    builder.session(0.0, 20.0, [
        (5.0, "oc", [gfma_state(BELEGT, 0, 0x0000)]),
        (5.1, "oc", [gfma_state(GESTOERT, 0, 0x0000)]),
        (8.0, "ze", [azgh()]),
    ])
    return builder.build(custom_block)


# --- CANoe report text (pypdf layout mode lists the lines of every page bottom-up) -----------------

def report_pages() -> List[List[str]]:
    """Report of 3 test cases matching disturbed_capture() (CANoe time = capture time + 3.5 s)."""
    overview = [
        "10/02/2026 12:32:11 PM +02:00",
        "Test Unit End:    10/02/2026 12:24:31 PM +02:00",
        "Test Unit Begin:  10/02/2026 12:24:11 PM +02:00",
        "                                   SCI-TDS      [1 .. 3]                                      Fail",
        " Computer Name:        BENCH-01",
        " Test Configuration:   TDS-Test",
        "                       \\ZE_RealOC_Stimulation.cfg",
        " Version:              CANoe.CAN.Ethernet.BasicEthernet 20.0.195 /pro",
        "Measurement stop forced. Test is incomplete!",
        "                                   TDS-Test      [1 .. 3]                                     Fail",
    ]
    test_cases = [
        "      26.000000         3. TC_NPRO.295.00522.01(O-ReZE)                                       Inconclusive",
        "       6.000000         2. TC_NPRO.295.00525.01(F-ReZE)                                       Fail",
        "       3.700000         1. TC_NPRO.295.02283.01(O)                                            Pass",
        "  Time Stamp         Title                                                                    Verdict",
    ]
    test_case_1 = [
        "       4.500000            1        Sende 'KommandoAchszaehlgrundstellungHilfsbedienung'",
        "       4.600000            2        AZG/AZGH-Antwort geprueft: 0 erwartete Belegungsmeldungen.       Pass",
    ]
    test_case_2 = [
        "      24.000000                        Test aborted due to BreakOnFail behavior.",
        "                                       Grundstellungsfaehigkeit=0.",
        "      24.000000            Init        Zeitlimit 15000 ms fuer manuelle Vorbereitung abgelaufen: Belegungszustand=3,      Fail",
        "     GFM-A manuell vorbereiten; bei Bedarf vorbereitende AZGH                                     Fail",
        "      25.000000         Cleanup        Sende 'KommandoAchszaehlgrundstellungHilfsbedienung'",
        "      25.500000         Cleanup        Cleanup-Ziel nach 500 ms nicht erreicht (frei erforderlich=0): Zustand=3, Grundstellbarkeit=0.   Fail",
        "     Cleanup: GFM-A 0 frei und nicht grundstellbar herstellen                                     Fail",
    ]
    test_case_3 = [
        "      27.500000                  Measurement stop forced.    Test is incomplete!                    Inconclusive",
        "      26.800000                  Test execution aborted due to stop of the test unit. Test is incomplete!   Inconclusive",
        "     40 s Wartezeit vor dem BTP-Verbindungsaufbau                                                   Inconclusive",
    ]
    return [overview, test_cases, test_case_1, test_case_2, test_case_3]
