# ADR 0003 — Evidence, determinism, and epistemic honesty

- **Status:** Accepted
- **Date:** 2026-08-22
- **Responsible:** Lead Engineering Agent (ox-alpha)

## Context

The SPEC §§1, 9, 28, 35–37 define the product as a deterministic diagnostician:
every conclusion carries cited evidence; when the evidence is insufficient, the answer
is `UNKNOWN`; critical hypotheses require independent validation. The forbidden
failure mode is the silent guess — the same one that makes "driver updaters" dangerous.

## Decisions

### D1 — Every derived fact carries provenance

Each conclusion emitted by the tool references the evidence that produced it:

```text
evidence_id → source (file/command/package) → experiment → result
```

Single runtime representation (`Evidence` object) and serialization in the
output JSON (SPEC §27). Without attached evidence, a conclusion does not compile in the flow —
diagnostic functions require `Evidence` as an argument.

### D2 — Closed confidence scale

Exactly five levels (SPEC §28): `CONFIRMED`, `HIGH_CONFIDENCE`, `PROBABLE`,
`POSSIBLE`, `UNKNOWN`. Assignment rules documented per layer
(SPEC §7): USB descriptor read = CONFIRMED for device existence;
modules.alias match = HIGH_CONFIDENCE for driver candidacy; upstream
table (btrtl ic_id_table) = CONFIRMED for firmware decisions.

### D3 — UNKNOWN is a valid result, not an exception

Any chain that does not close returns `UNKNOWN` + an explanation of the missing link +
a declared manual path (SPEC §11: `identify --chip`, board photo, USB dump).
Never infer a chipset from a commercial brand.

### D4 — Output determinism

Same system state ⇒ same report: stable list ordering
(by canonical key, not by mtime/readdir order), no embedded timestamps
in comparable fields, pinned schema version (`schema_version: 1`). This is what
enables byte-for-byte regression tests over fixtures.

### D5 — Consensus for critical decisions

Chipset→module→firmware mappings published in the product (consolidated research
data) are admitted only after: agent A researches, agent B
independently researches, agent C tries to refute; divergence is resolved by a
primary source (kernel code / WHENCE), never by persuasion. Each consolidated-table
row carries the D2 confidence level and the citation.

### D6 — Reversible transactions

Every mutation (repair) produces a transaction with before_state/change/after_state/
rollback_action (SPEC §24); idempotent rollback; nothing executes without an
available equivalent dry-run (SPEC §23).

## Consequences

- Regression tests compare full JSON against golden files per fixture.
- The consolidated chipset table lives in versioned data
  (`src/dongle_rescue/data/chipsets.json`) generated from
  `docs/research/*.md`, never hand-typed in code.
