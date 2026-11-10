#include <algorithm>
#include <cassert>
#include <cmath>
#include <fstream>
#include <iostream>
#include <iterator>
#include <vector>
#include "head.h"
#include "mel_extractor.h"
#include "kws_postprocess.h"
#include "wake_window.h"
#include "tensorflow/lite/schema/schema_generated.h"

static_assert(MEL_TIME == 98 && MEL_N_MELS == 32 && KWS_HEAD_D == 256);
static_assert(MEL_SAMPLE_RATE == 16000 && MEL_NFFT == 512 && MEL_HOP_LEN == 160);
static_assert(WAKE_WINDOW_SAMPLES == MEL_AUDIO_LEN && WAKE_WINDOW_SAMPLES == 16192);
static_assert(WAKE_HOP_SAMPLES == 2560);

static void check_tensor(const tflite::Tensor *t, std::initializer_list<int> shape) {
    assert(t && t->type() == tflite::TensorType_INT8);
    assert(t->shape() && t->shape()->size() == shape.size());
    unsigned i = 0;
    for (int n : shape) assert(t->shape()->Get(i++) == n);
    auto q = t->quantization();
    assert(q && q->scale() && q->scale()->size() == 1);
    assert(q->zero_point() && q->zero_point()->size() == 1);
    assert(std::isfinite(q->scale()->Get(0)) && q->scale()->Get(0) > 0);
    assert(q->zero_point()->Get(0) >= -128 && q->zero_point()->Get(0) <= 127);
}

static void check_window() {
    std::vector<int16_t> pcm(WAKE_WINDOW_SAMPLES);
    std::vector<int16_t> guarded(WAKE_WINDOW_SAMPLES + 2, -12345);
    wake_window_t w = {};
    w.pcm = pcm.data();
    int64_t at = 100;
    auto append = [&](size_t n, size_t first) {
        std::vector<int16_t> input(n);
        for (size_t i = 0; i < n; ++i) input[i] = (first + i) % 30000;
        wake_window_append(&w, input.data(), n, at);
        at += 40;
    };
    for (size_t offset = 0; offset < WAKE_WINDOW_SAMPLES - 1;) {
        size_t n = std::min<size_t>(640, WAKE_WINDOW_SAMPLES - 1 - offset);
        append(n, offset);
        assert(!wake_window_snapshot(&w, guarded.data() + 1));
        offset += n;
    }
    append(1, WAKE_WINDOW_SAMPLES - 1);
    assert(wake_window_snapshot(&w, guarded.data() + 1));
    for (size_t i = 0; i < WAKE_WINDOW_SAMPLES; ++i)
        assert(guarded[i + 1] == static_cast<int16_t>(i));
    assert(!wake_window_snapshot(&w, guarded.data() + 1));
    for (size_t offset = 0; offset < WAKE_HOP_SAMPLES; offset += 640)
        append(640, WAKE_WINDOW_SAMPLES + offset);
    assert(wake_window_snapshot(&w, guarded.data() + 1));
    for (size_t i = 0; i < WAKE_WINDOW_SAMPLES; ++i)
        assert(guarded[i + 1] == static_cast<int16_t>((i + WAKE_HOP_SAMPLES) % 30000));
    assert(guarded.front() == -12345 && guarded.back() == -12345);
    uint32_t epoch = w.epoch;
    at += 200;
    append(640, 0);
    assert(w.epoch == epoch + 1 && w.count == 640);
    assert(!wake_window_snapshot(&w, guarded.data() + 1));
    assert(wake_result_check(true, false, w.epoch, w.epoch, 100, 110, 0) == WAKE_ACCEPT);
    assert(wake_result_check(true, true, w.epoch, w.epoch, 100, 110, 0) == WAKE_REJECT_EPOCH);
    assert(wake_result_check(true, false, epoch, w.epoch, 100, 110, 0) == WAKE_REJECT_EPOCH);
    assert(wake_result_check(true, false, w.epoch, w.epoch, 100, 1101, 0) == WAKE_REJECT_AGE);
    assert(wake_result_check(true, false, w.epoch, w.epoch, 100, 110, 111) == WAKE_REJECT_COOLDOWN);
}

int main(int argc, char **argv) {
    assert(argc == 2);
    std::ifstream file(argv[1], std::ios::binary);
    assert(file);
    std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(file)), {});
    flatbuffers::Verifier verifier(bytes.data(), bytes.size());
    assert(tflite::VerifyModelBuffer(verifier));
    auto model = tflite::GetModel(bytes.data());
    assert(model->version() == 3 && model->subgraphs()->size() == 1);
    auto graph = model->subgraphs()->Get(0);
    assert(graph->inputs()->size() == 1 && graph->outputs()->size() == 1);
    check_tensor(graph->tensors()->Get(graph->inputs()->Get(0)), {1, MEL_TIME, MEL_N_MELS});
    check_tensor(graph->tensors()->Get(graph->outputs()->Get(0)), {1, KWS_HEAD_D});
    for (auto code : *model->operator_codes()) {
        switch (code->builtin_code()) {
            case tflite::BuiltinOperator_RESHAPE:
            case tflite::BuiltinOperator_PAD:
            case tflite::BuiltinOperator_CONV_2D:
            case tflite::BuiltinOperator_DEPTHWISE_CONV_2D:
            case tflite::BuiltinOperator_ADD:
            case tflite::BuiltinOperator_MEAN:
            case tflite::BuiltinOperator_STRIDED_SLICE:
            case tflite::BuiltinOperator_CONCATENATION: break;
            default: assert(!"operator missing from the production resolver");
        }
    }
    auto first = graph->operators()->Get(0);
    assert(model->operator_codes()->Get(first->opcode_index())->builtin_code() == tflite::BuiltinOperator_RESHAPE);
    check_tensor(graph->tensors()->Get(first->outputs()->Get(0)), {1, MEL_TIME, 1, MEL_N_MELS});
    bytes[4] ^= 0xff;
    flatbuffers::Verifier corrupt(bytes.data(), bytes.size());
    assert(!tflite::VerifyModelBuffer(corrupt));
    assert(std::isfinite(KWS_ABS_TEMP) && KWS_ABS_TEMP > 0);
    for (unsigned k = 0; k < KWS_HEAD_K; ++k) {
        float norm = 0;
        for (float value : KWS_PROTO_NORM[k]) { assert(std::isfinite(value)); norm += value * value; }
        assert(std::abs(norm - 1) < 0.001f && std::isfinite(KWS_FC_W[k]));
    }
    int8_t embedding[KWS_HEAD_D];
    for (int value = -128; value <= 127; ++value) {
        std::fill_n(embedding, KWS_HEAD_D, static_cast<int8_t>(value));
        float probability = kws_postprocess(embedding, 0.0342066f, -64);
        assert(std::isfinite(probability) && probability >= 0 && probability <= 1);
    }
    check_window();
    std::cout << "PASS: " << WAKE_MODEL_ID << " verified FlatBuffer, INT8 98x32/256, internal NHWC, resolver operators, paired head, 16192-sample window/hop/wrap/gap/stale guards\n";
}
