# ADR 0002 — Segurança e política de supply chain

- **Status:** Aceito
- **Data:** 2026-08-22
- **Responsável:** Lead Engineering Agent (ox-alpha)

## Contexto

O produto executa operações privilegiadas (bind/unbind de drivers, escrita em
sysfs, persistência modprobe.d/udev) e consome dados hostis: strings USB,
saída de dmesg, metadados de repositórios remotos, conteúdo de páginas web.
A SPEC §§14, 29, 37 define red team independente e proíbe instalar artefato
encontrado na web sem validação completa.

## Decisões

### S1 — Superfície de execução mínima

Nenhuma shell intermediária. Todo subprocesso é invocado com lista de argumentos
(`subprocess.run([...], shell=False)`). Nenhum dado de origem externa (USB string,
nome de arquivo de firmware, saída de log) jamais entra em um comando, template
de comando ou path concatenado sem passar pela camada de validação S2/S3.

### S2 — Allowlist estrita de executáveis

O core mantém tabela única `ALLOWED_BINARIES` com caminho absoluto verificado
(`/usr/bin/modinfo`, `/usr/bin/journalctl`, ...). Executável fora da tabela =
erro de configuração, nunca fallback.

### S3 — Validação de identificadores

Todo identificador que atravessa fronteira externa→interna→sistema passa por
gramática fechada:

- VID/PID: exatamente 4 hex, case-insensitive, zero-padded.
- Nome de módulo: `[a-z0-9_-]{1,64}`.
- Caminho de firmware: normalizado, proibido `..`, symlink resolvido antes de
  qualquer uso, prefixo obrigatório `/lib/firmware/`.

### S4 — Política de download (supply chain)

Ordem de origem aceita para artefato externo:

1. Pacote da distribuição via gerenciador nativo (`apt`, `dnf`, `pacman`) —
   assinado pela distro, canal existente.
2. Checkout/tag do git upstream `linux-firmware` com hash de commit fixado.

Proibido na V1: download de binário solto de mirror, hospedagem própria de
firmware/driver, instalação automática de driver out-of-tree (estado E apenas
**aponta** o repositório upstream, nunca clona/compila sem confirmação explícita).

Toda ação de rede registra em log estruturado o quê/para onde/quando;
`--no-network` desliga todo caminho de rede por construção (feature flag checada
no único ponto de saída de rede).

### S5 — Privilégio

Diagnóstico roda sem privilégio sempre que possível; leitura de dmesg pode
exigir grupo adequado — a ferramenta informa, não eleva sozinha. Operações de
reparo exigem root declarado explicitamente e exibem plano dry-run antes.

### S6 — Conteúdo externo é untrusted input

Saída de pesquisa web, README, issue ou página nunca vira instrução de execução
nem valor de configuração sem passar por S2–S4. Vale para agentes e para o código.

### S7 — Privacidade

Sem telemetria, conta ou nuvem (SPEC §30). O único tráfego possível é consulta
de metadados de pacote/repositório para resolução de firmware, registrada e
desligável.

## Consequências

- Red team (Milestone 7) valida S1–S7 com cenários de exploração real.
- Fixtures `tests/fixtures/malicious/` exercitam S3 contra entradas hostis.
