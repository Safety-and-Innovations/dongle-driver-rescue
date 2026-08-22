# Research — Realtek Wi-Fi & Bluetooth chipsets

- **Fontes:** código-fonte do kernel upstream coletado em `~/.research_realtek`
  (arquivos citados por `arquivo:linha` abaixo), WHENCE completo do linux-firmware
  (10.672 linhas), `modules.alias` do host local (kernel 6.17.0-oracle).
- **Regra:** cada fato cita fonte; sem evidência = `UNKNOWN`.

## 1. Achado crítico — `rtl8xxxu` rejeita `new_id`

```c
static struct usb_driver rtl8xxxu_driver = {
    ...
    .id_table = dev_table,
    .no_dynamic_id = 1,
```
— `drivers_net_wireless_realtek_rtl8xxxu_core.c:8289`

**Consequência de produto (CONFIRMED):** o reparo Estado B via escrita em
`/sys/bus/usb/drivers/rtl8xxxu/new_id` **não funciona** para toda a família
coberta pelo rtl8xxxu (RTL8188/8192/8811/8812/8821/8814 USB). O plano de reparo B
para esses chips deve declarar isso e apontar alternativa legítima
(recompilar não é opção da V1; reportar ID ausente + origem oficial).
Drivers que aceitam `new_id`: qualquer `usb_driver` sem essa flag
(mecanismo em `drivers/usb/core/driver.c`, acervo `/tmp/ksrc/driver.c`).

A tabela `dev_table` tem **122 entradas** `USB_DEVICE(_AND_INTERFACE_INFO)`
cobrindo VID 0x0bda e OEMs (TP-Link 0x2357, D-Link 0x2001, Mercusys 0x2c4e,
Edimax 0x07b8, Netgear 0x0846 etc.) — todas com interface class 0xff/0xff/0xff
nos chips AC (`rtl8xxxu_core.c`, contagem verificada por grep).

## 2. Wi-Fi — mapeamento chipset → módulo in-tree

| Chipset | Módulo in-tree | Firmware (WHENCE:linha) | Confiança |
|---|---|---|---|
| RTL8188EU | r8188eu (fora do rtl8xxxu no 6.x) ou rtl8xxxu | `rtlwifi/rtl8188eufw.bin` (WHENCE:3521); variante `rtl8188efw.bin` (:3356) | HIGH_CONFIDENCE |
| RTL8192EU | rtl8xxxu | via dev_table (IDs 0x818c, 2357:0107, 2019:ab33, 2001:3312...) | CONFIRMED (fonte: tabela) |
| RTL8811CU / RTL8821CU | rtl8xxxu | `rtlwifi/rtl8821aefw.bin` + `_wowlan`/`_29` (:3375-3378) | HIGH_CONFIDENCE |
| RTL8812AU / RTL8814AU | rtl8xxxu | `rtlwifi/rtl8812aefw.bin` (:3365) | HIGH_CONFIDENCE |
| RTL8192CU (legado) | rtl8192cu (rtlwifi) | `rtl8192cufw{,_A,_B,_TMSC}.bin` (:3280-83) | CONFIRMED |

UNKNOWN / confirmar na implementação: qual módulo reivindica cada PID exato em
cada versão de kernel (r8188eu foi removido do mainline no 6.9 e parte dos chips
migrou ao rtl8xxxu — verificar contra `modules.alias` da distro-alvo na execução,
não aqui).

## 3. Bluetooth — a decisão de firmware já está no kernel (`btrtl`)

Tabela oficial `ic_id_table` — `drivers_bluetooth_btrtl.c:106` ss. Formato:
`IC_INFO(lmp_subver, hci_rev, hci_ver, bus)` → `fw_name`/`cfg_name`.
Defines em `btrtl.c:25-33`; casamento em `:350` (match_flags LMPSUBV/HCIREV).

| Chip | lmp_subver | hci_rev | hci_ver | Bus | Firmware |
|---|---|---|---|---|---|
| 8723A | 0x1200 | 0xb | 0x6 | USB | `rtl_bt/rtl8723a_fw` |
| 8723B | 0x8723 | 0xb | 0x6 | USB | `rtl_bt/rtl8723b_fw` + `_config` |
| 8821A | 0x8821 | 0xa | 0x6 | USB | `rtl_bt/rtl8821a_fw` + `_config` |
| 8821C | 0x8821 | 0xc | 0x8 | USB | `rtl_bt/rtl8821c_fw` + `_config` |
| 8761A | 0x8761 | 0xa | 0x6 | USB | `rtl_bt/rtl8761a_fw` + `_config` |
| 8761B | 0x8761 | 0xb | 0xa | UART | `rtl_bt/rtl8761b_fw` + `_config` |
| 8761BU | 0x8761 | 0xb | 0xa | **USB** | `rtl_bt/rtl8761bu_fw` + `_config` |
| 8761CU | 0x8761 | 0xe | — | USB | `rtl_bt/rtl8761cu_fw` + `_config` |

**Achado RTL8761B vs BU (CONFIRMED):** mesmos `lmp_subver=0x8761`,
`hci_rev=0xb`, `hci_ver=0xa` — o que os distingue é o **barramento**
(HCI_UART vs HCI_USB). "RTL8761BUV" não é entrada separada na tabela: é o BU
com variação de embalagem. Erro clássico de tabela manual evitado: copiar a
decisão do kernel, incluindo o campo de barramento.
Prova extra: o próprio driver valida projeto pós-download e rejeita mismatch
com `"firmware is for %x but this is a %x"` (`btrtl.c:747-751`).

## 4. Revisões de silício — RTL8192CU A/B/TMSC cut

WHENCE:3280-3291 declara quatro arquivos e a proveniência exata:

```text
rtl8192cufw_A.bin:    Rtl8192CUFwUMCACutImgArray   (UMC A-cut)
rtl8192cufw_B.bin:    Rtl8192CUFwUMCBCutImgArray   (UMC B-cut)
rtl8192cufw_TMSC.bin: Rtl8192CUFwTSMCImgArray      (fab TSMC)
```

Seleção no driver por versão de hardware: `IS_VENDOR_UMC_A_CUT(rtlhal->version)`
(`rtlwifi/rtl8192cu_hw.c:894`). Para a ferramenta: quando o módulo expõe mais de
um firmware candidato para o mesmo chip, o diagnóstico lista TODOS os arquivos
que o módulo pode pedir (`modinfo -F firmware`) e usa o log do driver
(dmesg) como árbitro do arquivo realmente requisitado — nunca escolhe sozinho.

## 5. Clones CSR8510

Acervo não capturou evidência primária específica sobre detecção de clones CSR
(LMP subversion divergente). Status: **UNKNOWN** — ponteiro para confirmar:
`drivers/bluetooth/btusb.c` blacklists conhecidas e relatórios de LMP de
clones (fóruns técnicos; exigiria experimento com hardware físico).

## 6. Verificação local (host)

Host com três kernels Oracle 6.17 instalados: o em execução (1018) não traz
nenhum módulo wireless/BT; o instalado 1020 traz **194 módulos wireless**
(`find /lib/modules/6.17.0-1020-oracle -path '*wireless*' -name '*.ko*'`),
incluindo `rtl8xxxu.ko`, `mt7601u.ko`, `ath9k_htc.ko`, `btusb.ko`, `btrtl.ko`
(caminhos verificados por find neste host). Implicações:

1. Fixtures de teste carregam linhas de `modules.alias` sintéticas
   derivadas destas fontes (não do host).
2. O diagnóstico consulta sempre o tree do kernel **em execução** e sinaliza
   divergência com kernels instalados pendentes de reboot.
3. "Kernel sem driver algum" é cenário real de Estado E que o produto deve
   diagnosticar explicitamente, não exceção.
