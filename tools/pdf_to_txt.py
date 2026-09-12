#!/usr/bin/env python3
"""Convert Internet Archive–style PDFs to Rapid Reader .txt files.

Requires pdftotext (poppler-utils) on PATH. Cleans soft wraps, hyphenation,
running headers, and page numbers typical of digitized scans.

Usage:
  python3 tools/pdf_to_txt.py                  # all to_convert/*.pdf → ebooks/
  python3 tools/pdf_to_txt.py path.pdf ...
  python3 tools/pdf_to_txt.py --out DIR path.pdf
"""

from __future__ import annotations

import argparse
import collections
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DEFAULT_IN = os.path.join(ROOT, "to_convert")
DEFAULT_OUT = os.path.join(ROOT, "ebooks")

_PAGE_NUM = re.compile(r"^\d{1,4}$")
_SENT_END = re.compile(r'[.!?]["\'\u201d\u2019)\]]*$')
_MULTI_SPACE = re.compile(r"[ \t]+")
_MULTI_BLANK = re.compile(r"\n{3,}")
_GARBAGE_LINE = re.compile(r"^[\W\d_]{1,}$")
_MOSTLY_JUNK = re.compile(r"^[\^|\\/_=~*`'\".\-\s]+$")
_CHAPTER_HEAD = re.compile(
    r"^(Chapter|Letter|Part|Book|Volume)\s+(\d+|[IVXLCDM]+)\b(.*)$",
    re.IGNORECASE,
)
# TOC rows often break across lines: Chapter\n1\nThe Tar Pit\n3
_TOC_BLOCK = re.compile(
    r"(Chapter|Letter|Part|Book|Volume)\s+(\d+|[IVXLCDM]+)\s+"
    r"(.+?)\s+(\d{1,3})(?=\s+(?:Chapter|Letter|Part|Book|Volume|Epilogue|"
    r"Notes|Index|\Z))",
    re.IGNORECASE | re.DOTALL,
)


def _require_pdftotext():
    if shutil.which("pdftotext") is None:
        sys.exit(
            "pdftotext not found. Install poppler (e.g. poppler-utils / poppler)."
        )


def extract_raw(pdf_path: str) -> str:
    """Run pdftotext without -layout (reflow-friendly)."""
    try:
        proc = subprocess.run(
            ["pdftotext", pdf_path, "-"],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        sys.exit(
            "pdftotext not found. Install poppler (e.g. poppler-utils / poppler)."
        )
    except subprocess.CalledProcessError as e:
        err = (e.stderr or "").strip() or str(e)
        sys.exit(f"pdftotext failed on {pdf_path}: {err}")
    return proc.stdout


def _is_noise_line(s: str) -> bool:
    if not s or _PAGE_NUM.match(s):
        return True
    if _MOSTLY_JUNK.match(s) or _GARBAGE_LINE.match(s):
        return True
    if len(s) <= 2 and not s.isalnum():
        return True
    return False


def _norm_title(s: str) -> str:
    return _MULTI_SPACE.sub(" ", s).strip().lower()


def _detect_running_headers(pages: list[str], min_count: int = 3) -> set[str]:
    """Lines that recur near the top of pages (running titles / section heads)."""
    counts: collections.Counter[str] = collections.Counter()
    for page in pages:
        lines = [ln.strip() for ln in page.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        for ln in lines[:5]:
            if _is_noise_line(ln) or _CHAPTER_HEAD.match(ln):
                continue
            if len(ln) < 4 or len(ln) > 70:
                continue
            counts[ln] += 1
    return {ln for ln, n in counts.items() if n >= min_count}


def _extract_toc_map(raw: str) -> dict[str, str]:
    """Map normalized chapter title → 'Chapter N Title' from early TOC pages."""
    head = raw.split("\x0c", 40)
    flat = _MULTI_SPACE.sub(" ", "\n".join(head[:40]).replace("\n", " "))
    out: dict[str, str] = {}
    for m in _TOC_BLOCK.finditer(flat):
        section, num, title = m.group(1), m.group(2), m.group(3).strip(" .-")
        title = _MULTI_SPACE.sub(" ", title)
        # Drop page-number bleed from a missing 'Chapter' on the next TOC row
        title = re.sub(r"\s+\d{1,3}\s+.*", "", title).strip()
        if not title or len(title.split()) > 12:
            continue
        heading = f"{section.title()} {num} {title}".strip()
        out[_norm_title(title)] = heading
    return out


def _toc_strip_set(toc_map: dict[str, str], headers: set[str]) -> set[str]:
    """Lines to drop as chrome: recurring headers + known chapter titles."""
    strip = set(headers)
    for title_key, heading in toc_map.items():
        # heading is "Chapter N Title"; recover display variants from headers
        strip.add(heading.split(" ", 2)[-1] if heading.count(" ") >= 2 else title_key)
    # Also strip exact header spellings whose normalized form is a TOC title
    for h in headers:
        if _norm_title(h) in toc_map:
            strip.add(h)
    for key in toc_map:
        # Title-case rebuild for common OCR capitalization drift
        strip.add(" ".join(w.capitalize() if w[0].islower() else w
                           for w in key.split()))
        strip.add(key.title())
    return strip


def _page_chapter_from_toc(
    page: str, toc_map: dict[str, str], seen: set[str]
) -> str | None:
    """Emit a chapter heading the first time a TOC title opens a page.

    Front-matter title pages often reuse a chapter title (e.g. the book title
    is also Chapter 2). Wait until Chapter 1 has been seen before accepting
    later chapter titles; always accept Chapter 1 when it appears.
    """
    for ln in page.splitlines():
        s = ln.strip()
        if not s or _is_noise_line(s):
            continue
        key = _norm_title(s)
        if key not in toc_map or key in seen:
            return None
        heading = toc_map[key]
        m = re.match(r"(?:Chapter|Letter|Part|Book|Volume)\s+(\d+)", heading, re.I)
        num = int(m.group(1)) if m and m.group(1).isdigit() else None
        started = any(
            re.match(r"(?:Chapter|Letter|Part|Book|Volume)\s+1\b", toc_map[k], re.I)
            for k in seen
        )
        if num == 1 or started:
            seen.add(key)
            return heading
        return None
    return None


def _page_lines(page: str, strip_lines: set[str], toc_map: dict[str, str]) -> list[str]:
    lines = []
    for ln in page.splitlines():
        s = ln.strip()
        if not s or _is_noise_line(s):
            continue
        if s in strip_lines or _norm_title(s) in toc_map:
            continue
        lines.append(s)
    return lines


def _is_toc_page(lines: list[str]) -> bool:
    return sum(1 for ln in lines if _CHAPTER_HEAD.match(ln)) >= 4


def _dehyphenate_join(a: str, b: str) -> str:
    if a.endswith("-") and b and b[0].islower():
        return a[:-1] + b
    return a + " " + b


def _looks_like_heading(line: str) -> bool:
    if _CHAPTER_HEAD.match(line):
        return True
    words = line.split()
    if not words or len(words) > 10:
        return False
    if _SENT_END.search(words[-1]):
        return False
    if line.isupper() and len(line) >= 4:
        return True
    return False


def _reflow_lines(lines: list[str]) -> str:
    """Join OCR soft wraps; keep short Chapter headings as their own paragraphs."""
    if not lines:
        return ""
    paras: list[str] = []
    buf = lines[0]
    for line in lines[1:]:
        m = _CHAPTER_HEAD.match(line)
        chapter = None
        # Only promote "Chapter N Title" lines; bare "Chapter N" (notes/TOC
        # debris) stays in the prose stream so jump targets stay clean.
        if m and len(line.split()) <= 12:
            rest = (m.group(3) or "").strip(" .-")
            if rest and not rest.isdigit() and len(rest.split()) <= 10:
                chapter = f"{m.group(1).title()} {m.group(2)} {rest}".strip()

        if chapter:
            if buf.strip():
                paras.append(_MULTI_SPACE.sub(" ", buf).strip())
            paras.append(chapter)
            buf = ""
            continue

        if buf and _SENT_END.search(buf.split()[-1]) and _looks_like_heading(line):
            paras.append(_MULTI_SPACE.sub(" ", buf).strip())
            buf = line
            continue

        if not buf:
            buf = line
        else:
            buf = _dehyphenate_join(buf, line)

    if buf.strip():
        paras.append(_MULTI_SPACE.sub(" ", buf).strip())
    return "\n\n".join(p for p in paras if p)


def _fix_ocr_hyphens(text: str) -> str:
    """Join 'Com- ^ puter' / 'Com- puter' OCR hyphen debris."""
    return re.sub(
        r"(\w)-\s+[^\w\s]{0,3}\s*(\w)",
        lambda m: m.group(1) + m.group(2) if m.group(2)[0].islower()
        else m.group(0),
        text,
    )


def clean_text(raw: str) -> str:
    pages = raw.split("\x0c")
    headers = _detect_running_headers(pages)
    toc_map = _extract_toc_map(raw)
    strip_lines = _toc_strip_set(toc_map, headers)
    seen_chapters: set[str] = set()

    parts: list[str] = []
    for page in pages:
        raw_lines = [ln.strip() for ln in page.splitlines() if ln.strip()]
        if _is_toc_page(raw_lines):
            continue

        marker = _page_chapter_from_toc(page, toc_map, seen_chapters)
        lines = _page_lines(page, strip_lines, toc_map)
        reflowed = _reflow_lines(lines)
        if marker:
            chunk = marker if not reflowed else marker + "\n\n" + reflowed
        else:
            chunk = reflowed
        if not chunk:
            continue

        if not parts:
            parts.append(chunk)
            continue

        first_para, _, rest = chunk.partition("\n\n")
        prev_paras = parts[-1].split("\n\n")
        last = prev_paras[-1]
        if (
            last
            and not _CHAPTER_HEAD.match(last)
            and not _CHAPTER_HEAD.match(first_para)
            and not _SENT_END.search(last.split()[-1])
            and not _looks_like_heading(first_para)
        ):
            prev_paras[-1] = _dehyphenate_join(last, first_para)
            merged = "\n\n".join(prev_paras)
            if rest:
                merged = merged + "\n\n" + rest
            parts[-1] = merged
        else:
            parts.append(chunk)

    body = "\n\n".join(parts)
    body = _fix_ocr_hyphens(body)
    body = _MULTI_BLANK.sub("\n\n", body).strip()
    return body + "\n" if body else ""


def out_name(pdf_path: str) -> str:
    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    stem = re.sub(r'[<>:"/\\|?*]', "", stem).strip(" .")
    return (stem or "book") + ".txt"


def convert_one(pdf_path: str, out_dir: str) -> str:
    raw = extract_raw(pdf_path)
    text = clean_text(raw)
    if not text.strip():
        sys.exit(f"no extractable text in {pdf_path}")
    os.makedirs(out_dir, exist_ok=True)
    dest = os.path.join(out_dir, out_name(pdf_path))
    with open(dest, "w", encoding="utf-8") as f:
        f.write(text)
    return dest


def _default_pdfs() -> list[str]:
    if not os.path.isdir(DEFAULT_IN):
        return []
    return sorted(
        os.path.join(DEFAULT_IN, name)
        for name in os.listdir(DEFAULT_IN)
        if name.lower().endswith(".pdf") and not name.startswith(".")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert IA-style PDFs to Rapid Reader .txt files."
    )
    parser.add_argument(
        "pdfs",
        nargs="*",
        help="PDF paths (default: to_convert/*.pdf)",
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT,
        help=f"output directory (default: {DEFAULT_OUT})",
    )
    args = parser.parse_args(argv)

    _require_pdftotext()
    pdfs = args.pdfs or _default_pdfs()
    if not pdfs:
        sys.exit(f"no PDFs given and none found in {DEFAULT_IN}/")

    for pdf in pdfs:
        if not os.path.isfile(pdf):
            sys.exit(f"not a file: {pdf}")
        dest = convert_one(pdf, args.out)
        print(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
