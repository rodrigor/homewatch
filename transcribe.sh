#!/bin/bash
# transcribe.sh <audiofile> -> texto (stdout). Usa whisper.cpp local.
set -uo pipefail
WC=/home/rodrigor/whisper.cpp
MODEL="$WC/models/ggml-base.bin"
IN="${1:?uso: transcribe.sh <audio>}"
WAV="/tmp/wt_$$.wav"
ffmpeg -y -i "$IN" -ar 16000 -ac 1 "$WAV" >/dev/null 2>&1 || { echo ""; exit 0; }
"$WC/build/bin/whisper-cli" -m "$MODEL" -f "$WAV" -l pt -nt -t 4 2>/dev/null \
  | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' | tr -d '\r' | grep -v '^$' | paste -sd' '
rm -f "$WAV"
