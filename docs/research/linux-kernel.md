# Research — Linux kernel: USB, binding, módulos e firmware

- **Fontes:** código-fonte do kernel coletado em `/tmp/ksrc` (arquivo:linha citado),
  `modules.alias` do host local (6.17.0-oracle), documentação upstream.
- **Regra:** fato sem citação = UNKNOWN.

## 1. sysfs — onde cada coisa mora (CONFIRMED, verificado no host + fonte)

Nó de **dispositivo** (`/sys/bus/usb/devices/1-2`):
`idVendor`, `idProduct`, `bcdDevice`, `bDeviceClass/SubClass/Protocol`,
strings `manufacturer/product/serial`, `uevent`. **Sem `modalias`** (verificado
no host; o atributo não existe no nó do dispositivo).

Nó de **interface** (`1-2:1.0`): `modalias`, `bInterfaceClass`,
symlink `driver`. Fonte: `modalias_show` em `/tmp/ksrc/sysfs.c:1157`
emite a partir de `intf->cur_altsetting` — só existe para interfaces:

```c
return sysfs_emit(buf,
        "usb:v%04Xp%04Xd%04Xdc%02Xdsc%02Xdp%02X"
        "ic%02Xisc%02Xip%02X", ...);
```

Dispositivos raiz são `usbN`; nós com `:` no nome são interfaces.

## 2. modules.alias — casamento modalias → módulo

Gerado pelo kbuild (`file2alias.c`) a partir das tabelas `usb_device_id` dos
drivers. Formato da linha:

```text
alias usb:v0BDAp8811d*dc*dsc*dp*icFFiscFFip00in* rtl8xxxu
```

O `d*` significa "qualquer bcdDevice"; drivers que fixam revisão emitem
`d0200*` etc. A resolução do kernel (modprobe) casa o modalias da interface
contra essas expressões; a ferramenta replica o mesmo algoritmo de glob sobre
o arquivo, na ordem do arquivo, e registra qual linha casou como evidência.

## 3. new_id — bind dinâmico, o mecanismo exato

`usb_store_new_id` (`/tmp/ksrc/driver.c:42-67`), CONFIRMED:

```c
fields = sscanf(buf, "%x %x %x %x %x", &idVendor, &idProduct,
                &bInterfaceClass, &refVendor, &refProduct);
if (fields < 2)
    return -EINVAL;
...
dynid->id.match_flags = USB_DEVICE_ID_MATCH_DEVICE;
```

- Formato aceito: `VID PID` (mínimo 2 campos hex); campo 3 opcional =
  `bInterfaceClass` (refina o match); campos 4-5 = refVendor/refProduct.
- Após inserir, o driver re-probeia dispositivos existentes.
- **Limitações:** não sobrevive a reboot; exige módulo já carregado;
  e alguns drivers desativam o mecanismo — caso crítico:
  `rtl8xxxu` tem `.no_dynamic_id = 1` (ver docs/research/realtek.md §1).
- Leitura de volta: `new_id_show` lista os dynids inseridos
  (`driver.c:114-130`) — a ferramenta pode verificar o próprio bind.

## 4. Persistência do bind

Como `new_id` é volátil, persistência legítima pós-reboot por uma de:

1. **Alias modprobe.d** — criar `.conf` em `/etc/modprobe.d/` com um alias
   cujo valor case o modalias do dispositivo apontando ao módulo
   (ex.: `alias usb:v0BDApF000d*dc*dsc*dp*icFFiscFFip00in* rtl8xxxu`);
   o coldplug do systemd/udev roda `modprobe` por alias na inicialização.
2. **Regra udev** com `DRIVER==`/bind explícito via script helper — mais frágil
   (depende de ordem e de binário externo).

Escolha V1: alias modprobe.d (declarativo, reversível por remoção do arquivo,
sem execução de código). Risco declarado: aliases custom sobrevivem a upgrades
de kernel porque o modalias não muda com o kernel.

## 5. Blacklist e bloqueio (Estado D)

Sintaxe: `blacklist <module>` impede o alias resolution automático;
`blacklist <module>` em `/etc/modprobe.d/*.conf`; precedência: último arquivo
em ordem lexicográfica vence em conflito de opções; `install <mod> /bin/false`
bloqueia totalmente. Secure Boot: módulo não assinado gera
"module verification failed" / "Lockdown: ..." no dmesg (fonte:
`lockdown_lsm.c` e `module-signing.rst` no acervo; mensagem exata a validar
na implementação contra o kernel-alvo).

## 6. Firmware — ordem real de busca e mensagem de falha (CONFIRMED)

`fw_path[]` (`/tmp/ksrc/fw_main.c:472-478`):

```c
static const char * const fw_path[] = {
    fw_path_para,                       /* kernel cmdline fw_class.path= */
    "/lib/firmware/updates/" UTS_RELEASE,
    "/lib/firmware/updates",
    "/lib/firmware/" UTS_RELEASE,
    "/lib/firmware"
};
```

Mensagem de falha exata (`fw_main.c:903`):
`"Direct firmware load for %s failed with error %d"` — padrão canônico para o
detector do Estado C. `-2` = ENOENT (arquivo ausente).

## 6. Verificação local (host)

Host com três kernels Oracle 6.17 instalados. O **em execução** (uname -r =
6.17.0-1018-oracle) não empacota nenhum módulo wireless/BT. O instalado
6.17.0-**1020**-oracle traz **194 módulos wireless** (verificado por find),
incluindo mt7601u com aliases reais (`modinfo` contra esse tree funcionou).

Implicações de produto:

1. A ferramenta deve resolver `modules.alias` do kernel **em execução**
   (`uname -r`), nunca "o mais novo instalado" — e detectar explicitamente o
   cenário "novo kernel instalado, reboot pendente", onde driver/firmware já
   existem no tree futuro mas não no ativo.
2. Fixtures de teste derivam das fontes citadas aqui, não do host.
3. "Kernel sem driver algum" permanece cenário válido de Estado E.
