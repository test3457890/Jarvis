"""Opt-in local full-text index of explicitly selected document folders."""
import os
import re
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

from . import config, documents

_LOCK = threading.Lock()


def path():
    return config.APP_DIR / 'documents-index.sqlite3'


def delete():
    """Remove the index when the user turns it off or changes selected folders."""
    with _LOCK:
        path().unlink(missing_ok=True)


def _files(cfg, tesseract):
    roots = documents.roots(cfg)
    allowed = documents.EXTENSIONS | (documents.IMAGE_EXTENSIONS if tesseract else set())
    entries = scanned = 0
    seen = set()
    skipped = 0
    for root in roots:
        if not root.is_dir():
            skipped += 1
            continue
        for parent, directories, files in os.walk(root, followlinks=False):
            entries += 1
            if entries > documents.MAX_ENTRIES:
                return seen, skipped, True
            directories[:] = sorted(name for name in directories if not name.startswith('.') and
                                     not Path(parent, name).is_symlink() and
                                     Path(parent, name).resolve().is_relative_to(root))
            for name in sorted(files):
                entries += 1
                if entries > documents.MAX_ENTRIES or scanned >= documents.MAX_FILES:
                    return seen, skipped, True
                candidate = Path(parent, name)
                if candidate.suffix.lower() not in allowed or candidate.is_symlink():
                    continue
                real = candidate.resolve()
                if not real.is_relative_to(root) or real in seen:
                    continue
                seen.add(real)
                scanned += 1
    return seen, skipped, False


def _connect():
    config.APP_DIR.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path(), timeout=10)
    connection.execute('CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, size INTEGER, mtime_ns INTEGER, ocr TEXT)')
    connection.execute('CREATE VIRTUAL TABLE IF NOT EXISTS sections USING fts5(path UNINDEXED, section UNINDEXED, body)')
    return connection


def _refresh(connection, cfg, tesseract):
    files, skipped, limited = _files(cfg, tesseract)
    old = {name: (size, mtime, ocr) for name, size, mtime, ocr in
           connection.execute('SELECT path, size, mtime_ns, ocr FROM files')}
    # When traversal is limited we cannot know whether an old path was omitted by
    # the bound. Query only current visible paths and remove stale rows next time.
    if not limited:
        for name in old.keys() - {str(item) for item in files}:
            connection.execute('DELETE FROM sections WHERE path=?', (name,))
            connection.execute('DELETE FROM files WHERE path=?', (name,))
    changed = 0
    for item in sorted(files):
        name = str(item)
        try:
            info = item.stat()
            if info.st_size > documents.MAX_BYTES or not item.is_file() or item.is_symlink():
                raise ValueError('Unsupported document')
            if old.get(name) == (info.st_size, info.st_mtime_ns, tesseract or ''):
                continue
            sections = list(documents.extract(item, tesseract))
            if item.stat().st_mtime_ns != info.st_mtime_ns:
                raise ValueError('Document changed while indexing')
        except ImportError:
            raise
        except Exception:
            skipped += 1
            connection.execute('DELETE FROM sections WHERE path=?', (name,))
            connection.execute('DELETE FROM files WHERE path=?', (name,))
            continue
        connection.execute('DELETE FROM sections WHERE path=?', (name,))
        connection.executemany('INSERT INTO sections(path,section,body) VALUES(?,?,?)',
                               ((name, section, content) for section, content in sections if content.strip()))
        connection.execute('INSERT OR REPLACE INTO files(path,size,mtime_ns,ocr) VALUES(?,?,?,?)',
                           (name, info.st_size, info.st_mtime_ns, tesseract or ''))
        changed += 1
    return files, skipped, limited, changed


def search(cfg, query):
    """Refresh changed documents, then search the local index with source labels."""
    terms = list(dict.fromkeys(re.findall(r'\w+', query.casefold())))[:30]
    if not terms:
        return 'Enter words to search for.'
    tesseract = documents.tesseract_path(cfg)
    with _LOCK:
        with closing(_connect()) as connection, connection:
            files, skipped, limited, changed = _refresh(connection, cfg, tesseract)
            expression = ' OR '.join('"' + term + '"' for term in terms)
            connection.execute('CREATE TEMP TABLE visible(path TEXT PRIMARY KEY)')
            connection.executemany('INSERT INTO visible(path) VALUES(?)',
                                   ((str(item),) for item in files))
            rows = connection.execute('SELECT sections.path,section,body FROM sections '
                                      'JOIN visible ON visible.path=sections.path WHERE sections MATCH ? '
                                      'ORDER BY bm25(sections) LIMIT 6', (expression,)).fetchall()
    header = f'Searched {len(files)} indexed documents. Updated {changed}. Skipped {skipped} unreadable files or unavailable folders.'
    if limited:
        header += ' Search limit reached. Select a smaller folder to cover more documents.'
    header += ' Extraction covers up to 200 PDF pages and 500,000 characters per document.'
    header += (' Scanned pages and images were read with local OCR; check OCR text against the original.'
               if tesseract else ' Scanned pages need OCR, which is off or not installed.')
    if not rows:
        return header + '\nNo matching extracted text found.'
    output = []
    for number, (name, section, content) in enumerate(rows, 1):
        start = 0
        for found in re.finditer(r'\w+', content.casefold()):
            if found.group() in terms:
                start = max(0, found.start() - 160)
                break
        output.append(f'[{number}] {name}, {section}\n{content[start:start+1000].strip()}')
    return header + '\n\n' + '\n\n'.join(output)
