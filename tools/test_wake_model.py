"""Validate model assets and real production window logic; not acoustic accuracy."""
from hashlib import sha256
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
voice = root / "components/starter_voice"
expected = {
    "head.h": "cc0364fa603a43c90d9de0b0fc39587c7c4d3350c3d1537b7018cf3a923d1a1e",
    "nihaoxiaotai.tflite": "1dcfe29a10733ec272854bfbafb8a231f10bf3b0399cf6192cc08b38006fac78",
}
for name, digest in expected.items():
    assert sha256((voice / "model" / name).read_bytes()).hexdigest() == digest, name
backend = (voice / "src/wake_backend.cpp").read_text(encoding="utf-8")
assert "MEL_TIME == 98 && MEL_N_MELS == 32 && KWS_HEAD_D == 256" in backend
assert "MEL_AUDIO_LEN == WAKE_MODEL_WINDOW_SAMPLES" in backend
assert "in->params.scale, in->params.zero_point" in backend
assert "kws_postprocess(out->data.int8, out->params.scale, out->params.zero_point)" in backend
owner = (voice / "src/starter_voice.c").read_text(encoding="utf-8")
assert "#define WAKE_THRESHOLD_MILLI 950U" in owner
with tempfile.TemporaryDirectory(prefix="wt99-wake-model-") as folder:
    binary = Path(folder) / "wake-model"
    tflm = root / "managed_components/espressif__esp-tflite-micro"
    includes = [voice / part for part in ("include", "model", "src", "vendor")]
    includes += [tflm, tflm / "third_party/flatbuffers/include"]
    subprocess.run([
        "c++", "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Wno-unused-variable",
        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
        *[f"-I{path}" for path in includes],
        str(root / "tools/test_wake_model.cpp"), "-o", str(binary),
    ], check=True)
    subprocess.run([str(binary), str(voice / "model/nihaoxiaotai.tflite")], check=True)
