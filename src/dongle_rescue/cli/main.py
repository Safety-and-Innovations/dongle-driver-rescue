"""CLI entry points (SPEC §26): identify, diagnose, repair, verify, rollback,
history, report, doctor. Flags: --json, --verbose, --debug, --non-interactive,
--no-network.

Design (SPEC §37 / ADR 0002 S1/S5):
- `run(argv, host=..., kb=..., journal=...)` returns (exit_code, text) so the
  whole CLI is unit-testable without a terminal.
- Repair is ALWAYS dry-run; execution requires --execute, which V1 refuses
  with exit code 3 after printing the plan.
- Exit codes: 0 ok · 2 unknown device · 3 repair refused · 4 not found.
"""

from __future__ import annotations

import json
import platform
from typing import Any

from ..diagnostics.classifier import classify
from ..firmware.resolver import (
    detect_package_managers,
    load_chipset_kb,
    parse_dmesg_firmware_failures,
)
from ..identification.resolver import resolve_device
from ..linux.modules_alias import match_with_lines, read_alias_lines
from ..host import RealHost
from ..linux.log_access import plan_kernel_log_access, reboot_pending
from ..repair.planner import plan_state_b
from ..repair.transaction import Journal, plan_rollback
from ..types import DiagnosisState
from ..usb.enumeration import bound_driver, enumerate_usb_devices

EXIT_OK = 0
EXIT_UNKNOWN = 2
EXIT_REFUSED = 3
EXIT_NOT_FOUND = 4


def run(
    argv: list[str],
    *,
    host=None,
    kb: dict | None = None,
    journal_path: str | None = None,
    stdin_lines: list[str] | None = None,
) -> tuple[int, str]:
    """Parse argv and dispatch. Returns (exit_code, stdout_text)."""
    kb = kb if kb is not None else load_chipset_kb()
    opts, args = _parse(argv)
    if not args:
        return EXIT_OK, _usage()
    cmd, rest = args[0], args[1:]

    if cmd == "diagnose":
        return _cmd_diagnose(opts, host, kb)
    if cmd == "identify":
        return _cmd_identify(opts, host, kb)
    if cmd == "repair":
        return _cmd_repair(opts, host, kb, journal_path)
    if cmd == "history":
        jp = _opt_value(opts, "--journal") or journal_path
        return _cmd_history(jp)
    if cmd == "rollback":
        jp = _opt_value(opts, "--journal") or journal_path
        return _cmd_rollback(rest, jp)
    if cmd == "verify":
        return _cmd_verify(opts, host, kb)
    if cmd == "report":
        return _cmd_diagnose(opts, host, kb)  # same content; reporting layer later
    if cmd == "doctor":
        return _cmd_doctor(host, kb)
    return EXIT_OK, f"unknown command: {cmd}\n{_usage()}"


# ------------------------------------------------------------------ plumbing


def _parse(argv: list[str]) -> tuple[list[tuple[str, str | None]], list[str]]:
    opts: list[tuple[str, str | None]] = []
    positional: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok.startswith("--"):
            if "=" in tok:
                k, v = tok.split("=", 1)
                opts.append((k, v))
                i += 1
                continue
            nxt = argv[i + 1] if i + 1 < len(argv) else None
            if nxt is not None and not nxt.startswith("--"):
                opts.append((tok, nxt))
                i += 2
            else:
                opts.append((tok, None))
                i += 1
            continue
        positional.append(tok)
        i += 1
    return opts, positional


def _has(opts, name: str) -> bool:
    return any(k == name for k, _ in opts)


def _opt_value(opts, name: str) -> str | None:
    for k, v in opts:
        if k == name:
            return v
    return None


def _usage() -> str:
    return (
        "dongle-rescue <command> [options]\n"
        "commands: identify diagnose repair verify rollback history report doctor\n"
        "flags: --json --verbose --debug --non-interactive --no-network\n"
        "       --kernel-release R --device VID:PID --chip NAME --journal P\n"
        "       --dry-run --execute\n"
    )


def _pick_device(host, vid_pid: str | None):
    devs = enumerate_usb_devices(host) if host else []
    if vid_pid:
        want = vid_pid.lower()
        devs = [d for d in devs if d.vid_pid == want]
    return devs[0] if devs else None


def _dmesg_for(host) -> list[str]:
    # V1: dmesg comes from an injectable fixture file when running on fixtures;
    # real collection lands with the privileged diagnostics layer.
    try:
        raw = host.read("/proc/dmesg_fixtures")  # never present on fixtures
        return raw.splitlines()
    except Exception:
        return []


def _diagnose_one(device, host, kb, release: str | None, chip_override: str | None):

    rel = release or platform.release()
    alias_lines = read_alias_lines(host, rel) if (host and rel) else []
    res = resolve_device(device, alias_lines, kb)
    if chip_override:
        from ..types import ChipsetId, Confidence

        res_chipset = ChipsetId(
            chipset=chip_override,
            family="manual",
            confidence=Confidence.HIGH_CONFIDENCE,
            revision_note=None,
            evidence=res.chipset_id.evidence,
        )
        from ..identification.resolver import DiagnosisInput
        import dataclasses

        res = dataclasses.replace(res, chipset_id=res_chipset)
    iface = device.sysfs_path + ":1.0"
    drv = bound_driver(host, iface) or bound_driver(host, device.sysfs_path)
    diagnosis = classify(res, bound_driver=drv, dmesg_lines=[], modprobe_d={})
    plan = plan_state_b(device=device, kb=kb, bound_driver=drv)
    return diagnosis, plan


# ----------------------------------------------------------------- commands


def _cmd_diagnose(opts, host, kb):
    release = _opt_value(opts, "--kernel-release")
    dev_spec = _opt_value(opts, "--device")
    device = _pick_device(host, dev_spec)
    if device is None:
        return (
            EXIT_UNKNOWN,
            "UNKNOWN — no diagnosable USB device found.\n"
            "Continue manually with `dongle-rescue identify --chip <name>` "
            "(SPEC §11).\n",
        )
    diagnosis, plan = _diagnose_one(device, host, kb, release, None)

    if _has(opts, "--json"):
        doc = diagnosis.to_dict()
        doc["dry_run_plan"] = {
            "feasible": plan.feasible,
            "what": plan.what,
            "files_affected": sorted(plan.files_affected),
            "commands": list(plan.commands),
            "transaction_id": getattr(plan.transaction, "transaction_id", None),
        }
        return EXIT_OK, json.dumps(doc, indent=1, sort_keys=True) + "\n"

    state_label = f"STATE {diagnosis.state.value}"
    lines = [
        "Dongle Driver Rescue",
        "====================",
        "",
        f"USB:          {device.vid_pid}  rev {device.bcd_device}",
        f"Product:      {device.product or '?'}",
        f"Chipset:      {diagnosis.identification.chipset}"
        f"  ({diagnosis.identification.confidence.value})",
        f"Candidates:   "
        + (
            ", ".join(dict.fromkeys(c.module for c in diagnosis.driver_candidates))
            or "-"
        ),
        f"Diagnosis:    {state_label}"
        f"  [{diagnosis.confidence.value}]",
        f"Action:       {diagnosis.recommended_action.kind}",
        "",
        "Evidence:",
    ]
    for ev in diagnosis.evidence[:6]:
        lines.append(f"  - {ev.source}: {ev.detail}")
    lines += ["", "Dry-run repair plan:"]
    if plan.feasible:
        lines.append(f"  WHAT:      {plan.what}")
        lines.append(f"  FILES:     {', '.join(plan.files_affected)}")
        for c in plan.commands:
            lines.append(f"  COMMAND:   {c}")
        lines.append(f"  ROLLBACK:  {plan.rollback}")
        lines.append("  (display only — nothing was executed)")
    else:
        lines.append(f"  {plan.what}: {plan.why}")
        lines.append(f"  official origin: {plan.official_origin}")
    if diagnosis.state == DiagnosisState.A_WORKING:
        lines.append("NO_ACTION_REQUIRED")
    return EXIT_OK, "\n".join(lines) + "\n"


def _cmd_identify(opts, host, kb):
    chip = _opt_value(opts, "--chip")
    if not chip:
        return EXIT_OK, "identify: pass --chip NAME to continue manually (SPEC §11)\n"
    known = any(c.get("chipset") == chip for c in kb.get("chipsets", []))
    body = (
        f"Manual chip identification accepted: {chip}\n"
        f"KB coverage: {'yes' if known else 'no — treated as UNKNOWN'}\n"
        "Attach evidence (photos, descriptor dump, HCI info) to the case file.\n"
    )
    return EXIT_OK, body


def _cmd_repair(opts, host, kb, journal_path):
    release = _opt_value(opts, "--kernel-release")
    dev_spec = _opt_value(opts, "--device")
    chip = _opt_value(opts, "--chip")

    if chip:
        # explicit-chip path: build the plan straight from the KB entry
        entry = next(
            (e for e in kb.get("chipsets", []) if e["chipset"] == chip), None
        )
        if entry is None:
            return EXIT_NOT_FOUND, f"chip {chip} not covered by the knowledge base\n"
        device = _pick_device(host, dev_spec)
        if device is None:
            return EXIT_UNKNOWN, "no USB device present for the requested repair\n"
        plan = plan_state_b(device=device, kb=kb, bound_driver=None)
        feasible_hint = bool(entry.get("new_id_feasible"))
        if not plan.feasible is False and not feasible_hint:
            from ..repair.planner import EMPTY_PLAN
            from dataclasses import replace as _dc_replace

            plan = _dc_replace(
                EMPTY_PLAN,
                why=f"{chip} driver rejects dynamic IDs (no_dynamic_id); "
                    "binding by new_id is not feasible.",
                source=f"chipsets.json[{chip}]",
                confidence=str(entry.get("confidence", "UNKNOWN")),
            )
    else:
        device = _pick_device(host, dev_spec)
        if device is None:
            return EXIT_UNKNOWN, "no diagnosable USB device found\n"
        _, plan = _diagnose_one(device, host, kb, release, None)

    out = ["Repair plan (DRY RUN — nothing executed)", ""]
    out.append(f"  WHAT:           {plan.what}")
    out.append(f"  WHY:            {plan.why}")
    out.append(f"  SOURCE:         {plan.source}")
    ev_lines = [f"{ev.source}: {ev.detail}" for ev in plan.evidence[:3]] or ["-"]
    out.append("  EVIDENCE:       " + "; ".join(ev_lines))
    out.append(f"  CONFIDENCE:     {plan.confidence}")
    out.append(f"  FILES AFFECTED: {', '.join(plan.files_affected) or '-'}")
    for c in plan.commands:
        out.append(f"  COMMANDS:       {c}")
    out.append(f"  ROLLBACK:       {plan.rollback}")
    tid = getattr(plan.transaction, "transaction_id", None)
    if tid:
        out.append(f"  TRANSACTION:    {tid}")
    if not plan.feasible:
        out.append(f"  OFFICIAL ORIGIN: {plan.official_origin}")

    # V1 policy (SPEC §37): the tool NEVER executes repairs. Any request
    # that asks for real execution (--execute) is refused with exit code 3;
    # the default invocation stays a pure dry-run (exit 0).
    if _has(opts, "--execute"):
        out.append("")
        out.append(
            "REFUSED: execution is not available in V1 (SPEC §37). Apply the "
            "printed commands manually; the transaction id above keys the "
            "rollback."
        )
        return EXIT_REFUSED, "\n".join(out) + "\n"

    out.append("")
    out.append("(not executed — this was a dry run)")
    return EXIT_OK, "\n".join(out) + "\n"


def _cmd_history(journal_path: str | None):
    if not journal_path:
        return EXIT_OK, "no transactions (no journal configured)\n"
    j = Journal(journal_path)
    try:
        records = j.load()
    except ValueError as exc:
        return EXIT_NOT_FOUND, f"history error: {exc}\n"
    if not records:
        return EXIT_OK, "no transactions recorded yet\n"
    lines = ["transactions:"]
    for r in records:
        lines.append(
            f"  {r.transaction_id[:12]}  {r.change.get('op', '?')}  "
            f"rollback={r.rollback_action.get('op', '?')}"
        )
    return EXIT_OK, "\n".join(lines) + "\n"


def _cmd_rollback(rest: list[str], journal_path: str | None):
    if not rest:
        return EXIT_NOT_FOUND, "rollback: pass a transaction-id\n"
    wanted = rest[0]
    if not journal_path:
        return EXIT_NOT_FOUND, "rollback: no journal configured\n"
    records = Journal(journal_path).load()
    match = [r for r in records if r.transaction_id.startswith(wanted)]
    if not match:
        return EXIT_NOT_FOUND, f"rollback: transaction {wanted[:12]} not found\n"
    rec = match[0]
    steps = plan_rollback(rec)
    lines = [f"Rollback plan for {rec.transaction_id[:12]} (nothing executed):"]
    for s in steps:
        lines.append(f"  step {s['seq']}: {s['action']} {s.get('path', s.get('vid_pid', ''))}"
                     f"  if_present={s.get('if_present')}")
    lines.append("Applying twice is a declared no-op (idempotent, SPEC §24).")
    return EXIT_OK, "\n".join(lines) + "\n"


def _cmd_verify(opts, host, kb):
    """SPEC §25: functional verification after a repair (offline checks)."""
    if host is None:
        return EXIT_OK, "verify: no host available\n"
    dev_spec = _opt_value(opts, "--device")
    device = _pick_device(host, dev_spec)
    if device is None:
        return EXIT_UNKNOWN, "verify: no device present\n"
    from ..verification.checker import verify_device

    iface = device.sysfs_path + ":1.0"
    kind = "wifi"  # BT detection via interface class lands with live probing
    rep = verify_device(host, kind=kind, sysfs_iface=iface, dmesg_lines=[])
    lines = [f"Verification ({kind}):", f"  verdict: {rep.verdict}"]
    for c in rep.checks:
        state = {True: "PASS", False: "FAIL", None: "UNKNOWN"}[c.passed]
        lines.append(f"  {c.name:22} {state:7} {c.detail}")
    if rep.verdict == "HARDWARE_FUNCTIONAL":
        lines.append("RESULT: HARDWARE FUNCTIONAL")
    elif rep.verdict == "UNKNOWN":
        lines.append("RESULT: UNKNOWN — host reads failed; inspect manually")
    else:
        lines.append("RESULT: NOT FUNCTIONAL — see failed checks above")
    return EXIT_OK, "\n".join(lines) + "\n"


def _cmd_verify_placeholder():
    return (
        EXIT_OK,
        "verify: functional radio checks land with the verification layer "
        "(SPEC §25); nothing to verify without a completed repair.\n",
    )


def _cmd_doctor(host, kb):
    release = platform.release()
    lines = [f"kernel release: {release}"]
    alias_ok = False
    if host is not None:
        try:
            alias_ok = bool(read_alias_lines(host, release))
        except Exception:
            alias_ok = False
    lines.append(f"modules.alias readable: {'yes' if alias_ok else 'NO'}")
    mgrs = detect_package_managers()
    lines.append(f"package manager detected: {', '.join(mgrs) if mgrs else 'none'}")
    lines.append(f"knowledge base entries: {len(kb.get('chipsets', []))}")
    lines.append("network policy: offline by default (--no-network respected)")

    # Acesso ao log do kernel: o `doctor` existe para dizer o que dá para
    # inspecionar nesta máquina, e ler o dmesg é parte central do diagnóstico
    # de estado C. O planejador existia mas não era chamado por ninguém.
    if host is not None:
        try:
            tem_journalctl, plano = plan_kernel_log_access(host, release)
            lines.append(f"journalctl available: {'yes' if tem_journalctl else 'NO'}")
            lines.append(f"kernel log plan: {plano}")
        except Exception as exc:  # nunca derruba o doctor
            lines.append(f"kernel log plan: unavailable ({exc})")

        pendente, motivo = reboot_pending(host, release)
        estado = {True: "yes", False: "no", None: "unknown"}[pendente]
        lines.append(f"reboot pending: {estado} ({motivo})")

    return EXIT_OK, "\n".join(lines) + "\n"


def main() -> int:  # console_scripts entry point
    import sys

    # O HOST REAL entra aqui.
    #
    # `run()` aceita host=None porque e a costura de injecao usada pelos testes.
    # Mas main() tambem chamava run() SEM host, entao em producao host era
    # sempre None: `enumerate_usb_devices(host) if host else []` devolvia lista
    # vazia, `verify` respondia "no host available" e o `doctor` pulava tudo que
    # depende da maquina. Ou seja, a ferramenta nunca conseguia diagnosticar um
    # dongle de verdade pela linha de comando — so pelos testes, que injetam um
    # host falso. RealHost ja existia (host.py) e nunca era instanciado.
    code, text = run(sys.argv[1:], host=RealHost())
    print(text, end="")
    return code


# `python -m dongle_rescue.cli.main <cmd>` precisa deste guard.
#
# Sem ele o modulo era apenas importado: definia tudo, nao chamava nada e saia
# com codigo 0 SEM IMPRIMIR NADA. O entry point de console (dongle-rescue,
# declarado no pyproject) funcionava, mas a invocacao que o proprio README
# documenta rodava em silencio.
if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
