import io
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
        self.assertIn(r"VALID    IPv6  fe80::1%lan\tsegment", output)
        self.assertIn(r"INVALID        bad\ninput", output)

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
