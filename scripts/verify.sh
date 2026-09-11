#!/usr/bin/env bash
# Full repository verification, running LOCALLY.
#
# Runs the SAME checks as the .github/workflows/ci.yml jobs. It exists because the
# org's monthly Actions quota has already been consumed: the jobs fail at
# startup ("The job was not started because recent account payments have failed
# or your spending limit needs to be increased") until the month turns over. The
# workflow triggers stay on on purpose, so CI comes back on its own.
#
# Each check exists because of a defect that already reached the repository.
#
# Usage:
#   ./scripts/verify.sh            everything
#   ./scripts/verify.sh --quick    skip the history scan
#   ./scripts/verify.sh fixtures   only one group: fixtures|tests|smoke|secrets

set -uo pipefail
cd "$(dirname "$0")/.."

QUICK=0
ONLY=""
for a in "$@"; do
    case "$a" in
        --quick) QUICK=1 ;;
        fixtures|tests|smoke|secrets) ONLY="$a" ;;
    esac
done

FAILURES=()
WARNINGS=()

title() { printf '\n%s\n  %s\n%s\n' "$(printf '=%.0s' {1..68})" "$1" "$(printf '=%.0s' {1..68})"; }
ok()    { printf '  [OK]    %s\n' "$1"; }
fail()  { printf '  [FAIL] %s\n' "$1"; FAILURES+=("$1"); }
warn()  { printf '  [WARNING] %s\n' "$1"; WARNINGS+=("$1"); }
should_run() { [ -z "$ONLY" ] || [ "$ONLY" = "$1" ]; }

# pick the venv python, if present
PY="./.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3 || true)"

# ------------------------------------------------------------- fixtures ----
if should_run fixtures; then
    title "FIXTURE TREE"
    # Fixtures reproduce sysfs and contain directories like `1-3:1.0`.
    # Colons are reserved on NTFS: a Windows checkout writes mangled 8.3
    # names and marks the real files as deleted — and a `git add -A`
    # in that state DELETES the fixtures from the repository.
    missing_any=0
    for d in \
      "tests/fixtures/tree/mt7601_ok/sys/bus/usb/devices/1-3:1.0" \
      "tests/fixtures/tree/rtl8811cu_unbound/sys/bus/usb/devices/1-2:1.0" \
      "tests/fixtures/tree/collision_760a/sys/bus/usb/devices/1-4:1.0" ; do
        if [ -d "$d" ]; then ok "$d"; else fail "missing: $d"; missing_any=1; fi
    done
    if git ls-files | grep -qE '~[A-Z0-9]{2}\.[0-9]'; then
        fail "mangled 8.3 names committed (broken Windows checkout)"
        git ls-files | grep -E '~[A-Z0-9]{2}\.[0-9]' | sed 's/^/          /'
    else
        ok "no mangled 8.3 names committed"
    fi
    [ "$missing_any" -eq 1 ] && printf '          -> clone and run this repo on Linux/WSL, never on Windows\n'
fi

# ------------------------------------------------------------------ tests ---
if should_run tests; then
    title "TESTS + COVERAGE (85% gate)"
    if [ -z "$PY" ]; then
        warn "python3 missing; tests skipped"
    elif ! "$PY" -c 'import pytest' 2>/dev/null; then
        warn "pytest missing; run: $PY -m pip install pytest pytest-cov"
    else
        output=$(PYTHONPATH=src "$PY" -m pytest tests/ -q --no-header \
                  --cov=src/dongle_rescue --cov-report=term \
                  --cov-fail-under=85 2>&1)
        rc=$?
        result_line=$(echo "$output" | grep -E 'passed|failed' | tail -1)
        cov=$(echo "$output" | grep -E '^TOTAL' | awk '{print $NF}')
        if [ $rc -eq 0 ]; then ok "${result_line:-tests ok} | coverage ${cov:-?}"
        else
            fail "tests/coverage failed (${cov:-?})"
            echo "$output" | grep -E 'FAILED|Required test coverage' | head -8 | sed 's/^/          /'
        fi
    fi
fi

# ------------------------------------------------------------------ smoke ---
if should_run smoke; then
    title "CLI SMOKE (real entry point)"
    # The CLI was once COMPLETELY broken while all 186 tests passed:
    # main() never injected the real host and the __main__ guard was missing, so
    # `python -m ...` exited with code 0 without printing ANYTHING. No unit
    # test caught it, because all of them inject a fake host.
    if [ -z "$PY" ]; then
        warn "python3 missing; smoke skipped"
    else
        output=$(PYTHONPATH=src "$PY" -m dongle_rescue.cli.main doctor 2>&1)
        if [ -z "$output" ]; then
            fail "\`python -m\` printed nothing (__main__ guard missing?)"
        else
            ok "CLI produces output"
            for expected in "kernel release:" "journalctl available:" "reboot pending:" ; do
                if echo "$output" | grep -q "$expected"; then ok "reports '$expected'"
                else fail "does not report '$expected' (real host not injected?)"; fi
            done
        fi
    fi
fi

# ---------------------------------------------------------------- secrets ---
if should_run secrets; then
    title "SECRETS"
    # `senha` is Portuguese for "password": the tree scan intentionally matches
    # password assignments in English and Portuguese (plus passwd).
    patterns='ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|gho_[A-Za-z0-9]{30,}|BEGIN [A-Z ]*PRIVATE KEY|(password|senha|passwd)[[:space:]]*[:=][[:space:]]*["\x27][^"\x27]{3,}'
    if git grep -nEI "$patterns" -- . >/dev/null 2>&1; then
        fail "secret in working tree"
        git grep -nEI "$patterns" -- . | head -5 | sed 's/^/          /'
    else
        ok "no secrets in working tree"
    fi
    if [ "$QUICK" -eq 1 ]; then
        warn "--quick: history scan skipped"
    elif git log -p --all -G "$patterns" --oneline 2>/dev/null | head -1 | grep -q .; then
        fail "secret in history"
        git log --all -G "$patterns" --oneline 2>/dev/null | head -3 | sed 's/^/          /'
    else
        ok "no secrets in full history"
    fi
fi

# ---------------------------------------------------------------- summary ---
title "SUMMARY"
if [ ${#WARNINGS[@]} -gt 0 ]; then
    printf '  warnings (%d):\n' "${#WARNINGS[@]}"
    for a in "${WARNINGS[@]}"; do printf '    - %s\n' "$a"; done
fi
if [ ${#FAILURES[@]} -eq 0 ]; then
    printf '\n  ALL GREEN\n\n'; exit 0
fi
printf '\n  %d FAILURE(S):\n' "${#FAILURES[@]}"
for f in "${FAILURES[@]}"; do printf '    - %s\n' "$f"; done
printf '\n'
exit 1
