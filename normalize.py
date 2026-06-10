#!/usr/bin/env python3
"""
normalize.py — normaliza texto para Telegram (HTML) ou TTS (texto puro)

Uso:
  python3 normalize.py html  "texto com **markdown**"   → HTML para Telegram
  python3 normalize.py plain "texto com **markdown**"   → texto limpo para TTS
"""
import sys, re, html

def md_to_html(text):
    """Converte Markdown para HTML do Telegram. Entrada pode ser MD ou HTML misto."""

    # 1. Escapa caracteres HTML que NÃO fazem parte de tags já existentes
    #    (evita double-escape de HTML legítimo já presente no texto)
    # Primeiro preserva tags HTML legítimas do Telegram
    TAG_PLACEHOLDER = {}
    counter = [0]

    def stash_tag(m):
        key = f"\x00TAG{counter[0]}\x00"
        TAG_PLACEHOLDER[key] = m.group(0)
        counter[0] += 1
        return key

    # preserva tags HTML já existentes
    text = re.sub(r'<(/?(b|i|u|s|code|pre|a|tg-spoiler)(\s[^>]*)?)>', stash_tag, text)

    # escapa < > & soltos (que não são tags)
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    # restaura tags preservadas
    for key, tag in TAG_PLACEHOLDER.items():
        text = text.replace(key, tag)

    # 2. Markdown → HTML
    # Bloco de código ```...```
    text = re.sub(r'```(?:\w+\n)?(.*?)```', lambda m: '<pre>' + m.group(1).strip() + '</pre>', text, flags=re.DOTALL)
    # Código inline `...`
    text = re.sub(r'`([^`\n]+)`', r'<code>\1</code>', text)
    # Negrito **texto** ou __texto__
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)
    # Itálico *texto* ou _texto_ (cuidado para não pegar ** já processado)
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'<i>\1</i>', text)
    text = re.sub(r'(?<!_)_(?!_)(.+?)(?<!_)_(?!_)', r'<i>\1</i>', text)
    # Tachado ~~texto~~
    text = re.sub(r'~~(.+?)~~', r'<s>\1</s>', text)
    # Cabeçalhos ## → <b>
    text = re.sub(r'^#{1,6}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
    # Linhas horizontais ---
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)

    return text.strip()


def md_to_plain(text):
    """Remove toda formatação Markdown e HTML, retorna texto puro para TTS."""
    # Remove tags HTML
    text = re.sub(r'<[^>]+>', '', text)
    # Decodifica entidades HTML
    text = html.unescape(text)
    # Remove formatação Markdown
    text = re.sub(r'```(?:\w+\n)?(.*?)```', r'\1', text, flags=re.DOTALL)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'__(.+?)__', r'\1', text)
    text = re.sub(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)', r'\1', text)
    text = re.sub(r'(?<!_)_(?!_)(.+?)(?<!_)_(?!_)', r'\1', text)
    text = re.sub(r'~~(.+?)~~', r'\1', text)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    # Limpa espaços
    text = re.sub(r'\s+', ' ', text).strip()
    return text


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'html'
    text = sys.argv[2] if len(sys.argv) > 2 else sys.stdin.read()
    if mode == 'plain':
        print(md_to_plain(text), end='')
    else:
        print(md_to_html(text), end='')
