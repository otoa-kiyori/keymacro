"""
plugins/g13/lcd.py — G13 LCD renderer.

The G13 has a 160×43 pixel monochrome LCD.

Wire format (961 bytes written to USB endpoint 0x02):
  byte[0]        = 0x03  (report ID)
  bytes[1..960]  = 6 pages × 160 columns
                   page  = row // 8   (page 0 = rows 0-7, … page 5 = rows 40-47)
                   col   = x (0..159)
                   bit   = row % 8    (bit 0 = topmost row of the page)
  Only 43 of the 48 addressable rows are visible; the bottom 5 bits of
  page 5 are ignored by the display hardware.

Requires Pillow (python3-pil).  If Pillow is not available, all functions
return None / empty buffers — the G13 plugin disables LCD feedback gracefully.

Install: sudo apt install python3-pil
"""

from __future__ import annotations

LCD_WIDTH  = 160
LCD_HEIGHT = 43
LCD_PAGES  = 6                              # 6 × 8 = 48 rows
LCD_BUF    = 1 + LCD_PAGES * LCD_WIDTH     # 961 bytes

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


def is_available() -> bool:
    """Return True if Pillow is installed and LCD rendering is possible."""
    return _PIL_OK


def render_text(text: str) -> bytes | None:
    """
    Render `text` centred on the G13 LCD and return a 961-byte buffer
    ready to write to USB endpoint 0x02.

    Returns None if Pillow is not installed.
    """
    if not _PIL_OK:
        return None

    img  = Image.new("1", (LCD_WIDTH, LCD_HEIGHT), 0)   # 1-bit, black bg
    draw = ImageDraw.Draw(img)

    # Pillow 10+ supports size= on the built-in font; older versions ignore it.
    try:
        font = ImageFont.load_default(size=14)
    except TypeError:
        font = ImageFont.load_default()

    # Centre the text on the display.
    bbox   = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = max(0, (LCD_WIDTH  - text_w) // 2) - bbox[0]
    y = max(0, (LCD_HEIGHT - text_h) // 2) - bbox[1]

    draw.text((x, y), text, fill=1, font=font)

    return _image_to_lcd_buf(img)


def clear_buffer() -> bytes:
    """Return a 961-byte all-black (blank) LCD buffer."""
    buf    = bytearray(LCD_BUF)
    buf[0] = 0x03
    return bytes(buf)


def write_lcd(dev, buffer: bytes) -> None:
    """
    Write a 961-byte LCD buffer to the G13 USB device.

    Must be called from the capture thread (which owns the USB handle)
    to avoid concurrent USB access.
    """
    try:
        dev.write(0x02, buffer)
    except Exception:
        pass   # best-effort; never crash the caller


def _image_to_lcd_buf(img: "Image.Image") -> bytes:
    """Convert a 160×43 mode-'1' PIL image to the G13 LCD wire format."""
    buf    = bytearray(LCD_BUF)
    buf[0] = 0x03
    pixels = img.load()
    for y in range(LCD_HEIGHT):
        page = y // 8
        bit  = y % 8
        for x in range(LCD_WIDTH):
            if pixels[x, y]:
                buf[1 + page * LCD_WIDTH + x] |= (1 << bit)
    return bytes(buf)
