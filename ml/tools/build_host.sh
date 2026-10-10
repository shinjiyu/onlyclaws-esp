#!/usr/bin/env bash
# Build ml/tools/tflm_host from the vendored TFLite Micro tree
# (bash scripts/fetch_tflm.sh first). Reference kernels replace esp-nn.
# Output: ml/tools/build/tflm_host
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TFLM="$ROOT/rlcd/lib/tflm"
OUT="$ROOT/ml/tools/build"
CXX="${CXX:-c++}"
[ -d "$TFLM/tensorflow" ] || { echo "run scripts/fetch_tflm.sh first" >&2; exit 1; }
mkdir -p "$OUT/obj"

FLAGS=(-std=c++17 -O2 -DTF_LITE_STATIC_MEMORY -DTF_LITE_DISABLE_X86_NEON
  -Wno-unused-parameter -Wno-deprecated-declarations
  -I"$TFLM" -I"$TFLM/third_party/flatbuffers/include" -I"$TFLM/third_party/gemmlowp"
  -I"$TFLM/third_party/kissfft" -I"$TFLM/third_party/ruy")

cd "$TFLM"
{
  ls tensorflow/lite/micro/*.cc | grep -vE '(test_helper|mock_micro_graph|fake_micro_context|recording_)'
  ls tensorflow/lite/micro/kernels/*.cc | grep -vE '/(decode|ethosu|kernel_runner)'
  ls tensorflow/lite/micro/tflite_bridge/*.cc
  ls tensorflow/lite/micro/memory_planner/{greedy,linear}_memory_planner.cc
  ls tensorflow/lite/micro/arena_allocator/*.cc
  ls signal/micro/kernels/*.cc signal/src/*.cc
  ls signal/src/kiss_fft_wrappers/kiss_fft_{float,int16,int32}.cc
  ls tensorflow/lite/kernels/kernel_util.cc tensorflow/lite/core/c/common.cc
  ls tensorflow/lite/core/api/{flatbuffer_conversions,tensor_utils}.cc
  ls tensorflow/lite/kernels/internal/{common,quantization_util,portable_tensor_utils,tensor_utils,tensor_ctypes}.cc
  ls tensorflow/lite/kernels/internal/reference/portable_tensor_utils.cc
  ls tensorflow/compiler/mlir/lite/core/api/error_reporter.cc tensorflow/compiler/mlir/lite/schema/schema_utils.cc
} | grep -v '_test\.cc$' > "$OUT/sources.txt"

export OUT CXX
export FLAGS_STR="${FLAGS[*]}"
# shellcheck disable=SC2016
xargs -P "$(sysctl -n hw.ncpu 2>/dev/null || nproc)" -I{} bash -c \
  'src={}; obj="$OUT/obj/${src//\//_}.o"; [ -f "$obj" ] && [ ! "$src" -nt "$obj" ] || $CXX $FLAGS_STR -c "$src" -o "$obj"' \
  < "$OUT/sources.txt"

"$CXX" "${FLAGS[@]}" "$ROOT/ml/tools/tflm_host.cc" "$OUT"/obj/*.o -o "$OUT/tflm_host"
echo "built $OUT/tflm_host"
