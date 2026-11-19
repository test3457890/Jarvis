"""Measure document search time on a synthetic folder, to decide whether a persistent index helps.

    python -m scripts.measure_document_search [--ocr]

Creates 200 text files, 20 text PDFs and (with --ocr) 5 scanned PDF pages in a temporary folder,
then times three searches. Prints JSON. Results depend on the PC and disk.
"""
import argparse
import json
import random
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from jarvis import config, documents, skills

WORDS = ("budget river compass lantern orbit harvest signal meadow copper ledger timber canyon "
         "voltage harbor saddle quartz maple beacon").split()


def make_scans(folder, count):
    for number in range(count):
        image = Image.new("L", (1700, 400), 255)
        font = ImageFont.load_default(size=64)
        ImageDraw.Draw(image).text((40, 120), f"Scanned invoice {number} total 42", fill=0, font=font)
        image.save(folder / f"scan_{number}.pdf", "PDF", resolution=200)


def make_corpus(folder, scanned=0):
    random.seed(7)
    for number in range(200):
        text = "\n".join(" ".join(random.choice(WORDS) for _ in range(12)) for _ in range(160))
        (folder / f"note_{number:03}.txt").write_text(text + ("\nneedle phrase here" if number == 150 else ""))
    for number in range(20):
        image = Image.new("RGB", (800, 300), "white")
        ImageDraw.Draw(image).text((20, 20), "ledger summary " * 5, fill="black")
        (folder / f"text_{number}.pdf").write_bytes(b"")
        _text_pdf(folder / f"text_{number}.pdf", " ".join(random.choice(WORDS) for _ in range(300)))


def _text_pdf(path, text):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject, DictionaryObject
    writer = PdfWriter()
    page = writer.add_blank_page(612, 792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 10 Tf 40 700 Td ({text[:900]}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as handle:
        writer.write(handle)


def timed(ctx, query):
    started = time.perf_counter()
    result = skills.run(ctx, "search_documents", {"query": query})
    return round(time.perf_counter() - started, 3), result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--ocr", action="store_true")
    args = parser.parse_args(argv)
    report = {}
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        make_corpus(folder)
        cfg = dict(config.DEFAULTS, document_folders=[str(folder)], ocr_enabled=args.ocr)
        ctx = skills.Context(cfg, None)
        report["files"] = len(list(folder.iterdir()))
        report["note"] = f"search covers up to {documents.MAX_FILES} documents per request"
        report["search_seconds"] = {q: timed(ctx, q)[0] for q in ("needle phrase", "ledger canyon", "missingword")}
    if args.ocr:
        with tempfile.TemporaryDirectory() as tmp:
            make_scans(Path(tmp), 5)
            cfg = dict(config.DEFAULTS, document_folders=[tmp], ocr_enabled=True)
            ctx = skills.Context(cfg, None)
            documents._OCR_CACHE.clear()
            first, result = timed(ctx, "scanned invoice")
            again, _ = timed(ctx, "scanned invoice")
            report["ocr"] = {"scanned_pages": 5, "first_search_seconds": first,
                             "repeat_search_seconds": again, "found": "(OCR)" in result}
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    main()
