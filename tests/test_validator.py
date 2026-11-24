import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

from ip_validator import (
    ValidationResult,
    is_valid_ip,
    is_valid_ipv4,
    is_valid_ipv6,
    validate_ip,
)
from ip_validator.__main__ import main

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
        # every platform, so "\r" reaches the separator handling unchanged.
        result = subprocess.run(
            [sys.executable, "-m", "ip_validator"],
            input=b"::1\r\n::1\r\r\nfe80::1%eth0\x1b\r\n",
            capture_output=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, b"")
        lines = result.stdout.decode().splitlines()
        self.assertEqual(lines[0], "VALID    IPv6  ::1")
        self.assertTrue(lines[1].startswith("INVALID        ::1\\r  ("), lines[1])
        self.assertTrue(lines[2].startswith("INVALID        fe80::1%eth0\\x1b  ("), lines[2])

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

    def test_help_still_exits_zero(self):
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as ctx:
            main(["--help"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("usage: ip_validator", out.getvalue())

    def test_module_help_handles_closed_stdout_pipe(self):
        # Regression: --help into a closed pipe printed "Exception ignored ...
        # BrokenPipeError" on stderr and exited with status 120.
        for flag in ("-h", "--help"):
            with self.subTest(flag=flag):
                read_fd, write_fd = os.pipe()
                os.close(read_fd)
                try:
                    result = subprocess.run(
                        [sys.executable, "-m", "ip_validator", flag],
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
