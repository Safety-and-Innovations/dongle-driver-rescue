# Research — MediaTek/Ralink (mt76 family) & Atheros (AR9271)

- **Fontes:** `modinfo` executado contra o tree real
  `/lib/modules/6.17.0-1020-oracle` (host, saída embutida), WHANCE/WHENCE do
  linux-firmware (`/tmp/ddr-research/WHENCE`, 10.672 linhas), pacotes Debian de
  firmware baixados e inspecionados com `dpkg-deb` (`/tmp/ddr-research/distro/`),
  probing de versões do código-fonte upstream (transcript do agente).
- **Regra:** fato sem citação = UNKNOWN.

## 1. mt7601u — driver dedicado in-tree (CONFIRMED, modinfo real)

```text
filename:  .../mediatek/mt7601u/mt7601u.ko.zst
license:   GPL
firmware:  mt7601u.bin
alias:     usb:v148Fp7601d*dc*dsc*dp*ic*isc*ip*in*   (canonical Ralink)
```

Outros IDs reais no alias list: `7392:7710` (Edimax), `2A5F:1000`,
`2955:0001/1001/1003`, `2717:4106` (Xiaomi), `2001:3D04` (D-Link),
`148F:760C/760D`. Total 17 aliases no tree 1020.
Firmware `mt7601u.bin`: pacote Debian **firmware-mediatek** (verificado por
`dpkg-deb -c` no .deb baixado) e no novo pacote unificado linux-firmware.
Erro típico quando falta: `Direct firmware load for mt7601u.bin failed with
error -2` (padrão canônico, docs/research/linux-kernel.md §6).

## 2. MT7610U / MT7612U — família mt76 (mt76x0u / mt76x2u)

```text
mt76x0u: firmware mediatek/mt7610u.bin, mediatek/mt7610e.bin
         aliases: 0E8D:7650, 0E8D:7630, 2357:0105/010B/0123 (TP-Link),
                  0DF6:0079, 7392:C711 (Edimax), 20F4:806B
mt76x2u: firmware mt7662_rom_patch.bin, mt7662.bin
         aliases: 2357:0137, 045E:02FE/02E6 (Microsoft), 0846:9053/9014,
                  2C4E:0103, 0471:7600/2126
```

Ambos CONFIRMED por modinfo no tree 1020. Diferença para os drivers antigos
fora-da-árvore (mt7610u_sta/mt7612u_sta da MediaTek): os in-tree usam o
framework mt76 e firmwares `mediatek/*` do linux-firmware — nunca os binários
do CD do fabricante. Versão exata de kernel de entrada de cada um: probing do
agente mostra mt76 core presente em v4.17-v4.20 e mt76x0/mt76x2 USB em v5.x;
entrada exata marcada UNKNOWN (confirmar com git log do upstream na
implementação, se necessário para matriz de suporte).

## 3. MT7921AU — mt7921u (kernel recente)

```text
mt7921u: firmware mediatek/WIFI_MT7961_patch_mcu_1_2_hdr.bin
                mediatek/WIFI_RAM_CODE_MT7961_1.bin
         aliases: 35BC:0107, 0846:9065/9060, 3574:6211, 0E8D:7961
         (todos com icFFiscFFipFF — interface vendor-specific)
```

CONFIRMED por modinfo no tree 1020. WHENCE:6251 declara
`WIFI_MT7961_patch_mcu_1_2_hdr.bin`; existe também variante `1a_2` (:6231).
Kernel mínimo para mt7921u: UNKNOWN nesta sessão (probing não fechou; o tree
local 6.17 tem — suficiente para V1 declarar "kernel 6.x atual").

## 4. AR9271 — ath9k_htc

```text
filename: .../ath/ath9k/ath9k_htc.ko.zst
firmware: ath9k_htc/htc_9271-1.4.0.fw    (AR9271)
          ath9k_htc/htc_7010-1.4.0.fw    (AR7010)
aliases:  0CF3:9271, 0CF3:20FF, 0930:0A08, 04DA:3904, 0411:0197/017F,
          083A:A704, 0846:9018, 0CF3:7010 ...
```

CONFIRMED por modinfo. WHENCE:305 declara `htc_9271-1.4.0.fw` com
`Licence: Redistributable. See LICENCE.atheros_firmware` (:287/:301) e existe
a variante openfw com `Licence: Free software.
See LICENCE.open-ath9k-htc-firmware` (:308). Versões antigas 1.3 são aceitas
pelo driver (compatibilidade declarada no WHENCE); a 1.4.0 é a atual.
Pacote Debian: **firmware-atheros** (1 ocorrência de htc_9271 verificada no
.deb; o novo linux-firmware unificado também contém).

## 5. Armadilhas confirmadas — colisão de ID entre módulos

Varredura dos 1.301 aliases USB wireless/BT do tree 1020 encontrou colisões
reais (mesmo alias, dois módulos):

| Alias | Módulos concorrentes |
|---|---|
| `148F:760A` | mt7601u **e** mt76x0u |
| `7392:B711` (Edimax) | mt76x0u **e** mt76x2u |
| `13B1:0043` (Linksys) | rtw88_8822bu **e** rtw88_8822cu |

**Consequência de produto (CONFIRMED):** "um VID:PID → um módulo" é falso.
O diagnóstico deve listar TODOS os candidatos, marcar qual está carregado
(symlink driver) e usar dmesg como árbitro; o reparo nunca assume o módulo
sem checar o bound driver. É também a armadilha do chip rebatizado: um
"MT7610" com ID 148F:760A pode ser atendido por dois drivers diferentes —
a evidência decisiva é qual probe funcionou, não o rótulo.

Ralink legado: RT2870/RT3070 são atendidos por rt2800usb (presente no tree;
IDs 148F:2870/3070 na família) — dongles vendidos como "MT76xx" com esses IDs
são Ralink antigo, não MediaTek novo. Detalhar rt2800usb: fora do escopo V1
dos alvos, mas o detector deve saber classificar.

## 6. Tabela consolidada (alvos MediaTek/Atheros)

| Chipset | Módulo | Firmware | Pacote Debian | Confiança |
|---|---|---|---|---|
| MT7601U | mt7601u | mt7601u.bin | firmware-mediatek | CONFIRMED |
| MT7610U | mt76x0u | mediatek/mt7610u.bin (+e) | firmware-mediatek | CONFIRMED |
| MT7612U | mt76x2u | mt7662.bin + _rom_patch | firmware-mediatek | CONFIRMED |
| MT7921AU | mt7921u | mediatek/WIFI_MT7961_{patch_mcu_1_2_hdr,RAM_CODE_MT7961_1}.bin | firmware-mediatek | CONFIRMED |
| AR9271 | ath9k_htc | ath9k_htc/htc_9271-1.4.0.fw | firmware-atheros | CONFIRMED |

Todos os arquivos de firmware acima verificados presentes nos .deb baixados
(`dpkg-deb -c`), exceto `WIFI_RAM_CODE_MT7961_1.bin` (presente no
firmware-mediatek, confirmado junto ao patch).
