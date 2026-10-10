#pragma once

#include <stddef.h>
#include <stdint.h>

#include <string>
#include <vector>

// Model manifest delivered by the control plane next to every .tflite blob.
// The control plane signs the exact manifest bytes; the device verifies the
// signature, then this parser, then the blob's sha256. Pure C++ (ArduinoJson
// + std) so host tests can drive it. Format: doc/structurizr/ML-PLUGIN.md.

constexpr int kMlOpsetVersion = 1;
constexpr size_t kMlMaxModelBytes = 2u * 1024u * 1024u;
constexpr int kMlMaxArenaKb = 1024;
constexpr int kMlMicRate = 16000;

struct MlAudioSpec {
  int rate = 0;
  int windowMs = 0;
  int strideMs = 0;
  int frames = 0;    // feature rows fed to the classifier
  int features = 0;  // values per row (frontend output size)
  std::string frontend;

  int windowSamples() const { return rate * windowMs / 1000; }
  int strideSamples() const { return rate * strideMs / 1000; }
  // Mic samples needed for one classification.
  int totalSamples() const {
    return frames > 0 ? (frames - 1) * strideSamples() + windowSamples() : 0;
  }
};

struct MlManifest {
  std::string name;
  int version = 0;
  int opset = 0;
  std::string kind;  // "audio" | "tensor" | "frontend"
  std::string sha256;
  size_t bytes = 0;
  int arenaKb = 0;
  MlAudioSpec audio;
  std::vector<std::string> labels;
};

bool mlNameOk(const char *name);
// Parses and range-checks; `err` says why on failure.
bool mlParseManifest(const char *json, size_t n, MlManifest &out, std::string &err);

// Index of the highest score, -1 if empty.
int mlArgMax(const std::vector<float> &scores);
