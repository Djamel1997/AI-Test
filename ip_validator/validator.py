"""Core IPv4 / IPv6 validation logic.

Validation relies on the standard library ``ipaddress`` module, with a few
extra strictness rules on top of it:

* only ``str`` inputs are accepted (``ipaddress`` would also accept integers
  and bytes, which is not what a textual validator should do);
* leading/trailing whitespace is rejected;
* IPv4 octets with leading zeros (e.g. ``192.168.01.1``) are rejected both
  in standalone IPv4 addresses and in dotted IPv6 suffixes;
* IPv6 zone IDs containing control or other non-printable characters
  (e.g. ``fe80::1%eth0\n``) are rejected.
"""

import ipaddress
from dataclasses import dataclass
from typing import Optional

__all__ = [
    "ValidationResult",
    "is_valid_ipv4",
    "is_valid_ipv6",
    "is_valid_ip",
    "validate_ip",
]

_LEADING_ZERO_ERROR = "IPv4 octets must not have leading zeros"
_ZONE_ID_CHARACTER_ERROR = "IPv6 zone ID must not contain control or non-printable characters"


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of validating a single address string."""

    address: str
    is_valid: bool
    version: Optional[int] = None
    reason: Optional[str] = None


def _check_input(address: str) -> Optional[str]:
    """Return an error message if ``address`` is not a usable string."""
    if not address:
        return "address is empty"
    if address != address.strip():
        return "address contains leading or trailing whitespace"
    return None


def _has_leading_zero_octet(address: str) -> bool:
    return any(
        len(octet) > 1 and octet.isdigit() and octet.startswith("0")
        for octet in address.split(".")
    )


def _ipv4_error(address: str) -> Optional[str]:
    # Checked before ``ipaddress`` so the behaviour and message are identical
    # across Python versions (older 3.9.x releases accepted leading zeros).
    if _has_leading_zero_octet(address):
        return _LEADING_ZERO_ERROR
    try:
        ipaddress.IPv4Address(address)
    except ipaddress.AddressValueError as exc:
        return str(exc)
    return None


def _ipv6_error(address: str) -> Optional[str]:
    # A zone ID can contain dots and is separate from the address suffix.
    literal, _, zone_id = address.partition("%")
    # ``ipaddress`` accepts any character in a zone ID, including control
    # characters such as NUL, tab or newline. Interior spaces stay allowed.
    if not zone_id.isprintable():
        return _ZONE_ID_CHARACTER_ERROR
    _, separator, suffix = literal.rpartition(":")
    if separator and "." in suffix and _has_leading_zero_octet(suffix):
        return _LEADING_ZERO_ERROR
    try:
        ipaddress.IPv6Address(address)
    except ipaddress.AddressValueError as exc:
        return str(exc)
    return None


def is_valid_ipv4(address: object) -> bool:
    """Return ``True`` if ``address`` is a valid dotted-decimal IPv4 address."""
    return (
        isinstance(address, str)
        and _check_input(address) is None
        and _ipv4_error(address) is None
    )


def is_valid_ipv6(address: object) -> bool:
    """Return ``True`` if ``address`` is a valid IPv6 address.

    Compressed forms (``::1``), embedded IPv4 (``::ffff:1.2.3.4``) and scope
    IDs (``fe80::1%eth0``) are accepted. Zone IDs follow ``ipaddress`` syntax,
    must not contain control or non-printable characters, and are
    interpreted as opaque strings.
    """
    return (
        isinstance(address, str)
        and _check_input(address) is None
        and _ipv6_error(address) is None
    )


def is_valid_ip(address: object) -> bool:
    """Return ``True`` if ``address`` is a valid IPv4 or IPv6 address."""
    return validate_ip(address).is_valid


def validate_ip(address: object) -> ValidationResult:
    """Validate ``address`` and report its IP version or the failure reason."""
    if not isinstance(address, str):
        display_address = "None" if address is None else "<non-string input>"
        return ValidationResult(display_address, False, reason="address must be a string")

    input_error = _check_input(address)
    if input_error:
        return ValidationResult(address, False, reason=input_error)

    if ":" in address:
        error = _ipv6_error(address)
        return ValidationResult(address, error is None, 6 if error is None else None, error)

    error = _ipv4_error(address)
    return ValidationResult(address, error is None, 4 if error is None else None, error)
