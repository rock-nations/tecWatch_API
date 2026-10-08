"""
Packet times and IP addresses of a capture for the I/O graph of the Web GUI (like the Wireshark I/O graph):
the GUI counts the packets per interval (1 ms to 10 min) for all frames and for the selected addresses.
"""
from collections import Counter
from typing import Dict, List, Optional

from src.analyzer.capture import Packet, ip_addresses

MAX_HOSTS = 20  # the busiest addresses; packets of other addresses only count as "all packets"


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
    timed = sorted((p for p in packets if p.timestamp > 0), key=lambda p: p.timestamp)
    if not timed:
        return None
    start = timed[0].timestamp
    addresses = [ip_addresses(packet) for packet in timed]
    sent = Counter(pair[0] for pair in addresses if pair)
    received = Counter(pair[1] for pair in addresses if pair)
    ranked = sorted(set(sent) | set(received), key=lambda address: (-(sent[address] + received[address]), address))
    index = {address: position for position, address in enumerate(ranked[:MAX_HOSTS])}

    return {
        "capture_file": file_name[:256],
        "start_epoch_s": round(start, 6),
        "duration_s": round(timed[-1].timestamp - start, 6),
        "utc_offset_min": utc_offset_min,
        "canoe_zero_epoch_s": round(canoe_zero_epoch_s, 6) if canoe_zero_epoch_s is not None else None,
        "total_packets": len(timed),
        "packet_time_us": [round((packet.timestamp - start) * 1e6) for packet in timed],
        "packet_src": [index.get(pair[0], -1) if pair else -1 for pair in addresses],
        "packet_dst": [index.get(pair[1], -1) if pair else -1 for pair in addresses],
        "other_hosts": max(0, len(ranked) - MAX_HOSTS),
        "hosts": [
            {
                "address": address,
                "role": roles.get(address),
                "packets_sent": sent[address],
                "packets_received": received[address],
            }
            for address in ranked[:MAX_HOSTS]
        ],
    }
