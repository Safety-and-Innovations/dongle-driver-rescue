# ADR 0003 — Evidência, determinismo e honestidade epistêmica

- **Status:** Aceito
- **Data:** 2026-08-22
- **Responsável:** Lead Engineering Agent (ox-alpha)

## Contexto

A SPEC §§1, 9, 28, 35–37 define o produto como diagnosticador determinístico:
toda conclusão carrega evidência citada; quando a evidência não basta, a resposta
é `UNKNOWN`; hipóteses críticas exigem validação independente. O modo de falha
proibido é o palpite silencioso — o mesmo que torna "driver updaters" perigosos.

## Decisões

### D1 — Todo fato derivado carrega proveniência

Cada conclusão emitida pela ferramenta referencia a evidência que a produziu:

```text
evidence_id → source (arquivo/comando/pacote) → experimento → resultado
```

Representação única em runtime (`Evidence` object) e serialização no JSON de
saída (SPEC §27). Sem evidência anexada, a conclusão não compila no fluxo —
as funções de diagnóstico exigem `Evidence` como argumento.

### D2 — Escala de confiança fechada

Exatamente cinco níveis (SPEC §28): `CONFIRMED`, `HIGH_CONFIDENCE`, `PROBABLE`,
`POSSIBLE`, `UNKNOWN`. Regras de atribuição documentadas por camada
(§7 da SPEC): descritor USB lido = CONFIRMED para existência do dispositivo;
casamento modules.alias = HIGH_CONFIDENCE para candidato a driver; tabela
upstream (btrtl ic_id_table) = CONFIRMED para decisão de firmware.

### D3 — UNKNOWN é resultado válido, não exceção

Qualquer cadeia que não feche retorna `UNKNOWN` + explicação do elo faltante +
caminho manual declarado (SPEC §11: `identify --chip`, foto da placa, dump USB).
Nunca inferir chipset a partir de marca comercial.

### D4 — Determinismo de saída

Mesmo estado de sistema ⇒ mesmo relatório: ordenação estável de listas
(por chave canônica, não por mtime/ordem de readdir), sem timestamps embutidos
em campos comparáveis, versão de schema fixada (`schema_version: 1`). Isso é o
que permite regression test byte-a-byte sobre fixtures.

### D5 — Consenso para decisões críticas

Mapeamentos chipset→módulo→firmware publicados no produto (dados consolidados
da pesquisa) só entram após: agente A pesquisa, agente B pesquisa
independentemente, agente C tenta refutar; divergência resolve por fonte
primária (código do kernel / WHENCE), nunca por persuasão. Cada linha da tabela
consolidada carrega o nível de confiança D2 e a citação.

### D6 — Transações reversíveis

Toda mutação (repair) produz transação com before_state/change/after_state/
rollback_action (SPEC §24); rollback idempotente; nada executa sem dry-run
equivalente disponível (SPEC §23).

## Consequências

- Testes de regressão comparam JSON completo contra golden files por fixture.
- A tabela consolidada de chipsets vive em dado versionado
  (`src/dongle_rescue/data/chipsets.json`) gerado a partir de
  `docs/research/*.md`, nunca digitada à mão no código.
