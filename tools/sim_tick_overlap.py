#!/usr/bin/env python3
"""Simulate RSVP word frames and report upper-tick / glyph overlap.

Renders real ``render.word_frame`` output (no layout changes) for tokens
sampled from the local ebook library, classifies single-line vs two-line
overflow, detects ink in the upper tick band that belongs to the word
(not the tick), and writes a visual report you can open in a browser.

Sampling is stratified over *unique* token types (not occurrences), so
Zipf-common words like "the"/"of" do not dominate. Within each stratum
the draw is shuffled, so successive runs differ unless ``--seed`` is set.

Runs append by default: tokens already in the report are skipped, new
PNGs are added, and ``index.html`` / ``summary.txt`` / ``flagged.md``
are rebuilt from ``results.jsonl``. Use ``--reset`` to wipe and start over.

Usage:
  python3 tools/sim_tick_overlap.py
  python3 tools/sim_tick_overlap.py --out /tmp/tick_overlap --seed 42
  python3 tools/sim_tick_overlap.py --ebooks /path/to/ebooks
  python3 tools/sim_tick_overlap.py --reset
"""

from __future__ import annotations

import argparse
import html
import json
import os
import random
import re
import secrets
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, replace

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "rapid_reader"))

import render  # noqa: E402
import rsvp  # noqa: E402
import theme as themes  # noqa: E402

DEFAULT_OUT = os.path.join(ROOT, "artifacts", "tick_overlap")
DEFAULT_EBOOKS = os.path.join(ROOT, "ebooks")
JSONL_NAME = "results.jsonl"
SCALE = 8
WORD_SIZES = ("small", "medium", "large")

# Quotas per stratum. Longer / punctuated types are oversampled relative
# to how often they appear in running text.
STRATUM_QUOTAS = {
    "short": 4,            # core 1–7: a few clean controls
    "mid": 8,              # core 8–11
    "long_under_split": 12,  # core 12–14: txt_to_txt will not chunk these
    "long": 8,             # core >= 15 (survivors / unprocessed)
    "trailing_punct": 12,  # core >= 8 with trailing punctuation
    "hyphen_chunk": 6,     # leftover "foo-" pieces from compound/chunk splits
}
STRATUM_ORDER = (
    "trailing_punct", "hyphen_chunk", "long", "long_under_split", "mid", "short",
)

# Upper tick band inclusive rows (matches render._TICK_ABOVE).
_TICK_Y0 = render.CENTER_Y - render._TICK_ABOVE[0]  # 16
_TICK_Y1 = render.CENTER_Y - render._TICK_ABOVE[1]  # 22


def ticks_theme():
    return replace(themes.THEMES["night"], pivot_style="ticks")


def bold_theme():
    return replace(themes.THEMES["night"], pivot_style="bold")


def measure_total(word: str, theme, word_size: str) -> tuple[float, int | None]:
    """Return (total_at_last_tried_size, fit_size_or_None).

    Mirrors ``render.word_frame``'s fit loop so two-line classification matches
    production without inspecting private draw state.
    """
    img, d = render._canvas()
    sizes = render._WORD_SIZE_TIERS.get(word_size, render._WORD_SIZE_TIERS["medium"])
    orp = rsvp.orp_index(word)
    pre, ch, post = word[:orp], word[orp], word[orp + 1:]
    fit_size = None
    total = 0.0
    for size in sizes:
        reg = themes.font(theme, size)
        bold = themes.font(theme, size, bold=True)
        ch_fnt = reg if theme.pivot_style == "box" else bold
        w_pre = d.textlength(pre, font=reg)
        w_ch = d.textlength(ch, font=ch_fnt)
        w_post = d.textlength(post, font=reg)
        total = w_pre + w_ch + w_post
        x0 = render.PIVOT_X - w_pre - w_ch / 2
        if x0 >= 4 and x0 + total <= render.W - 4:
            fit_size = size
            break
    return total, fit_size


def is_two_line(word: str, theme, word_size: str) -> bool:
    total, _ = measure_total(word, theme, word_size)
    return total > render.W - 8


def word_ink_in_tick_band(ticks_img: Image.Image, bold_img: Image.Image) -> int:
    """Count pixels that are ink on both frames in the upper tick band.

    Tick-only pixels light the ticks frame but not the bold frame; word
    glyphs light both. Overlap with the tick is therefore shared ink.
    """
    tp, bp = ticks_img.load(), bold_img.load()
    n = 0
    for y in range(_TICK_Y0, _TICK_Y1 + 1):
        for x in range(ticks_img.width):
            if tp[x, y] == render.INK and bp[x, y] == render.INK:
                n += 1
    return n


def tick_only_columns(ticks_img: Image.Image, bold_img: Image.Image) -> set[int]:
    """Columns lit in the upper band on the ticks frame but not on bold."""
    tp, bp = ticks_img.load(), bold_img.load()
    cols = set()
    for x in range(ticks_img.width):
        for y in range(_TICK_Y0, _TICK_Y1 + 1):
            if tp[x, y] == render.INK and bp[x, y] != render.INK:
                cols.add(x)
                break
    return cols


@dataclass
class CaseResult:
    word: str
    word_size: str
    total: float
    fit_size: int | None
    two_line: bool
    overlap_px: int
    tick_cols: set[int]
    note: str = ""
    plain: str = ""
    ann: str = ""

    @property
    def overlaps(self) -> bool:
        return self.overlap_px > 0

    @property
    def flagged(self) -> bool:
        return self.overlaps or self.two_line

    @property
    def slug(self) -> str:
        safe = "".join(c if c.isalnum() else "_" for c in self.word)[:40]
        digest = "%04x" % (sum(self.word.encode("utf-8", "replace")) % 0xFFFF)
        return f"{self.word_size}_{safe}_{digest}"

    @property
    def label(self) -> str:
        status = ["TWO-LINE" if self.two_line else "single"]
        status.append("OVERLAP" if self.overlaps else "clean")
        return " ".join(status)


def analyze(word: str, word_size: str, theme=None, note: str = "") -> CaseResult:
    theme = theme or ticks_theme()
    total, fit_size = measure_total(word, theme, word_size)
    two = total > render.W - 8
    ticks_img = render.word_frame(word, theme, word_size=word_size)
    bold_img = render.word_frame(word, bold_theme(), word_size=word_size)
    return CaseResult(
        word=word,
        word_size=word_size,
        total=total,
        fit_size=fit_size,
        two_line=two,
        overlap_px=word_ink_in_tick_band(ticks_img, bold_img),
        tick_cols=tick_only_columns(ticks_img, bold_img),
        note=note,
    )


def scale_nearest(img: Image.Image, scale: int = SCALE) -> Image.Image:
    return img.resize((img.width * scale, img.height * scale), Image.NEAREST)


def to_rgb_oled(img: Image.Image) -> Image.Image:
    """Map L 0/255 to black background / white ink for OLED-like preview."""
    rgb = Image.new("RGB", img.size, (0, 0, 0))
    px, out = img.load(), rgb.load()
    for y in range(img.height):
        for x in range(img.width):
            if px[x, y] == render.INK:
                out[x, y] = (255, 255, 255)
    return rgb


def annotate(ticks_img: Image.Image, bold_img: Image.Image,
             tick_cols: set[int]) -> Image.Image:
    """OLED frame with tick band tint + overlap pixels highlighted."""
    base = to_rgb_oled(ticks_img)
    out = base.convert("RGBA")
    overlay = Image.new("RGBA", out.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    # Tint the whole upper tick band.
    d.rectangle([0, _TICK_Y0, out.width - 1, _TICK_Y1],
                fill=(255, 200, 0, 50))
    tp, bp = ticks_img.load(), bold_img.load()
    for y in range(_TICK_Y0, _TICK_Y1 + 1):
        for x in range(ticks_img.width):
            if tp[x, y] == render.INK and bp[x, y] == render.INK:
                overlay.putpixel((x, y), (255, 60, 60, 200))
            elif x in tick_cols and tp[x, y] == render.INK:
                overlay.putpixel((x, y), (80, 180, 255, 220))
    return Image.alpha_composite(out, overlay).convert("RGB")


def core_len(word: str) -> int:
    start, end = rsvp.core_span(word)
    return end - start


def has_trailing_punct(word: str) -> bool:
    start, end = rsvp.core_span(word)
    return end < len(word)


def classify_stratum(word: str) -> str:
    """Most-specific bucket for a unique token type."""
    start, end = rsvp.core_span(word)
    n = end - start
    if n >= 8 and end < len(word):
        return "trailing_punct"
    if n >= 3 and word.endswith("-") and word[:-1].isalpha():
        return "hyphen_chunk"
    if n >= 15:
        return "long"
    if n >= 12:
        return "long_under_split"
    if n >= 8:
        return "mid"
    return "short"


def ebook_txt_paths(ebooks_dir: str) -> list[str]:
    out = []
    for root, dirnames, filenames in os.walk(ebooks_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.lower().endswith(".txt") and not name.startswith("."):
                out.append(os.path.join(root, name))
    return sorted(out)


def collect_unique_tokens(ebooks_dir: str) -> set[str]:
    """Whitespace tokens as the reader would flash them (unique types)."""
    seen: set[str] = set()
    for path in ebook_txt_paths(ebooks_dir):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        seen.update(text.split())
    return seen


def sample_ebook_tokens(
    ebooks_dir: str,
    rng: random.Random,
    quotas: dict[str, int] | None = None,
) -> list[tuple[str, str]]:
    """Return (word, stratum) pairs: shuffled draw within each quota.

    Unique types only, then stratified so short function words cannot crowd
    out the long / punctuated tokens that actually stress layout.
    """
    quotas = quotas or STRATUM_QUOTAS
    buckets: dict[str, list[str]] = defaultdict(list)
    for tok in collect_unique_tokens(ebooks_dir):
        buckets[classify_stratum(tok)].append(tok)
    picked: list[tuple[str, str]] = []
    used: set[str] = set()
    for stratum in STRATUM_ORDER:
        pool = [t for t in buckets.get(stratum, []) if t not in used]
        rng.shuffle(pool)
        take = pool[: quotas.get(stratum, 0)]
        for tok in take:
            used.add(tok)
            picked.append((tok, stratum))
    return picked


def write_case_images(out_dir: str, case: CaseResult) -> tuple[str, str]:
    th = ticks_theme()
    ticks_img = render.word_frame(case.word, th, word_size=case.word_size)
    bold_img = render.word_frame(case.word, bold_theme(), word_size=case.word_size)
    plain = scale_nearest(to_rgb_oled(ticks_img))
    ann = scale_nearest(annotate(ticks_img, bold_img, case.tick_cols))
    plain_name = f"{case.slug}.png"
    ann_name = f"{case.slug}_ann.png"
    plain.save(os.path.join(out_dir, plain_name))
    ann.save(os.path.join(out_dir, ann_name))
    return plain_name, ann_name


def case_to_record(case: CaseResult) -> dict:
    return {
        "word": case.word,
        "word_size": case.word_size,
        "total": case.total,
        "fit_size": case.fit_size,
        "two_line": case.two_line,
        "overlap_px": case.overlap_px,
        "tick_cols": sorted(case.tick_cols),
        "note": case.note,
        "plain": case.plain,
        "ann": case.ann,
    }


def case_from_record(d: dict) -> CaseResult:
    return CaseResult(
        word=d["word"],
        word_size=d["word_size"],
        total=float(d.get("total", 0)),
        fit_size=d.get("fit_size"),
        two_line=bool(d.get("two_line", False)),
        overlap_px=int(d.get("overlap_px", 0)),
        tick_cols=set(d.get("tick_cols") or []),
        note=d.get("note") or "",
        plain=d.get("plain") or "",
        ann=d.get("ann") or "",
    )


def load_jsonl(path: str) -> list[CaseResult]:
    cases: list[CaseResult] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cases.append(case_from_record(json.loads(line)))
    return cases


def save_jsonl(path: str, cases: list[CaseResult]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for case in cases:
            f.write(json.dumps(case_to_record(case), ensure_ascii=False) + "\n")


def parse_seen_words(html_text: str) -> set[str]:
    return {html.unescape(m) for m in re.findall(r"<code>(.*?)</code>", html_text)}


def parse_seeds(html_text: str) -> list[int]:
    m = re.search(r"Seeds?:\s*([^.<]+)", html_text)
    if not m:
        return []
    seeds: list[int] = []
    for part in m.group(1).split(","):
        part = part.strip()
        if part.lstrip("-").isdigit():
            seeds.append(int(part))
    return seeds


def _parse_meta(meta: str) -> dict:
    total_m = re.search(r"total=([\d.]+)px", meta)
    fit_m = re.search(r"fit_size=(None|\d+)", meta)
    ov_m = re.search(r"overlap_px=(\d+)", meta)
    cols_m = re.search(r"tick_cols=\[([^\]]*)\]", meta)
    note_m = re.search(r"tick_cols=\[[^\]]*\](?:\s*·\s*(.*))?", meta)
    tick_cols: set[int] = set()
    if cols_m and cols_m.group(1).strip():
        tick_cols = {int(x.strip()) for x in cols_m.group(1).split(",") if x.strip()}
    fit: int | None = None
    if fit_m and fit_m.group(1) != "None":
        fit = int(fit_m.group(1))
    return {
        "total": float(total_m.group(1)) if total_m else 0.0,
        "fit_size": fit,
        "overlap_px": int(ov_m.group(1)) if ov_m else 0,
        "tick_cols": tick_cols,
        "note": (note_m.group(1) or "").strip() if note_m else "",
    }


def parse_html_cases(html_text: str) -> list[CaseResult]:
    """Seed stored cases from a pre-jsonl index.html."""
    cases: list[CaseResult] = []
    for cls, body in re.findall(
        r"<section class='case([^']*)'>(.*?)</section>", html_text, re.DOTALL
    ):
        word_m = re.search(r"<code>(.*?)</code>", body)
        size_m = re.search(r"</code>\s*\(([^)]+)\)", body)
        if not word_m or not size_m:
            continue
        imgs = re.findall(r"<img src='([^']+)'", body)
        meta_m = re.search(r"<p class='meta'>(.*?)</p>", body, re.DOTALL)
        meta = _parse_meta(meta_m.group(1) if meta_m else "")
        classes = set(cls.split())
        two_line = "twoline" in classes
        overlap_px = meta["overlap_px"]
        if overlap_px == 0 and "overlap" in classes:
            overlap_px = 1
        cases.append(CaseResult(
            word=html.unescape(word_m.group(1)),
            word_size=size_m.group(1).strip(),
            total=meta["total"],
            fit_size=meta["fit_size"],
            two_line=two_line,
            overlap_px=overlap_px,
            tick_cols=meta["tick_cols"],
            note=html.unescape(meta["note"]),
            plain=imgs[0] if imgs else "",
            ann=imgs[1] if len(imgs) > 1 else "",
        ))
    return cases


def load_existing(out_dir: str) -> tuple[list[CaseResult], list[int]]:
    """Load prior cases and seeds; seed jsonl from HTML on first append."""
    jsonl_path = os.path.join(out_dir, JSONL_NAME)
    index_path = os.path.join(out_dir, "index.html")
    html_text = ""
    if os.path.isfile(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            html_text = f.read()
    seeds = parse_seeds(html_text) if html_text else []
    if os.path.isfile(jsonl_path):
        return load_jsonl(jsonl_path), seeds
    if html_text:
        cases = parse_html_cases(html_text)
        if cases:
            save_jsonl(jsonl_path, cases)
        return cases, seeds
    return [], seeds


def seen_tokens(out_dir: str, existing: list[CaseResult] | None = None) -> set[str]:
    """Tokens already in the report. Dedup is by word, not word+size."""
    if existing is not None:
        return {c.word for c in existing}
    jsonl_path = os.path.join(out_dir, JSONL_NAME)
    if os.path.isfile(jsonl_path):
        return {c.word for c in load_jsonl(jsonl_path)}
    index_path = os.path.join(out_dir, "index.html")
    if os.path.isfile(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return parse_seen_words(f.read())
    return set()


def _format_seeds(seeds: list[int]) -> str:
    return ", ".join(str(s) for s in seeds) if seeds else "n/a"


def _section_html(case: CaseResult) -> str:
    plain = case.plain or f"{case.slug}.png"
    ann = case.ann or f"{case.slug}_ann.png"
    return (
        f"<section class='case {'overlap' if case.overlaps else ''} "
        f"{'twoline' if case.two_line else ''}'>"
        f"<h2>{html.escape(case.label)} — "
        f"<code>{html.escape(case.word)}</code> "
        f"({html.escape(case.word_size)})</h2>"
        f"<p class='meta'>total={case.total:.1f}px "
        f"(threshold {render.W - 8}) · fit_size={case.fit_size} · "
        f"overlap_px={case.overlap_px} · tick_cols={sorted(case.tick_cols)}"
        f"{' · ' + html.escape(case.note) if case.note else ''}</p>"
        f"<div class='frames'>"
        f"<figure><img src='{plain}' alt='frame'><figcaption>OLED</figcaption></figure>"
        f"<figure><img src='{ann}' alt='annotated'>"
        f"<figcaption>annotated (yellow=tick band, blue=tick, red=word ink in band)"
        f"</figcaption></figure>"
        f"</div></section>"
    )


def write_flagged_md(out_dir: str, results: list[CaseResult]) -> None:
    blocks = []
    for case in results:
        if not case.flagged:
            continue
        plain = case.plain or f"{case.slug}.png"
        ann = case.ann or f"{case.slug}_ann.png"
        metrics = f"total={case.total:.1f}px · overlap_px={case.overlap_px}"
        if case.note:
            metrics += f" · {case.note}"
        blocks.append(
            f"## {case.label} — `{case.word}` ({case.word_size})\n"
            f"\n"
            f"{metrics}\n"
            f"\n"
            f"![OLED]({plain})\n"
            f"![annotated]({ann})\n"
        )
    text = "\n".join(blocks)
    if text:
        text += "\n"
    with open(os.path.join(out_dir, "flagged.md"), "w", encoding="utf-8") as f:
        f.write(text)


def write_summary_txt(out_dir: str, results: list[CaseResult],
                      seeds: list[int]) -> None:
    n_two = sum(1 for c in results if c.two_line)
    n_overlap = sum(1 for c in results if c.overlaps)
    n_both = sum(1 for c in results if c.two_line and c.overlaps)
    lines = [
        f"cases={len(results)} two_line={n_two} overlap={n_overlap} "
        f"two_line_and_overlap={n_both}",
        f"threshold_px={render.W - 8} tick_band_y={_TICK_Y0}..{_TICK_Y1} "
        f"seeds={_format_seeds(seeds)}",
        "",
        "OVERLAP cases:",
    ]
    for c in results:
        if c.overlaps:
            lines.append(
                f"  [{c.word_size}] {c.word!r} two_line={c.two_line} "
                f"total={c.total:.1f} overlap_px={c.overlap_px}"
                + (f" ({c.note})" if c.note else "")
            )
    lines.append("")
    lines.append("TWO-LINE cases:")
    for c in results:
        if c.two_line:
            lines.append(
                f"  [{c.word_size}] {c.word!r} total={c.total:.1f} "
                f"overlap_px={c.overlap_px}"
            )
    by_size = Counter(c.word_size for c in results if c.overlaps)
    lines.append("")
    lines.append(f"overlap_by_word_size={dict(by_size)}")
    with open(os.path.join(out_dir, "summary.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def write_index_html(out_dir: str, results: list[CaseResult],
                     seeds: list[int]) -> None:
    n_two = sum(1 for c in results if c.two_line)
    n_overlap = sum(1 for c in results if c.overlaps)
    n_both = sum(1 for c in results if c.two_line and c.overlaps)
    doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Tick overlap simulation</title>
<style>
body {{ font-family: system-ui, sans-serif; background: #111; color: #eee;
       margin: 1.5rem; }}
h1 {{ font-size: 1.4rem; }}
h2 {{ font-size: 1.05rem; margin: 0 0 .3rem; }}
.meta {{ color: #aaa; font-size: .85rem; margin: 0 0 .6rem; }}
.summary {{ background: #1c1c1c; padding: 1rem; border-radius: 6px;
            margin-bottom: 1.5rem; }}
.case {{ border-top: 1px solid #333; padding: 1rem 0; }}
.case.overlap {{ background: #2a1212; margin: 0 -1rem; padding: 1rem; }}
.frames {{ display: flex; gap: 1.5rem; flex-wrap: wrap; }}
figure {{ margin: 0; }}
img {{ image-rendering: pixelated; border: 1px solid #444; }}
figcaption {{ font-size: .75rem; color: #888; margin-top: .3rem; }}
code {{ color: #9cf; }}
</style></head><body>
<h1>Upper-tick overlap simulation</h1>
<div class="summary">
<p>Panel {render.W}×{render.H}, upper tick band y={_TICK_Y0}–{_TICK_Y1},
two-line threshold = {render.W - 8}px. Theme: night + ticks.
Seeds: {_format_seeds(seeds)}.</p>
<p><b>{len(results)}</b> cases · <b>{n_two}</b> two-line ·
<b>{n_overlap}</b> with word ink in tick band ·
<b>{n_both}</b> two-line <i>and</i> overlap.</p>
<p>Red pixels in the annotated view are the bug: word glyphs sharing the
upper tick band. Blue is the tick itself. Yellow tints the band.</p>
</div>
{"".join(_section_html(c) for c in results)}
</body></html>
"""
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(doc)


def write_reports(out_dir: str, results: list[CaseResult],
                  seeds: list[int]) -> None:
    """Rebuild index, summary, flagged.md, and jsonl from the full result list."""
    save_jsonl(os.path.join(out_dir, JSONL_NAME), results)
    write_index_html(out_dir, results, seeds)
    write_summary_txt(out_dir, results, seeds)
    write_flagged_md(out_dir, results)


def write_report(out_dir: str, results: list[CaseResult],
                 seed: int | None = None) -> None:
    """Write PNGs for ``results`` and rebuild reports (no wipe)."""
    os.makedirs(out_dir, exist_ok=True)
    for case in results:
        if not case.plain or not case.ann:
            case.plain, case.ann = write_case_images(out_dir, case)
    seeds = [seed] if seed is not None else []
    write_reports(out_dir, results, seeds)


def run(out_dir: str, ebooks_dir: str = DEFAULT_EBOOKS,
        seed: int | None = None, reset: bool = False) -> list[CaseResult]:
    if not os.path.isdir(ebooks_dir):
        raise FileNotFoundError(f"ebooks dir not found: {ebooks_dir}")
    if seed is None:
        seed = secrets.randbits(32)
    if reset and os.path.isdir(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    existing, seeds = load_existing(out_dir)
    seen = seen_tokens(out_dir, existing)
    corpus = sample_ebook_tokens(ebooks_dir, random.Random(seed))
    if not corpus:
        raise RuntimeError(f"no tokens found under {ebooks_dir}")
    n_sampled = len(corpus)
    fresh = [(w, s) for w, s in corpus if w not in seen]
    n_skipped = n_sampled - len(fresh)
    print(f"sampled={n_sampled} skipped={n_skipped} added={len(fresh)}")

    new_results: list[CaseResult] = []
    for word, stratum in fresh:
        for ws in WORD_SIZES:
            case = analyze(word, ws, note=f"ebook {stratum}")
            case.plain, case.ann = write_case_images(out_dir, case)
            new_results.append(case)

    combined = existing + new_results
    if seed not in seeds:
        seeds.append(seed)
    write_reports(out_dir, combined, seeds)
    return combined


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Simulate upper-tick / long-word overlap and write a visual report."
    )
    parser.add_argument(
        "--out", default=DEFAULT_OUT,
        help=f"report directory (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--ebooks", default=DEFAULT_EBOOKS,
        help=f"library to sample tokens from (default: {DEFAULT_EBOOKS})",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="sample seed (default: a fresh random seed each run)",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="wipe the report directory and start a fresh run (default: append)",
    )
    args = parser.parse_args(argv)
    results = run(args.out, ebooks_dir=args.ebooks, seed=args.seed,
                  reset=args.reset)
    n_overlap = sum(1 for c in results if c.overlaps)
    n_two = sum(1 for c in results if c.two_line)
    print(f"wrote {args.out}/index.html")
    print(f"  cases={len(results)} two_line={n_two} overlap={n_overlap}")
    print(f"  open file://{os.path.abspath(os.path.join(args.out, 'index.html'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
