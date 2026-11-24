"""Simple IPv4 / IPv6 address validator."""

from .validator import (
    ValidationResult,
    is_valid_ip,
    is_valid_ipv4,
    is_valid_ipv6,
    validate_ip,
)

__all__ = [
    "ValidationResult",
    "is_valid_ip",
    "is_valid_ipv4",
    "is_valid_ipv6",
    "validate_ip",
]
__version__ = "1.0.0"
