# ARCHITECTURE — Dongle Driver Rescue V1

- **Status:** Base aprovada no Milestone 3 (consolidação após pesquisa)
- **Stack:** Python 3.12+ stdlib ([ADR 0001](adr/0001-stack-python.md))
- **Princípios:** evidência citada em toda conclusão, UNKNOWN válido,
  saída determinística ([ADR 0003](adr/0003-evidencia-determinismo.md))

## Mapa de módulos

```text
src/dongle_rescue/
├── cli/            # argparse; comandos identify|diagnose|repair|verify|
│                   # rollback|history|report|doctor; flags --json --verbose
│                   # --debug --non-interactive --no-network
├── core/           # types.py (domínio), diagnosis.py (máquina A-E),
│                   # confidence.py (regras de atribuição)
├── usb/            # enumeration via sysfs + lsusb fallback; parsing de
│                   # descritores; modalias builder
├── linux/          # modules.alias parser, modinfo wrapper, dmesg/journalctl
│                   # reader, udev/modprobe.d inspectors
├── windows/        # V1 somente leitura: Get-PnpDevice/pnputil parsers
│                   # (documentado, executado só em host Windows)
├── identification/ # cadeia de camadas SPEC §7; resolução por revisão
│                   # (btrtl ic_id_table etc.)
├── drivers/        # candidates de modules.alias + base chipsets.json;
│                   # new_id feasibility (incl. .no_dynamic_id)
├── firmware/       # modinfo -F firmware → dmesg → WHENCE index → pacote
│                   # da distro (ADR 0002 S4)
├── diagnostics/    # estados B/C/D/E detectors sobre evidência
├── repair/         # transações, dry-run planner, new_id/bind executor,
│                   # persistência modprobe.d/udev
├── rollback/       # journal de transações idempotentes
├── verification/   # pós-reparo: interface/iw scan/HCI adapter checks
├── security/       # validação S1-S7 (allowlist binários, gramáticas)
├── provenance/     # Evidence objects e serialização
├── reporting/      # texto humano (formato SPEC §40) + JSON schema v1
└── data/           # chipsets.json gerado de docs/research/*.md
```

## Fluxo principal (`dongle-rescue diagnose`)

```text
usb.enumerate ──► identification.resolve ──► drivers.candidates
                                              │
             ┌────────────────────────────────┤
             ▼                                ▼
      firmware.requirements            diagnostics.classify ──► estado A-E/UNKNOWN
             │                                │
             └────────────► reporting.emit ◄──┘
                            (texto | JSON determinístico)
```

## Invariantes entre módulos

1. Nenhum módulo fala com o disco/sistema direto: tudo via `host.Host`
   (injeção; testes usam fixtures sintéticos).
2. Fronteiras externas passam pelas gramáticas de `types.py`
   (hex4, nome de módulo, path de firmware).
3. `chipsets.json` é dado versionado com confiança+citação por linha;
   regenerado dos docs de pesquisa, nunca editado à mão no código.
4. Reparo só existe como plano (dry-run) + transação com rollback;
   execução exige consentimento explícito.
5. Rede: um único ponto de saída, desligável com `--no-network`.

## Decisões abertas (fecham com a pesquisa)

- Formato exato aceito por cada driver em `new_id` (variou por driver:
  `.no_dynamic_id` bloqueia o mecanismo em alguns casos — evidência no
  relatório do agente Realtek).
- Persistência padrão do bind: alias modprobe.d vs regra udev.
- Detecção de pacote de firmware por família de distro.
