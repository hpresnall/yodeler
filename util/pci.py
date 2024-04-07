"""Utilities for handling PCI addresses."""
import re

# like 00:00.0
_VALID_PCI_ADDRESS = re.compile("^([0-9A-F]{2,4}):([0-9A-F]{2})\\.([09-A-F])$")


def split(address: str, location: str) -> tuple[int, int, int]:
    """Split the given PCI address into bus, slot and function as integers.
    Assumes PCI address in a form like '00:00.0' where each part is a hex digit."""
    match = _VALID_PCI_ADDRESS.match(address.upper())
    if not match:
        raise ValueError(
            f"invalid PCI address '{address}' for {location}; it must match '{_VALID_PCI_ADDRESS.pattern}'")

    # split PCI address into bus, slot & function; convert address components to int
    return (int(match.group(1), 16), int(match.group(2), 16), int(match.group(3), 16))
