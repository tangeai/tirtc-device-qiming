"""Render through the actual pinned LVGL, not a simulated buffer-sync algorithm."""
from pathlib import Path
import hashlib
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
lvgl = ROOT / "managed_components/lvgl__lvgl"
sources = sorted((lvgl / "src").rglob("*.c"))
product = (ROOT / "components/starter_product/src/starter_product.c").read_text(encoding="utf-8")
begin = product.index("static void set_object_visible(lv_obj_t *object, bool visible)")
end = product.index("\nstatic void refresh_settings_controls", begin)
visibility = product[begin:end]
with tempfile.TemporaryDirectory(prefix="lvgl-direct-") as directory:
    binary = Path(directory) / "test"
    test = Path(directory) / "test.c"
    folder = Path(directory)
    objects = folder / "objects"
    objects.mkdir()
    assert len({item.stem for item in sources}) == len(sources), "LVGL object basename collision"
    flags = ["-std=c11", "-g", "-DLV_CONF_SKIP", "-DLV_COLOR_DEPTH=16",
             "-DLV_MEM_SIZE=65536", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]
    subprocess.run(["cc", *flags, "-I", str(lvgl), "-c", *map(str, sources)], cwd=objects, check=True)
    library = folder / "liblvgl-common.a"
    subprocess.run(["ar", "rcs", str(library),
                    *map(str, sorted(item for item in objects.glob("*.o") if item.name != "lv_img.o"))], check=True)
    current_image = objects / "lv_img.o"

    def compile_test(extra=(), image=current_image):
        subprocess.run(["cc", *flags, *extra, "-I", str(lvgl), "-I", str(ROOT / "tools"),
                        str(test), str(image), str(library), "-lm", "-o", str(binary)], check=True)

    test.write_text('#include "lvgl.h"\n' + visibility +
                    (ROOT / "tools/test_lvgl_direct_framebuffers.c").read_text(encoding="utf-8"),
                    encoding="utf-8")
    compile_test()
    subprocess.run([str(binary)], check=True)

    # Run the original upstream and reviewed patch through the same real renderer.
    img_path = lvgl / "src/widgets/lv_img.c"
    img_text = img_path.read_text(encoding="utf-8")
    patch = (ROOT / "tools/patches/lvgl-8.4.0-image-cover.patch").read_text(encoding="utf-8")
    hunk = patch[patch.index("@@"):].splitlines()[1:]
    old = "".join(line[1:] + "\n" for line in hunk if line.startswith((" ", "-")))
    new = "".join(line[1:] + "\n" for line in hunk if line.startswith((" ", "+")))
    assert (old in img_text) != (new in img_text), "Unexpected pinned LVGL image source"
    original = img_text.replace(new, old) if new in img_text else img_text
    fixed = original.replace(old, new)
    hashes = []
    for enabled, image_source in enumerate((original, fixed)):
        replacement = Path(directory) / "lv_img.c"
        replacement.write_text(image_source, encoding="utf-8")
        print(f"LVGL image-cover variant={enabled} SHA256=" + hashlib.sha256(image_source.encode()).hexdigest(), flush=True)
        replacement_object = folder / "lv_img_variant.o"
        subprocess.run(["cc", *flags, "-I", str(lvgl), "-I", str(img_path.parent),
                        "-c", str(replacement), "-o", str(replacement_object)], check=True)
        compile_test(["-DDISPLAY_TEST_IMAGE_COVER=1", f"-DDISPLAY_TEST_IMAGE_COVER_FIXED={enabled}"], replacement_object)
        result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
        print(result.stdout, end="", flush=True)
        hashes.append(re.search(r"PIXEL_HASH: ([0-9a-f]+)", result.stdout)[1])
    assert hashes[0] == hashes[1], "Image-cover patch changed rendered output"

    from test_display_ppa import SUPPORT, source as ppa_source
    print("PPA adapter source SHA256: " + hashlib.sha256(ppa_source.encode("utf-8")).hexdigest(), flush=True)
    (folder / "driver").mkdir()
    (folder / "freertos").mkdir()
    (folder / "driver/ppa.h").write_text("", encoding="ascii")
    (folder / "freertos/task.h").write_text("", encoding="ascii")
    (folder / "esp_heap_caps.h").write_text("", encoding="ascii")
    test.write_text(SUPPORT.replace("#define BSP_LCD_H_RES 64", "#define BSP_LCD_H_RES 128")
                    .replace("#define BSP_LCD_V_RES 32", "#define BSP_LCD_V_RES 64") +
                    ppa_source + visibility +
                    (ROOT / "tools/test_lvgl_direct_framebuffers.c").read_text(encoding="utf-8"), encoding="utf-8")
    compile_test(["-DDISPLAY_PPA_REAL_LVGL=1", "-DDISPLAY_TEST_PPA=1", "-I", str(folder)])
    subprocess.run([str(binary)], check=True)

    def section(start, end):
        return product[product.index(start):product.index(end, product.index(start))]

    helper = section("static void label_set_text_if_changed(lv_obj_t *label, const char *text)", "\nstatic ")
    # Find definitions, not the earlier forward declarations.
    begin = product.index("static void refresh_call_controls(starter_runtime_status_t runtime,\n                                  const starter_runtime_product_snapshot_t *product)\n{")
    controls = product[begin:product.index("\nstatic void refresh_diagnostics", begin)]
    begin = product.index("static void set_button_text(lv_obj_t *button, const char *text)")
    text_helper = product[begin:product.index("\nstatic void set_object_visible", begin)]
    prefix = r'''
#include "lvgl.h"
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
enum { PAGE_CALL=12, STARTER_RUNTIME_CALL_INCOMING=4,
       STARTER_RUNTIME_CALL_CONNECTING=5, STARTER_RUNTIME_CALL_ACTIVE=6 };
typedef struct { int state; } starter_runtime_status_t;
typedef struct { bool call_video, call_wechat, call_camera_enabled; char call_peer[32]; } starter_runtime_product_snapshot_t;
static int s_page;
static bool s_door_call;
static unsigned door_refreshes;
static void door_refresh_call(starter_runtime_status_t runtime, const starter_runtime_product_snapshot_t *product) {
    (void)runtime; (void)product; door_refreshes++;
}
static struct { bool microphone_muted; } s_preferences;
static lv_obj_t *s_header_title, *s_call_peer_label, *s_call_status_label;
static lv_obj_t *s_call_camera_button, *s_call_accept_button, *s_call_reject_button;
static lv_obj_t *s_call_mute_button, *s_call_hangup_button;
static int64_t monotonic_ms(void) { return 0; }
static void s3_refresh_ui(int64_t now, starter_runtime_status_t runtime, const starter_runtime_product_snapshot_t *product) {
    (void)now; (void)runtime; (void)product;
}
'''
    test.write_text(prefix + helper + text_helper + visibility + controls +
                    (ROOT / "tools/test_call_controls.c").read_text(encoding="utf-8"), encoding="utf-8")
    compile_test(["-DCONFIG_IDF_TARGET_ESP32P4=1"])
    subprocess.run([str(binary)], check=True)
