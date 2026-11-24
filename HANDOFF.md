# Project Handoff

## Current Version
v1.0.0 (unreleased fixes on branch `fix/validator-improvements`)

## Status
- Initial implementation completed.
- Independent review completed.
- Six audit findings addressed.
- Initial Git commit completed.
- Both known issues, three Codex review findings and two findings from the
  second Codex review fixed on `fix/validator-improvements`.
- These fixes are committed (`8600de8`, "Fix IP validation and CLI edge
  cases") and pushed to `origin/fix/validator-improvements`.
- Pull request #1 (`fix/validator-improvements` -> `main`) is open as a
  draft and must stay a draft until the CI matrix has run.
- GitHub Actions workflow `.github/workflows/tests.yml` exists locally only:
  it is untracked (not committed, not pushed), so it has never run on GitHub.
- Third Codex review (verdict CHANGES REQUIRED) addressed in `HANDOFF.md`
  and `tests/test_validator.py` (not committed yet, see below).
- Fourth Codex review (verdict CHANGES REQUIRED, `BrokenPipeError` swallowed
  by argparse on Python 3.11+) fixed in `ip_validator/__main__.py`,
  `tests/test_validator.py` and `HANDOFF.md` (not committed yet).
- Fifth Codex review (verdict CHANGES REQUIRED, regression of the fourth
  review fix on stderr) fixed in the same three files (not committed yet).

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
   - The Tests section records which added tests already pass on `ab73af1`.

## Third Review Fixes (Codex findings, not committed yet)
Only `HANDOFF.md` and `tests/test_validator.py` were changed. The validator
source code and the workflow file are unchanged.
1. HANDOFF accuracy: commit/push state, draft PR #1, untracked workflow,
   the nine OS/Python combinations and pending native Windows validation.
2. `test_module_stdin_keeps_extra_carriage_returns` strengthened. It now
   writes raw bytes directly to the stdin pipe of `python -m ip_validator`
   (`subprocess.run(input=<bytes>)`) in six sub-tests:
   - CRLF separators only and mixed LF/CRLF separators (exit 0);
   - extra CRs before LF: `::1\r\r\n`, `::1\r\r\r\n`, `\r\r\n`, plus an
     empty `\r\n` line (exit 1);
   - CRs inside a line: `10.0.0.1\r::1`, `::1\r10.0.0.1`, plus a zone ID
     with ESC (exit 1);
   - a lone CR at the end of the stream (`::1\r\n::1\r`) and a stream made
     of a single `\r` (exit 1).
   Each sub-test checks the exact number of output lines, each result line
   (exact text for messages produced by this project; prefix only for the
   `ipaddress` reason, whose wording may differ between Python versions),
   the exit code and an empty stderr. CRLF in the child's stdout (Windows
   text mode) is normalised before splitting; the output must contain no
   other CR. Uses only syntax and APIs available in Python 3.9.
3. Windows broken pipes: risk documented under Known Issues; the
   `BrokenPipeError` handling is intentionally unchanged until the
   `windows-latest` CI results are available. No test was disabled.

## Fourth Review Fixes (Codex findings, not committed yet)
Changed files: `ip_validator/__main__.py`, `tests/test_validator.py`,
`HANDOFF.md`. `ip_validator/validator.py`, `README.md` and the workflow file
are unchanged.
1. `BrokenPipeError` swallowed by argparse while printing help
   - Root cause: since Python 3.11, `ArgumentParser._print_message` wraps
     `file.write(message)` in `try/except (AttributeError, OSError): pass`
     (3.9 lets the error propagate). When `write()` itself raises - stdout
     unbuffered (`python -u`), or a stream whose `write()` fails - the
     `BrokenPipeError` was swallowed and `--help` ended with `SystemExit(0)`
     instead of status 141. In buffered mode the write only fills the buffer
     and the explicit flush in `_parse_args` already raised the error, so
     only the `-u`/direct-write cases were affected.
   - Fix (local, argparse itself is not patched): `build_parser` now creates
     a private subclass `_ArgumentParser` whose `_print_message` hands the
     standard implementation a `_BrokenPipeRecorder` proxy around the target
     stream. The proxy records a `BrokenPipeError` raised by `write()` and
     re-raises it; after `super()._print_message` returns, the recorded
     error is raised again so it reaches the handler in `main` (exit 141).
   - Every other error keeps the standard library behaviour of the running
     version (propagates on 3.9/3.10, ignored by argparse on 3.11+), so no
     other I/O error is masked or turned into 141. `sys.stderr is None`
     (e.g. `pythonw`) is passed through unchanged.
   - Note: `_print_message` is a private argparse method; it exists with the
     same signature in 3.9, 3.11, 3.13 and 3.14 (checked natively).
2. Tests (40 tests, previously 37; no test removed, disabled or weakened;
   the six CR sub-tests are unchanged):
   - `test_broken_pipe_while_printing_help_is_handled` (existing):
     `BrokenPipeError` on `write()` or on `flush()`, `-h` and `--help`,
     in-process, exit 141.
   - `test_broken_pipe_during_help_write_reaches_handler_in_one_write`
     (new): `BrokenPipeError` on `write()`, exit 141 and exactly one write.
   - `test_other_os_errors_during_help_are_not_reported_as_broken_pipe`
     (new): `OSError(EINVAL)` on `write()` is never reported as 141; it
     propagates (3.9) or argparse exits 0 (3.11+).
   - `test_help_still_exits_zero` (extended): `-h` and `--help`, exit 0.
   - `test_module_help_to_normal_stdout_exits_zero` (new): subprocess,
     buffered and `-u`, `-h` and `--help`: exit 0, usage on stdout, empty
     stderr.
   - `test_module_help_handles_closed_stdout_pipe` (extended): subprocess,
     closed pipe, buffered and `-u`, `-h` and `--help`: exit 141, empty
     stderr.
3. Python 3.14.9 anomalies (analysed, not fixed - out of scope)
   - Help/broken-pipe anomaly: same root cause as above, fixed.
   - `test_module_exit_codes_and_end_of_options` sub-test
     `args=['-1.2.3.4']` fails on 3.14.9 (exit 1 instead of 2). Python 3.14
     changed argparse's negative-number pattern from
     `^-\d+$|^-\d*\.\d+$` (3.9, 3.11.17, 3.13.17) to `-\.?\d`. Since the
     parser has no option that looks like a negative number, `-1.2.3.4` is
     now accepted as a positional address, validated and reported
     `INVALID` (exit 1) instead of an argument error (exit 2). The address
     is still rejected; only the exit code differs. `-x` still exits 2.
   - Decision (user): document only, no code or test change. 3.14 is not in
     the CI matrix. To be decided later: either make `-...` arguments exit 2
     on every version, or document the version-dependent exit code.

## Fifth Review Fixes (Codex findings, not committed yet)
Changed files: `ip_validator/__main__.py`, `tests/test_validator.py`,
`HANDOFF.md`. The workflow file is unchanged.
1. Regression: `_BrokenPipeRecorder` was applied to every stream, including
   `sys.stderr`. A usage error (`--unknown-option`) written to a closed
   stderr pipe was therefore re-raised as `BrokenPipeError` and reported as
   141, whereas commit `8600de8` kept argparse's standard behaviour.
   Measured natively with `python -u -m ip_validator --unknown-option`,
   stdout open, stderr connected to a closed pipe:

   | Interpreter | `8600de8` | Fourth review fix | Fifth review fix |
   |-------------|-----------|-------------------|------------------|
   | 3.9.6 | 141 | 141 | 141 |
   | 3.11.17 | 2 | 141 (regression) | 2 |
   | 3.13.17 | 2 | 141 (regression) | 2 |

   Buffered mode (no `-u`) exits 120 with all three code versions on all
   three interpreters (stderr fails at the shutdown flush); unchanged.
2. Fix (minimal): `_ArgumentParser._print_message` only wraps the target in
   `_BrokenPipeRecorder` when it is `sys.stdout` (help output). Any other
   target, including `sys.stderr` and `file=None`, is passed unchanged to
   `argparse.ArgumentParser._print_message`. No Python version is checked in
   the source; the 141/2 difference on stderr comes from the standard
   library of each version.
3. Tests (45 tests, previously 40; no test removed, disabled or weakened;
   the eight `-h`/`--help` scenarios - normal stdout, closed pipe, buffered,
   `-u`, `write()` and `flush()` failures - and the six CR sub-tests are kept):
   - Helper `argparse_ignores_write_errors()` probes the standard
     `ArgumentParser` so tests derive the expected result without
     hard-coding versions; `test_argparse_write_error_handling_matches_python_version`
     (new) pins it: propagates on < 3.10, ignored on >= 3.11 (3.10 is not
     asserted, not in the matrix).
   - `test_other_os_errors_during_help_are_not_reported_as_broken_pipe`
     (strengthened): EIO and EINVAL, `-h` and `--help`; exact outcome per
     version (`OSError` with the same errno on 3.9, `SystemExit(0)` on
     3.11+) and exactly one `write()`.
   - `test_argument_errors_on_stderr_keep_standard_behaviour` (new,
     in-process): `BrokenPipeError` or EIO on stderr during
     `--unknown-option`: `SystemExit(2)` on 3.11+; 141 (BrokenPipeError) or
     `OSError(EIO)` on 3.9; stdout stays empty.
   - `test_module_argument_errors_with_normal_stderr_exit_two` (new):
     buffered and `-u`, `--unknown-option`, `-x`, `-q --unknown-option ::1`:
     exit 2, empty stdout, usage and "unrecognized arguments" on stderr.
   - `test_module_argument_errors_with_closed_stderr_pipe` (new): stdout
     open, stderr closed pipe, `--unknown-option` and `-x`: buffered 120,
     `-u` 2 (3.11+) or 141 (3.9), empty stdout.
   - `test_module_help_with_closed_stderr_pipe_still_prints_help` (new):
     buffered and `-u`, `-h` and `--help`: exit 0, usage on stdout.
4. Regression detection: the new tests were run against a copy of the
   fourth-review code (only the fix reverted): 3 failing sub-tests on
   3.11.17 and on 3.13.17 (`test_argument_errors_on_stderr_keep_standard_behaviour`
   with BrokenPipeError, and both `-u` sub-tests of
   `test_module_argument_errors_with_closed_stderr_pipe`). On 3.9.6 the
   regression is not observable (141 either way). The code of `8600de8`
   passes all new stderr tests on the three interpreters (behaviour
   preserved) and still fails the help write tests on 3.11/3.13.

## Tests
- Fifth review, native runs (macOS arm64,
  `python -m unittest discover -s tests`, 45 tests): CPython 3.9.6 OK
  (45/45), 3.11.17 OK (45/45), 3.13.17 OK (45/45). CPython 3.14.9 (outside
  the matrix): 44/45, same single known failure (`-1.2.3.4`).
- Fourth review, native runs (macOS arm64,
  `python -m unittest discover -s tests`, 40 tests):

  | Interpreter (native) | Source | Current code | Code of `8600de8` |
  |----------------------|--------|--------------|-------------------|
  | CPython 3.9.6 | `/usr/bin/python3` | OK (40/40) | OK |
  | CPython 3.11.17 | uv | OK (40/40) | 6 failing sub-tests (help write) |
  | CPython 3.13.17 | uv | OK (40/40) | 6 failing sub-tests (help write) |
  | CPython 3.14.9 | uv | 1 failure (`-1.2.3.4`, see above) | 7 failing sub-tests |

  On 3.11.17, 3.13.17 and 3.14.9 the `8600de8` code fails the help
  write sub-tests of `test_broken_pipe_while_printing_help_is_handled`
  and `test_broken_pipe_during_help_write_reaches_handler_in_one_write`, and the
  `-u` sub-tests of `test_module_help_handles_closed_stdout_pipe`.
  On 3.9.6 the `8600de8` code passes (argparse does not swallow errors).
  3.11.17 and 3.13.17 were installed with `uv python install 3.11 3.13`
  (user-approved, outside the project; not a project dependency).
- Simulations (not native): Windows stdin translation (`newline=None`) and
  `write()`/`flush()` failures via `unittest.mock`. Windows itself has not
  been run.
- Third review: all 37 tests passed with
  `python3 -m unittest discover -s tests -v` on macOS with Python 3.9.6
  (the only interpreter available locally; 3.11 and 3.13 not run locally).
  The strengthened stdin test fails in 4 of its 6 sub-tests against the
  `ip_validator` package from `ab73af1` (pre-fix `rstrip("\r\n")`), and
  passes against the current code.
- Manual check (macOS, Windows stdin simulated by re-wrapping
  `sys.stdin.buffer` with `newline=None` before calling `main`):
  `::1\r\r\n10.0.0.1\r::1\n::1\r` gives three INVALID lines, exit 1.
- Second review: all 37 tests passed with `python3 -m unittest discover -s tests -v` on
  macOS with Python 3.9.6. The suite includes 25 tests already present in
  `ab73af1` and 12 added tests.
- Of the 12 added tests, 10 were verified to fail against the implementation
  of commit `ab73af1`. They cover rejection of control or non-printable
  characters in IPv6 zone IDs, stdin line separators and preserved carriage
  returns, fallback when stdin cannot be reconfigured, and broken stdout
  pipes during validation output and `-h`/`--help`.
- Two added non-regression tests also pass against `ab73af1`.
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

## Continuous Integration (local only, untracked)
- `.github/workflows/tests.yml` is untracked: it is not part of `8600de8`
  nor of PR #1, and has not run on GitHub. It was not modified during the
  third review fixes.
- It runs `python -m unittest discover -s tests -v` in 9 jobs
  (`fail-fast: false`, 15-minute timeout):

  | OS | Python 3.9 | Python 3.11 | Python 3.13 |
  |----|------------|-------------|-------------|
  | `ubuntu-24.04` | job 1 | job 2 | job 3 |
  | `windows-latest` | job 4 | job 5 | job 6 |
  | `macos-latest` | job 7 | job 8 | job 9 |

- Locally, the suite was run natively on macOS with Python 3.9.6, 3.11.17
  and 3.13.17 (the macOS column of the matrix, assuming the runner gets
  similar patch releases). None of the nine jobs has run on GitHub; native
  Ubuntu and Windows validation is still pending.
- Triggers: `push` to `main` and `pull_request` targeting `main`. Once the
  workflow is committed and pushed to `fix/validator-improvements`, PR #1
  (base `main`) will trigger it.
- Permissions: `contents: read` only; checkout with
  `persist-credentials: false`; actions pinned to commit SHAs
  (`actions/checkout` v7.0.1, `actions/setup-python` v7.1.0).
- `ubuntu-24.04` is pinned because setup-python has no Python 3.9 build for
  newer Ubuntu images.
- Verified locally: YAML parses, triggers/matrix/steps as expected; the
  suite now has 45 tests, all passing natively on macOS with Python 3.9.6,
  3.11.17 and 3.13.17 (37 tests at the time of the first local check). The workflow itself has not run on
  GitHub yet; `actionlint` was not available locally.

## Next Task
1. Codex re-audits the third, fourth and fifth review fixes.
2. After user approval, commit `ip_validator/__main__.py`, `HANDOFF.md`,
   `tests/test_validator.py` and `.github/workflows/tests.yml`, and push to `fix/validator-improvements`
   (PR #1 stays a draft).
3. Read the results of the nine CI jobs, especially `windows-latest`, and
   only then decide whether the broken-pipe handling needs a change.

## Known Issues
- Windows behaviour verified only by simulation on macOS (see Tests) until
  the CI runs on `windows-latest`. The strengthened subprocess stdin test
  will exercise real Windows stdin translation there.
- Potential Windows broken-pipe risk (identified by Codex, not reproduced):
  on Windows, writing or flushing to a closed pipe may raise
  `OSError(errno.EINVAL, "Invalid argument")` instead of `BrokenPipeError`.
  `main` only catches `BrokenPipeError`, so such an error would escape with a
  traceback and a status other than 141. Tests likely affected on
  `windows-latest`: `test_module_handles_closed_stdout_pipe` and
  `test_module_help_handles_closed_stdout_pipe`. Decision: no change to the
  handling before the real CI results; no test disabled. If they fail with
  EINVAL, a follow-up fix (with a regression test) should treat that case as
  a closed pipe on Windows only. Interaction with the fourth review fix:
  `_BrokenPipeRecorder` re-raises `BrokenPipeError` only; an `EINVAL`
  during `--help` output is still ignored by argparse on 3.11+ (exit 0)
  and would propagate on 3.9. The fifth review tests with a closed pipe
  (`test_module_argument_errors_with_closed_stderr_pipe`, expected 120 /
  2 / 141, and `test_module_help_with_closed_stderr_pipe_still_prints_help`)
  may also behave differently on Windows if EINVAL is raised instead of
  `BrokenPipeError` (e.g. 3.9 `-u` would not give 141); to be checked
  against the `windows-latest` results.
- The buffered closed-stderr exit status 120 is CPython's status for a
  failed flush at shutdown; verified on macOS only.
- Python 3.14: `-1.2.3.4` without `--` exits 1 instead of 2 (see Fourth
  Review Fixes, item 3); `test_module_exit_codes_and_end_of_options` fails
  on 3.14.9. Not in the CI matrix; decision pending.
- `_ArgumentParser` overrides the private argparse method
  `_print_message`; a future Python release could rename it. The
  subprocess tests would detect such a change.
