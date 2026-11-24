import argparse
import errno
import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from ip_validator import (
    ValidationResult,
    is_valid_ip,
    is_valid_ipv4,
    is_valid_ipv6,
    validate_ip,
)
from ip_validator.__main__ import main


def argparse_ignores_write_errors():
    """Return True if this Python's argparse ignores OSError on write.

    Probes the standard ``argparse.ArgumentParser`` (not the CLI parser) so
    tests can state the expected behaviour without hard-coding versions.
    """
    stream = mock.Mock()
    stream.write.side_effect = OSError(errno.EIO, os.strerror(errno.EIO))
    try:
        argparse.ArgumentParser(prog="probe")._print_message("x", stream)
    except OSError:
        return False
    return True

VALID_IPV4 = [
    "0.0.0.0",
    "127.0.0.1",
    "192.168.1.1",
    "10.0.0.255",
    "255.255.255.255",
    "8.8.8.8",
]

INVALID_IPV4 = [
    "",
    "256.0.0.1",
    "1.2.3",
    "1.2.3.4.5",
    "1.2.3.-4",
    "192.168.01.1",  # leading zero
    "01.2.3.4",
    "a.b.c.d",
    "1..2.3",
    "1.2.3.4.",
    " 1.2.3.4",
    "1.2.3.4 ",
    "1.2.3.4/24",
    "1",
    "::1",
]

VALID_IPV6 = [
    "::",
    "::1",
    "2001:db8::1",
    "2001:0db8:85a3:0000:0000:8a2e:0370:7334",
    "2001:DB8:85A3::8A2E:370:7334",
    "fe80::1",
    "fe80::1%eth0",
    "::ffff:192.168.1.1",
    "1:2:3:4:5:6:7:8",
]

INVALID_IPV6 = [
    "",
    ":::",
    "1:2:3:4:5:6:7:8:9",
    "2001:db8::1::1",
    "2001:db8:::1",
    "12345::1",
    "g::1",
    "2001:db8::1/64",
    " ::1",
    "192.168.1.1",
    "::ffff:256.1.1.1",
]


class TestIsValidIPv4(unittest.TestCase):
    def test_valid_addresses(self):
        for address in VALID_IPV4:
            with self.subTest(address=address):
                self.assertTrue(is_valid_ipv4(address))

    def test_invalid_addresses(self):
        for address in INVALID_IPV4:
            with self.subTest(address=address):
                self.assertFalse(is_valid_ipv4(address))

    def test_non_string_inputs_are_rejected(self):
        for value in (None, 3232235777, b"1.2.3.4", ["1.2.3.4"]):
            with self.subTest(value=value):
                self.assertFalse(is_valid_ipv4(value))


class TestIsValidIPv6(unittest.TestCase):
    def test_valid_addresses(self):
        for address in VALID_IPV6:
            with self.subTest(address=address):
                self.assertTrue(is_valid_ipv6(address))

    def test_invalid_addresses(self):
        for address in INVALID_IPV6:
            with self.subTest(address=address):
                self.assertFalse(is_valid_ipv6(address))

    def test_non_string_inputs_are_rejected(self):
        for value in (None, 1, b"::1"):
            with self.subTest(value=value):
                self.assertFalse(is_valid_ipv6(value))

    def test_zone_ids_follow_ipaddress_syntax(self):
        for zone in ("eth0", "3", "lan segment", "vlan.01"):
            with self.subTest(zone=zone):
                self.assertTrue(is_valid_ipv6(f"fe80::1%{zone}"))
                self.assertTrue(is_valid_ipv6(f"::ffff:192.168.1.1%{zone}"))
        for zone in ("", "eth0%eth1", "eth0/64"):
            with self.subTest(zone=zone):
                self.assertFalse(is_valid_ipv6(f"fe80::1%{zone}"))

    def test_zone_ids_with_control_characters_are_rejected(self):
        # Regression: ``ipaddress`` accepts these, so they used to be valid.
        for zone in (
            "eth0\x00",
            "eth\n0",
            "lan\tsegment",
            "eth\r0",
            "\x1b[31m",
            "eth0\x7f",
            "eth\x850",
            "eth0\u200b",  # zero-width space
            "eth0\u202e",  # right-to-left override
        ):
            with self.subTest(zone=zone):
                for address in (f"fe80::1%{zone}", f"::ffff:192.168.1.1%{zone}"):
                    self.assertFalse(is_valid_ipv6(address))
                    self.assertFalse(is_valid_ip(address))
                    result = validate_ip(address)
                    self.assertFalse(result.is_valid)
                    self.assertIsNone(result.version)
                    self.assertEqual(
                        result.reason,
                        "IPv6 zone ID must not contain control or non-printable characters",
                    )

    def test_zone_ids_with_printable_unicode_are_accepted(self):
        for zone in ("lan segment", "réseau", "eth0-é"):
            with self.subTest(zone=zone):
                self.assertTrue(is_valid_ipv6(f"fe80::1%{zone}"))


class TestValidateIP(unittest.TestCase):
    def test_detects_ipv4(self):
        result = validate_ip("192.168.1.1")
        self.assertTrue(result.is_valid)
        self.assertEqual(result.version, 4)
        self.assertIsNone(result.reason)

    def test_detects_ipv6(self):
        result = validate_ip("2001:db8::1")
        self.assertTrue(result.is_valid)
        self.assertEqual(result.version, 6)
        self.assertIsNone(result.reason)

    def test_invalid_address_has_reason(self):
        result = validate_ip("999.1.1.1")
        self.assertFalse(result.is_valid)
        self.assertIsNone(result.version)
        self.assertTrue(result.reason)

    def test_leading_zero_reason(self):
        result = validate_ip("10.0.00.1")
        self.assertFalse(result.is_valid)
        self.assertIn("leading zero", result.reason)

    def test_embedded_ipv4_leading_zeros_are_rejected_before_parsing(self):
        with mock.patch("ip_validator.validator.ipaddress.IPv6Address") as parser:
            for address in ("::ffff:192.168.01.1", "::010.0.0.1%eth0"):
                with self.subTest(address=address):
                    self.assertFalse(is_valid_ipv6(address))
                    result = validate_ip(address)
                    self.assertFalse(result.is_valid)
                    self.assertIsNone(result.version)
                    self.assertEqual(result.reason, "IPv4 octets must not have leading zeros")
            parser.assert_not_called()

    def test_whitespace_reason(self):
        result = validate_ip("  ::1")
        self.assertFalse(result.is_valid)
        self.assertIn("whitespace", result.reason)

    def test_empty_reason(self):
        self.assertEqual(validate_ip("").reason, "address is empty")

    def test_non_string_reason(self):
        result = validate_ip(None)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.address, "None")
        self.assertEqual(result.reason, "address must be a string")

    def test_non_string_inputs_do_not_require_repr(self):
        class Unrepresentable:
            def __repr__(self):
                raise RuntimeError("representation unavailable")

        value = Unrepresentable()
        self.assertFalse(is_valid_ip(value))
        self.assertEqual(
            validate_ip(value),
            ValidationResult("<non-string input>", False, reason="address must be a string"),
        )

    def test_is_valid_ip(self):
        for address in VALID_IPV4 + VALID_IPV6:
            with self.subTest(address=address):
                self.assertTrue(is_valid_ip(address))
        for address in ("not-an-ip", "300.1.1.1", "1:2:3", ""):
            with self.subTest(address=address):
                self.assertFalse(is_valid_ip(address))


class TestCLI(unittest.TestCase):
    def run_cli(self, argv, stdin=None):
        out = io.StringIO()
        with redirect_stdout(out), mock.patch("sys.stdin", io.StringIO(stdin or "")):
            code = main(argv)
        return code, out.getvalue()

    def test_all_valid_returns_zero(self):
        code, output = self.run_cli(["1.2.3.4", "::1"])
        self.assertEqual(code, 0)
        self.assertIn("VALID    IPv4  1.2.3.4", output)
        self.assertIn("VALID    IPv6  ::1", output)

    def test_any_invalid_returns_one(self):
        code, output = self.run_cli(["1.2.3.4", "bad"])
        self.assertEqual(code, 1)
        self.assertIn("INVALID", output)

    def test_quiet_mode_prints_nothing(self):
        code, output = self.run_cli(["-q", "bad"])
        self.assertEqual(code, 1)
        self.assertEqual(output, "")

    def test_reads_from_stdin(self):
        code, output = self.run_cli([], stdin="10.0.0.1\r\nfe80::1")
        self.assertEqual(code, 0)
        self.assertEqual(output, "VALID    IPv4  10.0.0.1\nVALID    IPv6  fe80::1\n")

    def test_stdin_strips_only_one_lf_or_crlf_separator(self):
        # Regression: rstrip("\r\n") also removed extra carriage returns,
        # so "::1\r\r\n" or a final "::1\r" were reported as valid.
        for stdin, expected_code, expected in (
            ("::1\n", 0, "VALID    IPv6  ::1\n"),
            ("::1\r\n", 0, "VALID    IPv6  ::1\n"),
            ("::1", 0, "VALID    IPv6  ::1\n"),
            ("::1\r\r\n", 1, "INVALID        ::1\\r  ("),
            ("::1\r", 1, "INVALID        ::1\\r  ("),
            ("::1\n\r\n", 1, "VALID    IPv6  ::1\nINVALID          ("),
            ("fe80::1%eth0\x1b\r\n", 1, "INVALID        fe80::1%eth0\\x1b  (IPv6 zone ID"),
            ("fe80::1%eth0\x00\n", 1, "INVALID        fe80::1%eth0\\x00  (IPv6 zone ID"),
        ):
            with self.subTest(stdin=stdin):
                code, output = self.run_cli([], stdin=stdin)
                self.assertEqual(code, expected_code)
                self.assertTrue(output.startswith(expected), output)

    def test_windows_style_stdin_keeps_carriage_returns(self):
        # Regression: on Windows sys.stdin uses universal newlines
        # (newline=None), which turned "::1\r\r\n" into "::1\n" + "\n" and
        # split "a\rb" into two lines. This simulates that stream on any OS.
        raw = b"::1\r\n::1\r\r\n10.0.0.1\r::1\nfe80::1%eth0\x1b\r\n::1\r"
        stdin = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8", newline=None)
        out = io.StringIO()
        with redirect_stdout(out), mock.patch("sys.stdin", stdin):
            self.assertEqual(main([]), 1)
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), 5, lines)
        self.assertEqual(lines[0], "VALID    IPv6  ::1")
        self.assertTrue(lines[1].startswith("INVALID        ::1\\r  ("), lines[1])
        self.assertTrue(lines[2].startswith("INVALID        10.0.0.1\\r::1  ("), lines[2])
        self.assertTrue(lines[3].startswith("INVALID        fe80::1%eth0\\x1b  ("), lines[3])
        self.assertTrue(lines[4].startswith("INVALID        ::1\\r  ("), lines[4])

    def test_stdin_that_cannot_be_reconfigured_is_still_read(self):
        stdin = mock.MagicMock()
        stdin.reconfigure.side_effect = ValueError("already read")
        stdin.__iter__.return_value = iter(["::1\r\n", "bad\n"])
        out = io.StringIO()
        with redirect_stdout(out), mock.patch("sys.stdin", stdin):
            self.assertEqual(main([]), 1)
        stdin.reconfigure.assert_called_once_with(newline="\n")
        self.assertTrue(out.getvalue().startswith("VALID    IPv6  ::1\nINVALID        bad"))

    def test_module_stdin_keeps_extra_carriage_returns(self):
        # Real sys.stdin is reconfigured to split lines on "\n" only, on
        # every platform (on Windows it would otherwise translate "\r" and
        # "\r\n" to "\n"), so "\r" reaches the separator handling unchanged.
        # Raw bytes are written straight to the child's stdin pipe.
        whitespace = "  (address contains leading or trailing whitespace)"
        zone_control = "  (IPv6 zone ID must not contain control or non-printable characters)"
        cases = (
            (
                "CRLF separators only",
                b"::1\r\n10.0.0.1\r\nfe80::1%eth0\r\n",
                0,
                [
                    "VALID    IPv6  ::1",
                    "VALID    IPv4  10.0.0.1",
                    "VALID    IPv6  fe80::1%eth0",
                ],
            ),
            (
                "mixed LF and CRLF separators",
                b"::1\n10.0.0.1\r\n::1",
                0,
                [
                    "VALID    IPv6  ::1",
                    "VALID    IPv4  10.0.0.1",
                    "VALID    IPv6  ::1",
                ],
            ),
            (
                "extra carriage returns before LF",
                b"::1\r\r\n::1\r\r\r\n\r\r\n\r\n10.0.0.1\r\n",
                1,
                [
                    "INVALID        ::1\\r" + whitespace,
                    "INVALID        ::1\\r\\r" + whitespace,
                    "INVALID        \\r" + whitespace,
                    "INVALID          (address is empty)",
                    "VALID    IPv4  10.0.0.1",
                ],
            ),
            (
                "carriage returns inside a line",
                b"10.0.0.1\r::1\n::1\r10.0.0.1\r\nfe80::1%eth0\x1b\r\n",
                1,
                [
                    # The reason comes from ipaddress and may vary by version.
                    "INVALID        10.0.0.1\\r::1  (",
                    "INVALID        ::1\\r10.0.0.1  (",
                    "INVALID        fe80::1%eth0\\x1b" + zone_control,
                ],
            ),
            (
                "lone carriage return at end of stream",
                b"::1\r\n::1\r",
                1,
                ["VALID    IPv6  ::1", "INVALID        ::1\\r" + whitespace],
            ),
            (
                "stream made of a single carriage return",
                b"\r",
                1,
                ["INVALID        \\r" + whitespace],
            ),
        )
        for name, raw, expected_code, expected_lines in cases:
            with self.subTest(name):
                result = subprocess.run(
                    [sys.executable, "-m", "ip_validator"],
                    input=raw,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=5,
                )
                self.assertEqual(result.returncode, expected_code, result.stdout)
                self.assertEqual(result.stderr, b"")
                # Output is pure ASCII (non-printable characters are escaped).
                # Windows writes "\r\n" for each "\n" printed to stdout.
                stdout = result.stdout.decode("ascii").replace("\r\n", "\n")
                self.assertNotIn("\r", stdout)
                self.assertTrue(stdout.endswith("\n"), stdout)
                lines = stdout[:-1].split("\n")
                self.assertEqual(len(lines), len(expected_lines), lines)
                for line, expected in zip(lines, expected_lines):
                    if expected.endswith("("):
                        self.assertTrue(line.startswith(expected), line)
                        self.assertTrue(line.endswith(")"), line)
                    else:
                        self.assertEqual(line, expected)

    def test_stdin_results_are_flushed_before_reading_the_next_line(self):
        out = mock.Mock(wraps=io.StringIO())

        def lines():
            yield "::1\n"
            self.assertEqual(out.getvalue(), "VALID    IPv6  ::1\n")
            out.flush.assert_called_once_with()
            yield "bad\n"

        with redirect_stdout(out), mock.patch("sys.stdin", lines()):
            self.assertEqual(main([]), 1)
        self.assertIn("INVALID        bad", out.getvalue())

    def test_control_characters_are_escaped_in_addresses(self):
        code, output = self.run_cli(["fe80::1%lan\tsegment", "bad\ninput"])
        self.assertEqual(code, 1)
        self.assertEqual(len(output.splitlines()), 2)
        self.assertNotIn("\t", output)
        self.assertIn(r"INVALID        fe80::1%lan\tsegment  (IPv6 zone ID", output)
        self.assertIn(r"INVALID        bad\ninput", output)

    def test_broken_pipe_while_writing_is_handled(self):
        # Regression: a closed pipe used to propagate BrokenPipeError.
        for argv, stdin in ((["::1", "1.2.3.4"], None), ([], "::1\n1.2.3.4\n")):
            with self.subTest(argv=argv):
                out = mock.Mock(wraps=io.StringIO())
                out.write.side_effect = BrokenPipeError
                with redirect_stdout(out), mock.patch("sys.stdin", io.StringIO(stdin or "")):
                    self.assertEqual(main(argv), 141)
                out.write.assert_called_once()

    def test_broken_pipe_on_final_flush_is_handled(self):
        out = mock.Mock(wraps=io.StringIO())
        out.flush.side_effect = BrokenPipeError
        with redirect_stdout(out):
            self.assertEqual(main(["::1"]), 141)

    def test_module_handles_closed_stdout_pipe(self):
        # Regression: the process used to print a traceback and
        # "Exception ignored ... BrokenPipeError" on stderr.
        for args, stdin in ((["::1", "bad"], ""), ([], "::1\nbad\n")):
            with self.subTest(args=args):
                read_fd, write_fd = os.pipe()
                os.close(read_fd)
                try:
                    result = subprocess.run(
                        [sys.executable, "-m", "ip_validator", *args],
                        input=stdin,
                        stdout=write_fd,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=5,
                    )
                finally:
                    os.close(write_fd)
                self.assertEqual(result.returncode, 141)
                self.assertEqual(result.stderr, "")

    def test_broken_pipe_while_printing_help_is_handled(self):
        # Regression: BrokenPipeError raised by argparse while printing
        # --help escaped main() (on write or on the shutdown flush).
        for side in ("write", "flush"):
            for flag in ("-h", "--help"):
                with self.subTest(side=side, flag=flag):
                    out = mock.Mock(wraps=io.StringIO())
                    getattr(out, side).side_effect = BrokenPipeError
                    with redirect_stdout(out):
                        self.assertEqual(main([flag]), 141)

    def test_broken_pipe_during_help_write_reaches_handler_in_one_write(self):
        # Regression: since Python 3.11, argparse's _print_message swallows
        # OSError (BrokenPipeError included) raised by write(), so --help
        # ended with SystemExit(0) instead of exit status 141.
        for flag in ("-h", "--help"):
            with self.subTest(flag=flag):
                out = mock.Mock(wraps=io.StringIO())
                out.write.side_effect = BrokenPipeError
                with redirect_stdout(out):
                    self.assertEqual(main([flag]), 141)
                out.write.assert_called_once()

    def test_argparse_write_error_handling_matches_python_version(self):
        # Pins the standard library behaviour the CLI relies on: argparse
        # lets write errors propagate on 3.9 and ignores them on 3.11+.
        # (3.10 is not in the supported test matrix and is not asserted.)
        if sys.version_info < (3, 10):
            self.assertFalse(argparse_ignores_write_errors())
        elif sys.version_info >= (3, 11):
            self.assertTrue(argparse_ignores_write_errors())

    def test_other_os_errors_during_help_are_not_reported_as_broken_pipe(self):
        # Only BrokenPipeError is re-raised. Any other OSError keeps the
        # standard library behaviour: it propagates (Python 3.9) or is
        # ignored by argparse, which then exits with status 0 (3.11+).
        expected_for = (
            (lambda code: ("exit", 0))
            if argparse_ignores_write_errors()
            else (lambda code: ("oserror", code))
        )
        for code in (errno.EIO, errno.EINVAL):
            for flag in ("-h", "--help"):
                with self.subTest(errno=errno.errorcode[code], flag=flag):
                    out = mock.Mock(wraps=io.StringIO())
                    out.write.side_effect = OSError(code, os.strerror(code))
                    with redirect_stdout(out):
                        try:
                            outcome = main([flag])
                        except SystemExit as exc:
                            outcome = ("exit", exc.code)
                        except OSError as exc:
                            outcome = ("oserror", exc.errno)
                    self.assertEqual(outcome, expected_for(code))
                    out.write.assert_called_once()

    def test_argument_errors_on_stderr_keep_standard_behaviour(self):
        # Regression (fifth review): BrokenPipeError on stderr while argparse
        # reports a usage error must not be turned into exit status 141 by
        # the stdout-only help handling. Errors on stderr keep the standard
        # library behaviour: ignored by argparse on 3.11+ (exit 2), or
        # propagated to main on 3.9 (exit 141, as in commit 8600de8).
        ignored = argparse_ignores_write_errors()
        for exc in (BrokenPipeError(), OSError(errno.EIO, os.strerror(errno.EIO))):
            with self.subTest(error=type(exc).__name__):
                err = mock.Mock(wraps=io.StringIO())
                err.write.side_effect = exc
                out = io.StringIO()
                with redirect_stdout(out), redirect_stderr(err):
                    try:
                        outcome = ("return", main(["--unknown-option"]))
                    except SystemExit as raised:
                        outcome = ("exit", raised.code)
                    except OSError as raised:
                        outcome = ("oserror", raised.errno)
                if ignored:
                    expected = ("exit", 2)
                elif isinstance(exc, BrokenPipeError):
                    expected = ("return", 141)
                else:
                    expected = ("oserror", errno.EIO)
                self.assertEqual(outcome, expected)
                self.assertEqual(out.getvalue(), "")

    def test_module_argument_errors_with_normal_stderr_exit_two(self):
        for mode, python_flags in (("buffered", []), ("unbuffered", ["-u"])):
            for args in (["--unknown-option"], ["-x"], ["-q", "--unknown-option", "::1"]):
                with self.subTest(mode=mode, args=args):
                    result = subprocess.run(
                        [sys.executable, *python_flags, "-m", "ip_validator", *args],
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, "")
                    self.assertTrue(result.stderr.startswith("usage: ip_validator"), result.stderr)
                    self.assertIn("error: unrecognized arguments: ", result.stderr)

    def test_module_argument_errors_with_closed_stderr_pipe(self):
        # Regression (fifth review): with stdout open and stderr connected to
        # a closed pipe, "python -u -m ip_validator --unknown-option" must
        # keep the behaviour of commit 8600de8: exit 2 where argparse ignores
        # the write error (3.11+), exit 141 where it propagates (3.9).
        # Buffered mode: the error surfaces when stderr is flushed at
        # interpreter shutdown, which exits with status 120 on every version.
        unbuffered_code = 2 if argparse_ignores_write_errors() else 141
        for mode, python_flags, expected in (
            ("buffered", [], 120),
            ("unbuffered", ["-u"], unbuffered_code),
        ):
            for args in (["--unknown-option"], ["-x"]):
                with self.subTest(mode=mode, args=args):
                    read_fd, write_fd = os.pipe()
                    os.close(read_fd)
                    try:
                        result = subprocess.run(
                            [sys.executable, *python_flags, "-m", "ip_validator", *args],
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE,
                            stderr=write_fd,
                            timeout=5,
                        )
                    finally:
                        os.close(write_fd)
                    self.assertEqual(result.returncode, expected)
                    self.assertEqual(result.stdout, b"")

    def test_module_help_with_closed_stderr_pipe_still_prints_help(self):
        # Help goes to stdout: a closed stderr must not affect it.
        for mode, python_flags in (("buffered", []), ("unbuffered", ["-u"])):
            for flag in ("-h", "--help"):
                with self.subTest(mode=mode, flag=flag):
                    read_fd, write_fd = os.pipe()
                    os.close(read_fd)
                    try:
                        result = subprocess.run(
                            [sys.executable, *python_flags, "-m", "ip_validator", flag],
                            stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE,
                            stderr=write_fd,
                            timeout=5,
                        )
                    finally:
                        os.close(write_fd)
                    self.assertEqual(result.returncode, 0)
                    self.assertTrue(result.stdout.startswith(b"usage: ip_validator"), result.stdout)

    def test_help_still_exits_zero(self):
        for flag in ("-h", "--help"):
            with self.subTest(flag=flag):
                out = io.StringIO()
                with redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
                    main([flag])
                self.assertEqual(ctx.exception.code, 0)
                self.assertIn("usage: ip_validator", out.getvalue())

    def test_module_help_to_normal_stdout_exits_zero(self):
        for mode, python_flags in (("buffered", []), ("unbuffered", ["-u"])):
            for flag in ("-h", "--help"):
                with self.subTest(mode=mode, flag=flag):
                    result = subprocess.run(
                        [sys.executable, *python_flags, "-m", "ip_validator", flag],
                        stdin=subprocess.DEVNULL,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    self.assertEqual(result.returncode, 0)
                    self.assertEqual(result.stderr, "")
                    self.assertTrue(result.stdout.startswith("usage: ip_validator"), result.stdout)

    def test_module_help_handles_closed_stdout_pipe(self):
        # Regression: --help into a closed pipe printed "Exception ignored ...
        # BrokenPipeError" on stderr and exited with status 120 (buffered),
        # or exited with status 0 on Python 3.11+ (unbuffered, -u), where
        # write() itself raises and argparse swallowed the error.
        for mode, python_flags in (("buffered", []), ("unbuffered", ["-u"])):
            for flag in ("-h", "--help"):
                with self.subTest(mode=mode, flag=flag):
                    read_fd, write_fd = os.pipe()
                    os.close(read_fd)
                    try:
                        result = subprocess.run(
                            [sys.executable, *python_flags, "-m", "ip_validator", flag],
                            stdin=subprocess.DEVNULL,
                            stdout=write_fd,
                            stderr=subprocess.PIPE,
                            text=True,
                            timeout=5,
                        )
                    finally:
                        os.close(write_fd)
                    self.assertEqual(result.returncode, 141)
                    self.assertEqual(result.stderr, "")

    def test_control_characters_are_escaped_in_error_messages(self):
        result = ValidationResult("bad", False, reason="invalid\rtext")
        with mock.patch("ip_validator.__main__.validate_ip", return_value=result):
            code, output = self.run_cli(["bad"])
        self.assertEqual(code, 1)
        self.assertEqual(output, "INVALID        bad  (invalid\\rtext)\n")

    def test_module_exit_codes_and_end_of_options(self):
        for args, stdin, expected in (
            ([], "", 0),
            ([], "\n", 1),
            (["-1.2.3.4"], "", 2),
            (["--", "-1.2.3.4"], "", 1),
        ):
            with self.subTest(args=args, stdin=stdin):
                result = subprocess.run(
                    [sys.executable, "-m", "ip_validator", *args],
                    input=stdin,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                self.assertEqual(result.returncode, expected)
                if expected == 2:
                    self.assertIn("unrecognized arguments", result.stderr)
                else:
                    self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
