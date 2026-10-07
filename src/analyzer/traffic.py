"""
Packets per interval over a capture, like Wireshark's I/O graph: all frames plus the packets every
IP address sent (ip.src) and received (ip.dst), so the Web GUI can draw one line per selected address.
"""
import math
from collections import Counter
from typing import Dict, List, Optional

from src.analyzer.capture import Packet, ip_addresses

INTERVAL_STEPS_S = (1, 2, 5, 10, 30, 60, 120, 300, 600, 1800, 3600)
MAX_INTERVALS = 3600  # 1 s resolution for captures up to one hour
MAX_HOSTS = 20  # the busiest addresses; the others are only counted in all_packets


def interval_for(duration_s: float) -> float:
    """Smallest interval step that keeps the graph within MAX_INTERVALS points."""
    step = next((s for s in INTERVAL_STEPS_S if duration_s / s < MAX_INTERVALS), None)
    return float(step if step is not None else math.ceil(duration_s / MAX_INTERVALS))


def build_io_graph(
    file_name: str,
    packets: List[Packet],
    roles: Dict[str, str],
    canoe_zero_epoch_s: Optional[float],
    utc_offset_min: Optional[int],
) -> Optional[dict]:
    """
    roles names known addresses (e.g. the ESTW-ZE); canoe_zero_epoch_s is the Unix time of CANoe
    measurement time 0 and utc_offset_min the UTC offset of the test bench, both None if unknown.
    """
    timed = [p for p in packets if p.timestamp > 0]
    if not timed:
        return None
    start = min(p.timestamp for p in timed)
    duration = max(p.timestamp for p in timed) - start
    interval = interval_for(duration)
    count = int(duration // interval) + 1

    all_packets = [0] * count
    sent: Dict[str, Counter] = {}
    received: Dict[str, Counter] = {}
    for packet in timed:
        index = int((packet.timestamp - start) // interval)
        all_packets[index] += 1
        addresses = ip_addresses(packet)
        if addresses:
            source, destination = addresses
            sent.setdefault(source, Counter())[index] += 1
            received.setdefault(destination, Counter())[index] += 1

    def total(counts: Optional[Counter]) -> int:
        return sum(counts.values()) if counts else 0

    def per_interval(counts: Optional[Counter]) -> List[int]:
        values = [0] * count
        for index, packets_in_interval in (counts or {}).items():
            values[index] = packets_in_interval
        return values

    ranked = sorted(set(sent) | set(received),
                    key=lambda address: (-(total(sent.get(address)) + total(received.get(address))), address))
    return {
        "capture_file": file_name[:256],
        "start_epoch_s": round(start, 6),
        "interval_s": interval,
        "utc_offset_min": utc_offset_min,
        "canoe_zero_epoch_s": round(canoe_zero_epoch_s, 6) if canoe_zero_epoch_s is not None else None,
        "total_packets": len(timed),
        "all_packets": all_packets,
        "other_hosts": max(0, len(ranked) - MAX_HOSTS),
        "hosts": [
            {
                "address": address,
                "role": roles.get(address),
                "packets_sent": total(sent.get(address)),
                "packets_received": total(received.get(address)),
                "sent": per_interval(sent.get(address)),
                "received": per_interval(received.get(address)),
            }
            for address in ranked[:MAX_HOSTS]
        ],
    }
