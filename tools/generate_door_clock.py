#!/usr/bin/env python3
"""Generate the V4 Inter Light 128px clock subset using the local font pipeline."""
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("door_fonts", ROOT / "tools/generate_door_fonts.py")
fonts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fonts)
ASSETS = ROOT / "components/starter_product/assets/fonts/inter"
REVISION = "6c1dbe27dcf7d817d4b62cec033ba77fa8e2a5ec"
FONT_HASH = "29160a80ff49ddcab2c97711247e08b1fab27a484a329ce8b813d820dc559031"
LICENSE_HASH = "5b9321a4298cfeb6b34354164a1c3afc3db114569984c502b9b35d988fd58c57"


def main():
    for name, expected in [("Inter.ttf", FONT_HASH), ("OFL.txt", LICENSE_HASH)]:
        if hashlib.sha256((ASSETS / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"Pinned Inter source mismatch: {name}")
    data = fonts.rasterize(ASSETS / "Inter.ttf", sorted(map(ord, " -0123456789:")), 128, 300)
    if data["line_height"] > 144:
        raise ValueError("Inter clock exceeds design line height")
    # Inter's typographic ascender (124px at this EM) places the baseline in
    # the design's 144px line box, not at the subset's tight digit ink bounds.
    from PIL import ImageFont
    source = ImageFont.truetype(str(ASSETS / "Inter.ttf"), 128)
    ascent, descent = source.getmetrics()
    baseline = ascent + (144 - ascent - descent) // 2
    data.update(symbol="ui_font_door_clock_128", line_height=144, base_line=144 - baseline,
        generator="tools/generate_door_clock.py",
        family="Inter", source_sha256=FONT_HASH,
        copyright="Copyright 2020 The Inter Project Authors (https://github.com/rsms/inter)",
        license_path="components/starter_product/assets/fonts/inter/OFL.txt")
    content = fonts.emit_c(data)
    (ROOT / "components/starter_product/src/ui_font_door_clock_128.c").write_bytes(content)
    manifest = dict(source_repository="https://github.com/google/fonts", revision=REVISION,
        font_sha256=FONT_HASH, license_sha256=LICENSE_HASH, em_pixels=128, weight=300,
        optical_size="source default", line_height=144, baseline=baseline, charset=" -0123456789:",
        bitmap_bytes=len(data["bitmap"]), generated_sha256=hashlib.sha256(content).hexdigest())
    (ASSETS / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Inter Light: {len(data['glyphs'])} glyphs; {len(data['bitmap'])} bitmap bytes; baseline {baseline}.")


if __name__ == "__main__":
    main()
