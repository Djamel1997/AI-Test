"""Command-line interface: ``python -m ip_validator <address> [...]``."""

import argparse
import sys
from typing import Iterable, List, Optional

from .validator import validate_ip

EXIT_ALL_VALID = 0
EXIT_SOME_INVALID = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ip_validator",
        description="Validate IPv4 and IPv6 addresses.",
    )
    parser.add_argument(
        "addresses",
        nargs="*",
        help="addresses to validate (read from stdin, one per line, if omitted)",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="suppress validation results and report their status via the exit code",
    )
    return parser


def _escape_non_printable(text: str) -> str:
    return "".join(char if char.isprintable() else ascii(char)[1:-1] for char in text)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    reads_stdin = not args.addresses
    addresses: Iterable[str] = args.addresses
    if reads_stdin:
        addresses = (line.rstrip("\r\n") for line in sys.stdin)

    all_valid = True
    for address in addresses:
        result = validate_ip(address)
        all_valid = all_valid and result.is_valid
        if args.quiet:
            continue
        display_address = _escape_non_printable(result.address)
        if result.is_valid:
            print(f"VALID    IPv{result.version}  {display_address}", flush=reads_stdin)
        else:
            reason = _escape_non_printable(result.reason or "")
            print(f"INVALID        {display_address}  ({reason})", flush=reads_stdin)

    return EXIT_ALL_VALID if all_valid else EXIT_SOME_INVALID


if __name__ == "__main__":
    sys.exit(main())
