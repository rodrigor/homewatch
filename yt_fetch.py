#!/usr/bin/env python3
"""yt_fetch.py <url|id> — imprime a transcrição do vídeo (PT preferido; traduz p/ PT se só houver outra).
Usa youtube-transcript-api (endpoint que não sofre o 429 do download de legenda do yt-dlp)."""
import sys, re
from youtube_transcript_api import YouTubeTranscriptApi

def vid_id(u):
    m = re.search(r'(?:v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})', u or "")
    return m.group(1) if m else (u or "").strip()

def main():
    if len(sys.argv) < 2:
        sys.exit("uso: yt_fetch.py <url|id>")
    vid = vid_id(sys.argv[1])
    api = YouTubeTranscriptApi()
    fetched = None
    try:
        fetched = api.fetch(vid, languages=['pt', 'pt-BR', 'pt-PT', 'en', 'en-orig'])
    except Exception:
        try:
            tl = api.list(vid)
            try:
                tr = tl.find_transcript(['pt', 'pt-BR', 'pt-PT', 'en', 'en-orig'])
            except Exception:
                tr = next(iter(tl))
                try:
                    tr = tr.translate('pt')   # traduz p/ PT se a original for outra língua
                except Exception:
                    pass
            fetched = tr.fetch()
        except Exception:
            return  # sem transcrição — stdout vazio (o shell cai pro whisper)
    txt = " ".join(s.text.strip() for s in fetched if s.text and s.text.strip())
    print(txt)

if __name__ == "__main__":
    main()
