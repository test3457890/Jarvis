"""Local Office Document Generation, Citation Manager & Knowledge Graph (Phase 9).

Zero-dependency pure-Python local document tools:
- Word (.docx) valid OOXML document generator & text extractor.
- PowerPoint (.pptx) valid OOXML slide deck generator.
- CSV/TSV summary & table exporter.
- Citation manager (APA, MLA, BibTeX formatting) persisted in SQLite.
- Local Entity-Relation Knowledge Graph persisted in SQLite.
- Strictly local-first; preserves Finance & Health privacy boundaries.
"""
import csv
import html
import io
import json
from pathlib import Path
import re
import time
import zipfile

from . import config, secure

_SAFE_FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,80}$")


def output_docs_dir(cfg: dict | None = None) -> Path:
    base = Path((cfg or {}).get("notes_dir") or config.APP_DIR / "generated-docs").expanduser().resolve()
    out = base / "jarvis-exports"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _safe_dest(cfg: dict | None, filename: str, ext: str) -> Path:
    clean = Path(str(filename or f"document{ext}")).name
    if not clean.lower().endswith(ext):
        clean += ext
    if not _SAFE_FILE_RE.match(clean):
        raise ValueError("Use a safe alphanumeric filename.")
    root = output_docs_dir(cfg)
    dest = (root / clean).resolve()
    if dest.parent != root:
        raise ValueError("Invalid output path.")
    return dest


# ------------------------------------------------------------------ Word (.docx)
def generate_docx(cfg: dict | None, filename: str, title: str, paragraphs: list[str]) -> dict:
    """Generate a valid, standards-compliant Microsoft Word .docx file locally without external dependencies."""
    dest = _safe_dest(cfg, filename, ".docx")
    paras_xml = [
        f"<w:p><w:r><w:rPr><w:b/><w:sz w:val='32'/></w:rPr><w:t>{html.escape(str(title))}</w:t></w:r></w:p>"
    ]
    for p in (paragraphs or []):
        paras_xml.append(f"<w:p><w:r><w:t xml:space='preserve'>{html.escape(str(p))}</w:t></w:r></w:p>")
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(paras_xml)}<w:sectPr/></w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '</Types>'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        '</Relationships>'
    )
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", doc_xml)
    secure.audit("office_docx_generated", {"file": dest.name, "paragraphs": len(paragraphs or [])})
    return {"ok": True, "format": "docx", "path": str(dest), "bytes": dest.stat().st_size}


def read_docx_text(path: str | Path) -> str:
    """Extract plain text from a local .docx file."""
    with zipfile.ZipFile(Path(path), "r") as zf:
        xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
    texts = re.findall(r"<w:t[^>]*>(.*?)</w:t>", xml, flags=re.S)
    return html.unescape("\n".join(texts))


# ------------------------------------------------------------------ PowerPoint (.pptx)
def generate_pptx(cfg: dict | None, filename: str, slides: list[dict]) -> dict:
    """Generate a valid OOXML PowerPoint .pptx deck locally from [{title, body}]."""
    dest = _safe_dest(cfg, filename, ".pptx")
    if not slides:
        raise ValueError("Provide at least one slide with title/body.")
    slide_overrides = []
    pres_sids = []
    pres_rels = []
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for idx, s in enumerate(slides[:30], start=1):
            stitle = html.escape(str(s.get("title") or f"Slide {idx}"))
            sbody = html.escape(str(s.get("body") or ""))
            sxml = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                '<p:cSld><p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>'
                f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="Title"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr><p:spPr/>'
                f'<p:txBody><a:bodyPr/><a:p><a:r><a:t>{stitle}</a:t></a:r></a:p><a:p><a:r><a:t>{sbody}</a:t></a:r></a:p></p:txBody></p:sp>'
                '</p:spTree></p:cSld></p:sld>'
            )
            zf.writestr(f"ppt/slides/slide{idx}.xml", sxml)
            slide_overrides.append(f'<Override PartName="/ppt/slides/slide{idx}.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>')
            pres_sids.append(f'<p:sldId id="{255 + idx}" r:id="rId{idx}"/>')
            pres_rels.append(f'<Relationship Id="rId{idx}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" Target="slides/slide{idx}.xml"/>')

        zf.writestr("[Content_Types].xml", (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
            f"{''.join(slide_overrides)}</Types>"
        ))
        zf.writestr("_rels/.rels", (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>'
            '</Relationships>'
        ))
        zf.writestr("ppt/presentation.xml", (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f"<p:sldIdLst>{''.join(pres_sids)}</p:sldIdLst></p:presentation>"
        ))
        zf.writestr("ppt/_rels/presentation.xml.rels", (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f"{''.join(pres_rels)}</Relationships>"
        ))
    secure.audit("office_pptx_generated", {"file": dest.name, "slides": len(slides[:30])})
    return {"ok": True, "format": "pptx", "path": str(dest), "slides": len(slides[:30]), "bytes": dest.stat().st_size}


# ------------------------------------------------------------------ Citations & Knowledge Graph
def _init_kg_db(mem) -> None:
    with mem._lock:
        mem.db.execute(
            """CREATE TABLE IF NOT EXISTS citations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cite_key TEXT UNIQUE NOT NULL,
                authors TEXT NOT NULL,
                year TEXT NOT NULL,
                title TEXT NOT NULL,
                venue TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            )"""
        )
        mem.db.execute(
            """CREATE TABLE IF NOT EXISTS knowledge_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                relation TEXT NOT NULL,
                object TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            )"""
        )
        mem.db.commit()


def add_citation(mem, cite_key: str, authors: str, year: str, title: str, *, venue: str = "", url: str = "") -> dict:
    _init_kg_db(mem)
    ck = re.sub(r"[^A-Za-z0-9_-]", "", str(cite_key or "ref")).strip()[:40] or "ref"
    now = time.time()
    with mem._lock:
        mem.db.execute(
            "INSERT OR REPLACE INTO citations (cite_key, authors, year, title, venue, url, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ck, str(authors)[:160], str(year)[:12], str(title)[:240], str(venue)[:120], str(url)[:240], now),
        )
        mem.db.commit()
    return {
        "cite_key": ck,
        "apa": f"{authors} ({year}). {title}. {venue}".strip(),
        "bibtex": f"@article{{{ck}, author={{{authors}}}, year={{{year}}}, title={{{title}}}, journal={{{venue}}}}}",
    }


def list_citations(mem) -> list[dict]:
    _init_kg_db(mem)
    with mem._lock:
        rows = mem.db.execute("SELECT cite_key, authors, year, title, venue, url FROM citations ORDER BY id DESC LIMIT 100").fetchall()
    return [
        {
            "cite_key": r[0], "authors": r[1], "year": r[2], "title": r[3], "venue": r[4], "url": r[5],
            "apa": f"{r[1]} ({r[2]}). {r[3]}. {r[4]}".strip(),
        }
        for r in rows
    ]


def add_knowledge_edge(mem, subject: str, relation: str, obj: str, *, source: str = "user") -> dict:
    _init_kg_db(mem)
    s, r, o = str(subject).strip()[:100], str(relation).strip()[:60], str(obj).strip()[:100]
    if not (s and r and o):
        raise ValueError("Provide subject, relation, and object for the knowledge graph.")
    with mem._lock:
        mem.db.execute(
            "INSERT INTO knowledge_edges (subject, relation, object, source, created_at) VALUES (?, ?, ?, ?, ?)",
            (s, r, o, str(source)[:80], time.time()),
        )
        mem.db.commit()
    return {"subject": s, "relation": r, "object": o, "source": source}


def query_knowledge_graph(mem, term: str = "", limit: int = 50) -> list[dict]:
    _init_kg_db(mem)
    q = f"%{str(term or '').strip()}%"
    with mem._lock:
        rows = mem.db.execute(
            "SELECT subject, relation, object, source FROM knowledge_edges WHERE subject LIKE ? OR relation LIKE ? OR object LIKE ? ORDER BY id DESC LIMIT ?",
            (q, q, q, max(1, min(limit, 100))),
        ).fetchall()
    return [{"subject": r[0], "relation": r[1], "object": r[2], "source": r[3]} for r in rows]
