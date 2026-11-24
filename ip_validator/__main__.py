"""Command-line interface: ``python -m ip_validator <address> [...]``."""

import argparse
import os
import sys
from typing import Iterable, List, Optional

from .validator import validate_ip

EXIT_ALL_VALID = 0
EXIT_SOME_INVALID = 1
# Conventional shell status for a process stopped by SIGPIPE (128 + 13).
EXIT_BROKEN_PIPE = 141


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


def _discard_stdout() -> None:
    """Redirect the stdout file descriptor to the null device.

    After a ``BrokenPipeError``, Python would try to flush the remaining
    buffered output again at shutdown and print an "Exception ignored"
    message. Pointing the descriptor at ``os.devnull`` prevents that.
    """
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
    except OSError:
        return
    try:
        os.dup2(devnull, sys.stdout.fileno())
    except (OSError, ValueError):
        # stdout has no usable file descriptor (e.g. replaced by a StringIO).
        pass
    finally:
        os.close(devnull)


def _strip_line_separator(line: str) -> str:
    r"""Remove exactly one trailing LF or CRLF line separator.

    Unlike ``str.rstrip("\r\n")``, extra carriage returns (``"::1\r\r\n"``)
    or a lone trailing ``"\r"`` are kept so that validation rejects them.
    """
    if line.endswith("\r\n"):
        return line[:-2]
    if line.endswith("\n"):
        return line[:-1]
    return line


def _disable_newline_translation(stream: object) -> None:
    r"""Make a text stream split lines on LF only and keep CR characters.

    On Windows, ``sys.stdin`` uses universal newlines: ``"\r\n"`` and a lone
    ``"\r"`` are translated to ``"\n"``, so ``"::1\r\r\n"`` would become two
    lines and stray carriage returns would never reach validation. Switching
    to ``newline="\n"`` gives the POSIX behaviour on every platform; CRLF
    separators are then removed by ``_strip_line_separator``.

    Streams without ``reconfigure`` (e.g. ``io.StringIO`` in tests) or that
    cannot be reconfigured (data already read) are left unchanged.
    """
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(newline="\n")
    except (ValueError, OSError):
        pass


def _parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    try:
        return build_parser().parse_args(argv)
    except SystemExit:
        # ``--help`` writes to buffered stdout before exiting. Flush here so a
        # closed pipe is reported inside ``main`` rather than during
        # interpreter shutdown.
        sys.stdout.flush()
        raise


def main(argv: Optional[List[str]] = None) -> int:
    try:
        args = _parse_args(argv)
        return _validate_all(args.addresses, args.quiet)
    except BrokenPipeError:
        # The reader closed the pipe early (e.g. ``| head -n 1``): stop quietly.
        _discard_stdout()
        return EXIT_BROKEN_PIPE


def _validate_all(cli_addresses: List[str], quiet: bool) -> int:
    reads_stdin = not cli_addresses
    addresses: Iterable[str] = cli_addresses
    if reads_stdin:
        _disable_newline_translation(sys.stdin)
        addresses =(_strip_line_separator(line) for line in sys.stdin)

    all_valid = True
    for address in addresses:
        result = validate_ip(address)
        all_valid = all_valid and result.is_valid
        if quiet:
            continue
        display_address = _escape_non_printable(result.address)
        if result.is_valid:
            print(f"VALID    IPv{result.version}  {display_address}", flush=reads_stdin)
        else:
            reason = _escape_non_printable(result.reason or "")
            print(f"INVALID        {display_address}  ({reason})", flush=reads_stdin)

    # Flush here so a closed pipe is reported inside ``main`` rather than
    # during interpreter shutdown.
    sys.stdout.flush()
    return EXIT_ALL_VALID if all_valid else EXIT_SOME_INVALID


if __name__ == "__main__":
    sys.exit(main())
