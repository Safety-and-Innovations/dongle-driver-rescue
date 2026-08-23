# Research — acesso a logs de kernel sem root & reboot pendente

Data: 2026-08-23 · Host do experimento: Ubuntu 24.04 arm64 VM (usuário
`ubuntu`, grupos `adm cdrom sudo dip lxd docker`).

## 1. Matriz de acesso observada (CONFIRMED neste host)

| Comando | argv (shell=False) | Resultado |
|---|---|---|
| dmesg | `/usr/bin/dmesg` | `dmesg: read kernel buffer failed: Operation not permitted`, **exit 1** (`dmesg_restrict=1`) |
| journalctl | `/usr/bin/journalctl -k --no-pager -o short` | funciona, **exit 0** — usuário no grupo `adm` |

Regras documentadas: `dmesg_restrict=1` exige CAP_SYSLOG; leitura do journal é
liberada para membros de `systemd-journal`/`adm`/`wheel`
(man sd_journal_access / journald.conf). Ambos os binários vivem em
`/usr/bin/` aqui; em sistemas split-usr podem estar em `/bin` (mesmo arquivo).

## 2. Estratégia recomendada (ADR 0002 S1/S2)

1. Tentar `/usr/bin/journalctl -k --no-pager -o short` (cobre Ubuntu/Fedora/
   Arch com systemd; exit 0 sem root nos grupos acima).
2. Fallback `/usr/bin/dmesg`; negação mapeada para HostError com a mensagem
   observada e instrução ("adicione o usuário ao grupo adm/systemd-journal ou
   reexecute privilegiado").
3. Nunca shell intermediário; argv arrays literais.

## 3. Reboot pendente (linux-kernel.md §6 item 1)

Sinais, por risco de falso-positivo:

1. **Kernel instalado mais novo que `uname -r`** em `/lib/modules/` — sinal
   forte; comparação numérica (abinum incluído); strings incomparáveis NUNCA
   contam como mais novas (conservador).
   CONFIRMED aqui: módulos 1018/1019/1020 + uname 1018 + dpkg linux-image
   1018/1020 → pendente real.
2. **`/var/run/reboot-required`** (marcador vazio, root-owned) — grosso, mas
   raramente falso-positivo. Presente neste host.

## 4. READY FOR IMPLEMENTATION

Implementado em `src/dongle_rescue/linux/log_access.py`:
`JOURNALCTL_ARGV`/`DMESG_ARGV`, `collect_kernel_log()` (plano determinístico
para doctor) e `reboot_pending(host, running_release)` → `(True|False|None,
explicação)`; None = indeterminado (SPEC §37). Testes:
tests/test_log_access.py.
