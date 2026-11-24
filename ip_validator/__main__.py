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


class _BrokenPipeRecorder:
    """Proxy for an output stream that remembers a ``BrokenPipeError``."""

    def __init__(self, stream: object) -> None:
        self._stream = stream
        self.error: Optional[BrokenPipeError] = None

    def write(self, text: str) -> object:
        try:
            return self._stream.write(text)  # type: ignore[attr-defined]
        except BrokenPipeError as exc:
            self.error = exc
            raise

    def __getattr__(self, name: str) -> object:
        return getattr(self._stream, name)


class _ArgumentParser(argparse.ArgumentParser):
    """Parser that lets ``BrokenPipeError`` from help/usage output propagate.

    Since Python 3.11, ``ArgumentParser._print_message`` silently ignores
    ``OSError`` (including ``BrokenPipeError``) raised while writing, so
    ``--help`` into a closed pipe ended with ``SystemExit(0)`` instead of
    reaching the broken-pipe handler in ``main``. Only ``BrokenPipeError``
    raised while writing to ``sys.stdout`` (help output) is re-raised.
    Messages for other streams, such as usage errors on ``sys.stderr``, and
    every other error keep the standard library behaviour.
    """

    def _print_message(self, message: str, file: Optional[object] = None) -> None:
        if file is None or file is not sys.stdout:
            super()._print_message(message, file)  # type: ignore[arg-type]
            return
        recorder = _BrokenPipeRecorder(file)
        super()._print_message(message, recorder)  # type: ignore[arg-type]
        if recorder.error is not None:
            raise recorder.error


def build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(
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
