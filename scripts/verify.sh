#!/usr/bin/env bash
# Verificacao completa do repositorio, rodando LOCALMENTE.
#
# Roda as MESMAS checagens dos jobs de .github/workflows/ci.yml. Existe porque a
# franquia mensal de Actions da organizacao ja foi consumida: os jobs falham no
# arranque ("The job was not started because recent account payments have failed
# or your spending limit needs to be increased") ate a virada do mes. Os
# gatilhos do workflow ficam ligados de proposito, para o CI voltar sozinho.
#
# Cada checagem existe por causa de um defeito que ja chegou ao repositorio.
#
# Uso:
#   ./scripts/verify.sh            tudo
#   ./scripts/verify.sh --quick    pula a varredura de historico
#   ./scripts/verify.sh fixtures   so um grupo: fixtures|tests|smoke|secrets

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

FALHAS=()
AVISOS=()

titulo() { printf '\n%s\n  %s\n%s\n' "$(printf '=%.0s' {1..68})" "$1" "$(printf '=%.0s' {1..68})"; }
ok()     { printf '  [OK]    %s\n' "$1"; }
falha()  { printf '  [FALHA] %s\n' "$1"; FALHAS+=("$1"); }
aviso()  { printf '  [AVISO] %s\n' "$1"; AVISOS+=("$1"); }
rodar()  { [ -z "$ONLY" ] || [ "$ONLY" = "$1" ]; }

# escolhe o python do venv, se existir
PY="./.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3 || true)"

# ------------------------------------------------------------- fixtures ----
if rodar fixtures; then
    titulo "ARVORE DE FIXTURES"
    # As fixtures reproduzem o sysfs e contem diretorios como `1-3:1.0`.
    # Dois-pontos e reservado no NTFS: um checkout Windows grava nomes 8.3
    # mutilados e marca os arquivos reais como deletados — e um `git add -A`
    # nesse estado APAGA as fixtures do repositorio.
    faltando=0
    for d in \
      "tests/fixtures/tree/mt7601_ok/sys/bus/usb/devices/1-3:1.0" \
      "tests/fixtures/tree/rtl8811cu_unbound/sys/bus/usb/devices/1-2:1.0" \
      "tests/fixtures/tree/collision_760a/sys/bus/usb/devices/1-4:1.0" ; do
        if [ -d "$d" ]; then ok "$d"; else falha "ausente: $d"; faltando=1; fi
    done
    if git ls-files | grep -qE '~[A-Z0-9]{2}\.[0-9]'; then
        falha "nomes 8.3 mutilados versionados (checkout Windows quebrado)"
        git ls-files | grep -E '~[A-Z0-9]{2}\.[0-9]' | sed 's/^/          /'
    else
        ok "nenhum nome 8.3 mutilado versionado"
    fi
    [ "$faltando" -eq 1 ] && printf '          -> clone e rode este repo em Linux/WSL, nunca em Windows\n'
fi

# ---------------------------------------------------------------- testes ---
if rodar tests; then
    titulo "TESTES + COBERTURA (gate 85%)"
    if [ -z "$PY" ]; then
        aviso "python3 ausente; testes pulados"
    elif ! "$PY" -c 'import pytest' 2>/dev/null; then
        aviso "pytest ausente; rode: $PY -m pip install pytest pytest-cov"
    else
        saida=$(PYTHONPATH=src "$PY" -m pytest tests/ -q --no-header \
                  --cov=src/dongle_rescue --cov-report=term \
                  --cov-fail-under=85 2>&1)
        rc=$?
        linha=$(echo "$saida" | grep -E 'passed|failed' | tail -1)
        cob=$(echo "$saida" | grep -E '^TOTAL' | awk '{print $NF}')
        if [ $rc -eq 0 ]; then ok "${linha:-testes ok} | cobertura ${cob:-?}"
        else
            falha "testes/cobertura reprovaram (${cob:-?})"
            echo "$saida" | grep -E 'FAILED|Required test coverage' | head -8 | sed 's/^/          /'
        fi
    fi
fi

# ----------------------------------------------------------------- smoke ---
if rodar smoke; then
    titulo "SMOKE DO CLI (ponto de entrada real)"
    # O CLI ja esteve COMPLETAMENTE inoperante enquanto os 186 testes passavam:
    # main() nunca injetava o host real e faltava o guard __main__, entao
    # `python -m ...` saia com codigo 0 sem imprimir NADA. Nenhum teste
    # unitario pegava, porque todos injetam host falso.
    if [ -z "$PY" ]; then
        aviso "python3 ausente; smoke pulado"
    else
        saida=$(PYTHONPATH=src "$PY" -m dongle_rescue.cli.main doctor 2>&1)
        if [ -z "$saida" ]; then
            falha "\`python -m\` nao imprimiu nada (guard __main__ ausente?)"
        else
            ok "o CLI produz saida"
            for esperado in "kernel release:" "journalctl available:" "reboot pending:" ; do
                if echo "$saida" | grep -q "$esperado"; then ok "reporta '$esperado'"
                else falha "nao reporta '$esperado' (host real nao injetado?)"; fi
            done
        fi
    fi
fi

# -------------------------------------------------------------- segredos ---
if rodar secrets; then
    titulo "SEGREDOS"
    padroes='ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|gho_[A-Za-z0-9]{30,}|BEGIN [A-Z ]*PRIVATE KEY|(password|senha|passwd)[[:space:]]*[:=][[:space:]]*["\x27][^"\x27]{3,}'
    if git grep -nEI "$padroes" -- . >/dev/null 2>&1; then
        falha "segredo na arvore de trabalho"
        git grep -nEI "$padroes" -- . | head -5 | sed 's/^/          /'
    else
        ok "nenhum segredo na arvore de trabalho"
    fi
    if [ "$QUICK" -eq 1 ]; then
        aviso "--quick: varredura de historico pulada"
    elif git log -p --all -G "$padroes" --oneline 2>/dev/null | head -1 | grep -q .; then
        falha "segredo no historico"
        git log --all -G "$padroes" --oneline 2>/dev/null | head -3 | sed 's/^/          /'
    else
        ok "nenhum segredo no historico completo"
    fi
fi

# ---------------------------------------------------------------- resumo ---
titulo "RESUMO"
if [ ${#AVISOS[@]} -gt 0 ]; then
    printf '  avisos (%d):\n' "${#AVISOS[@]}"
    for a in "${AVISOS[@]}"; do printf '    - %s\n' "$a"; done
fi
if [ ${#FALHAS[@]} -eq 0 ]; then
    printf '\n  TUDO VERDE\n\n'; exit 0
fi
printf '\n  %d FALHA(S):\n' "${#FALHAS[@]}"
for f in "${FALHAS[@]}"; do printf '    - %s\n' "$f"; done
printf '\n'
exit 1
