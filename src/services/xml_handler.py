import xml.etree.ElementTree as ET
from typing import Any, Dict
import defusedxml.ElementTree as DefusedET
from defusedxml.common import DefusedXmlException


class XMLParseError(ValueError):
    """Raised when XML parsing fails due to syntax error or security restriction."""
    pass


def parse_xml_to_dict(xml_bytes: bytes) -> Dict[str, Any]:
    """
    Safely parse XML bytes into a nested dictionary structure.
    Uses defusedxml to guard against XML vulnerabilities (XXE, entity bombs).
    """
    try:
        root = DefusedET.fromstring(xml_bytes)
    except (DefusedXmlException, ET.ParseError) as e:
        raise XMLParseError(f"Invalid XML syntax or entity error: {str(e)}") from e

    return {root.tag: _element_to_dict(root)}


def _element_to_dict(element: ET.Element) -> Any:
    # If element has children
    children = list(element)
    if not children:
        text = element.text
        return text.strip() if text is not None else ""

    result: Dict[str, Any] = {}
    for child in children:
        child_val = _element_to_dict(child)
        if child.tag in result:
            # Handle multiple tags with same name as list
            if isinstance(result[child.tag], list):
                result[child.tag].append(child_val)
            else:
                result[child.tag] = [result[child.tag], child_val]
        else:
            result[child.tag] = child_val
    return result


def dict_to_xml_str(root_tag: str, data: Dict[str, Any]) -> str:
    """Serialize a dictionary into a clean XML string."""
    root = ET.Element(root_tag)
    _dict_to_element(root, data)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")


def _dict_to_element(parent: ET.Element, data: Any) -> None:
    if isinstance(data, dict):
        for key, val in data.items():
            if isinstance(val, list):
                for item in val:
                    sub_elem = ET.SubElement(parent, key)
                    _dict_to_element(sub_elem, item)
            else:
                sub_elem = ET.SubElement(parent, key)
                _dict_to_element(sub_elem, val)
    elif isinstance(data, bool):
        parent.text = str(data).lower()
    elif data is not None:
        parent.text = str(data)
