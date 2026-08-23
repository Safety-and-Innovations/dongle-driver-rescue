"""TDD: log access plan + reboot-pending detector.

Facts CONFIRMED on this host (Ubuntu 24.04 arm64, user 'ubuntu' in 'adm'):
- dmesg_restrict=1 → dmesg(1) fails "Operation not permitted" exit 1
- journalctl -k works (exit 0) for adm/systemd-journal members
- /lib/modules may hold kernels newer than uname -r → reboot pending
"""

from __future__ import annotations

from dongle_rescue.host import Host, HostError
from dongle_rescue.linux.log_access import (
    plan_kernel_log_access,
    DMESG_ARGV,
    JOURNALCTL_ARGV,
    reboot_pending,
)


class MapHost(Host):
    """Minimal dict-backed host."""

    def __init__(self, files=None, dirs=None):
        self.files = set(files or [])
        self.dirs = {k: list(v) for k, v in (dirs or {}).items()}

    def read(self, path):
        if path in self.files:
            return ""
        raise HostError(f"read {path}: No such file")

    def exists(self, path):
        return path in self.files or path in self.dirs

    def listdir(self, path):
        if path in self.dirs:
            return list(self.dirs[path])
        raise HostError(f"listdir {path}: No such file")

    def resolve_realpath(self, path):
        return path


def test_journalctl_argv_is_shell_false_safe():
    assert JOURNALCTL_ARGV == ["/usr/bin/journalctl", "-k", "--no-pager", "-o", "short"]
    assert DMESG_ARGV == ["/usr/bin/dmesg"]
    for argv in (JOURNALCTL_ARGV, DMESG_ARGV):
        assert all(isinstance(a, str) for a in argv)
        assert " " not in " ".join(argv).split("/usr/bin/", 1)[0]


def test_reboot_pending_when_newer_kernel_installed():
    host = MapHost(
        files=["/var/run/reboot-required"],
        dirs={"/lib/modules": ["6.17.0-1018-oracle", "6.17.0-1020-oracle"]},
    )
    pending, why = reboot_pending(host, running_release="6.17.0-1018-oracle")
    assert pending is True
    assert "1020" in why and "newer" in why


def test_not_pending_when_running_is_newest():
    host = MapHost(dirs={"/lib/modules": ["6.17.0-1018-oracle"]})
    pending, why = reboot_pending(host, running_release="6.17.0-1018-oracle")
    assert pending is False
    assert "newest" in why


def test_marker_alone_counts_as_pending():
    host = MapHost(files=["/var/run/reboot-required"],
                   dirs={"/lib/modules": []})
    pending, why = reboot_pending(host, running_release="6.17.0-1018-oracle")
    assert pending is True
    assert "reboot-required" in why


def test_older_kernels_do_not_trigger_pending():
    host = MapHost(dirs={"/lib/modules": ["6.17.0-1018-oracle",
                                          "6.17.0-1017-oracle"]})
    pending, _ = reboot_pending(host, running_release="6.17.0-1018-oracle")
    assert pending is False


def test_unreadable_modules_dir_is_unknown_never_false():
    host = MapHost()  # nothing readable
    pending, why = reboot_pending(host, running_release="6.17.0-1018-oracle")
    assert pending is None
    assert why


def test_non_comparable_release_strings_never_claim_newer():
    host = MapHost(dirs={"/lib/modules": ["weird-custom-build"]})
    pending, _ = reboot_pending(host, running_release="6.17.0-1018-oracle")
    assert pending is False  # conservative: no false positive


# ---------------------------------------------------------------------------
# plan_kernel_log_access: era `collect_kernel_log`, que prometia coletar o log
# e devolvia None em todos os caminhos. Nunca foi chamada por produção nem por
# teste — a cobertura mostrava as linhas sem execução alguma. Agora o `doctor`
# a usa, e estes testes fixam o contrato.
# ---------------------------------------------------------------------------


class _HostFalso:
    """Host mínimo: decide se journalctl existe e registra o que perguntaram."""

    def __init__(self, com_journalctl: bool):
        self.com_journalctl = com_journalctl
        self.consultados: list[str] = []

    def exists(self, path):
        self.consultados.append(path)
        return self.com_journalctl and path == "/usr/bin/journalctl"

    def read(self, path):
        raise AssertionError("o planejador nao deve LER nada, so planejar")

    def listdir(self, path):
        raise AssertionError("o planejador nao deve listar nada")

    def resolve_realpath(self, path):
        return path


def test_plano_usa_journalctl_quando_disponivel():
    host = _HostFalso(com_journalctl=True)

    tem, plano = plan_kernel_log_access(host, release="6.17.0-1018-oracle")

    assert tem is True
    assert "journalctl" in plano
    assert "6.17.0-1018-oracle" in plano
    # o fallback continua descrito, com o sintoma exato da negativa
    assert "dmesg" in plano
    assert "Operation not permitted" in plano


def test_plano_cai_para_dmesg_sem_journalctl():
    host = _HostFalso(com_journalctl=False)

    tem, plano = plan_kernel_log_access(host, release="6.17.0-1018-oracle")

    assert tem is False
    assert "dmesg" in plano
    assert "nao encontrado" in plano or "não encontrado" in plano


def test_planejador_nao_executa_nem_le_nada():
    """SPEC 37: o nucleo puro nao cria processos nem le arquivos aqui."""
    host = _HostFalso(com_journalctl=True)

    plan_kernel_log_access(host, release="6.17.0-1018-oracle")

    # se tivesse lido algo, o _HostFalso teria levantado AssertionError
    assert host.consultados == ["/usr/bin/journalctl"]


def test_plano_tolera_host_que_falha():
    class HostQuebrado(_HostFalso):
        def exists(self, path):
            raise OSError("sistema de arquivos indisponivel")

    tem, plano = plan_kernel_log_access(HostQuebrado(True), release="6.1.0")

    assert tem is False
    assert "dmesg" in plano
