#!/usr/bin/env bash
# Fetch TensorFlow Lite Micro (esp-tflite-micro) and esp-nn into rlcd/lib as
# PlatformIO local libs for the ml plugin. Pinned commits; the source trees
# stay out of git, only this script and the generated library.json matter.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LIB="$ROOT/rlcd/lib"
TFLM_URL="${TFLM_URL:-https://github.com/espressif/esp-tflite-micro.git}"
TFLM_REV="${TFLM_REV:-dd4085950a119d9e33a6de1d7be1fc7fe29e0cfc}"
NN_URL="${ESP_NN_URL:-https://github.com/espressif/esp-nn.git}"
NN_REV="${ESP_NN_REV:-f1bfc45cb0edfdbe8fd4871f3abc0adfc7fe1c47}"

fetch() {  # url rev dest
  rm -rf "$3"
  git init -q "$3"
  git -C "$3" fetch -q --depth 1 "$1" "$2"
  git -C "$3" checkout -q FETCH_HEAD
  rm -rf "$3/.git"
}

fetch "$NN_URL" "$NN_REV" "$LIB/esp-nn"
rm -rf "$LIB/esp-nn/test_app" "$LIB/esp-nn/tests" "$LIB/esp-nn/tools"
cat > "$LIB/esp-nn/library.json" <<'JSON'
{
  "name": "esp-nn",
  "version": "0.0.0-pinned",
  "platforms": "espressif32",
  "build": {
    "srcDir": "src",
    "includeDir": "include",
    "flags": ["-Isrc/common", "-mlongcalls", "-fno-unroll-loops", "-O2",
              "-Wno-unused-function"],
    "srcFilter": [
      "-<*>",
      "+<activation_functions/esp_nn_relu_ansi.c>",
      "+<activation_functions/esp_nn_hard_swish_ansi.c>",
      "+<common/esp_nn_mean_ansi.c>",
      "+<basic_math/esp_nn_add_ansi.c>",
      "+<basic_math/esp_nn_mul_ansi.c>",
      "+<convolution/esp_nn_conv_ansi.c>",
      "+<convolution/esp_nn_conv_opt.c>",
      "+<convolution/esp_nn_depthwise_conv_ansi.c>",
      "+<convolution/esp_nn_depthwise_conv_opt.c>",
      "+<fully_connected/esp_nn_fully_connected_ansi.c>",
      "+<softmax/esp_nn_softmax_ansi.c>",
      "+<softmax/esp_nn_softmax_opt.c>",
      "+<logistic/esp_nn_logistic_ansi.c>",
      "+<pooling/esp_nn_avg_pool_ansi.c>",
      "+<pooling/esp_nn_max_pool_ansi.c>",
      "+<common/esp_nn_multicore.c>",
      "+<convolution/esp_nn_conv_mt_split.c>",
      "+<basic_math/esp_nn_mul_mt.c>",
      "+<**/*esp32s3.S>",
      "+<**/*esp32s3.c>"
    ]
  }
}
JSON

fetch "$TFLM_URL" "$TFLM_REV" "$LIB/tflm"
rm -rf "$LIB/tflm/examples" "$LIB/tflm/scripts"
cat > "$LIB/tflm/library.json" <<'JSON'
{
  "name": "tflm",
  "version": "1.4.1-pinned",
  "platforms": "espressif32",
  "dependencies": [{ "name": "esp-nn" }],
  "build": {
    "srcDir": ".",
    "includeDir": ".",
    "flags": ["-fno-rtti", "-fno-exceptions", "-Wno-unused-parameter", "-Wno-maybe-uninitialized",
              "-Wno-missing-field-initializers", "-Wno-sign-compare",
              "-Wno-double-promotion", "-Wno-type-limits", "-Wno-nonnull",
              "-Wno-return-type", "-Wno-strict-aliasing", "-Wno-shadow"],
    "srcFilter": [
      "-<*>",
      "+<tensorflow/lite/micro/debug_log.cc>",
      "+<tensorflow/lite/micro/flatbuffer_utils.cc>",
      "+<tensorflow/lite/micro/memory_helpers.cc>",
      "+<tensorflow/lite/micro/micro_allocation_info.cc>",
      "+<tensorflow/lite/micro/micro_allocator.cc>",
      "+<tensorflow/lite/micro/micro_context.cc>",
      "+<tensorflow/lite/micro/micro_interpreter_context.cc>",
      "+<tensorflow/lite/micro/micro_interpreter_graph.cc>",
      "+<tensorflow/lite/micro/micro_interpreter.cc>",
      "+<tensorflow/lite/micro/micro_log.cc>",
      "+<tensorflow/lite/micro/micro_op_resolver.cc>",
      "+<tensorflow/lite/micro/micro_profiler.cc>",
      "+<tensorflow/lite/micro/micro_resource_variable.cc>",
      "+<tensorflow/lite/micro/micro_utils.cc>",
      "+<tensorflow/lite/micro/recording_micro_allocator.cc>",
      "+<tensorflow/lite/micro/system_setup.cc>",
      "+<tensorflow/lite/micro/esp/micro_time.cc>",
      "+<tensorflow/lite/micro/tflite_bridge/*.cc>",
      "+<tensorflow/lite/micro/kernels/*.cc>",
      "-<tensorflow/lite/micro/kernels/add.cc>",
      "-<tensorflow/lite/micro/kernels/conv.cc>",
      "-<tensorflow/lite/micro/kernels/depthwise_conv.cc>",
      "-<tensorflow/lite/micro/kernels/fully_connected.cc>",
      "-<tensorflow/lite/micro/kernels/mul.cc>",
      "-<tensorflow/lite/micro/kernels/pooling.cc>",
      "-<tensorflow/lite/micro/kernels/decode*.cc>",
      "-<tensorflow/lite/micro/kernels/softmax.cc>",
      "+<tensorflow/lite/micro/kernels/esp_nn/*.cc>",
      "+<signal/micro/kernels/*.cc>",
      "+<signal/src/*.cc>",
      "+<signal/src/kiss_fft_wrappers/kiss_fft_float.cc>",
      "+<signal/src/kiss_fft_wrappers/kiss_fft_int16.cc>",
      "+<signal/src/kiss_fft_wrappers/kiss_fft_int32.cc>",
      "+<tensorflow/lite/kernels/kernel_util.cc>",
      "+<tensorflow/lite/micro/memory_planner/greedy_memory_planner.cc>",
      "+<tensorflow/lite/micro/memory_planner/linear_memory_planner.cc>",
      "+<tensorflow/lite/micro/arena_allocator/*.cc>",
      "+<tensorflow/lite/core/c/common.cc>",
      "+<tensorflow/lite/core/api/flatbuffer_conversions.cc>",
      "+<tensorflow/lite/core/api/tensor_utils.cc>",
      "+<tensorflow/lite/kernels/internal/common.cc>",
      "+<tensorflow/lite/kernels/internal/quantization_util.cc>",
      "+<tensorflow/lite/kernels/internal/portable_tensor_utils.cc>",
      "+<tensorflow/lite/kernels/internal/tensor_utils.cc>",
      "+<tensorflow/lite/kernels/internal/tensor_ctypes.cc>",
      "+<tensorflow/lite/kernels/internal/reference/portable_tensor_utils.cc>",
      "+<tensorflow/compiler/mlir/lite/core/api/error_reporter.cc>",
      "+<tensorflow/compiler/mlir/lite/schema/schema_utils.cc>"
    ]
  }
}
JSON
echo "OK -> $LIB/esp-nn, $LIB/tflm"
