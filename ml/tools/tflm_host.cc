// Host runner for the firmware's audio pipeline, built from the same vendored
// TFLite Micro sources (reference kernels instead of esp-nn). Used to make
// training features and to score models exactly as ml_engine.cpp would.
//
//   tflm_host features <frontend.tflite> <list.txt>
//       each line "<in.s16> <out.i8>": 16 kHz mono int16 LE in, one row of
//       frontend output per 20 ms stride out (int8 or raw bytes, row-major).
//   tflm_host classify <frontend.tflite> <classifier.tflite> <frames> <hop> <in.s16>
//       runs the frontend over the whole file, then the classifier on every
//       window of <frames> rows, stepping <hop> rows; prints one line of
//       dequantized scores per window.
//
// Window 30 ms / stride 20 ms, as in the micro_speech manifest.

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <string>
#include <vector>

#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"

namespace {

constexpr int kWindow = 480;
constexpr int kStride = 320;
constexpr size_t kArena = 512 * 1024;
alignas(16) uint8_t gArena[kArena];
alignas(16) uint8_t gArena2[kArena];

using Resolver = tflite::MicroMutableOpResolver<48>;

void registerOps(Resolver &r) {
  r.AddAdd(); r.AddAveragePool2D(); r.AddCast(); r.AddConcatenation(); r.AddConv2D();
  r.AddDepthwiseConv2D(); r.AddDequantize(); r.AddDiv(); r.AddExpandDims();
  r.AddFullyConnected(); r.AddHardSwish(); r.AddLeakyRelu(); r.AddLogistic();
  r.AddMaxPool2D(); r.AddMaximum(); r.AddMean(); r.AddMinimum(); r.AddMul(); r.AddPack();
  r.AddPad(); r.AddQuantize(); r.AddRelu(); r.AddRelu6(); r.AddReshape(); r.AddShape();
  r.AddSlice(); r.AddSoftmax(); r.AddSplit(); r.AddSqueeze(); r.AddStridedSlice(); r.AddSub();
  r.AddTanh(); r.AddTranspose(); r.AddUnpack(); r.AddWindow(); r.AddFftAutoScale();
  r.AddRfft(); r.AddEnergy(); r.AddFilterBank(); r.AddFilterBankSquareRoot();
  r.AddFilterBankSpectralSubtraction(); r.AddPCAN(); r.AddFilterBankLog(); r.AddFramer();
  r.AddStacker();
}

std::vector<uint8_t> readFile(const char *path) {
  std::vector<uint8_t> out;
  FILE *f = fopen(path, "rb");
  if (!f) return out;
  fseek(f, 0, SEEK_END);
  out.resize((size_t)ftell(f));
  fseek(f, 0, SEEK_SET);
  if (fread(out.data(), 1, out.size(), f) != out.size()) out.clear();
  fclose(f);
  return out;
}

size_t elems(const TfLiteTensor *t) {
  size_t n = 1;
  for (int i = 0; i < t->dims->size; ++i) n *= (size_t)t->dims->data[i];
  return n;
}

// Fresh interpreter per file: frontend noise/PCAN state starts from zero, the
// same as the device's first clip after ml.load.
std::vector<uint8_t> frontendRows(const tflite::Model *model, const Resolver &r,
                                  const std::vector<uint8_t> &pcmBytes, size_t *rowBytes) {
  std::vector<uint8_t> rows;
  tflite::MicroInterpreter interp(model, r, gArena, kArena);
  if (interp.AllocateTensors() != kTfLiteOk) {
    fprintf(stderr, "frontend AllocateTensors failed\n");
    exit(2);
  }
  TfLiteTensor *in = interp.input(0);
  const TfLiteTensor *out = interp.output(0);
  *rowBytes = out->bytes;
  const int16_t *pcm = (const int16_t *)pcmBytes.data();
  const size_t n = pcmBytes.size() / 2;
  for (size_t off = 0; off + kWindow <= n; off += kStride) {
    memcpy(in->data.i16, pcm + off, kWindow * sizeof(int16_t));
    if (interp.Invoke() != kTfLiteOk) {
      fprintf(stderr, "frontend invoke failed\n");
      exit(2);
    }
    rows.insert(rows.end(), out->data.uint8, out->data.uint8 + out->bytes);
  }
  return rows;
}

float dequant(const TfLiteTensor *t, size_t i) {
  switch (t->type) {
    case kTfLiteFloat32: return t->data.f[i];
    case kTfLiteInt8: return (t->data.int8[i] - t->params.zero_point) * t->params.scale;
    case kTfLiteUInt8: return (t->data.uint8[i] - t->params.zero_point) * t->params.scale;
    default: return 0;
  }
}

int cmdFeatures(const char *fePath, const char *listPath) {
  std::vector<uint8_t> fe = readFile(fePath);
  if (fe.empty()) return fprintf(stderr, "cannot read %s\n", fePath), 2;
  const tflite::Model *model = tflite::GetModel(fe.data());
  Resolver r;
  registerOps(r);
  FILE *list = fopen(listPath, "r");
  if (!list) return fprintf(stderr, "cannot read %s\n", listPath), 2;
  char a[4096], b[4096];
  int done = 0;
  while (fscanf(list, "%4095s %4095s", a, b) == 2) {
    size_t rowBytes = 0;
    std::vector<uint8_t> rows = frontendRows(model, r, readFile(a), &rowBytes);
    FILE *o = fopen(b, "wb");
    if (!o) return fprintf(stderr, "cannot write %s\n", b), 2;
    fwrite(rows.data(), 1, rows.size(), o);
    fclose(o);
    ++done;
  }
  fclose(list);
  fprintf(stderr, "features: %d files\n", done);
  return 0;
}

int cmdClassify(const char *fePath, const char *clsPath, int frames, int hop, const char *pcmPath) {
  std::vector<uint8_t> fe = readFile(fePath), cls = readFile(clsPath);
  if (fe.empty() || cls.empty()) return fprintf(stderr, "cannot read models\n"), 2;
  Resolver r;
  registerOps(r);
  size_t rowBytes = 0;
  std::vector<uint8_t> rows = frontendRows(tflite::GetModel(fe.data()), r, readFile(pcmPath), &rowBytes);
  const size_t nRows = rowBytes ? rows.size() / rowBytes : 0;
  tflite::MicroInterpreter interp(tflite::GetModel(cls.data()), r, gArena2, kArena);
  if (interp.AllocateTensors() != kTfLiteOk) return fprintf(stderr, "classifier alloc failed\n"), 2;
  TfLiteTensor *in = interp.input(0);
  const TfLiteTensor *out = interp.output(0);
  if (in->bytes != (size_t)frames * rowBytes) {
    return fprintf(stderr, "classifier input %zu bytes != %d x %zu\n", in->bytes, frames, rowBytes), 2;
  }
  for (size_t start = 0; start + (size_t)frames <= nRows; start += (size_t)hop) {
    memcpy(in->data.raw, rows.data() + start * rowBytes, in->bytes);
    if (interp.Invoke() != kTfLiteOk) return fprintf(stderr, "classifier invoke failed\n"), 2;
    for (size_t i = 0; i < elems(out); ++i) printf(i ? " %.4f" : "%.4f", dequant(out, i));
    printf("\n");
  }
  return 0;
}

}  // namespace

int main(int argc, char **argv) {
  if (argc == 4 && !strcmp(argv[1], "features")) return cmdFeatures(argv[2], argv[3]);
  if (argc == 7 && !strcmp(argv[1], "classify")) {
    return cmdClassify(argv[2], argv[3], atoi(argv[4]), atoi(argv[5]), argv[6]);
  }
  fprintf(stderr,
          "usage: tflm_host features <frontend> <list.txt>\n"
          "       tflm_host classify <frontend> <classifier> <frames> <hop> <in.s16>\n");
  return 1;
}
