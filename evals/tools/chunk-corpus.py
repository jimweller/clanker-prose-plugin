#!/usr/bin/env python3
"""Turns cached Confluence bodies into word-budgeted prose chunks.

Paragraph boundaries survive, because the rhythm bullets need them. Headings,
tables, code, and short structural blocks are dropped, because the contract
exempts them and they waste judge tokens.

Chunks land in corpus/chunks/, which is gitignored.

Usage
    tools/chunk-corpus.py [--source raw] [--budget 700] [--min-words 60]
"""

import argparse
import html
import json
import pathlib
import re
import sys

EVAL_ROOT = pathlib.Path(__file__).resolve().parent.parent
CORPUS = EVAL_ROOT / "corpus"

TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"[ \t]+")
# Paragraphs only. Splitting on </li>, </td> and </h*> let every list item and
# table cell past twelve words through as a "paragraph", which is 8 percent of
# the corpus and is structured content rather than prose.
BLOCK = re.compile(r"</p>")
STRUCTURAL = re.compile(r"<(?:table|ac:structured-macro|pre|code)\b", re.I)


def blocks(body: str):
    """Prose paragraphs only, in document order."""
    for raw in BLOCK.split(body):
        if STRUCTURAL.search(raw):
            continue
        text = html.unescape(WS.sub(" ", TAG.sub(" ", raw))).strip()
        if not text:
            continue
        words = text.split()
        # A prose paragraph runs past a headline and carries a finished sentence.
        if len(words) < 12 or not re.search(r"[.!?]\s|[.!?]$", text):
            continue
        yield text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="raw", help="corpus subdirectory to chunk")
    parser.add_argument("--budget", type=int, default=700, help="target words per chunk")
    parser.add_argument("--min-words", type=int, default=60, help="drop chunks below this")
    args = parser.parse_args()

    src = CORPUS / args.source
    if not src.exists():
        print(f"no such corpus directory, {src}", file=sys.stderr)
        return 1

    out_dir = CORPUS / "chunks" / args.source
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.txt"):
        stale.unlink()

    pages = chunks = total_words = 0
    for path in sorted(src.glob("*.json")):
        try:
            page = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        body = page.get("body", {}).get("storage", {}).get("value", "")
        if not body:
            continue
        pages += 1

        buf, count, index = [], 0, 0
        def flush():
            nonlocal buf, count, index, chunks, total_words
            if count >= args.min_words:
                (out_dir / f"{path.stem}-{index:03d}.txt").write_text("\n\n".join(buf))
                chunks += 1
                total_words += count
                index += 1
            buf, count = [], 0

        for para in blocks(body):
            words = len(para.split())
            if count and count + words > args.budget:
                flush()
            buf.append(para)
            count += words
        flush()

    print(f"source {args.source}, {pages} pages to {chunks} chunks, {total_words} prose words")
    print(f"wrote {out_dir.relative_to(EVAL_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
