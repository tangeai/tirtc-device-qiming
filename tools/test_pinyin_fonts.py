"""Exercise production LVGL glyph lookup, bitmap and fallback for NFC pinyin."""
from pathlib import Path
import string
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
LVGL = ROOT / "managed_components/lvgl__lvgl"
FONTS = ROOT / "components/starter_product/src"
NAMES = ("cn_18", "cn_18_supplement", "pinyin_18", "door_18", "door_24",
         "door_body_24", "door_26", "door_32")
ACCENTS = "\u00fc\u0101\u00e1\u01ce\u00e0\u0113\u00e9\u011b\u00e8\u012b\u00ed\u01d0\u00ec\u014d\u00f3\u01d2\u00f2\u016b\u00fa\u01d4\u00f9\u01d6\u01d8\u01da\u01dc"
CHARS = string.ascii_letters + ACCENTS + ACCENTS.upper()
MAIN = [NAMES[0], *NAMES[3:]]
SOURCE = r'''
#include "lvgl.h"
#include <assert.h>
#include <stdio.h>
@DECLARATIONS@
static const lv_font_t *fonts[] = {@FONTS@};
static const uint32_t letters[] = {@LETTERS@};

int main(void) {
    unsigned checked = 0, fallback = 0;
    for (unsigned f = 0; f < sizeof(fonts) / sizeof(*fonts); f++) {
        const lv_font_t *font = fonts[f];
        for (unsigned i = 0; i < sizeof(letters) / sizeof(*letters); i++) {
            lv_font_glyph_dsc_t glyph;
            assert(lv_font_get_glyph_dsc(font, &glyph, letters[i], 0));
            assert(!glyph.is_placeholder && glyph.box_w && glyph.box_h && glyph.adv_w);
            assert(glyph.box_h + glyph.ofs_y <= font->line_height - font->base_line);
            assert(-glyph.ofs_y <= font->base_line);
            assert(lv_font_get_glyph_bitmap(glyph.resolved_font, letters[i]));
            if (f != 0 || i < 52) assert(glyph.resolved_font == font);
            fallback += glyph.resolved_font == &ui_font_pinyin_18;
            checked++;
        }
    }
    lv_font_glyph_dsc_t glyph;
    assert(fallback > 0);
    assert(lv_font_get_glyph_dsc(&ui_font_cn_18, &glyph, 0x95e8, 0));
    assert(glyph.resolved_font == &ui_font_cn_18);
    assert(!lv_font_get_glyph_dsc(&ui_font_cn_18, &glyph, 0x10ffff, 0));
    printf("PASS: %u pinyin lookups, %u terminal fallback hits; Han glyph and missing glyph preserved\n",
           checked, fallback);
}
'''

with tempfile.TemporaryDirectory(prefix="wt99-pinyin-") as tmp:
    src, exe = Path(tmp) / "test.c", Path(tmp) / "test"
    src.write_text(SOURCE.replace("@DECLARATIONS@", "\n".join(
        f"LV_FONT_DECLARE(ui_font_{name});" for name in NAMES
    )).replace("@FONTS@", ", ".join(f"&ui_font_{name}" for name in MAIN)
    ).replace("@LETTERS@", ", ".join(hex(ord(char)) for char in CHARS)), encoding="ascii")
    subprocess.run(["cc", "-std=gnu11", "-DLV_CONF_SKIP", "-DLV_FONT_FMT_TXT_LARGE=1",
                    "-fsanitize=address,undefined", "-I", str(LVGL),
                    str(src), *[str(FONTS / f"ui_font_{name}.c") for name in NAMES],
                    *[str(LVGL / path) for path in ("src/font/lv_font.c",
                       "src/font/lv_font_fmt_txt.c", "src/misc/lv_utils.c")],
                    "-o", str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
