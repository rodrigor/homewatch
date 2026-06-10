#!/bin/bash
# tts.sh <texto> <saida.ogg> — gera voz pt-BR (Piper) em ogg/opus p/ Telegram
set -uo pipefail
PIPER=/home/rodrigor/piper
VOICE="$PIPER/voices/pt_BR-faber-medium.onnx"
TXT="${1:?texto}"; OUT="${2:?saida}"
WAV="/tmp/tts_$$.wav"
printf '%s' "$TXT" | ( cd "$PIPER" && ./piper --model "$VOICE" --output_file "$WAV" ) >/dev/null 2>&1
ffmpeg -y -i "$WAV" -c:a libopus -b:a 32k "$OUT" >/dev/null 2>&1
rm -f "$WAV"
[ -s "$OUT" ]
