# ip_validator

A small, dependency-free Python tool to validate IPv4 and IPv6 addresses,
usable both as a library and from the command line.

## Requirements

- Python 3.9 or later
- No third-party dependencies (only the standard library: `ipaddress`, `argparse`, `unittest`)

## Installation

```bash
git clone <repository-url>
cd AI-Test
# Optional: create an isolated environment
python3 -m venv .venv
source .venv/bin/activate
```

Run the examples from the checkout directory. No configuration or environment
variables are required.

## Command-line usage

```bash
python3 -m ip_validator 192.168.1.1 2001:db8::1 999.1.1.1
```

```
VALID    IPv4  192.168.1.1
VALID    IPv6  2001:db8::1
INVALID        999.1.1.1  (Octet 999 (> 255) not permitted in '999.1.1.1')
```

With no address arguments, the CLI reads standard input one line at a time
and prints each result as it processes the line:

```bash
cat addresses.txt | python3 -m ip_validator
```

Exactly one trailing line separator (LF or CRLF) is removed from each line.
Any other character, including an extra carriage return (`::1\r\r\n`) or a
final lone `\r`, is kept and validated, so the line is reported as invalid.

Use `--` before a value that starts with `-` to pass it to the validator:

```bash
python3 -m ip_validator -- -1.2.3.4
```

The CLI escapes control characters and other non-printable characters in
displayed addresses and error messages. `-q` or `--quiet` suppresses validation
results. Argument errors still go to standard error.

| Exit code | Meaning |
|-----------|---------|
| `0` | All supplied addresses are valid, or standard input is empty. |
| `1` | At least one address is invalid. A blank input line counts as an invalid address. |
| `2` | Command-line argument error. |
| `141` | Standard output was closed early (broken pipe, e.g. `\| head -n 1`), including while printing `--help`. Remaining output is discarded silently. This is the status of the Python process; the status of a whole shell pipeline depends on the shell (usually the last command, unless `pipefail` is set). |

## Library usage

```python
from ip_validator import is_valid_ipv4, is_valid_ipv6, is_valid_ip, validate_ip

is_valid_ipv4("10.0.0.1")       # True
is_valid_ipv6("fe80::1%eth0")   # True
is_valid_ip("not-an-ip")        # False

result = validate_ip("192.168.01.1")
result.is_valid  # False
result.version   # None
result.reason    # 'IPv4 octets must not have leading zeros'
```

For string inputs, `result.address` contains the original string. For
non-string inputs, it contains `"None"` for `None` and `"<non-string input>"`
for other objects.

## Validation rules

Validation is built on Python's standard `ipaddress` module, with stricter rules:

- Only `str` inputs are accepted (integers and bytes are rejected).
- Empty strings and leading/trailing whitespace are rejected.
- IPv4 octets with leading zeros (`192.168.01.1`) are rejected, as they are
  ambiguous (octal vs. decimal). This rule also applies to dotted IPv4 suffixes
  in IPv6 addresses (`::ffff:192.168.01.1`).
- CIDR notation (`10.0.0.0/8`, `2001:db8::/32`) is rejected: only single
  addresses are validated.
- IPv6 compressed forms (`::1`) and embedded IPv4 (`::ffff:1.2.3.4`) are accepted.
- IPv6 zone IDs, such as `eth0` in `fe80::1%eth0` and `3` in `fe80::1%3`,
  follow `ipaddress` syntax. The suffix after `%` must be non-empty and may
  contain interior spaces. Additional `%` characters, `/`, and control or
  other non-printable characters (such as NUL, tab, newline, escape or
  zero-width/bidirectional formatting characters) are rejected.
  Validation treats the zone ID as an opaque string and does not look up
  local network interfaces.

## Running the tests

```bash
python3 -m unittest discover -s tests -v
```

## Project structure

```
ip_validator/
    __init__.py     # Public API
    __main__.py     # Command-line interface
    validator.py    # Validation logic
tests/
    test_validator.py
```
