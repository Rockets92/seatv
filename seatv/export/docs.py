"""Pagina `guida-api.html`: la Guida API (docs/api.md), leggibile dal sito.

I file Markdown del repository usano poche cose (titoli, paragrafi, elenchi,
tabelle, blocchi di codice, grassetto, codice e link): questo convertitore
copre solo quelle, senza dipendenze esterne.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
REPO_URL = "https://github.com/Rockets92/seatv"
# (file, ancora nella pagina). L'ordine è quello della pagina.
DOCS = (("docs/api.md", "api"),)
# Negli esempi della guida l'indirizzo del sito è scritto così; nella pagina
# pubblicata diventa quello vero, se è noto.
BASE_PLACEHOLDER = "https://seatv.pages.dev/<token>/"

_INLINE = re.compile(
    r"`(?P<code>[^`]+)`"
    r"|\*\*(?P<bold>.+?)\*\*"
    r"|\[(?P<text>[^\]]+)\]\((?P<href>[^)\s]+)\)"
    r"|<(?P<auto>https?://[^>\s]+)>"
)


def slug(text: str) -> str:
    text = re.sub(r"[`*]", "", text).lower()
    return re.sub(r"[^a-z0-9àèéìòù]+", "-", text).strip("-")


def _href(target: str) -> str:
    """Link fra documenti del repository: ancora nella pagina o pagina su GitHub."""
    if target.startswith(("https://", "http://", "#")):
        return target
    for path, anchor in DOCS:
        if target == path:
            return f"#{anchor}"
    return f"{REPO_URL}/blob/main/{target}"


def inline(text: str) -> str:
    out, pos = [], 0
    for m in _INLINE.finditer(text):
        out.append(html.escape(text[pos:m.start()], quote=False))
        if m["code"] is not None:
            out.append(f"<code>{html.escape(m['code'], quote=False)}</code>")
        elif m["bold"] is not None:
            out.append(f"<strong>{inline(m['bold'])}</strong>")
        elif m["auto"] is not None:
            url = html.escape(m["auto"])
            out.append(f'<a href="{url}" target="_blank" rel="noreferrer">{url}</a>')
        else:
            href = _href(m["href"])
            extra = "" if href.startswith("#") else ' target="_blank" rel="noreferrer"'
            out.append(f'<a href="{html.escape(href)}"{extra}>{inline(m["text"])}</a>')
        pos = m.end()
    out.append(html.escape(text[pos:], quote=False))
    return "".join(out)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def to_html(markdown: str, anchor: str) -> tuple[str, list[tuple[int, str, str]]]:
    """Restituisce l'HTML e i titoli (livello, id, testo) per l'indice."""
    lines = markdown.splitlines()
    out: list[str] = []
    headings: list[tuple[int, str, str]] = []
    para: list[str] = []
    i = 0

    def flush() -> None:
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            body = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                body.append(lines[i])
                i += 1
            out.append(f"<pre><code>{html.escape(chr(10).join(body), quote=False)}</code></pre>")
        elif m := re.match(r"(#{1,4})\s+(.*)", stripped):
            flush()
            level = len(m[1])
            # Il primo titolo prende l'ancora del documento, così i link fra documenti funzionano.
            hid = anchor if not headings else f"{anchor}-{slug(m[2])}"
            headings.append((level, hid, re.sub(r"[`*]", "", m[2])))
            out.append(f'<h{level + 1} id="{hid}">{inline(m[2])}</h{level + 1}>')
        elif stripped.startswith("|") and i + 1 < len(lines) and re.match(r"\|?\s*:?-+", lines[i + 1].strip()):
            flush()
            head = "".join(f"<th>{inline(c)}</th>" for c in _cells(stripped))
            rows = []
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in _cells(lines[i])) + "</tr>")
                i += 1
            out.append(f'<div class="table"><table><thead><tr>{head}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>')
            continue
        elif re.match(r"(- |\d+\. )", stripped):
            flush()
            tag = "ol" if stripped[0].isdigit() else "ul"
            items = []
            while i < len(lines) and re.match(r"(- |\d+\. )", lines[i].strip()):
                items.append(f"<li>{inline(re.sub(r'^(- |\d+\. )', '', lines[i].strip()))}</li>")
                i += 1
            out.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue
        elif not stripped or stripped.startswith("<"):
            # Righe vuote e HTML grezzo (il logo in cima al README) chiudono il paragrafo.
            flush()
        else:
            para.append(stripped)
        i += 1
    flush()
    return "\n".join(out), headings


PAGE = """<!doctype html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>SEA-TV · Guida API</title>
<meta name="robots" content="noindex, nofollow">
<meta name="referrer" content="no-referrer">
<meta name="theme-color" content="#020817">
<link rel="icon" href="static/favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="static/apple-touch-icon.png">
<link rel="manifest" href="manifest.webmanifest">
<link rel="stylesheet" href="static/guide.css">
</head>
<body class="doc-page">
<div class="aurora" aria-hidden="true"></div>
<header class="doc-bar">
  <a class="pill" href="./">‹ Torna alla guida TV</a>
  <a class="brand" href="./" aria-label="SEA-TV, guida TV"><img src="static/logo.png" alt="SEA-TV" width="960" height="316"></a>
</header>
<main class="doc">
<nav class="doc-toc" aria-label="Indice"><strong>Indice</strong>
{toc}
</nav>
{body}
<p class="doc-foot">Sorgenti e documentazione anche su <a href="{repo}" target="_blank" rel="noreferrer">GitHub</a>.</p>
</main>
</body>
</html>
"""


def render_docs(root: Path = ROOT, base_url: str = "") -> str:
    sections, toc = [], []
    for path, anchor in DOCS:
        file = root / path
        if not file.exists():
            continue
        text = file.read_text(encoding="utf-8")
        if base_url:
            text = text.replace(BASE_PLACEHOLDER, base_url.rstrip("/") + "/")
        body, headings = to_html(text, anchor)
        sections.append(f'<section class="doc-section">\n{body}\n</section>')
        toc.extend(
            f'<a class="toc-{level}" href="#{hid}">{html.escape(text)}</a>'
            for level, hid, text in headings
            if level <= 2
        )
    if not sections:
        sections.append(f'<p>La guida è su <a href="{REPO_URL}" target="_blank" rel="noreferrer">GitHub</a>.</p>')
    return PAGE.format(toc="\n".join(toc), body="\n".join(sections), repo=REPO_URL)
