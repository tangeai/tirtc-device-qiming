"""Check the actual P4 profile JSON and revision sent to the platform."""
import ast
import json
from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
source = (root / "components/starter_runtime/src/starter_runtime.c").read_text(encoding="utf-8")
function = source.split("static void request_device_profile(void)", 1)[1]
profile = function.split("static const char profile[] =", 1)[1].split(";", 1)[0]
snapshot = json.loads("".join(ast.literal_eval(item) for item in re.findall(r'"(?:\\.|[^"\\])*"', profile)))
assert set(snapshot) == {"profiles"}
scenes = snapshot["profiles"]
assert set(scenes) == {"stream", "call", "voip"}
for name, scene in scenes.items():
    assert scene["audio_rate"] == 16000 and scene["audio_channels"] == 1
    assert scene["camera_rotation"] == 0 and scene["no_video"] is False
    assert scene["object_fit"] == "contain"
    assert scene["hor_mirror"] is False and scene["vert_mirror"] is False
    if name != "voip":
        assert scene["up_video_mt"] == scene["down_video_mt"] == ["h264"]
        assert scene["up_audio_mt"] == ["opus"]
assert scenes["stream"]["down_audio_mt"] == ["opus", "alaw"]
assert scenes["call"]["down_audio_mt"] == ["opus"]
assert scenes["call"]["aspect_ratio"] == "3:2"
for name in ("stream", "voip"):
    assert abs(scenes[name]["aspect_ratio"] - 1024 / 600) < 1e-9
assert [scenes["stream"][key] for key in (
    "up_audio_streamid", "up_video_streamid", "down_audio_streamid", "down_video_streamid"
)] == [10, 11, 14, 15]
assert (scenes["voip"]["screen_width"], scenes["voip"]["screen_height"]) == (1024, 600)
assert scenes["voip"]["video_res_mode"] == "fit_screen"
assert scenes["voip"]["up_video_mt"] == "h264"
assert scenes["voip"]["down_video_mt"] == "mjpeg"
assert scenes["voip"]["down_audio_mt"] == "opus"
assert scenes["voip"]["down_video_rotation"] == 0
assert scenes["voip"]["calling_timeout_sec"] == 30
board = re.search(r'cJSON_AddStringToObject\(hardware, "board_model",\s*"([^"]+)"', function)
assert board and board[1] == "WT99P461-S1-1V1"
assert 'cJSON_AddStringToObject(snapshot, "firmware_version", app->version)' in function
print("PASS: actual 1V1 profile; three complete media scenes, stream IDs, dimensions and running version")
