# Project Handoff

## Current Version
v1.0.0 (unreleased fixes on branch `fix/validator-improvements`)

## Status
- Initial implementation completed.
- Independent review completed.
- Six audit findings addressed.
- Initial Git commit completed.
- Both known issues fixed on `fix/validator-improvements` (not committed yet).
- Three Codex review findings fixed (not committed yet).
- Two findings from the second Codex review fixed (not committed yet).

## Latest Changes (fix/validator-improvements)
1. IPv6 zone ID control characters
   - `ip_validator/validator.py`: `_ipv6_error` now rejects zone IDs that are
     not printable (`str.isprintable()`), e.g. NUL, tab, newline, CR, ESC,
     DEL, C1 controls, zero-width space, bidi overrides. Interior spaces and
     printable Unicode remain accepted.
   - New reason: `IPv6 zone ID must not contain control or non-printable characters`.
   - Behaviour change: `fe80::1%lan\tsegment` is now INVALID (the existing CLI
     escaping test was updated accordingly).
2. BrokenPipeError in the CLI
   - `ip_validator/__main__.py`: output loop moved to `_validate_all`; `main`
     catches `BrokenPipeError`, redirects the stdout descriptor to
     `os.devnull` (avoids the "Exception ignored" message at shutdown) and
     returns new exit code `141` (`EXIT_BROKEN_PIPE`, 128 + SIGPIPE).
   - stdout is flushed explicitly before `main` returns so buffered output
     (address-argument mode) fails inside the handler, not at shutdown.
3. `README.md`: zone ID rule and exit code `141` documented.

## Review Fixes (Codex findings, fix/validator-improvements)
1. Standard input line separators
   - `ip_validator/__main__.py`: `rstrip("\r\n")` replaced by
     `_strip_line_separator`, which removes exactly one trailing LF or CRLF.
   - Extra carriage returns (`::1\r\r\n`) and a final lone `\r` are now kept
     and rejected; control characters such as ESC or NUL in zone IDs are
     still detected and rejected.
2. BrokenPipeError during argument parsing
   - `parse_args()` now runs inside the `BrokenPipeError` handler of `main`
     through `_parse_args`, which flushes stdout before re-raising
     `SystemExit` so `--help` output to a closed pipe fails inside `main`.
   - `-h`/`--help` into a closed pipe: exit status 141, empty stderr.
     `--help` to a normal stdout still exits with status 0.
3. Exit status 141 scope
   - 141 is the exit status of the Python process (`python3 -m ip_validator`)
     only. The status reported for a complete shell pipeline depends on the
     shell: by default it is the status of the last command (e.g. `head`,
     usually 0); with `set -o pipefail` (bash/zsh) or via `PIPESTATUS`
     (bash) / `pipestatus` (zsh) the 141 becomes visible.

## Second Review Fixes (Codex findings, fix/validator-improvements)
1. Carriage returns in stdin on Windows
   - On Windows, Python opens `sys.stdin` with universal newlines
     (`newline=None`): `"\r\n"` and a lone `"\r"` are translated to `"\n"`,
     so `::1\r\r\n` became `::1` + an empty line and `a\rb` was split.
   - `ip_validator/__main__.py`: new `_disable_newline_translation`, called
     before reading stdin, runs `sys.stdin.reconfigure(newline="\n")`
     (Python 3.7+, standard library only). Lines are split on LF only and CR
     characters are kept on every platform; `_strip_line_separator` still
     removes one LF/CRLF. Reading stays line by line.
   - Streams without `reconfigure` (e.g. `io.StringIO`) or that refuse it
     (`ValueError`/`OSError`) are read unchanged.
2. HANDOFF accuracy
   - The Tests section records which added tests already pass on `HEAD`.

## Tests
- All 37 tests passed with `python3 -m unittest discover -s tests -v` on
  macOS with Python 3.9.6. The suite includes 25 tests already present on
  `HEAD` and 12 added tests.
- Of the 12 added tests, 10 were verified to fail against the implementation
  at `HEAD` (`ab73af1`). They cover rejection of control or non-printable
  characters in IPv6 zone IDs, stdin line separators and preserved carriage
  returns, fallback when stdin cannot be reconfigured, and broken stdout
  pipes during validation output and `-h`/`--help`.
- Two added non-regression tests also pass against `HEAD`.
  `test_zone_ids_with_printable_unicode_are_accepted` checks that printable
  Unicode in IPv6 zone IDs remains accepted. `test_help_still_exits_zero`
  checks that `--help` exits with status 0 when stdout is open.
- `test_windows_style_stdin_keeps_carriage_returns` and
  `test_stdin_that_cannot_be_reconfigured_is_still_read` also fail with just
  the stdin reconfiguration bypassed in the current implementation.
- Windows stdin behaviour was simulated on macOS with
  `io.TextIOWrapper(..., newline=None)`. Native Windows runs of the test
  suite and a CLI check with raw CR input are still pending.
- Manual check: `yes ::1 | head -n 100000 | python3 -m ip_validator | head -n 1`
  prints one line, no stderr output, Python process exit status 141
  (read from `pipestatus`; the pipeline itself returns `head`'s status).
- Manual check: `python3 -m ip_validator --help` with a closed stdout pipe
  returns 141 with empty stderr; `printf '::1\r\r\n10.0.0.1\r\n' | python3 -m ip_validator`
  reports `::1\r` INVALID and `10.0.0.1` VALID (exit 1).
- Manual check (macOS): `printf '::1\r\r\n10.0.0.1\r\n10.0.0.1\r::1\n' | python3 -m ip_validator`
  reports `::1\r` INVALID, `10.0.0.1` VALID, `10.0.0.1\r::1` INVALID (exit 1).

## Next Task
Commit after user approval and open a pull request. Before merging, run the
test suite and the CLI check with raw CR input on Windows.

## Known Issues
- Windows behaviour verified only by simulation on macOS (see Tests).
