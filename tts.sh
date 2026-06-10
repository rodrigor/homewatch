#!/bin/bash
# tts.sh <texto> <saida.ogg> — gera voz pt-BR (Piper/cadu) em ogg/opus p/ Telegram
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
PIPER=/home/rodrigor/piper
VOICE="$PIPER/voices/pt_BR-cadu-medium.onnx"
TXT="${1:?texto}"; OUT="${2:?saida}"
WAV="/tmp/tts_$$.wav"
# converte Markdown/HTML para texto puro (ponto único: normalize.py)
CLEAN=$(python3 "$DIR/normalize.py" plain "$TXT")
printf '%s' "$CLEAN" | ( cd "$PIPER" && ./piper --model "$VOICE" --output_file "$WAV" ) >/dev/null 2>&1
ffmpeg -y -i "$WAV" -c:a libopus -b:a 32k "$OUT" >/dev/null 2>&1
rm -f "$WAV"
[ -s "$OUT" ]
