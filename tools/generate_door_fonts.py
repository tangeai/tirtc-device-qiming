#!/usr/bin/env python3
"""Generate the door UI's static LVGL 8.4 fonts (Pillow/FreeType required).

Run from the project root or another trusted directory, never a download folder:
  C:/Espressif/tools/python/v5.5.5/venv/Scripts/python.exe -I -X utf8 \
      tools/generate_door_fonts.py

The original TTF and OFL are pinned and retained in assets/fonts. No downloads,
font installation, firmware builds, runtime decompression or glyph cache are used.
Door text fonts cover printable ASCII, precomposed pinyin, Chinese C string
literals in starter_product_door.inc, and EXTRA_TEXT. The legacy font chain
uses a small terminal pinyin fallback without replacing its Han glyphs.
Use --check to compare generated resources without writing; --preview optionally
writes a proof image rendered from the actual packed 4bpp data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
from bisect import bisect_left
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, __version__ as PILLOW_VERSION, features

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "components/starter_product/assets/fonts"
DOOR_SOURCE = ROOT / "components/starter_product/src/starter_product_door.inc"
FONT = ASSETS / "notosanssc-original/NotoSansSC[wght].ttf"
LICENSE = ASSETS / "notosanssc-license/OFL.txt"
REVISION = "a85815a42757630ce188fdad368c2dfc444d4773"
FONT_SHA256 = "a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da"
LICENSE_SHA256 = "1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9"
EXTRA_TEXT = (
    "门禁机本机角色查看端发送端等待来访有人来访时在这里接听选择设备发起呼叫呼叫查看端"
    "对端设备更换设备在线离线尚未选择设备已移除请重新选择设备尚未就绪请检查网络和设备绑定"
    "呼叫后等待对方接听接听后显示对端画面其他功能正在使用远程查看中正在提交呼叫通话中"
    "正在接听正在拒接正在结束通话接听拒接取消呼叫关闭麦克风开启麦克风关摄像头开摄像头"
    "摄像头已关闭门锁尚未配置无法开门开门挂断更多功能上一屏下一屏表情时钟当前设备暂无设备"
    "联系人请先在平台添加对端设备再同步通讯录已选择已切换为正在同步同步未受理请重试正在保存"
    "设置设置保存失败重启后可能恢复原设置设备离线请等待对端上线先选择一台设备接通后显示"
    "画面连接中正在建立通话等待对方接听来访呼叫网络未连接已联网未绑定已绑定操作未受理请重试"
    "等待来电·…✓›‹"
    "小钛入户门口机客厅分机一楼二楼玄关室内室外大门前后院单元中心管理物业测试"
)
# Readable Chinese C literals, including adjacent strings and escaped codepoints.
C_TOKEN = re.compile(r'//[^\n]*|/\*.*?\*/|(?P<string>"(?:\\.|[^"\\])*")|\'(?:\\.|[^\'\\])*\'', re.S)
C_ESCAPE = re.compile(r'\\(?:u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|x[0-9a-fA-F]+|[0-7]{1,3}|.)', re.S)
PINYIN = (
    "\u00fc\u0101\u00e1\u01ce\u00e0\u0113\u00e9\u011b\u00e8"
    "\u012b\u00ed\u01d0\u00ec\u014d\u00f3\u01d2\u00f2"
    "\u016b\u00fa\u01d4\u00f9\u01d6\u01d8\u01da\u01dc"
)
PINYIN_CODEPOINTS = sorted(map(ord, PINYIN + PINYIN.upper()))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_c_string(token: str) -> str:
    simple = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "a": "\a"}

    def decode(match: re.Match) -> str:
        value = match.group()[1:]
        if value[0] in "uUx":
            return chr(int(value[1:], 16))
        if value[0] in "01234567":
            return chr(int(value, 8))
        return simple.get(value, value)

    return C_ESCAPE.sub(decode, token[1:-1])


def charset(source: str) -> list[int]:
    text = EXTRA_TEXT
    for match in C_TOKEN.finditer(source):
        if match.group("string"):
            literal = decode_c_string(match.group("string"))
            if any("\u3400" <= char <= "\u9fff" or "\U00020000" <= char <= "\U000323af" for char in literal):
                text += literal
    return sorted(set(range(0x20, 0x7F)) | set(PINYIN_CODEPOINTS) |
                  {ord(char) for char in text if ord(char) >= 0x20})


def source_cmap(data: bytes) -> set[int]:
    """Read the pinned font's Unicode cmap format 12, without extra dependencies.

    Only the verified original is accepted. Fail explicitly if its cmap changes;
    never rasterize .notdef as if it were an available Chinese glyph.
    """
    table_count = struct.unpack_from(">H", data, 4)[0]
    for index in range(table_count):
        tag, _, offset, _ = struct.unpack_from(">4sIII", data, 12 + index * 16)
        if tag == b"cmap":
            cmap_offset = offset
            break
    else:
        raise ValueError("Source font has no cmap")
    records = struct.unpack_from(">H", data, cmap_offset + 2)[0]
    for index in range(records):
        platform, encoding, relative = struct.unpack_from(">HHI", data, cmap_offset + 4 + index * 8)
        offset = cmap_offset + relative
        if platform not in (0, 3) or (platform == 3 and encoding != 10):
            continue
        if struct.unpack_from(">H", data, offset)[0] != 12:
            continue
        count = struct.unpack_from(">I", data, offset + 12)[0]
        supported = set()
        for group in range(count):
            start, end, gid = struct.unpack_from(">III", data, offset + 16 + group * 12)
            supported.update(range(start + (gid == 0), end + 1))
        return supported
    raise ValueError("Pinned source requires a Unicode cmap format 12")


def rasterize(path: Path, codepoints: list[int], size: int, weight: int) -> dict:
    font = ImageFont.truetype(str(path), size, layout_engine=ImageFont.Layout.BASIC)
    axes = font.get_variation_axes()
    if sum(axis["name"] == b"Weight" for axis in axes) != 1:
        raise ValueError("Expected one weight axis")
    font.set_variation_by_axes([weight if axis["name"] == b"Weight" else axis["default"] for axis in axes])
    glyphs, bitmap = [], bytearray()
    ascent = descent = 0
    for cp in codepoints:
        char = chr(cp)
        mask, (left, top) = font.getmask2(char, mode="L", anchor="ls")
        # Quantize before cropping so every stored edge has non-zero 4bpp ink.
        image = Image.frombytes("L", mask.size, bytes(mask))
        image = image.point([(value * 15 + 127) // 255 for value in range(256)])
        bounds = image.getbbox()
        pixels = b""
        width = height = ofs_x = ofs_y = 0
        if bounds:
            cropped = image.crop(bounds)
            width, height = cropped.size
            ofs_x = left + bounds[0]
            # Pillow's ls anchor is the baseline; LVGL's positive ofs_y is up.
            ofs_y = -(top + bounds[3])
            ascent = max(ascent, height + ofs_y)
            descent = max(descent, -ofs_y)
            pixels = cropped.tobytes()
        elif cp != 0x20:
            raise ValueError(f"Empty required glyph U+{cp:04X}")
        packed = bytearray((len(pixels) + 1) // 2)
        for index, value in enumerate(pixels):
            # LVGL plain glyphs are a continuous pixel stream, high nibble first;
            # rows do NOT receive padding, even when the glyph width is odd.
            packed[index // 2] |= value << (4 if index % 2 == 0 else 0)
        restored = bytes((packed[i // 2] >> (4 if i % 2 == 0 else 0)) & 15 for i in range(len(pixels)))
        if restored != pixels:
            raise ValueError(f"4bpp round-trip failed for U+{cp:04X}")
        advance = int(font.getlength(char) * 16 + 0.5)
        if not (0 < advance < 4096 and width <= 255 and height <= 255 and -128 <= ofs_x <= 127 and -128 <= ofs_y <= 127):
            raise ValueError(f"Glyph outside LVGL compact descriptor limits: U+{cp:04X}")
        glyphs.append(dict(cp=cp, bitmap_index=len(bitmap), adv_w=advance,
                           box_w=width, box_h=height, ofs_x=ofs_x, ofs_y=ofs_y))
        bitmap.extend(packed)
    # Tight line metrics encompass all emitted glyphs and the existing 20/3
    # fallback line. No unused Noto typographic leading is imposed on buttons.
    ascent, descent = max(ascent, 17), max(descent, 3)
    if len(bitmap) >= 1 << 20:
        raise ValueError("Bitmap exceeds LVGL compact 20-bit index")
    for glyph in glyphs:
        y = ascent - glyph["box_h"] - glyph["ofs_y"]
        if y < 0 or y + glyph["box_h"] > ascent + descent:
            raise ValueError("Glyph would clip outside declared line metrics")
    # Split sparse ranges when the uint16 range_length would overflow. Sparse
    # lookup also avoids LVGL 8.4's inclusive range-end quirk for format0 maps.
    cmaps = []
    start = 0
    while start < len(codepoints):
        end = start + 1
        while end < len(codepoints) and codepoints[end] - codepoints[start] < 65535:
            end += 1
        cmaps.append(dict(start=codepoints[start], length=codepoints[end - 1] - codepoints[start] + 1,
                          glyph_id=start + 1, offsets=[cp - codepoints[start] for cp in codepoints[start:end]]))
        start = end
    # Mirror the runtime sparse binary lookup and validate every glyph ID.
    for index, cp in enumerate(codepoints, 1):
        found = 0
        for cmap in cmaps:
            relative = cp - cmap["start"]
            if 0 <= relative <= cmap["length"]:
                offset = bisect_left(cmap["offsets"], relative)
                if offset < len(cmap["offsets"]) and cmap["offsets"][offset] == relative:
                    found = cmap["glyph_id"] + offset
                break
        if found != index:
            raise ValueError(f"Sparse cmap lookup failed for U+{cp:04X}")
    return dict(size=size, weight=weight, glyphs=glyphs, bitmap=bytes(bitmap), cmaps=cmaps,
                line_height=ascent + descent, base_line=descent, ascent=ascent)


def emit_c(data: dict) -> bytes:
    name = data.get("symbol", f"ui_font_door_{data['size']}")
    fallback = data.get("fallback", "ui_font_cn_18")
    lines = [
        "/* SPDX-License-Identifier: OFL-1.1",
        " * " + data.get("copyright", "Copyright 2014-2021 Adobe (http://www.adobe.com/), with Reserved Font Name 'Source'."),
        f" * Modified font: {name}; derived from {data.get('family', 'Noto Sans SC')}, weight {data['weight']}.",
        f" * Source SHA-256: {data.get('source_sha256', FONT_SHA256)}",
        " * License: " + data.get("license_path", "components/starter_product/assets/fonts/notosanssc-license/OFL.txt"),
        " * Generated by " + data.get("generator", "tools/generate_door_fonts.py") + "; do not edit by hand.",
        f" * {len(data['glyphs'])} glyphs, {data['size']}px EM, 4bpp plain, {len(data['bitmap'])} bitmap bytes.",
        " * All data is const; no decompression, allocation or glyph cache.",
        (" * Missing characters fall back to ui_font_cn_18 at its native size." if fallback
         else " * Terminal fallback for precomposed pinyin glyphs."),
        " */", '#include "lvgl.h"', "",
        "#if LVGL_VERSION_MAJOR != 8 || !LV_VERSION_CHECK(8, 2, 0)",
        '#error "Door fonts require LVGL 8.2 or newer within LVGL 8 (fallback support)"',
        "#endif", "", f"LV_FONT_DECLARE({fallback});" if fallback else "", "",
        "static LV_ATTRIBUTE_LARGE_CONST const uint8_t glyph_bitmap[] = {",
    ]
    bitmap = data["bitmap"]
    for index, glyph in enumerate(data["glyphs"]):
        cp = glyph["cp"]
        # Codepoints alone are safe even for ASCII comment delimiters.
        lines.append(f"    /* U+{cp:04X} */")
        end = data["glyphs"][index + 1]["bitmap_index"] if index + 1 < len(data["glyphs"]) else len(bitmap)
        chunk = bitmap[glyph["bitmap_index"]:end]
        for offset in range(0, len(chunk), 16):
            lines.append("    " + ", ".join(f"0x{byte:02x}" for byte in chunk[offset:offset + 16]) + ",")
    lines += ["};", "", "static const lv_font_fmt_txt_glyph_dsc_t glyph_dsc[] = {",
              "    { .bitmap_index = 0, .adv_w = 0, .box_w = 0, .box_h = 0, .ofs_x = 0, .ofs_y = 0 }, /* reserved */"]
    for glyph in data["glyphs"]:
        fields = ", ".join(f".{key} = {glyph[key]}" for key in ("bitmap_index", "adv_w", "box_w", "box_h", "ofs_x", "ofs_y"))
        lines.append(f"    {{ {fields} }}, /* U+{glyph['cp']:04X} */")
    lines += ["};", ""]
    for index, cmap in enumerate(data["cmaps"]):
        lines.append(f"static const uint16_t unicode_list_{index}[] = {{")
        for offset in range(0, len(cmap["offsets"]), 12):
            lines.append("    " + ", ".join(f"0x{value:04x}" for value in cmap["offsets"][offset:offset + 12]) + ",")
        lines += ["};", ""]
    lines.append("static const lv_font_fmt_txt_cmap_t cmaps[] = {")
    for index, cmap in enumerate(data["cmaps"]):
        lines += ["    {", f"        .range_start = {cmap['start']}, .range_length = {cmap['length']},",
                  f"        .glyph_id_start = {cmap['glyph_id']}, .unicode_list = unicode_list_{index},",
                  f"        .glyph_id_ofs_list = NULL, .list_length = {len(cmap['offsets'])},",
                  "        .type = LV_FONT_FMT_TXT_CMAP_SPARSE_TINY", "    },"]
    lines += ["};", "", "static const lv_font_fmt_txt_dsc_t font_dsc = {",
              "    .glyph_bitmap = glyph_bitmap,", "    .glyph_dsc = glyph_dsc,", "    .cmaps = cmaps,",
              "    .kern_dsc = NULL,", "    .kern_scale = 0,", f"    .cmap_num = {len(data['cmaps'])},",
              "    .bpp = 4,", "    .kern_classes = 0,", "    .bitmap_format = LV_FONT_FMT_TXT_PLAIN,",
              "    .cache = NULL", "};", "", f"const lv_font_t {name} = {{",
              "    .get_glyph_dsc = lv_font_get_glyph_dsc_fmt_txt,",
              "    .get_glyph_bitmap = lv_font_get_bitmap_fmt_txt,",
              f"    .line_height = {data['line_height']},", f"    .base_line = {data['base_line']},",
              "    .subpx = LV_FONT_SUBPX_NONE,", f"    .underline_position = -{max(1, data['size'] // 12)},",
              f"    .underline_thickness = {max(1, data['size'] // 16)},", "    .dsc = &font_dsc,",
              f"    .fallback = {'&' + fallback if fallback else 'NULL'},", "    .user_data = NULL", "};", ""]
    return "\n".join(lines).encode("utf-8")


def preview(fonts: list[dict]) -> None:
    image = Image.new("RGB", (1000, 460), "#EEF3F6")
    draw = ImageDraw.Draw(image)
    samples = ["门禁机  本机角色  查看端 / 发送端", "等待来访 · 选择设备 › 已选择 ✓",
               "正在建立通话… 00:59  接听 / 拒接", "门锁尚未配置，无法开门  Agjpqy | [] {}"]
    y = 12
    for data in fonts:
        draw.text((24, y), f"{data['size']}px / weight {data['weight']} / line {data['line_height']} / baseline {data['base_line']}", fill="#526878")
        y += 24
        glyphs = {glyph["cp"]: glyph for glyph in data["glyphs"]}
        for sample in samples:
            x = 24
            baseline = y + data["ascent"]
            draw.line((20, baseline, 980, baseline), fill="#DCE6ED")
            for char in sample:
                glyph = glyphs[ord(char)]
                count = glyph["box_w"] * glyph["box_h"]
                if count:
                    start = glyph["bitmap_index"]
                    packed = data["bitmap"][start:start + (count + 1) // 2]
                    pixels = bytes(((packed[i // 2] >> (4 if i % 2 == 0 else 0)) & 15) * 17 for i in range(count))
                    mask = Image.frombytes("L", (glyph["box_w"], glyph["box_h"]), pixels)
                    image.paste("#193448", (x + glyph["ofs_x"], baseline - glyph["box_h"] - glyph["ofs_y"]), mask)
                x += (glyph["adv_w"] + 8) >> 4
            y += data["line_height"] + 7
        y += 18
    image.save(ASSETS / "door_fonts_preview.png")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Compare resources without writing")
    parser.add_argument("--preview", action="store_true", help="Write a proof PNG from packed glyphs")
    args = parser.parse_args()
    if args.check and args.preview:
        parser.error("--check cannot write --preview")
    font_bytes, license_bytes = FONT.read_bytes(), LICENSE.read_bytes()
    if sha256(font_bytes) != FONT_SHA256 or sha256(license_bytes) != LICENSE_SHA256:
        raise ValueError("Original font/OFL hash mismatch; do not silently accept a replacement")
    source_bytes = DOOR_SOURCE.read_bytes()
    codepoints = charset(source_bytes.decode("utf-8"))
    missing = sorted(set(codepoints) - source_cmap(font_bytes))
    if missing:
        raise ValueError("Source missing required glyphs: " + " ".join(f"U+{cp:04X}" for cp in missing))
    fonts = []
    for size, weight, line, symbol in [(24, 500, 35, "ui_font_door_24"),
            (32, 500, 47, "ui_font_door_32"), (24, 400, 35, "ui_font_door_body_24"),
            (18, 500, 27, "ui_font_door_18"), (26, 500, 38, "ui_font_door_26")]:
        data = rasterize(FONT, codepoints, size, weight)
        if data["line_height"] > line:
            raise ValueError("Design line height clips required glyphs")
        ascent, descent = ImageFont.truetype(str(FONT), size).getmetrics()
        baseline = ascent + (line - ascent - descent) // 2
        data["base_line"] = line - baseline
        data["ascent"] = baseline
        data["line_height"], data["symbol"] = line, symbol
        fonts.append(data)
    # Stacked uppercase tone marks need a smaller EM to fit the legacy line.
    pinyin = rasterize(FONT, PINYIN_CODEPOINTS, 15, 400)
    if (pinyin["line_height"], pinyin["base_line"]) != (20, 3):
        raise ValueError("Pinyin fallback must fit the existing 20/3 body font metrics")
    pinyin.update(symbol="ui_font_pinyin_18", fallback=None)
    fonts.append(pinyin)
    outputs = {}
    manifest = dict(
        license="OFL-1.1", copyright="Copyright 2014-2021 Adobe (http://www.adobe.com/), with Reserved Font Name 'Source'",
        source_repository="https://github.com/google/fonts", source_revision=REVISION,
        upstream_project="https://github.com/notofonts/noto-cjk",
        original_font=dict(path=FONT.relative_to(ROOT).as_posix(), bytes=len(font_bytes), sha256=FONT_SHA256,
                           url=f"https://raw.githubusercontent.com/google/fonts/{REVISION}/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf"),
        original_license=dict(path=LICENSE.relative_to(ROOT).as_posix(), bytes=len(license_bytes), sha256=LICENSE_SHA256,
                              url=f"https://raw.githubusercontent.com/google/fonts/{REVISION}/ofl/notosanssc/OFL.txt"),
        generator="tools/generate_door_fonts.py", pillow=PILLOW_VERSION, freetype=features.version_module("freetype2"),
        rasterization="FreeType BASIC, baseline anchor ls, grayscale 0..255 rounded to 0..15; cropped; high nibble first; no row padding",
        charset_source=DOOR_SOURCE.relative_to(ROOT).as_posix(), charset_source_sha256=sha256(source_bytes),
        extra_text=EXTRA_TEXT, codepoints=[f"U+{cp:04X}" for cp in codepoints], glyph_count=len(codepoints), missing_required_glyphs=[],
        fallback="ui_font_cn_18 -> ui_font_cn_18_supplement -> ui_font_pinyin_18; pinyin 15px EM fits the legacy 20/3 line; LVGL placeholder if absent throughout chain",
        fallback_license="Existing font licensing is separate; ui_font_cn_18 cites simhei.ttf and THIRD_PARTY.md. New OFL fonts do not relicense the fallback.",
        fonts=[])
    for data in fonts:
        path = ROOT / f"components/starter_product/src/{data['symbol']}.c"
        content = emit_c(data)
        outputs[path] = content
        manifest["fonts"].append(dict(
            symbol=data['symbol'], path=path.relative_to(ROOT).as_posix(), bytes=len(content), sha256=sha256(content),
            em_pixels=data["size"], weight=data["weight"], glyph_count=len(data["glyphs"]), bitmap_bytes=len(data["bitmap"]),
            bpp=4, bitmap_format="LV_FONT_FMT_TXT_PLAIN", cmap_format="LV_FONT_FMT_TXT_CMAP_SPARSE_TINY",
            cmap_count=len(data["cmaps"]), line_height=data["line_height"], base_line=data["base_line"], cache=None,
            descriptor_count=len(data["glyphs"]) + 1,
            # Actual binary sizes depend on LV_FONT_FMT_TXT_LARGE, ABI and linker.
            bitmap_and_unicode_bytes=len(data["bitmap"]) + 2 * len(data["glyphs"])))
    outputs[ASSETS / "door_fonts_manifest.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    for path, content in outputs.items():
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                raise ValueError(f"Generated resource differs: {path}")
        else:
            path.write_bytes(content)
    if args.preview:
        preview(fonts[:2])
    for data in manifest["fonts"]:
        print(f"{data['symbol']}: {data['glyph_count']} glyphs; bitmap {data['bitmap_bytes']} B; C {data['bytes']} B; line/base {data['line_height']}/{data['base_line']}")
    print("Required glyph coverage, packed 4bpp, sparse cmaps and baseline bounds verified.")
    if args.check:
        print("Generated C files and manifest match byte-for-byte.")


if __name__ == "__main__":
    main()
