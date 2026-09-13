#!/usr/bin/env bash
# Download the books.md list into ebooks/ (plain text / epub) and
# to_convert/ (PDFs), then run pdf_to_txt.py and txt_to_txt.py.
#
# Usage:
#   tools/books.sh                 # tools/books.md → ebooks/ + to_convert/
#   tools/books.sh path/to/list.md
#
# Gutenberg .txt (or .epub when no text exists) lands in ebooks/.
# Archive.org items, Gutenberg scan PDFs, and URLs that end in .pdf land
# in to_convert/, then pdf_to_txt.py writes ebooks/.
# Landing-page HTML (SRE book, OSTEP, …) is listed and skipped.
# txt_to_txt.py runs with --no-backup so <file>.orig copies are not created.
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
INPUT_FILE=${1:-"$HERE/tools/books.md"}
EBOOKS_DIR=$HERE/ebooks
PDF_DIR=$HERE/to_convert
SLEEP_SECS=2
UA="RapidReader-books/1.0 (personal offline library; +https://github.com)"

log() { printf '%s\n' "$*"; }
die() { echo "error: $*" >&2; exit 1; }

[[ -f $INPUT_FILE ]] || die "could not find $INPUT_FILE"
command -v curl >/dev/null || die "curl is required"
command -v python3 >/dev/null || die "python3 is required"

mkdir -p "$EBOOKS_DIR" "$PDF_DIR"

ok_txt=0
ok_pdf=0
ok_epub=0
skipped_exist=0
skipped_html=0
failed=0
SKIP_HTML=()
FAIL_LIST=()

# Unwrap Google wrappers and classify. Prints "kind<TAB>payload".
# kind is gutenberg, pdf, txt, archive, html.
classify_url() {
    python3 - "$1" <<'PY'
import sys, urllib.parse
url = sys.argv[1].strip()
parsed = urllib.parse.urlparse(url)
host = parsed.netloc.lower()
if "google." in host and parsed.path.startswith("/search"):
    q = urllib.parse.parse_qs(parsed.query).get("q", [""])[0]
    if q.startswith("http"):
        url = q
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc.lower()
low = url.lower()
if "gutenberg.org" in host:
    print("gutenberg\t" + url)
    raise SystemExit(0)
if low.endswith(".pdf") or ".pdf?" in low or ".pdf#" in low:
    print("pdf\t" + url)
    raise SystemExit(0)
if low.endswith(".txt") or ".txt?" in low:
    print("txt\t" + url)
    raise SystemExit(0)
if "archive.org" in host:
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parts[0] in ("details", "download", "stream"):
        print("archive\t" + parts[1])
        raise SystemExit(0)
print("html\t" + url)
PY
}

# Pick a file on an Archive.org item, or search by title if the id is gone.
# Prints "pdf|txt<TAB>url" on success.
archive_file() {
    local ident=$1 title=$2
    python3 - "$ident" "$title" "$UA" <<'PY'
import json, sys, urllib.error, urllib.parse, urllib.request

ident, title, ua = sys.argv[1], sys.argv[2], sys.argv[3]

def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def pick_from_files(ident, files):
    def pdf_score(f):
        name = (f.get("name") or "").lower()
        fmt = (f.get("format") or "").lower()
        if not name.endswith(".pdf"):
            return -1
        if any(x in name for x in ("thumb", "cover", "_bw.pdf", "sample")):
            return 0
        try:
            size = int(f.get("size") or 0)
        except ValueError:
            size = 0
        score = 10
        if fmt == "text pdf" or name.endswith("_text.pdf"):
            score = 100
        elif "pdf" in fmt:
            score = 50
        return score * 10**12 + size

    best = max(files, key=pdf_score, default=None)
    if best and pdf_score(best) > 0:
        quoted = urllib.parse.quote(best["name"], safe="/")
        print(f"pdf\thttps://archive.org/download/{ident}/{quoted}")
        return True

    def txt_score(f):
        name = (f.get("name") or "").lower()
        if name.endswith("_djvu.txt") or name.endswith(".djvu.txt"):
            return 20
        if name.endswith(".txt") and not name.endswith("_meta.txt"):
            return 10
        return -1

    best = max(files, key=txt_score, default=None)
    if best and txt_score(best) > 0:
        quoted = urllib.parse.quote(best["name"], safe="/")
        print(f"txt\thttps://archive.org/download/{ident}/{quoted}")
        return True
    return False

def files_for(ident):
    try:
        meta = get_json(f"https://archive.org/metadata/{ident}")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return []
    if not isinstance(meta, dict):
        return []
    return meta.get("files") or []

candidates = [ident]
if ident.endswith("goog"):
    candidates.append(ident[:-4].rstrip("._-"))

for cand in candidates:
    files = files_for(cand)
    if pick_from_files(cand, files):
        raise SystemExit(0)

search = (
    "https://archive.org/advancedsearch.php?"
    + urllib.parse.urlencode({
        "q": f'title:("{title}") AND mediatype:texts',
        "output": "json",
        "rows": "5",
    })
    + "&fl[]=identifier"
)
try:
    data = get_json(search)
    docs = (data.get("response") or {}).get("docs") or []
except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, AttributeError):
    docs = []
seen = set(candidates)
for doc in docs:
    alt = doc.get("identifier") or ""
    if not alt or alt in seen:
        continue
    seen.add(alt)
    files = files_for(alt)
    if pick_from_files(alt, files):
        raise SystemExit(0)

raise SystemExit(1)
PY
}

gutenberg_id() {
    python3 -c 'import re,sys; m=re.search(r"gutenberg\.org/ebooks/(\d+)", sys.argv[1]); print(m.group(1) if m else "")' "$1"
}

# Find a Gutenberg download. Prints "txt|epub|pdf<TAB>url".
gutenberg_file() {
    local id=$1
    python3 - "$id" "$UA" <<'PY'
import re, sys, urllib.error, urllib.request

book_id, ua = sys.argv[1], sys.argv[2]

def listing_hrefs(url):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read()
    except (urllib.error.URLError, TimeoutError):
        return []
    return [h.decode("ascii", "replace") for h in re.findall(rb'href="([^"]+)"', body)]

hrefs = listing_hrefs(f"https://www.gutenberg.org/cache/epub/{book_id}/")
for name in hrefs:
    if name == f"pg{book_id}.txt" or name.endswith(".txt"):
        print(f"txt\thttps://www.gutenberg.org/cache/epub/{book_id}/{name}")
        raise SystemExit(0)
for name in (f"pg{book_id}.epub", f"pg{book_id}-images.epub"):
    if name in hrefs:
        print(f"epub\thttps://www.gutenberg.org/cache/epub/{book_id}/{name}")
        raise SystemExit(0)
for name in hrefs:
    if name.endswith(".epub"):
        print(f"epub\thttps://www.gutenberg.org/cache/epub/{book_id}/{name}")
        raise SystemExit(0)

hrefs = listing_hrefs(f"https://www.gutenberg.org/files/{book_id}/")
for name in hrefs:
    if name.endswith("-0.txt") or name.endswith("-8.txt") or name == f"{book_id}.txt":
        print(f"txt\thttps://www.gutenberg.org/files/{book_id}/{name}")
        raise SystemExit(0)
for name in hrefs:
    if name.endswith(".pdf"):
        print(f"pdf\thttps://www.gutenberg.org/files/{book_id}/{name}")
        raise SystemExit(0)

raise SystemExit(1)
PY
}

safe_title() {
    local s
    s=$(printf '%s' "$1" | tr -cs 'a-zA-Z0-9' '_')
    s=${s#_}
    s=${s%_}
    printf '%s' "${s:-book}"
}

looks_like_html() {
    local path=$1 head
    head=$(head -c 200 "$path" 2>/dev/null | tr -d '\0' || true)
    [[ $head == *'<!DOCTYPE'* || $head == *'<!doctype'* || $head == *'<html'* ]]
}

fetch() {
    local url=$1 dest=$2 tmp
    tmp=$(mktemp)
    if ! curl -f -L -sS --retry 3 --retry-delay 2 \
            --connect-timeout 30 --max-time 600 \
            -A "$UA" -o "$tmp" "$url"
    then
        rm -f "$tmp"
        return 1
    fi
    if [[ ! -s $tmp ]]; then
        rm -f "$tmp"
        return 1
    fi
    mv "$tmp" "$dest"
}

already_have() {
    local safe=$1 gid=${2:-}
    [[ -s $PDF_DIR/${safe}.pdf ]] && return 0
    # Search the tree: books may live in category subdirs.
    if find "$EBOOKS_DIR" -type f \( -name "${safe}.txt" -o -name "${safe}.epub" \) \
            -size +0c -print -quit 2>/dev/null | grep -q .; then
        return 0
    fi
    if [[ -n $gid ]]; then
        if find "$EBOOKS_DIR" -type f \( -name "${gid}_${safe}.txt" -o -name "${gid}_${safe}.epub" \) \
                -size +0c -print -quit 2>/dev/null | grep -q .; then
            return 0
        fi
        [[ -s $PDF_DIR/${gid}_${safe}.pdf ]] && return 0
    fi
    return 1
}

pause() { sleep "$SLEEP_SECS"; }

log "Reading $INPUT_FILE"
log "Text → $EBOOKS_DIR"
log "PDFs → $PDF_DIR"
log ""

link_re='\[([^]]+)\]\((https?://[^)]+)\)'
while IFS= read -r line || [[ -n $line ]]; do
    [[ $line =~ $link_re ]] || continue
    title=${BASH_REMATCH[1]}
    url=${BASH_REMATCH[2]}
    safe=$(safe_title "$title")

    resolved=$(classify_url "$url")
    kind=${resolved%%$'\t'*}
    src=${resolved#*$'\t'}

    if [[ $kind == archive ]]; then
        if already_have "$safe"; then
            log "skip  $title (already have ${safe})"
            skipped_exist=$((skipped_exist + 1))
            continue
        fi
        picked=$(archive_file "$src" "$title") && [[ -n $picked ]] || {
            log "FAIL  $title (no Archive.org file for $src)"
            FAIL_LIST+=("$title")
            failed=$((failed + 1))
            pause
            continue
        }
        kind=${picked%%$'\t'*}
        src=${picked#*$'\t'}
    fi

    if [[ $kind == gutenberg ]]; then
        gid=$(gutenberg_id "$src")
        if [[ -z $gid ]]; then
            log "FAIL  $title (no Gutenberg id in $src)"
            FAIL_LIST+=("$title")
            failed=$((failed + 1))
            continue
        fi
        if already_have "$safe" "$gid"; then
            log "skip  $title (already have Gutenberg $gid)"
            skipped_exist=$((skipped_exist + 1))
            continue
        fi
        picked=$(gutenberg_file "$gid") && [[ -n $picked ]] || {
            log "FAIL  $title (no Gutenberg file for $gid)"
            FAIL_LIST+=("$title")
            failed=$((failed + 1))
            pause
            continue
        }
        kind=${picked%%$'\t'*}
        src=${picked#*$'\t'}
        case $kind in
            txt) dest="$EBOOKS_DIR/${gid}_${safe}.txt" ;;
            epub) dest="$EBOOKS_DIR/${gid}_${safe}.epub" ;;
            pdf) dest="$PDF_DIR/${gid}_${safe}.pdf" ;;
            *)
                log "FAIL  $title (unexpected Gutenberg kind: $kind)"
                FAIL_LIST+=("$title")
                failed=$((failed + 1))
                pause
                continue
                ;;
        esac
        log "$kind   $title  (Gutenberg $gid)"
        if fetch "$src" "$dest" && ! looks_like_html "$dest"; then
            if [[ $kind == pdf && $(head -c 4 "$dest") != '%PDF' ]]; then
                log "  → not a PDF, discarding"
                rm -f "$dest"
                FAIL_LIST+=("$title")
                failed=$((failed + 1))
            else
                log "  → $dest"
                case $kind in
                    txt) ok_txt=$((ok_txt + 1)) ;;
                    epub) ok_epub=$((ok_epub + 1)) ;;
                    pdf) ok_pdf=$((ok_pdf + 1)) ;;
                esac
            fi
        else
            log "  → failed"
            rm -f "$dest"
            FAIL_LIST+=("$title")
            failed=$((failed + 1))
        fi
        pause
        continue
    fi

    case $kind in
        pdf)
            dest="$PDF_DIR/${safe}.pdf"
            if [[ -s $dest ]]; then
                log "skip  $title (already have $dest)"
                skipped_exist=$((skipped_exist + 1))
                continue
            fi
            log "pdf   $title"
            if fetch "$src" "$dest" && ! looks_like_html "$dest" \
                    && [[ $(head -c 4 "$dest") == '%PDF' ]]; then
                log "  → $dest"
                ok_pdf=$((ok_pdf + 1))
            else
                log "  → failed"
                rm -f "$dest"
                FAIL_LIST+=("$title")
                failed=$((failed + 1))
            fi
            pause
            ;;
        txt)
            dest="$EBOOKS_DIR/${safe}.txt"
            if [[ -s $dest ]]; then
                log "skip  $title (already have $dest)"
                skipped_exist=$((skipped_exist + 1))
                continue
            fi
            log "txt   $title"
            if fetch "$src" "$dest" && ! looks_like_html "$dest"; then
                log "  → $dest"
                ok_txt=$((ok_txt + 1))
            else
                log "  → failed"
                rm -f "$dest"
                FAIL_LIST+=("$title")
                failed=$((failed + 1))
            fi
            pause
            ;;
        html)
            log "skip  $title (HTML landing page, no file URL)"
            SKIP_HTML+=("$title")
            skipped_html=$((skipped_html + 1))
            ;;
        *)
            log "FAIL  $title (unknown kind: ${kind:-empty})"
            FAIL_LIST+=("$title")
            failed=$((failed + 1))
            ;;
    esac
done < "$INPUT_FILE"

log ""
log "Download summary: ${ok_txt} txt, ${ok_epub} epub, ${ok_pdf} pdf, ${skipped_exist} already present, ${skipped_html} HTML skipped, ${failed} failed"

if ((${#SKIP_HTML[@]})); then
    log "HTML landing pages (not downloaded):"
    for t in "${SKIP_HTML[@]}"; do
        log "  - $t"
    done
fi
if ((${#FAIL_LIST[@]})); then
    log "Failed:"
    for t in "${FAIL_LIST[@]}"; do
        log "  - $t"
    done
fi

log ""
need_pdf=()
shopt -s nullglob
for pdf in "$PDF_DIR"/*.pdf; do
    stem=$(basename "$pdf" .pdf)
    if ! find "$EBOOKS_DIR" -type f -name "${stem}.txt" -size +0c -print -quit 2>/dev/null | grep -q .; then
        need_pdf+=("$pdf")
    fi
done
shopt -u nullglob

if ((${#need_pdf[@]})); then
    log "pdf_to_txt.py: ${#need_pdf[@]} PDF(s) → $EBOOKS_DIR"
    for pdf in "${need_pdf[@]}"; do
        if ! python3 "$HERE/tools/pdf_to_txt.py" --out "$EBOOKS_DIR" "$pdf"; then
            log "  convert failed: $pdf"
        fi
    done
else
    log "pdf_to_txt.py: nothing new in $PDF_DIR"
fi

log "txt_to_txt.py: RSVP cleanup of $EBOOKS_DIR (no .orig backups)"
python3 "$HERE/tools/txt_to_txt.py" --no-backup
find "$EBOOKS_DIR" -name '*.orig' -type f -delete

log "Done."
