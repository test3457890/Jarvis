"""Search explicitly selected local folders and cite extracted document sections."""
import io
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from .skills import skill

MAX_BYTES = 10 * 1024 * 1024
MAX_FILES = 200
MAX_ENTRIES = 3000
MAX_TEXT = 500_000
EXTENSIONS = {'.txt', '.md', '.pdf', '.docx'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.tif', '.tiff'}
OCR_TIMEOUT = 60
OCR_MIN_TEXT = 20  # a PDF page with less extracted text than this is treated as scanned
_OCR_CACHE = {}  # (path, size, mtime_ns) -> list of (section, text); kept for this session only
_OCR_LOCK = threading.Lock()


def tesseract_path(cfg):
    """The Tesseract OCR program, if the user enabled OCR and installed it."""
    if not cfg.get('ocr_enabled'):
        return None
    configured = cfg.get('tesseract_path') or ''
    candidates = [configured, shutil.which('tesseract') or '',
                  os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'), 'Tesseract-OCR', 'tesseract.exe')]
    return next((c for c in candidates if c and Path(c).is_file()), None)


def ocr_image(tesseract, data, suffix='.png'):
    """Run local Tesseract on image bytes. Nothing leaves the PC."""
    with tempfile.TemporaryDirectory() as folder:
        image = Path(folder) / ('page' + suffix)
        image.write_bytes(data)
        result = subprocess.run([tesseract, str(image), 'stdout', '-l', 'eng'], capture_output=True,
                                timeout=OCR_TIMEOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise ValueError('OCR failed: ' + result.stderr.decode(errors='replace')[-200:])
    return result.stdout.decode('utf-8', errors='replace')[:MAX_TEXT]


def roots(cfg):
    values = cfg.get('document_folders', [])
    return [Path(value).expanduser().resolve() for value in values if isinstance(value, str) and value.strip()]


def extract(path, tesseract=None):
    # Bound input before handing it to a document parser.
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('File exceeds the 10 MiB limit.')
    suffix = path.suffix.lower()
    if suffix in IMAGE_EXTENSIONS:
        if tesseract:
            yield from _cached_ocr(path, lambda: [('image (OCR)', ocr_image(tesseract, raw, suffix))])
        return
    if suffix == '.pdf':
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:
            raise ValueError('Encrypted PDF requires an unlocked copy.')
        total = 0
        for index, page in enumerate(reader.pages):
            text = (page.extract_text() or '')[:MAX_TEXT - total]
            if tesseract and len(text.strip()) < OCR_MIN_TEXT:
                def read_page(page=page, index=index):
                    pieces = [ocr_image(tesseract, image.data, Path(image.name).suffix or '.png')
                              for image in list(page.images)[:3]]
                    return [(f'page {index + 1} (OCR)', '\n'.join(pieces))]
                for section, ocr_text in _cached_ocr(path, read_page, key=index):
                    yield section, ocr_text[:MAX_TEXT - total]
                    total += len(ocr_text)
            else:
                yield f'page {index + 1}', text
                total += len(text)
            if total >= MAX_TEXT or index >= 199:
                break
    elif path.suffix.lower() == '.docx':
        # Word pagination depends on the renderer. Cite paragraphs and tables.
        import zipfile
        from docx import Document
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if sum(entry.file_size for entry in archive.infolist()) > 30 * 1024 * 1024:
                raise ValueError('Expanded Word document exceeds the extraction limit.')
        document = Document(io.BytesIO(raw))
        total = 0
        for index, paragraph in enumerate(document.paragraphs):
            text = paragraph.text[:MAX_TEXT - total]
            yield f'paragraph {index + 1}', text
            total += len(text)
            if total >= MAX_TEXT:
                return
        for index, table in enumerate(document.tables):
            text = '\n'.join(' | '.join(cell.text for cell in row.cells) for row in table.rows)[:MAX_TEXT-total]
            yield f'table {index + 1}', text
            total += len(text)
            if total >= MAX_TEXT:
                return
    else:
        text = raw.decode('utf-8-sig', errors='replace')[:MAX_TEXT]
        yield from _lines(text)


def _lines(text):
    lines = text.splitlines()
    for index in range(0, len(lines), 40):
        yield f'lines {index + 1}-{min(index + 40, len(lines))}', '\n'.join(lines[index:index+40])


def _cached_ocr(path, produce, key=None):
    """OCR is slow, so results are reused while the file is unchanged."""
    info = path.stat()
    cache_key = (str(path), info.st_size, info.st_mtime_ns, key)
    with _OCR_LOCK:
        cached = _OCR_CACHE.get(cache_key)
    if cached is None:
        cached = produce()
        with _OCR_LOCK:
            if len(_OCR_CACHE) > 2000:
                _OCR_CACHE.clear()
            _OCR_CACHE[cache_key] = cached
    yield from cached


@skill('Search text inside selected local PDF, Word, Markdown and text documents. '
       'Return source excerpts with file and page or section references.',
       params={'query': ('string', 'Words or a phrase to find in local documents', True)}, untrusted=True)
def search_documents(ctx, query):
    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        return 'Enter a search query between 1 and 500 characters.'
    folders = roots(ctx.cfg)
    if not folders:
        return 'Choose document folders in Jarvis setup first.'
    tesseract = tesseract_path(ctx.cfg)
    allowed = EXTENSIONS | (IMAGE_EXTENSIONS if tesseract else set())
    terms = set(re.findall(r'\w+', query.casefold()))
    if not terms:
        return 'Enter words to search for.'
    matches, seen = [], set()
    scanned = entries = skipped = 0
    limited = False
    for root in folders:
        if not root.is_dir():
            skipped += 1
            continue
        for parent, directories, files in os.walk(root, followlinks=False):
            entries += 1
            if entries > MAX_ENTRIES:
                limited = True
                break
            directories[:] = sorted(name for name in directories if not name.startswith('.') and
                                     not Path(parent, name).is_symlink() and
                                     Path(parent, name).resolve().is_relative_to(root))
            for name in sorted(files):
                entries += 1
                if entries > MAX_ENTRIES or scanned >= MAX_FILES:
                    limited = True
                    break
                candidate = Path(parent, name)
                if candidate.suffix.lower() not in allowed or candidate.is_symlink():
                    continue
                path = candidate.resolve()
                if not path.is_relative_to(root) or path in seen:
                    continue
                seen.add(path)
                scanned += 1
                try:
                    for section, content in extract(path, tesseract):
                        words = set(re.findall(r'\w+', content.casefold()))
                        score = len(terms & words)
                        if not score:
                            continue
                        positions = [m.start() for m in re.finditer(r'\w+', content.casefold()) if m.group() in terms]
                        start = max(0, min(positions, default=0) - 160)
                        excerpt = content[start:start+1000].strip()
                        matches.append((score, str(path), section, excerpt))
                        # Keep bounded results even for very large sets of paragraphs.
                        matches.sort(key=lambda item: (-item[0], item[1], item[2]))
                        del matches[6:]
                except ImportError:
                    return 'Install document readers with: .venv\\Scripts\\python.exe -m pip install -r requirements.txt'
                except Exception:
                    skipped += 1
            if limited:
                break
        if limited:
            break
    header = f'Searched {scanned} documents. Skipped {skipped} unreadable files or unavailable folders.'
    if limited:
        header += ' Search limit reached. Select a smaller folder to cover more documents.'
    header += ' Extraction covers up to 200 PDF pages and 500,000 characters per document.'
    header += (' Scanned pages and images were read with local OCR; check OCR text against the original.'
               if tesseract else ' Scanned pages need OCR, which is off or not installed.')
    if not matches:
        return header + '\nNo matching extracted text found.'
    return header + '\n\n' + '\n\n'.join(
        f'[{index}] {path}, {section}\n{excerpt}'
        for index, (_, path, section, excerpt) in enumerate(matches, 1)
    )
