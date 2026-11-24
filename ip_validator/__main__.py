"""Command-line interface: ``python -m ip_validator <address> [...]``."""

import argparse
import errno
import os
import stat
import sys
from contextlib import contextmanager
from typing import Iterator, Iterable, List, Optional

from .validator import validate_ip

EXIT_ALL_VALID = 0
EXIT_SOME_INVALID = 1
# Conventional shell status for a process stopped by SIGPIPE (128 + 13).
EXIT_BROKEN_PIPE = 141

_WINDOWS = os.name == "nt"


def _is_pipe(stream: object) -> bool:
    """Return True if ``stream`` is backed by a pipe file descriptor."""
    try:
        return stat.S_ISFIFO(os.fstat(stream.fileno()).st_mode)  # type: ignore[attr-defined]
    except (AttributeError, OSError, ValueError):
        return False


# NtQueryInformationFile(FilePipeLocalInformation) constants (ntifs.h).
_FILE_PIPE_LOCAL_INFORMATION_CLASS = 24
_FILE_PIPE_CLOSING_STATE = 4


def _pipe_reader_closed(stream: object) -> bool:
    """Return True only if Windows confirms the other end of the pipe closed.

    Queries the pipe state of ``stream``'s handle with
    ``NtQueryInformationFile(FilePipeLocalInformation)``: ``NamedPipeState``
    is ``FILE_PIPE_CLOSING_STATE`` once the other end (the reader of a
    stdout/stderr pipe) has been closed. This is a read-only query: nothing
    is written, no data is consumed and it does not wait for the reader.
    Any failure (not Windows, no ``ctypes``/``msvcrt``, no file descriptor,
    query refused) returns False, so the closure is never assumed.
    """
    if not _WINDOWS:
        return False
    try:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        handle = msvcrt.get_osfhandle(stream.fileno())  # type: ignore[attr-defined]

        class _IoStatusBlock(ctypes.Structure):
            _fields_ = [("Status", ctypes.c_void_p), ("Information", ctypes.c_size_t)]

        class _FilePipeLocalInformation(ctypes.Structure):
            _fields_ = [
                (name, wintypes.ULONG)
                for name in (
                    "NamedPipeType",
                    "NamedPipeConfiguration",
                    "MaximumInstances",
                    "CurrentInstances",
                    "InboundQuota",
                    "ReadDataAvailable",
                    "OutboundQuota",
                    "WriteQuotaAvailable",
                    "NamedPipeState",
                    "NamedPipeEnd",
                )
            ]

        query = ctypes.WinDLL("ntdll").NtQueryInformationFile  # type: ignore[attr-defined]
        query.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_IoStatusBlock),
            ctypes.c_void_p,
            wintypes.ULONG,
            ctypes.c_int,
        ]
        query.restype = ctypes.c_long  # NTSTATUS
        status_block = _IoStatusBlock()
        info = _FilePipeLocalInformation()
        status = query(
            handle,
            ctypes.byref(status_block),
            ctypes.byref(info),
            ctypes.sizeof(info),
            _FILE_PIPE_LOCAL_INFORMATION_CLASS,
        )
    except Exception:  # ImportError, OSError, ValueError, AttributeError...
        return False
    return status == 0 and info.NamedPipeState == _FILE_PIPE_CLOSING_STATE


def _as_broken_pipe(exc: OSError, stream: object) -> OSError:
    """Map Windows' closed-pipe ``EINVAL`` to ``BrokenPipeError``.

    On Windows, writing to a pipe whose reader has gone away fails with
    ``OSError(EINVAL)`` instead of ``BrokenPipeError`` (the standard library
    handles the same case in ``subprocess.Popen._stdin_write``, bpo-19612 and
    bpo-30418). ``EINVAL`` alone does not prove the reader is gone, so the
    error is translated only when the closure is confirmed: Windows, errno
    ``EINVAL``, ``stream`` is a pipe and ``_pipe_reader_closed`` confirms
    the closing state. Otherwise the original error is returned unchanged.
    """
    if (
        _WINDOWS
        and not isinstance(exc, BrokenPipeError)
        and exc.errno == errno.EINVAL
        and _is_pipe(stream)
        and _pipe_reader_closed(stream)
    ):
        error = BrokenPipeError(errno.EPIPE, exc.strerror)
        error.__cause__ = exc
        return error
    return exc


@contextmanager
def _stdout_pipe_errors() -> Iterator[None]:
    """Raise ``BrokenPipeError`` for a closed stdout pipe on every platform."""
    try:
        yield
    except OSError as exc:
        translated = _as_broken_pipe(exc, sys.stdout)
        if translated is exc:
            raise
        raise translated from exc


class _BrokenPipeRecorder:
    """Proxy for an output stream that remembers a ``BrokenPipeError``.

    A closed-pipe ``EINVAL`` on Windows is raised as ``BrokenPipeError``
    (see ``_as_broken_pipe``) so every platform reports the same error.
    """

    def __init__(self, stream: object) -> None:
        self._stream = stream
        self.error: Optional[BrokenPipeError] = None

    def write(self, text: str) -> object:
        try:
            return self._stream.write(text)  # type: ignore[attr-defined]
        except BrokenPipeError as exc:
            self.error = exc
            raise
        except OSError as exc:
            translated = _as_broken_pipe(exc, self._stream)
            if translated is exc:
                raise
            self.error = translated  # type: ignore[assignment]
            raise translated from exc

    def __getattr__(self, name: str) -> object:
        return getattr(self._stream, name)


class _ArgumentParser(argparse.ArgumentParser):
    """Parser that lets ``BrokenPipeError`` from help/usage output propagate.

    Since Python 3.11, ``ArgumentParser._print_message`` silently ignores
    ``OSError`` (including ``BrokenPipeError``) raised while writing, so
    ``--help`` into a closed pipe ended with ``SystemExit(0)`` instead of
    reaching the broken-pipe handler in ``main``. Only ``BrokenPipeError``
    raised while writing to ``sys.stdout`` (help output) is re-raised after
    argparse returns. Messages for other streams, such as usage errors on
    ``sys.stderr``, keep the standard library behaviour (ignored on 3.11+,
    propagated on 3.9); on Windows their closed-pipe ``EINVAL`` is first
    reported as ``BrokenPipeError`` so the result matches POSIX. Every other
    error is left unchanged.
    """

    def _print_message(self, message: str, file: Optional[object] = None) -> None:
        if file is None:
            file = sys.stderr
        if file is None:
            super()._print_message(message, file)
            return
        recorder = _BrokenPipeRecorder(file)
        super()._print_message(message, recorder)  # type: ignore[arg-type]
        if file is sys.stdout and recorder.error is not None:
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
        with _stdout_pipe_errors():
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
            line = f"VALID    IPv{result.version}  {display_address}"
        else:
            reason = _escape_non_printable(result.reason or "")
            line = f"INVALID        {display_address}  ({reason})"
        with _stdout_pipe_errors():
            print(line, flush=reads_stdin)

    # Flush here so a closed pipe is reported inside ``main`` rather than
    # during interpreter shutdown.
    with _stdout_pipe_errors():
        sys.stdout.flush()
    return EXIT_ALL_VALID if all_valid else EXIT_SOME_INVALID


if __name__ == "__main__":
    sys.exit(main())
