.section .rodata
.global voice_xiaoxin_start
.global voice_xiaoxin_end
.align 4
voice_xiaoxin_start:
.incbin "third_party/esp_tts/xiaoxin_small.dat"
.align 4
voice_xiaoxin_end:
