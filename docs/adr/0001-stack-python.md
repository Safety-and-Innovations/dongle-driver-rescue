# ADR 0001 — Linguagem e stack da V1

- **Status:** Aceito
- **Data:** 2026-08-22
- **Responsável:** Lead Engineering Agent (ox-alpha), por ordem de forg3
- **Decisores:** Lead Agent; revisão pelo gate do Milestone 3

## Contexto

A SPEC (§31) exige escolha de stack com base em: segurança, integração com o SO,
manutenção, portabilidade, capacidade de gerar binário, facilidade de testes e
integração com APIs nativas — não preferência pessoal. Candidatos avaliados:
Rust, Go, Python, C/C++.

Fatos verificados no host de referência (Ubuntu 24.04, kernel 6.17):

| Fato | Evidência |
|---|---|
| Toolchains Rust/Go ausentes | `rustc`, `cargo`, `go` não instalados; instalação via rustup/golang adicionaria dependência de rede ao ciclo de build |
| Cadeia de ferramentas do domínio toda é executável a partir de Python | `lsusb`, `modinfo`, `journalctl`, `udevadm`, `modprobe`, `iw`, `bluetoothctl` são binários do SO que a ferramenta invoca e cuja saída parseia |
| Python 3.12 presente | `python3 --version` = 3.12.3 |
| Toda a "API nativa" relevante é sysfs + netlink + logs de texto | `/sys/bus/usb/devices/*`, `/lib/modules/$(uname -r)/modules.alias`, dmesg — acesso via stdlib (`os`, `pathlib`, `subprocess`) |

Análise por critério:

- **Integração com SO:** empate técnico entre as quatro linguagens; todas chamam
  os mesmos binários e leem os mesmos arquivos.
- **Capacidade de gerar binário:** Rust/Go geram binário único; Python exige
  PyInstaller/Shiv (aceitável para ferramenta de técnico).
- **Segurança:** linguagem não elimina a classe de risco dominante deste produto
  (injeção em comando, path traversal em nome de firmware vindo de log, parsing
  de entrada hostil). O controle está em camada de design — ver ADR 0002.
- **Facilidade de testes/fixtures:** pytest com parametrização sobre fixtures de
  sysfs sintéticos é o caminho mais direto para o requisito §20 (testes sem
  hardware físico) e §22 (failure injection).
- **Manutenção:** equipe real é enxuta; ecossistema de parse/CLI maduro pesa.

## Decisão

**Python 3.12+ (somente stdlib na V1 para o núcleo; pytest como dependência de
desenvolvimento).** Empacotamento executável via entry point `dongle-rescue`;
geração de binário autônomo (PyInstaller) fica para o Milestone 8.

## Consequências

- Zero dependência de runtime além do interpretador já presente nas distros-alvo.
- Módulos que exigissem extensão C (ex.: raw netlink próprio) ficam fora da V1;
  tudo passa por CLIs do SO, o que também isola a superfície de segurança.
- Revisitar este ADR se surgir requisito de performance que Python não atenda
  (improvável: o gargalo é I/O de subprocesso, não CPU).

## Alternativas rejeitadas

- **Rust:** melhor binário e memória-safe, mas custo de iteração maior para uma
  V1 cujo risco dominante é corretude da lógica de evidência, não performance.
- **Go:** bom binário único; perde para Python em expressividade de fixtures de
  teste e na curva de contribuição externa (topo de funil da comunidade Linux).
- **C/C++:** memória insegura em um produto que parseia entrada hostil — pior
  opção para o perfil de ameaça (ADR 0002).
