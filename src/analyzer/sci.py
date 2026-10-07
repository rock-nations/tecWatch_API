"""
RaSTA (redundancy + safety layer) and SCI-TDS Baseline 5 decoding.
Ported from the DB Wireshark Lua dissectors (rasta_redundancy_layer.lua, rasta_safety_layer.lua,
sci_common.lua, SCI-TDS_BL5.lua).
"""
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union

RASTA_TYPES = {
    6200: "Connection Request",
    6201: "Connection Response",
    6212: "Retransmission Request",
    6213: "Retransmission Response",
    6216: "Disconnect Request",
    6220: "Heartbeat",
    6240: "Data",
    6241: "Retransmission Data",
}
CONNECTION_REQUEST, CONNECTION_RESPONSE = 6200, 6201
RETRANSMISSION_TYPES = (6212, 6213, 6241)
DISCONNECT_REQUEST, HEARTBEAT, DATA, RETRANSMISSION_DATA = 6216, 6220, 6240, 6241

DISCONNECT_REASONS = {
    0: "User Request",
    1: "Undefined Message Type Received",
    2: "Message Type Not Allowed in Current State",
    3: "Sequence Number Error while Connecting",
    4: "Timeout",
    5: "Service not Allowed in Current State",
    6: "Wrong Protocol Version",
    7: "Retransmission failed, Sequence Number not available",
    8: "Protocol Failure",
}

SCI_PROTOCOLS = {0x01: "ILS", 0x20: "TDS", 0x30: "LS", 0x40: "P", 0x50: "RBC", 0x60: "LX", 0x90: "IO"}

# (name, label) per message type
SCI_COMMON_TYPES = {
    0x0021: ("KOMMANDO_AUFRUESTANFORDERUNG", "Kommando 'Aufrüstanforderung'"),
    0x0022: ("MELDUNG_AUFRUESTBEGINN", "Meldung 'Aufrüstbeginn'"),
    0x0023: ("MELDUNG_AUFRUESTENDE", "Meldung 'Aufrüstende'"),
    0x0024: ("KOMMANDO_BTP_VERSIONSABGLEICH", "Kommando 'BTP_Versionsabgleich'"),
    0x0025: ("MELDUNG_BTP_VERSIONSABGLEICH", "Meldung 'BTP_Versionsabgleich'"),
}
TDS_BL5_TYPES = {
    0x0001: ("KOMMANDO_AZG", "Kommando AZG"),
    0x0002: ("KOMMANDO_ACHSZAEHLFUELLSTAND_AKTUALISIERUNG", "Kommando Achszählfüllstand-Aktualisierung"),
    0x0003: ("KOMMANDO_AZGH", "Kommando AZGH"),
    0x000A: ("KOMMANDO_ZDP_AKTIVIERUNG", "Kommando ZDP-Aktivierung"),
    0x0006: ("MELDUNG_KOMMANDO_ABGEWIESEN", "Meldung Kommando abgewiesen"),
    0x0007: ("MELDUNG_GFMA_BELEGUNGSZUSTAND", "Meldung GFM-A Belegungszustand"),
    0x0009: ("MELDUNG_AZGH_QUITTUNG", "Meldung AZGH-Quittung"),
    0x000B: ("MELDUNG_ZDP_BEFAHRUNGSZUSTAND", "Meldung ZDP-Befahrungszustand"),
}

KOMMANDO_AZG, KOMMANDO_AZGH = 0x0001, 0x0003
MELDUNG_KOMMANDO_ABGEWIESEN, MELDUNG_BELEGUNGSZUSTAND, MELDUNG_AZGH_QUITTUNG = 0x0006, 0x0007, 0x0009
KOMMANDO_VERSION, MELDUNG_VERSION = 0x0024, 0x0025
AUFRUEST_TYPES = (0x0021, 0x0022, 0x0023)

OCCUPANCY = {0: "ungültig", 1: "frei", 2: "belegt", 3: "gestört", 4: "warten Zugfahrt", 5: "warten Quittung"}
RESETTABLE = {0: "nicht grundst.", 1: "grundst.", 2: "ungültig"}
AZG_TYPES = {0: "ungültig", 1: "AZDG", 2: "AZEG", 3: "AZVGQ", 4: "AZVG"}
REJECT_REASONS = {0: "ungültig", 1: "betrieblich", 2: "technisch"}
VERSION_RESULTS = {1: "BTP-Versionswerte nicht gleich", 2: "BTP-Versionswerte gleich"}

SCI_HEADER_LENGTH = 43  # protocol type (1) + message type (2) + sender (20) + receiver (20)


@dataclass
class RastaPdu:
    pdu_type: int
    receiver: int
    sender: int
    seq: int
    confirmed_seq: int
    timestamp: int
    confirmed_timestamp: int
    version: Optional[str] = None
    disconnect_reason: Optional[int] = None
    messages: List[bytes] = field(default_factory=list)

    @property
    def type_name(self) -> str:
        return RASTA_TYPES.get(self.pdu_type, f"Type {self.pdu_type}")


@dataclass
class SciTelegram:
    protocol: str
    message_type: int
    name: str
    label: str
    sender: str
    receiver: str
    length: int
    fields: Dict[str, Union[int, str]]

    @property
    def is_command(self) -> bool:
        return self.name.startswith("KOMMANDO")

    def describe(self) -> str:
        """Short text like the Wireshark info column, e.g. "Meldung GFM-A Belegungszustand(0x0007) [gestört, nicht grundst.]"."""
        text = f"{self.label}(0x{self.message_type:04X})"
        if self.message_type == MELDUNG_BELEGUNGSZUSTAND and self.protocol == "TDS":
            text += f" [{self.fields['belegung_text']}, {self.fields['grundstellbar_text']}]"
        elif self.message_type == KOMMANDO_AZG and self.protocol == "TDS":
            text += f" [{self.fields['grundstellungsart_text']}]"
        elif self.message_type == MELDUNG_KOMMANDO_ABGEWIESEN and self.protocol == "TDS":
            text += f" [{self.fields['abweisungsgrund_text']}]"
        elif self.message_type == MELDUNG_VERSION:
            text += f" [{self.fields['ergebnis_text']}]"
        return text


def _le16(data: bytes, offset: int) -> int:
    return struct.unpack_from("<H", data, offset)[0]


def decode_rasta(payload: bytes) -> Optional[RastaPdu]:
    """Decodes a UDP payload as RaSTA redundancy + safety layer PDU (None if it is not RaSTA)."""
    if len(payload) < 8 + 28 or _le16(payload, 0) != len(payload):
        return None
    safety = payload[8:]
    safety_length = _le16(safety, 0)
    pdu_type = _le16(safety, 2)
    if safety_length < 28 or safety_length > len(safety) or pdu_type not in RASTA_TYPES:
        return None
    receiver, sender, seq, confirmed_seq, timestamp, confirmed_timestamp = struct.unpack_from("<IIIIII", safety, 4)
    pdu = RastaPdu(pdu_type, receiver, sender, seq, confirmed_seq, timestamp, confirmed_timestamp)
    body = safety[28:safety_length]  # type specific data followed by the safety code

    if pdu_type in (CONNECTION_REQUEST, CONNECTION_RESPONSE) and len(body) >= 4:
        pdu.version = body[:4].decode("ascii", "replace")
    elif pdu_type == DISCONNECT_REQUEST and len(body) >= 4:
        pdu.disconnect_reason = _le16(body, 2)
    elif pdu_type in (DATA, RETRANSMISSION_DATA):
        pdu.messages = _split_application_data(body)
    return pdu


def _split_application_data(body: bytes) -> List[bytes]:
    """Splits length-prefixed application packets; tries the safety code lengths 8, 16 and 0 bytes."""
    for code_length in (8, 16, 0):
        data = body[:len(body) - code_length] if code_length else body
        messages, offset = [], 0
        while offset + 2 <= len(data):
            length = _le16(data, offset)
            if length == 0 or offset + 2 + length > len(data):
                break
            messages.append(data[offset + 2:offset + 2 + length])
            offset += 2 + length
        if messages and offset == len(data):
            return messages
    return []


def _identifier(raw: bytes) -> str:
    """Technical identifiers are 20 bytes, padded with '_' (0x5F) or NUL."""
    return raw.decode("latin-1").rstrip("_\x00 ").strip()


def decode_sci(message: bytes) -> Optional[SciTelegram]:
    """Decodes one SCI application packet (SCI-TDS uses the Baseline 5 coding of the real OC)."""
    if len(message) < SCI_HEADER_LENGTH or message[0] not in SCI_PROTOCOLS:
        return None
    protocol = SCI_PROTOCOLS[message[0]]
    message_type = _le16(message, 1)
    types = dict(SCI_COMMON_TYPES)
    if protocol == "TDS":
        types.update(TDS_BL5_TYPES)
    name, label = types.get(message_type, (f"UNKNOWN_0x{message_type:04X}", f"Unbekannte Nachricht 0x{message_type:04X}"))
    payload = message[SCI_HEADER_LENGTH:]
    fields: Dict[str, Union[int, str]] = {}

    if message_type == KOMMANDO_VERSION and len(payload) >= 1:
        fields["btp_version"] = payload[0]
    elif message_type == MELDUNG_VERSION and len(payload) >= 2:
        fields["ergebnis"] = payload[0]
        fields["ergebnis_text"] = VERSION_RESULTS.get(payload[0], "ungültig")
        fields["btp_version"] = payload[1]
    elif protocol == "TDS" and message_type == MELDUNG_BELEGUNGSZUSTAND and len(payload) >= 4:
        fields["belegung"] = payload[0]
        fields["belegung_text"] = OCCUPANCY.get(payload[0], "ungültig")
        fields["grundstellbar"] = payload[1]
        fields["grundstellbar_text"] = RESETTABLE.get(payload[1], "ungültig")
        fields["achszaehlfuellstand"] = _le16(payload, 2)
    elif protocol == "TDS" and message_type == KOMMANDO_AZG and len(payload) >= 1:
        fields["grundstellungsart"] = payload[0]
        fields["grundstellungsart_text"] = AZG_TYPES.get(payload[0], "ungültig")
    elif protocol == "TDS" and message_type == MELDUNG_KOMMANDO_ABGEWIESEN and len(payload) >= 1:
        fields["abweisungsgrund"] = payload[0]
        fields["abweisungsgrund_text"] = REJECT_REASONS.get(payload[0], "ungültig")

    return SciTelegram(
        protocol=protocol,
        message_type=message_type,
        name=name,
        label=label,
        sender=_identifier(message[3:23]),
        receiver=_identifier(message[23:43]),
        length=len(message),
        fields=fields,
    )
