import spidev
import lgpio
import subprocess
import time

EPD_SCK_PIN  = 11
EPD_MOSI_PIN = 10
EPD_CS_M_PIN = 8   # CE0 / M area  (driven manually via pinctrl)
EPD_CS_S_PIN = 7   # CE1 / S area  (driven manually via pinctrl)
EPD_DC_PIN   = 25
EPD_RST_PIN  = 17
EPD_BUSY_PIN = 24
EPD_PWR_PIN  = 18

_h = None       # lgpio handle (for RST/DC/PWR/BUSY)
_spi_m = None   # spidev0.0, no_cs (M area)
_spi_s = None   # spidev0.1, no_cs (S area)
_cs_m  = True   # CS line level high (inactive) at start
_cs_s  = True

def _pinctrl(args):
    # GPIO7/8 are kernel-owned (spidev CS pins); lgpio cannot claim them.
    # With no_cs=True the kernel stops toggling them, so we drive them via pinctrl.
    subprocess.run(["pinctrl", "set"] + args, check=False)

def module_init():
    global _h, _spi_m, _spi_s, _cs_m, _cs_s
    _h = lgpio.gpiochip_open(0)
    for pin in [EPD_RST_PIN, EPD_DC_PIN, EPD_PWR_PIN]:
        lgpio.gpio_claim_output(_h, pin, 0)
    lgpio.gpio_claim_input(_h, EPD_BUSY_PIN, lgpio.SET_PULL_NONE)

    _spi_m = spidev.SpiDev()
    _spi_m.open(0, 0)
    _spi_m.max_speed_hz = 4_000_000
    _spi_m.mode = 0
    _spi_m.no_cs = True   # kernel must NOT toggle CE — we drive GPIO8/7 manually

    _spi_s = spidev.SpiDev()
    _spi_s.open(0, 1)
    _spi_s.max_speed_hz = 4_000_000
    _spi_s.mode = 0
    _spi_s.no_cs = True

    # Make CS pins idle-high (inactive).
    _pinctrl(["7,8", "op", "dh"])
    _cs_m = True
    _cs_s = True

    lgpio.gpio_write(_h, EPD_PWR_PIN, 1)
    time.sleep(0.1)

def module_exit():
    global _h, _spi_m, _spi_s
    if _spi_m: _spi_m.close(); _spi_m = None
    if _spi_s: _spi_s.close(); _spi_s = None
    if _h:
        for pin in [EPD_RST_PIN, EPD_DC_PIN, EPD_PWR_PIN, EPD_BUSY_PIN]:
            try: lgpio.gpio_free(_h, pin)
            except: pass
        lgpio.gpiochip_close(_h)
        _h = None

def _apply_cs():
    m = "dl" if not _cs_m else "dh"   # _cs_m True == inactive(high)
    s = "dl" if not _cs_s else "dh"
    if m == s:
        _pinctrl(["7,8", m])
    else:
        _pinctrl(["8", m])
        _pinctrl(["7", s])

def digital_write(pin, value):
    global _cs_m, _cs_s
    if pin == EPD_CS_M_PIN:
        _cs_m = (value != 0)
        _apply_cs()
    elif pin == EPD_CS_S_PIN:
        _cs_s = (value != 0)
        _apply_cs()
    else:
        lgpio.gpio_write(_h, pin, value)

def digital_read(pin):
    return lgpio.gpio_read(_h, pin)

def spi_writebyte(data):
    # Both spidev0.0 and spidev0.1 share the same physical SPI bus (MOSI/CLK).
    # CS selection is handled exclusively by pinctrl, not by which fd we write to.
    # Writing to both fds would send each byte twice — always use _spi_m only.
    _spi_m.writebytes([data])

def spi_writebyte2(buf, length):
    data = list(buf) if not isinstance(buf, (list, bytes, bytearray)) else buf
    _spi_m.writebytes2(data)

def delay_ms(ms):
    time.sleep(ms / 1000.0)
