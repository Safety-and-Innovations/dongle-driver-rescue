# Research — MediaTek/Ralink (mt7601u + família mt76) & Atheros (AR9271)

| Campo | Valor |
|---|---|
| Documento | `docs/research/mediatek-atheros.md` |
| Data | 2026-08-22 |
| Revisão | 2 (substitui o rascunho da rev. 1; corrige licença do firmware 1.4.0 do ath9k_htc e fecha as versões de kernel que estavam UNKNOWN) |
| Responsável | forg3 |

Regra do projeto (docs/SPEC.md §28): fato sem citação/evidência = `UNKNOWN`.
Marcadores usados abaixo: **CONFIRMED** (verificado nesta sessão, saída embutida),
**HIGH_CONFIDENCE** (fonte primária lida, sem execução local),
`[unverified]` (afirmação sem fonte primária anexada).

## 0. Método e fontes

Três cadeias de evidência independentes, todas fonte primária:

1. **Host local** — `modinfo` executado contra o tree real
   `/lib/modules/6.17.0-1020-oracle` (kernel instalado, não o em execução — ver
   §8) e `grep` em `/lib/modules/6.17.0-1020-oracle/modules.alias`.
2. **Código do kernel** — arquivos baixados do git canônico
   `git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git` (endpoint
   `plain`, branch `master`) + sparse clone raso para resolução de `#define`.
3. **Versão de entrada por probing de tags** — para cada arquivo-chave, o
   mesmo `plain/<arquivo>?h=vX.Y` foi consultado em tags consecutivas do
   torvalds/linux; a fronteira 404→200 delimita a janela de merge. Este método
   usa apenas o repositório canônico e é reproduzível.

`WHENCE` citado é o `plain/WHENCE` do
`git.kernel.org/pub/scm/linux/kernel/git/firmware/linux-firmware.git`
(master desta sessão, 10.672 linhas; números de linha referem-se a essa cópia).

---

## 1. MT7601U — driver dedicado in-tree `mt7601u`

### 1.1 Entrada no kernel — CONFIRMED por probing

| Caminho | `?h=v4.1` | `?h=v4.2` |
|---|---|---|
| `drivers/net/wireless/mediatek/mt7601u/usb.c` | HTTP 404 | HTTP 200 |

Janela de merge: **kernel 4.2** (2015).

### 1.2 Tabela de IDs USB — CONFIRMED (fonte: `mt7601u/usb.c`, master)

```c
static const struct usb_device_id mt7601u_device_table[] = {
	{ USB_DEVICE(0x0b05, 0x17d3) },
	{ USB_DEVICE(0x0e8d, 0x760a) },
	{ USB_DEVICE(0x0e8d, 0x760b) },
	{ USB_DEVICE(0x13d3, 0x3431) },
	{ USB_DEVICE(0x13d3, 0x3434) },
	{ USB_DEVICE(0x148f, 0x7601) },     /* canonical Ralink/MediaTek */
	{ USB_DEVICE(0x148f, 0x760a) },
	{ USB_DEVICE(0x148f, 0x760b) },
	{ USB_DEVICE(0x148f, 0x760c) },
	{ USB_DEVICE(0x148f, 0x760d) },
	{ USB_DEVICE(0x2001, 0x3d04) },
	{ USB_DEVICE(0x2717, 0x4106) },
	{ USB_DEVICE(0x2955, 0x0001) },
	{ USB_DEVICE(0x2955, 0x1001) },
	{ USB_DEVICE(0x2955, 0x1003) },
	{ USB_DEVICE(0x2a5f, 0x1000) },
	{ USB_DEVICE(0x7392, 0x7710) },
	{ 0, }
};
```

Corroboração no host (saída REAL, tree 1020): `modinfo mt7601u.ko.zst` →

```text
license:        GPL
description:    MediaTek MT7601U USB Wireless LAN driver
firmware:       mt7601u.bin
depends:        mac80211,cfg80211
alias:          usb:v148Fp7601d*dc*dsc*dp*ic*isc*ip*in*
alias:          usb:v0B05p17D3d*dc*dsc*dp*ic*isc*ip*in*
alias:          usb:v2001p3D04d*dc*dsc*dp*ic*isc*ip*in*   (+14 demais)
```

Total de aliases no tree 1020: **17** — bate 1:1 com a tabela do código.
Nota: **nenhum ID 0BDA** pertence ao mt7601u; VID Realtek nesse chipset não
existe nas tabelas upstream (a hipótese "0BDA?" do enunciado é refutada pela
fonte primária).

### 1.3 Firmware requisitado — CONFIRMED

`mt7601u/usb.h` (master, linha 11):

```c
#define MT7601U_FIRMWARE	"mt7601u.bin"
```

`mt7601u/mcu.c` (master, linhas 405–430) — o driver tenta dois caminhos:

```c
static const char * const mt7601u_fw_paths[] = {
	"mediatek/" MT7601U_FIRMWARE,
	MT7601U_FIRMWARE,
};
...
	for (i = 0; i < MT7601U_FIRMWARE_PATHS; i++) {
		ret = request_firmware(&fw, mt7601u_fw_paths[i], dev->dev);
		if (ret == 0)
			break;
	}
	if (ret)
		return ret;
```

Sobre "**MT765023ROM**": esse nome **não aparece** nem no `mcu.c`/`usb.h` em
`v4.2` nem no master — em ambos o pedido é literalmente `mt7601u.bin`.
O nome MT765023ROM circula como identificador de ROM do SDK do fabricante
`[unverified]`; para o produto, o único nome relevante é o que o módulo pede
(`mt7601u.bin`, confirmado também pelo `MODULE_FIRMWARE()` no `usb.c:364`,
que alimenta o campo `firmware:` do modinfo).

### 1.4 Mensagens quando falta/corrompe — CONFIRMED (strings do código)

| Camada | Mensagem exata | Origem |
|---|---|---|
| Firmware core | `Direct firmware load for mt7601u.bin failed with error -2` | padrão canônico, documentado em `docs/research/linux-kernel.md` §6 (`fw_main.c:903`); `-2` = ENOENT |
| Driver (imagem inválida) | `Invalid firmware image` → `-ENOENT` | `mcu.c:499` |
| Driver (upload) | `Error: firmware upload timed out` / `Error: firmware upload urb failed:%d` | `mcu.c:318/323` |
| Sucesso | `Firmware Version: %d.%d.%02d Build: %x Build time: %.16s` | `mcu.c:453` |

### 1.5 Gancho anti-rebatização no próprio probe — CONFIRMED

`mt7601u/usb.c` (`mt7601u_probe`, master):

```c
	asic_rev = mt7601u_rr(dev, MT_ASIC_VERSION);
	mac_rev = mt7601u_rr(dev, MT_MAC_CSR0);
	dev_info(dev->dev, "ASIC revision: %08x MAC revision: %08x\n",
	 asic_rev, mac_rev);
	if ((asic_rev >> 16) != 0x7601) {
		ret = -ENODEV;
		goto err;
	}
```

Mesmo que um ID seja injetado via `new_id`, o hardware precisa responder com
revisão de ASIC `7601xxxx` — leitura direta do silício, imune ao rótulo da
caixa. Log de sucesso esperado no dmesg: `ASIC revision: ...`.

### 1.6 Licença do firmware (WHENCE:1673–1679) — HIGH_CONFIDENCE

```text
File: mediatek/mt7601u.bin
Version: 34
Link: mt7601u.bin -> mediatek/mt7601u.bin

Licence: Redistributable. See LICENCE.ralink_a_mediatek_company_firmware for details

Downloaded from http://www.mediatek.com/en/downloads/
```

O symlink raiz explica por que os dois caminhos do `mt7601u_fw_paths[]`
funcionam com um único pacote.

---

## 2. MT7610U / MT7612U — família `mt76` (`mt76x0u` / `mt76x2u`)

### 2.1 Versões de entrada — CONFIRMED por probing

| Caminho | tag anterior (404) | tag seguinte (200) | Janela |
|---|---|---|---|
| `mt76/Makefile` + `mt76/mt76.h` (núcleo, PCIe) | v4.15 | v4.16 | **4.16** |
| `mt76/mt76x0/usb.c` (MT7610U USB) | v4.18 | v4.19 | **4.19** |
| `mt76/mt76x2/usb.c` (MT7612U USB) | v4.19 | v4.20 | **4.20** |
| `mt76/mt7921/usb.c` (MT7921AU USB) | v5.17 | v5.18 | **5.18** (§3) |

Conteúdo real do `Makefile @v4.16` (confirma ser o núcleo mt76 e não header homônimo):

```make
obj-$(CONFIG_MT76_CORE) += mt76.o
obj-$(CONFIG_MT76x2E) += mt76x2e.o
```

### 2.2 Firmwares requisitados — CONFIRMED (modinfo real, tree 1020)

```text
===== mt76x0u =====
firmware:       mediatek/mt7610u.bin
firmware:       mediatek/mt7610e.bin
depends:        mt76x02-usb,mt76x0-common,mt76x02-lib,mt76,mac80211,mt76-usb
(total 25 aliases)

===== mt76x2u =====
license:        Dual BSD/GPL
author:         Lorenzo Bianconi <lorenzo.bianconi83@gmail.com>
firmware:       mt7662_rom_patch.bin
firmware:       mt7662.bin
depends:        mt76x02-usb,mt76,mt76x02-lib,mt76x2-common,mac80211,mt76-usb
(total 15 aliases)
```

Defines correspondentes na fonte (master): `mt76x0/mt76x0.h:23–26`
(`MT7610E_FIRMWARE "mediatek/mt7610e.bin"`, `MT7650E_FIRMWARE
"mediatek/mt7650e.bin"` — este só PCIe — e `MT7610U_FIRMWARE
"mediatek/mt7610u.bin"`) e `mt76x2/mt76x2.h:19–20`
(`MT7662_FIRMWARE "mt7662.bin"`, `MT7662_ROM_PATCH "mt7662_rom_patch.bin"`).
Os nomes do mt76x2u são raiz (sem prefixo `mediatek/`) porque o próprio
linux-firmware publica symlinks `mt7662*.bin -> mediatek/mt7662*.bin`
(WHENCE:6091–6097) — mesma solução do mt7601u.

Detalhe fino capturado no código (`mt76x0/usb_mcu.c:75–79`): o caminho USB
tenta **primeiro** o firmware do chip PCIe equivalente (`mt7610e.bin`) e só
então faz fallback para `mt7610u.bin` — por isso ambos aparecem no modinfo.
O detector deve aceitar qualquer dos dois como "atende o pedido".

### 2.3 Diferença para os drivers antigos fora-da-árvore

| Aspecto | SDK MediaTek fora-da-árvore (`mt7610u_sta`/`mt7612u_sta` `[unverified]` nomes) | `mt76x0u`/`mt76x2u` in-tree |
|---|---|---|
| Build | DKMS + headers de kernel + compilador | nenhum; módulo vem no pacote `linux-modules-extra` |
| Framework | stack própria do SDK | mac80211/cfg80211 nativos |
| Firmware | binários do CD/fabricante, caminhos próprios | arquivos do linux-firmware (`mediatek/*`, `mt7662*.bin`) com licença declarada no WHENCE |
| IDs novos | patch manual | commit upstream (tabela versionada pelo kernel) |
| Estado B (ID fora da tabela) | `new_id` costuma funcionar | idem; mecanismo em `docs/research/linux-kernel.md` §3 |

Consequência de produto: para Estado E desses chipsets, a recomendação correta
é **upgrade de kernel/distro**, não DKMS — desde o 4.20 todo MT7612U tem
driver in-tree mantido.

---

## 3. MT7921AU — `mt7921u`

### 3.1 Kernel mínimo — CONFIRMED por probing

`mt76/mt7921/usb.c`: HTTP 404 em `v5.17`, HTTP 200 em `v5.18` → suporte USB
entrou na **janela do kernel 5.18** (2022). Kernel mínimo declarável: **5.18**
(distro com backport pode ter antes; detectar por `modules.alias` do kernel em
execução, nunca por versão nominal).

### 3.2 Tabela de IDs — CONFIRMED (fonte: `mt7921/usb.c`, master)

```c
static const struct usb_device_id mt7921u_device_table[] = {
	{ USB_DEVICE_AND_INTERFACE_INFO(0x0e8d, 0x7902, 0xff, 0xff, 0xff),
		.driver_info = (kernel_ulong_t)MT7902_FIRMWARE_WM },
	{ USB_DEVICE_AND_INTERFACE_INFO(0x0e8d, 0x7961, 0xff, 0xff, 0xff),
		.driver_info = (kernel_ulong_t)MT7921_FIRMWARE_WM },
	/* Comfast CF-952AX */
	{ USB_DEVICE_AND_INTERFACE_INFO(0x3574, 0x6211, 0xff, 0xff, 0xff), ...
	/* Netgear, Inc. [A8000,AXE3000] */
	{ USB_DEVICE_AND_INTERFACE_INFO(0x0846, 0x9060, 0xff, 0xff, 0xff), ...
	/* Netgear, Inc. A7500 */
	{ USB_DEVICE_AND_INTERFACE_INFO(0x0846, 0x9065, 0xff, 0xff, 0xff), ...
	/* TP-Link TXE50UH */
	{ USB_DEVICE_AND_INTERFACE_INFO(0x35bc, 0x0107, 0xff, 0xff, 0xff), ...
	{ },
};
```

modinfo real (tree 1020): 5 aliases, todos `icFFiscFFipFF`; firmwares
`mediatek/WIFI_MT7961_patch_mcu_1_2_hdr.bin` +
`mediatek/WIFI_RAM_CODE_MT7961_1.bin`; `Dual BSD/GPL`.

### 3.3 Peculiaridades

1. **Match por classe de interface obrigatório** (`USB_DEVICE_AND_INTERFACE_INFO`
   com `ff/ff/ff`): um VID:PID igual mas com classe diferente **não** casa.
   O parser da ferramenta precisa implementar o escopo `ic/isc/ip` do
   modalias, senão gera falso positivo de Estado B.
2. **Seleção de firmware via `driver_info`**: o mesmo driver atende MT7921
   (`WIFI_MT7961_*_1*`) e MT7902/MT7922 — o arquivo correto depende do ID, e
   `driver_info` carrega essa decisão. Não existe "um firmware serve todos".
3. **Variante MT7920** (`mt76/mt792x.h:55–56`): usa
   `mediatek/WIFI_MT7961_patch_mcu_1a_2_hdr.bin` (WHENCE:6231–6234) — família
   de nomes parecida, conteúdo diferente; confundir as duas é erro clássico.

### 3.4 WHENCE (6231–6256) — HIGH_CONFIDENCE

```text
File: mediatek/WIFI_MT7961_patch_mcu_1a_2_hdr.bin      (variante MT7920)
File: mediatek/WIFI_RAM_CODE_MT7961_1a.bin
Licence: Redistributable. See LICENCE.mediatek for details.

File: mediatek/WIFI_MT7961_patch_mcu_1_2_hdr.bin
Version: 20260224110909a
File: mediatek/WIFI_RAM_CODE_MT7961_1.bin
Version: 20260224110949
Licence: Redistributable. See LICENCE.mediatek for details.
```

---

## 4. AR9271 — `ath9k_htc`

### 4.1 Tabela de IDs — CONFIRMED (`ath/ath9k/hif_usb.c`, master)

Grupo AR9271 (trecho verbatim; 27 aliases no tree 1020):

```c
static const struct usb_device_id ath9k_hif_usb_ids[] = {
	{ USB_DEVICE(0x0cf3, 0x9271) }, /* Atheros */
	{ USB_DEVICE(0x0cf3, 0x1006) }, /* Atheros */
	{ USB_DEVICE(0x0846, 0x9030) }, /* Netgear N150 */
	{ USB_DEVICE(0x07b8, 0x9271) }, /* Altai WA1011N-GU */
	{ USB_DEVICE(0x07D1, 0x3A10) }, /* Dlink Wireless 150 */
	{ USB_DEVICE(0x13D3, 0x3327) }, /* Azurewave */
	...
	{ USB_DEVICE(0x0cf3, 0xb002) }, /* Ubiquiti WifiStation */
	{ USB_DEVICE(0x057c, 0x8403) }, /* AVM FRITZ!WLAN 11N v2 USB */
	...
	{ USB_DEVICE(0x0cf3, 0x7015),
	  .driver_info = AR9287_USB },  /* Atheros */
	{ USB_DEVICE(0x0cf3, 0x7010),
	  .driver_info = AR9280_USB },  /* Atheros */
	...
	{ USB_DEVICE(0x0cf3, 0x20ff),
	  .driver_info = STORAGE_DEVICE },
	{ },
};
```

`0CF3:20FF` = dispositivo em modo CD-ROM (ZeroCD); o próprio driver executa
ejeção (`send_eject_command`, comentário no código: "An exact copy of the
function from zd1211rw") antes do casamento normal. Detalhe relevante para o
Estado D: um AR9271 "morto" pode estar apenas no modo storage.

### 4.2 Firmware — nomes, cadeia de fallback e versões

Definições (`ath9k/hif_usb.h:21–37`, master, verbatim):

```c
#define FIRMWARE_AR7010_1_1     "htc_7010.fw"
#define FIRMWARE_AR9271         "htc_9271.fw"

#define MAJOR_VERSION_REQ 1
#define MINOR_VERSION_REQ 3

#define FIRMWARE_MINOR_IDX_MAX  4
#define FIRMWARE_MINOR_IDX_MIN  3
#define HTC_FW_PATH	"ath9k_htc"
#define HTC_9271_MODULE_FW  HTC_FW_PATH "/htc_9271-" \
		__stringify(MAJOR_VERSION_REQ) \
		"." __stringify(FIRMWARE_MINOR_IDX_MAX) ".0.fw"
```

Algoritmo de seleção (`hif_usb.c:1158–1218`, master): começa em
`FIRMWARE_MINOR_IDX_MAX` e desce; enquanto `idx > 3` pede
`ath9k_htc/htc_<chip>-1.<idx>.0.fw` (na prática `htc_9271-1.4.0.fw`);
quando chega em `idx == 3` troca para o nome legado `htc_9271.fw`
(comentário do código: "stable version 1.3, **deprecated**"); abaixo disso:

```c
	} else if (hif_dev->fw_minor_index < FIRMWARE_MINOR_IDX_MIN) {
		dev_err(&hif_dev->udev->dev, "no suitable firmware found!\n");
		return -ENOENT;
```

modinfo real (tree 1020):

```text
firmware:       ath9k_htc/htc_9271-1.4.0.fw
firmware:       ath9k_htc/htc_7010-1.4.0.fw
license:        Dual BSD/GPL
depends:        ath9k_hw,ath9k_common,ath,mac80211,cfg80211
```

### 4.3 1.3 vs 1.4 e compatibilidade com openfw — CORREÇÃO da rev. 1

WHENCE (296–308), verbatim:

```text
File: htc_9271.fw
Version: 1.3.1
File: htc_7010.fw
Version: 1.3.1

Licence: Redistributable. See LICENCE.atheros_firmware for details

File: ath9k_htc/htc_7010-1.4.0.fw
Version: 1.4.0
File: ath9k_htc/htc_9271-1.4.0.fw
Version: 1.4.0

Licence: Free software. See LICENCE.open-ath9k-htc-firmware for details
```

Leitura correta (a rev. 1 deste documento invertia as licenças — erro corrigido):

- **1.3.1 legada** (`htc_9271.fw`, raiz): blob redistribuível proprietário
  (`LICENCE.atheros_firmware`); o kernel ainda a aceita como último recurso
  (`MINOR_IDX_MIN == 3`), mas ela é deprecated.
- **1.4.0** (`ath9k_htc/htc_9271-1.4.0.fw`): é o **openfw** — firmware livre,
  construído do projeto open-ath9k-htc-firmware da QCA
  (`LICENCE.open-ath9k-htc-firmware`). É o primeiro da cadeia de pedidos.
- Compatibilidade openfw↔1.3: o driver reporta/exige major 1 minor ≥ 3
  (`MINOR_VERSION_REQ 3`); builds do openfw publicados com versão 1.3 são
  aceitos pela mesma cadeia `[unverified]` — o contrato verificável no código
  é o par `MAJOR_VERSION_REQ/MINOR_VERSION_REQ`, não o arquivo.

### 4.4 Comportamento quando o firmware falta — CONFIRMED

Cadeia assíncrona: `request_firmware_nowait(...)` → callback `!fw` → nova
tentativa com nome seguinte → esgotada a cadeia:

1. `Direct firmware load for ath9k_htc/htc_9271-1.4.0.fw failed with error -2`
   (core, uma linha por nome tentado);
2. `ath9k_htc: Failed to get firmware <nome>` (`hif_usb.c`, callback);
   ou `ath9k_htc: Async request for firmware <nome> failed` (falha de enqueue);
3. `no suitable firmware found!` + `-ENOENT`;
4. `ath9k_hif_usb_firmware_fail()` → `device_release_driver(dev)` — o
   dispositivo é **desanexado** do driver. Sintoma externo: interface some /
   nada é criado, sem pânico. Correção: instalar pacote de firmware e
   reconectar/rebind (o driver não re-probeia sozinho após release).

---

## 5. Tabela consolidada — VID:PID representativos → módulo → firmware → licença

Fontes: tabelas `usb_device_id` citadas por seção + modinfo real (tree 1020) +
WHENCE master. Confiança conforme SPEC §28.

| Chipset | VID:PID representativos (fonte primária) | Módulo (kernel mín.) | Firmware pedido (modinfo) | Licença (WHENCE) | Confiança |
|---|---|---|---|---|---|
| MT7601U | `148F:7601`, `148F:760A/B/C/D`, `0E8D:760A/B`, `13D3:3431/3434`, `2001:3D04`, `2717:4106`, `2955:0001/1001/1003`, `2A5F:1000`, `7392:7710`, `0B05:17D3` | `mt7601u` (4.2) | `mt7601u.bin` (v34) | `LICENCE.ralink_a_mediatek_company_firmware` (Redistributable) | CONFIRMED |
| MT7610U | `0E8D:7610`, `148F:7610`, `148F:761A`, `148F:760A`, `13B1:003E`, `7392:A711/B711/C711`, `2357:0105/010B/0123`, `0DF6:0075/0079`, `2019:AB31`, `2001:3D02`, `0586:3425`, `07B8:7610`, `04BB:0951`, `057C:8502`, `293C:5702`, `20F4:806B`, `0B05:17D1/17DB` | `mt76x0u` (4.19; núcleo mt76 4.16) | `mediatek/mt7610u.bin`, `mediatek/mt7610e.bin` (fallback E→U) | `LICENCE.mediatek` (Redistributable) | CONFIRMED |
| MT7612U | `0E8D:7612`, `0E8D:7632`, `7392:B711`, `0B05:180B/1833/17EB`, `057C:8503`, `0846:9014/9053`, `045E:02E6/02FE`, `2357:0137`, `2C4E:0103`, `056E:400A`, `0471:2126/7600` | `mt76x2u` (4.20) | `mt7662.bin` (v1.9) + `mt7662_rom_patch.bin` (v0.0.2_P69) | `LICENCE.ralink_a_mediatek_company_firmware` (Redistributable) | CONFIRMED |
| MT7921AU | `0E8D:7961`, `3574:6211` (Comfast CF-952AX), `0846:9060/9065` (Netgear), `35BC:0107` (TP-Link TXE50UH) — todos `icFFiscFFipFF` | `mt7921u` (5.18) | `mediatek/WIFI_MT7961_patch_mcu_1_2_hdr.bin` + `mediatek/WIFI_RAM_CODE_MT7961_1.bin` | `LICENCE.mediatek` (Redistributable) | CONFIRMED |
| AR9271 | `0CF3:9271`, `0CF3:1006`, `0CF3:B002/B003`, `07B8:9271`, `0846:9030`, `07D1:3A10`, `13D3:3327…3350`, `057C:8403`, `0471:209E`, `1EDA:2315`, `040D:3801`, `04CA:4605`; ZeroCD `0CF3:20FF`; grupo AR9280 `0CF3:7010/7015` etc. | `ath9k_htc` (pré-histórico; ≥3.x) | `ath9k_htc/htc_9271-1.4.0.fw` → fallback `htc_9271.fw` (1.3.1) | 1.4.0: `LICENCE.open-ath9k-htc-firmware` (**Free software**); 1.3.1: `LICENCE.atheros_firmware` (Redistributable) | CONFIRMED |
| RT2870/RT3070 (referência p/ falsos "MT76xx") | `148F:2870/3070/3071/3072`, `148F:5370/5372/5572`, `148F:3572/3573`, `8516:2070…3572`, `0B05:1732/1742/1760/1761/1784/1790/17A7/17AD/17BC/17E8` (subconjunto real) | `rt2800usb` (≥2.6.31) | `rt2870.bin` (v36) | `LICENCE.ralink-firmware.txt` (Redistributable) | CONFIRMED (modinfo + WHENCE:1708–1714) |

Pacotes Debian apontados na rev. 1 (`firmware-mediatek`,
`firmware-atheros`, hoje também o novo `linux-firmware` unificado) permanecem
válidos; a verificação `dpkg-deb` feita então continua registrada em
`git log` (commit `8dda872`).

---

## 6. Armadilhas conhecidas

### 6.1 Colisões reais de ID entre módulos (mesmo alias, dois donos)

Varredura do `modules.alias` do tree 1020 (evidência com nº de linha):

| Alias | Concorrentes | Evidência |
|---|---|---|
| `usb:v148Fp760Ad*` | `mt7601u` **e** `mt76x0u` | ambos na lista de aliases (§1.2, §2.2); no código: `USB_DEVICE(0x148f, 0x760a)` nos dois drivers |
| `usb:v7392pB711d*` | `mt76x0u` **e** `mt76x2u` | idem; comentários divergentes ("Edimax/Elecom" × "Edimax EW 7722 UAC") |
| `usb:v0471p2126d*` | `mt76x2u` **e** `rt2800usb` | `modules.alias:17835` (mt76x2u, "LiteOn WN4516R module") × `:18108` (rt2800usb) |
| `usb:v13B1p0043d*` (fora do escopo MTK/Ath, exemplo inter-família) | `rtw88_8822bu` **e** `rtw88_8822cu` | `modules.alias:18649` × `:18671` |

Como o kernel resolve (comportamento observável, CONFIRMED na consequência):
o `modules.alias` mapeia o mesmo alias para vários módulos; o udev/kmod carrega
todos os candidatos, e o USB core liga o dispositivo ao primeiro driver
registrado cuja `id_table` casa — ordem dependente da sequência de carga
(initramfs/distro), portanto **não é propriedade do hardware** `[unverified]`
para os detalhes internos do kmod; o que é verificável é o resultado: o
bound driver visível em `/sys/.../driver` pode variar entre sistemas.

Regra para a ferramenta (obrigatória): **um VID:PID → zero, um ou N módulos**.
Diagnóstico lista todos os candidatos; o árbitro é o symlink `driver` do nó
da interface + `dmesg` do probe real. Reparo nunca assume candidato único.

### 6.2 Dongles "MT7601" rebatizados

- Defesa do driver: checagem de ASIC revision `0x7601` no probe (§1.5) —
  silício errado vira `-ENODEV` mesmo com ID injetado.
- Defesa da ferramenta: cruzar bcdDevice + classe de interface + resposta de
  registro (quando houver driver ligado) antes de afirmar chipset; rótulo
  comercial nunca é evidência (SPEC §7).
- Caso `148F:760A`: ID legítimo em **duas** gerações (mt7601u e mt76x0u) —
  desambiguar por classe de interface e pela resposta do probe.

### 6.3 Falsos "MT76xx" sobre silício Ralink antigo

IDs da família RT28xx/RT33xx/RT53xx/RT55xx pertencem ao `rt2800usb`
(tabela §5, última linha). Dongle vendido como "MT7601 AC600" com ID
`148F:3070` é Ralink rt2870-era: driver certo é `rt2800usb` + `rt2870.bin`,
e prometer 802.11ac é mentira do rótulo. Classificação: o detector decide por
ID (SPEC §7), registra `SUSPECTED_CLONE` quando descritores divergirem do
esperado para o chipset (SPEC §10).

### 6.4 ZeroCD no AR9271

`0CF3:20FF` é modo storage; o driver ejeta e re-enumeraria. Se a ejeção falhar
(máquina virtual, slot USB ruim), o diagnóstico deve sugerir `usb_modeswitch`
ou outra porta antes de concluir Estado E.

---

## 7. Handoff

**What changed** — Rev. 2 substitui integralmente a rev. 1: (a) fechou as
janelas de kernel que estavam UNKNOWN (mt76 núcleo 4.16; mt76x0u 4.19;
mt76x2u 4.20; mt7921u 5.18; mt7601u 4.2) por probing de tags no repositório
canônico; (b) corrigiu inversão de licenças do ath9k_htc (1.4.0 = openfw/free
software; 1.3.1 = blob redistributable deprecated); (c) adicionou as tabelas
de IDs verbatim de quatro drivers, a cadeia de fallback de firmware do
ath9k_htc, o gancho anti-rebatização do mt7601u e três colisões reais de ID
com evidência de linha.

**How it was verified** — `modinfo` real contra `/lib/modules/6.17.0-1020-oracle`
(saída embutida acima); `grep` no `modules.alias` do mesmo tree; arquivos-fonte
baixados do `git.kernel.org` (torvalds/linux e linux-firmware, endpoints
`plain`, tags explícitas); cada afirmação de versão respaldada por par
HTTP 404/200 em tags consecutivas. Itens sem fonte anexada estão marcados
`[unverified]`.

**What unblocks next** — (1) matriz kernel-mínimo por chipset pronta para
`SUPPORTED_OS.md` e fixtures de Estado C (nomes exatos de firmware por módulo);
(2) parser de modalias com escopo `ic/isc/ip` especificado (caso mt7921u);
(3) regra de desambiguação multi-candidato para o motor de diagnóstico
(colisões §6.1); (4) mensagens-canônico de dmesg para o detector de Estado C
já catalogadas por camada (core × driver).

**What risk remains** — (1) números de linha do WHENCE driftam com o upstream;
re-puxar o arquivo quando o detector for implementado; (2) a mecânica interna
de ordenação do kmod na carga simultânea de módulos concorrentes não é
contrato estável `[unverified]` — a ferramenta deve sempre arbitrar pelo
estado real do sistema, nunca pela teoria; (3) build do openfw com versão
reportada ≠ 1.4 pode seguir cadeias diferentes — validar com hardware físico
antes de automatizar reparo de ath9k_htc; (4) colisões listadas refletem o
tree 6.17 — novas entradas podem surgir a cada kernel.

---

## 8. Nota de ambiente (evidência negativa útil)

O kernel **em execução** neste host (`6.17.0-1018-oracle`) não empacota
nenhum dos módulos-alvo (`modinfo mt7601u` → "Module not found";
`linux-modules-extra` ausente para esse release), enquanto os trees
**instalados** 1019/1020 contêm todos. Já coberto como requisito de produto em
`docs/research/linux-kernel.md` §6 (resolver sempre contra `uname -r` e sinalizar
"reboot pendente"). Registrado aqui porque explica por que as saídas modinfo
deste documento usam o tree 1020 explicitamente.

## Fontes

Primárias (todas consultadas nesta sessão):

- torvalds/linux, `plain` master: `drivers/net/wireless/mediatek/mt7601u/{usb.c,usb.h,mcu.c}`,
  `drivers/net/wireless/mediatek/mt76/{Makefile,mt76.h}`, `mt76/mt76x0/{usb.c,usb_mcu.c,mt76x0.h}`,
  `mt76/mt76x2/{usb.c,mt76x2.h}`, `mt76/mt7921/usb.c`, `mt76/mt792x.h`,
  `drivers/net/wireless/ath/ath9k/{hif_usb.c,hif_usb.h}`
- torvalds/linux, probing por tag: mesmos caminhos em `?h=v4.1…v5.18` (tabela §2.1)
- linux-firmware, `plain/WHENCE` master (linhas 296–308, 1673–1679, 1708–1714,
  6079–6103, 6231–6256)
- Host: `/lib/modules/6.17.0-1020-oracle/` — `modinfo` (saídas embutidas §1.2,
  §2.2, §3.2, §4.2) e `modules.alias` (linhas 17835, 18108, 18649, 18671)
