#include "audio_plugin.h"

#include "oc_features.h"

#if OC_HAS_AUDIO
#include "audio_es8311.h"
#endif

namespace {
#if OC_HAS_AUDIO
bool hostBeep(uint16_t freq, uint16_t ms) {
  return audioIsReady() && audioPlayBeep(freq, ms);
}
bool hostPlayPcm(const int16_t *samples, size_t count) {
  return audioIsReady() && audioPlayPcm(samples, count);
}
uint32_t hostSampleRate() { return audioSampleRate(); }
void hostSetPa(bool on) { audioSetPa(on); }
bool hostAudioReady() { return audioIsReady(); }
#endif
}  // namespace

bool audioPluginBegin(uint32_t sampleRate) {
#if OC_HAS_AUDIO
  const bool ok = audioBegin(sampleRate);
  Serial.printf("[audio] %s\n", ok ? "es8311" : "es8311 begin failed");
  return ok;
#else
  (void)sampleRate;
  Serial.println("[audio] none");
  return false;
#endif
}

bool audioPluginReady() {
#if OC_HAS_AUDIO
  return audioIsReady();
#else
  return false;
#endif
}

bool audioPluginBeep(uint16_t freqHz, uint16_t ms) {
#if OC_HAS_AUDIO
  return audioIsReady() && audioPlayBeep(freqHz, ms);
#else
  (void)freqHz;
  (void)ms;
  return false;
#endif
}

void audioPluginAttach(ScriptHost &host) {
#if OC_HAS_AUDIO
  host.beep = hostBeep;
  host.playPcm = hostPlayPcm;
  host.sampleRate = hostSampleRate;
  host.setPa = hostSetPa;
  host.audioReady = hostAudioReady;
#else
  host.beep = nullptr;
  host.playPcm = nullptr;
  host.sampleRate = nullptr;
  host.setPa = nullptr;
  host.audioReady = nullptr;
#endif
}

const char *audioPluginName() {
#if OC_HAS_AUDIO
  return audioIsReady() ? "es8311" : "es8311-off";
#else
  return "none";
#endif
}
