#!/bin/bash
# yt_transcript.sh <youtube-url>
# stdout: TÍTULO/CANAL/DURAÇÃO/FONTE/URL + transcrição limpa do vídeo.
# Transcrição: youtube-transcript-api (yt_fetch.py) — endpoint que não sofre o 429 de legenda.
# Metadados: yt-dlp. Sem transcrição -> whisper.cpp no áudio (até WHISPER_MAX_SEC).
set -uo pipefail
URL="${1:?uso: yt_transcript.sh <url do youtube>}"
DIR="$(cd "$(dirname "$0")" && pwd)"
WHISPER_MAX_SEC="${WHISPER_MAX_SEC:-1500}"   # 25 min
TMP="$(mktemp -d /tmp/yt.XXXXXX)"; trap 'rm -rf "$TMP"' EXIT
YTDLP=(yt-dlp --no-warnings --no-playlist --ignore-no-formats-error)
if yt-dlp --list-impersonate-targets 2>/dev/null | grep -qi chrome; then YTDLP+=(--impersonate chrome); fi

# ---- metadados (título/duração/canal) ----
META="$("${YTDLP[@]}" --skip-download --print "%(title)s|||%(duration)s|||%(uploader)s" "$URL" 2>/dev/null | head -1)"
TITLE="${META%%|||*}"; REST="${META#*|||}"; DUR="${REST%%|||*}"; UP="${REST##*|||}"
{ [ -z "$TITLE" ] || [ "$TITLE" = "$META" ]; } && TITLE="${TITLE:-(vídeo)}"
case "$DUR" in ''|*[!0-9]*) DUR=0;; esac
DURH=""; [ "$DUR" -gt 0 ] && DURH="$(printf '%d:%02d' $((DUR/60)) $((DUR%60)))"

# ---- 1) transcrição via youtube-transcript-api ----
TRANSCRIPT="$(python3 "$DIR/yt_fetch.py" "$URL" 2>/dev/null)"
SRC="legenda"

# ---- 2) fallback: whisper.cpp no áudio ----
if [ -z "${TRANSCRIPT// }" ]; then
  if [ "$DUR" -gt 0 ] && [ "$DUR" -gt "$WHISPER_MAX_SEC" ]; then
    echo "TÍTULO: $TITLE"; echo "CANAL: $UP"; [ -n "$DURH" ] && echo "DURAÇÃO: $DURH"; echo "URL: $URL"; echo
    echo "[sem legenda e o vídeo tem ${DURH:-?} (> $((WHISPER_MAX_SEC/60)) min) — não transcrevi o áudio.]"
    exit 0
  fi
  "${YTDLP[@]}" -f "bestaudio/best" -x --audio-format m4a -o "$TMP/a.%(ext)s" "$URL" >/dev/null 2>&1 || true
  AUD="$(ls "$TMP"/a.* 2>/dev/null | head -1)"
  if [ -n "$AUD" ] && [ -x "$DIR/transcribe.sh" ]; then
    TRANSCRIPT="$("$DIR/transcribe.sh" "$AUD" 2>/dev/null)"; SRC="áudio (whisper)"
  fi
fi

echo "TÍTULO: $TITLE"
echo "CANAL: $UP"
[ -n "$DURH" ] && echo "DURAÇÃO: $DURH"
echo "FONTE: ${SRC}"
echo "URL: $URL"
echo
echo "${TRANSCRIPT:-[não consegui obter transcrição — vídeo sem legenda e sem áudio transcrevível.]}"
