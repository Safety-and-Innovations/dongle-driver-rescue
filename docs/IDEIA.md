# Dongle Driver Rescue

> Pendrive USB de Wi-Fi/Bluetooth chinês. Mal funciona no Windows, nunca
> funciona no Linux. O app descobre o que a coisa **é** e acha um driver
> genérico que funciona.

## A ideia central: o banco de dados já existe, e não é seu

Esta é a diferença entre este produto e o "Universal Hardware Fingerprint"
que foi descartado.

O Universal Hardware Fingerprint propunha **construir e curar** um banco
`Hardware ID → chipset → driver`. Isso é um negócio de dados, não de software:
alguém tem que alimentar aquilo para sempre.

Mas esse mapeamento **já está publicado, e está no disco da máquina**:

| SO | Onde o mapa já existe |
|---|---|
| Windows | Todo `.INF` declara, na seção `[Models]`, exatamente quais Hardware IDs ele atende. O DriverStore é um índice pesquisável. |
| Linux | `/lib/modules/$(uname -r)/modules.alias` é o mapa **completo e gerado** de `modalias → módulo`. `modinfo -F alias <mod>` dá o mesmo por módulo. |

O app não mantém banco. Ele **lê e cruza metadados que já vêm com o sistema
operacional e com os pacotes de driver de referência.** Quando o mapa muda,
ele muda sozinho, porque o mapa é do fabricante e do kernel, não nosso.

## O escopo estreito é o que salva o produto

Só dongles USB de Wi-Fi e Bluetooth. Nada de placa de captura, placa-mãe,
dispositivo industrial.

O motivo é aritmético: esse mercado inteiro roda em torno de **~25 chipsets**,
e essa lista é estável há anos.

- **Wi-Fi:** Realtek RTL8188EU/8192EU/8811CU/8812AU/8821CU/8814AU,
  MediaTek/Ralink MT7601U/MT7610U/MT7612U/MT7921AU, Atheros AR9271.
- **Bluetooth:** CSR8510 (e os clones falsificados), Realtek RTL8761B/BU,
  Broadcom BCM20702.

O rótulo da embalagem é ficção; o VID:PID não é. Um punhado de chipsets,
centenas de nomes de marca inventados.

## O que o app faz

### Fase 1 — Identificar (determinístico, sem rede)

```
USB → VID:PID:rev  →  bcdDevice, interface class/subclass
   → Windows: Hardware IDs + Compatible IDs (SetupAPI)
   → Linux:   /sys/bus/usb/devices/*/modalias
```

### Fase 2 — Diagnosticar o estado real

Não é "tem driver ou não tem". São cinco estados distintos, e cada um tem
uma correção diferente:

| Estado | Sintoma | Correção |
|---|---|---|
| A. Driver certo, já funcionando | — | nada a fazer |
| B. Driver existe, **ID não está na tabela dele** | dispositivo aparece, nada acontece | **bind manual** (ver abaixo) |
| C. Driver existe, **firmware faltando** | `dmesg`: *Direct firmware load failed* | instalar o pacote de firmware |
| D. Módulo existe mas está bloqueado | blacklist, conflito com outro módulo | desbloquear/descarregar o conflitante |
| E. Chipset não tem driver in-tree | nada, silêncio | driver out-of-tree (DKMS) |

O estado **B** é o que mais aparece nesses dongles e é o que ninguém sabe
consertar. O fabricante reciclou um chipset conhecido com um PID novo. O
driver correto está instalado e funcionando — só não sabe que aquele
dispositivo é dele. No Linux a correção é uma linha, reversível, sem
recompilar nada:

```sh
echo "0bda 8811" > /sys/bus/usb/drivers/rtl88XXau/new_id
```

E o app persiste isso como uma regra udev/modprobe, para sobreviver ao reboot.
Isso sozinho já justifica o produto.

O estado **C** também é puro determinismo: o `dmesg` diz o nome exato do
arquivo de firmware que faltou. O app lê, encontra o pacote que o contém,
instala, recarrega o módulo.

### Fase 3 — Instalar, verificar, reverter

- Nunca instalar sem mostrar origem, versão, assinatura e hash.
- Sempre com ponto de restauração (Windows) ou snapshot da configuração (Linux).
- Sempre com teste real depois: o rádio subiu? faz scan? pareia? Não basta
  "instalou sem erro".

## Identificar o chip — o núcleo do produto

> *"firmware faltando pode ser encontrado se tivermos o nome do chip, chipset,
> DSP ou qualquer chip que seja ali no hardware — facilita muito, e é muito
> difícil de encontrar."*

Exato. E é aqui que está o produto inteiro. O nome do chip é a chave que abre
tudo: firmware, driver de referência, módulo correto, erratas conhecidas.
Encontrar essa chave é o trabalho difícil que ninguém automatizou.

### A cadeia completa — e cada elo já existe no sistema

```
VID:PID:bcdDevice
      ↓  modules.alias  (gerado pelo kernel)
   módulo
      ↓  modinfo -F firmware
   lista COMPLETA de firmwares que aquele módulo pode pedir
      ↓  dmesg
   qual deles ele pediu e não achou
      ↓  WHENCE (índice do linux-firmware)
   arquivo exato + licença + driver que o consome
      ↓
   instalar → recarregar módulo → verificar rádio no ar
```

Nenhum elo dessa cadeia é curadoria nossa:

- **`modinfo -F firmware <mod>`** devolve a lista completa e exata dos
  firmwares que aquele módulo é capaz de requisitar. Está compilado dentro do
  módulo. Não é palpite.
- **`dmesg`** diz o nome do arquivo com todas as letras:
  `Direct firmware load for rtlwifi/rtl8192cufw.bin failed with error -2`.
- **`WHENCE`**, na raiz do `linux-firmware`, indexa cada arquivo de firmware
  com licença e driver consumidor. É o índice oficial, mantido upstream.

O app apenas **percorre uma cadeia que já está documentada em quatro lugares
diferentes** — e que hoje exige um humano experiente para ser percorrida.

### O caso difícil: quando o nome do arquivo não basta

É aqui que a sua observação fica mais afiada. Não basta saber "é um RTL8192CU".
Chips têm *revisões*, e a revisão errada não funciona:

- **RTL8192CU** tem firmware distinto para **A-cut** e **B-cut**
  (`rtl8192cufw_A.bin` vs `rtl8192cufw_B.bin`). Escolher errado = rádio morto.
- **RTL8761B / 8761BU / 8761BUV** — três firmwares diferentes
  (`rtl8761b_fw.bin`, `rtl8761bu_fw.bin`, e o `_config.bin` correspondente),
  todos vendidos sob o mesmo rótulo "adaptador Bluetooth 5.0".

Como o app resolve, sem adivinhar:

| Sinal | Onde ler | O que distingue |
|---|---|---|
| `bcdDevice` | descritor USB | costuma codificar a revisão do silício |
| `lmp_subver` + `hci_rev` | comando HCI de leitura de versão local | **identifica o chip Realtek BT exatamente** |
| efuse/EEPROM | via driver, quando algum liga | ID real do chip, imune ao rótulo |
| tabela `ic_id_table` | fonte do kernel (`btrtl.c`) | o mapeamento oficial `lmp_subver+hci_rev → firmware` |

O último é o achado bonito: **o kernel já contém a tabela de decisão** que
transforma versão de HCI em nome de arquivo de firmware. O `btrtl` faz
exatamente isso toda vez que um dongle Realtek é conectado. O app lê a mesma
tabela e explica a decisão em voz alta — em vez de falhar em silêncio, que é
o que acontece hoje.

### O mesmo raciocínio salva o lado Windows

Saber o chip real muda a pergunta de:

> "onde acho o driver do *TP-Mini AC600 Nano Ultra*?" — marca inventada,
> vendedor sumido, link morto, CD com malware

para:

> "onde acho o driver de referência do **RTL8811CU**?" — Realtek, oficial,
> assinado, existe há anos, atende centenas de produtos rebatizados.

A primeira pergunta não tem resposta. A segunda sempre tem. **Traduzir a
primeira na segunda é o produto.**

### O piso honesto: quando não dá

Se nenhum driver liga no dispositivo e os descritores USB mentem, não há como
ler o chip eletronicamente. Aí resta o que um humano faria: **abrir e olhar a
marcação impressa no chip.**

O app deve chegar nesse ponto e dizer isso — pedir uma foto da placa e aceitar
o nome do chip digitado à mão, seguindo a cadeia a partir dali. Um passo
manual declarado é infinitamente melhor que um palpite silencioso.

Essa é a diferença entre esta ferramenta e todo "driver updater" do mercado:
**quando ela não sabe, ela diz que não sabe.**

## Onde estão os limites — e a gente não passa deles

Ser honesto aqui é o que separa isto de um "driver updater" de malware.

- **Windows: não editar INF.** Forçar um Hardware ID dentro de um INF quebra
  a assinatura e obriga o usuário a ligar test signing / desabilitar a
  verificação. Isso é degradar a segurança da máquina do cliente. O app
  **detecta e explica** o caso B no Windows, e oferece o caminho legítimo
  (driver de referência do fabricante do chipset que já lista aquele ID).
  Se não existir, ele diz que não existe. Ponto.
- **Não redistribuir driver.** O app aponta para a origem oficial do
  fabricante do chipset, baixa de lá, e verifica hash + assinatura. Nunca
  hospeda binário de terceiro — isso é risco jurídico e é o que transformou
  todo "driver updater" do mercado em adware.
- **Não prometer o que o chipset não faz.** Alguns clones são lixo em
  silício. O app deve saber dizer "isto é um clone de CSR8510 e a única
  coisa que funciona é o perfil básico" em vez de tentar consertar.

## O único ponto onde há curadoria — e o teto dela

Estado **E** (chipset sem driver in-tree) precisa apontar para repositórios
DKMS mantidos pela comunidade — `morrownr/8821au`, `morrownr/88x2bu`,
`aircrack-ng/rtl8812au` e mais uns três.

**Isso é uma lista de ~6 repositórios, não um catálogo de produtos.** É o
teto explícito e escrito:

> **Regra:** a lista referencia *repositórios de driver por chipset*, nunca
> produtos, marcas ou modelos de dongle. Se um pedido só pode ser atendido
> adicionando uma linha por produto vendido, a resposta é não.

É a mesma regra do Printer Rescue, aplicada aqui.

## Custo, manutenção, lucro — a avaliação honesta

- **Infra: US$ 0/mês.** Local-first, igual às outras três.
- **Manutenção: a mais alta das quatro ideias.** Kernel novo muda caminho de
  módulo; repositório DKMS é abandonado; chipset novo aparece de vez em
  quando. Não é curadoria diária, mas também não é zero. Estimativa honesta:
  algumas horas por trimestre.
- **Lucro: o mais fraco das quatro.** Usuário de Linux com dongle de R$ 30 não
  paga assinatura. O lado Windows tem mais disposição a pagar, mas compete com
  a percepção (justa) de que "driver updater = golpe".

## Então por que fazer

Porque é o melhor **topo de funil** do conjunto. É a ideia com maior chance de
ser genuinamente amada e compartilhada: r/linuxquestions, r/HomeNetworking,
fóruns de Raspberry Pi, comunidade de pentest (esses dongles são material de
trabalho lá).

O caminho que faz sentido: **núcleo aberto e gratuito no Linux**, que constrói
audiência e reputação, e versão paga no Windows / versão de técnico. Ou
simplesmente: este é o produto que traz gente para os outros três.

Vender isto como produto principal, sozinho, é a leitura errada.

## A decidir

- [ ] Começa por Linux (onde a dor é maior e a solução é mais limpa) ou
      Windows (onde está o dinheiro)?
- [x] **CLI. Decidido.** Para este público CLI não é limitação, é preferência.
- [x] **Grátis. Decidido.** Barrado na Store pela política 10.1.5 de qualquer forma; vira topo de funil dos outros três.
- [ ] Open-core de verdade ou gratuito integral com upsell para os outros apps?
- [ ] Confirmar o levantamento dos ~25 chipsets antes de escrever código:
      se forem 200, a premissa cai e a ideia volta a ser o Hardware Fingerprint.

## Fonte

Reformulação de `ideias_apps_problemas_cronicos_ti_refinada.md` §7.1
(Universal Hardware Fingerprint) e `Qwen_...md` §5 (Generic Driver Bridge),
com o escopo estreitado a dongles USB Wi-Fi/BT e a premissa invertida:
ler o mapa que já existe, em vez de construir um.

---

**Distribuição e venda:** ver [`../CANAIS.md`](../CANAIS.md) — canal MSP, RMM, Microsoft Store e recebimento.

**Preço e modelo:** ver [`../PRECIFICACAO.md`](../PRECIFICACAO.md).
