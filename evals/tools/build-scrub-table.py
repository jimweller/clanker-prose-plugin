#!/usr/bin/env python3
"""Derives a scrub table from the mined corpus and known repo sources.

The table maps a proprietary term to a neutral stand-in. It is written to
corpus/scrub-table.json, which is gitignored, because the table is itself an
inventory of proprietary terms. Publishing it would publish what it hides.

Seeds come from real sources rather than guesses. ADO org and project names are
read out of configs/git/gitconfig-work. Everything else is mined from the corpus
by frequency and needs human review before use.

Usage
    tools/build-scrub-table.py [--min-count N]
"""

import argparse
import collections
import html
import json
import pathlib
import re
import sys

EVAL_ROOT = pathlib.Path(__file__).resolve().parent.parent
CORPUS = EVAL_ROOT / "corpus"
RAW = CORPUS / "raw"
GITCONFIG_WORK = pathlib.Path.home() / ".config/dotfiles/configs/git/gitconfig-work"

TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"\s+")

# Stand-in pools. Each is obviously fictional and grammatically interchangeable
# with what it replaces, so a scrubbed sentence keeps the shape the catalog
# bullet is meant to test.
PRODUCT_POOL = [
    "Alder", "Basalt", "Cinder", "Dovetail", "Ember", "Ferro", "Gantry",
    "Halyard", "Ingot", "Jetty", "Kiln", "Lintel", "Mullion", "Newel",
    "Oriel", "Purlin", "Quoin", "Rafter", "Soffit", "Transom", "Ulmus",
    "Verge", "Wainscot", "Xystus", "Yoke", "Zinc",
]
PERSON_POOL = [
    "Jordan Blake", "Casey Ruiz", "Morgan Tate", "Riley Chen", "Avery Solis",
    "Quinn Harper", "Rowan Diaz", "Sawyer Ellis", "Emerson Kade", "Finley Moss",
]

# Always replaced by pattern, no table entry needed.
PATTERN_RULES = [
    (re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d{1,6}\b"), "PROJ-000"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "name@example.com"),
    (re.compile(r"https?://[^\s\"'<>)]+"), "https://example.internal/path"),
    (re.compile(r"\b\d{12}\b"), "000000000000"),
    (re.compile(r"\b(?:10|172|192)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "10.0.0.1"),
]

# Terms that are public technology, never scrubbed.
PUBLIC_TECH = {
    "Azure", "AWS", "GitHub", "Kubernetes", "Postgres", "PostgreSQL", "Docker",
    "Terraform", "Python", "TypeScript", "JavaScript", "React", "Node", "Linux",
    "Windows", "macOS", "SonarQube", "Confluence", "Jira", "Slack", "Turborepo",
    "GraphQL", "REST", "JSON", "YAML", "SQL", "HTTP", "HTTPS", "TLS", "SSH",
    "DevOps", "CI", "CD", "API", "SDK", "CLI", "UI", "UX", "VM", "VMSS", "DNS",
    "Service Bus", "Synapse Analytics", "Microsoft", "Google", "Amazon",
    "OpenAI", "Anthropic", "Claude", "FHIR", "OCR", "PDF", "CSV", "HTML",
}


def read_seed_terms() -> set[str]:
    """ADO org and project names out of the tracked gitconfig."""
    if not GITCONFIG_WORK.exists():
        print(f"warning, {GITCONFIG_WORK} missing, no seed terms", file=sys.stderr)
        return set()
    text = GITCONFIG_WORK.read_text()
    terms = set()
    for org, project in re.findall(r"dev\.azure\.com/([^/\"]+)/([^/\"\s]+)", text):
        terms.add(org)
        terms.add(project.replace("%20", " "))
    for host in re.findall(r"([A-Za-z0-9-]+)@vs-ssh\.visualstudio\.com", text):
        terms.add(host)
    return {t for t in terms if t and t not in PUBLIC_TECH}


def corpus_text():
    for path in sorted(RAW.glob("*.json")):
        try:
            page = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        body = page.get("body", {}).get("storage", {}).get("value", "")
        title = page.get("title", "")
        if body:
            yield title + "\n" + html.unescape(WS.sub(" ", TAG.sub(" ", body)))


def mine_candidates(min_count: int):
    """Acronyms and TitleCase phrases that repeat often enough to be names."""
    acronyms = collections.Counter()
    phrases = collections.Counter()
    acro_re = re.compile(r"\b[A-Z][A-Z0-9]{1,7}(?:-[A-Z0-9]{1,4})?\b")
    phrase_re = re.compile(r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){0,2}\b")

    for text in corpus_text():
        for match in acro_re.findall(text):
            if match not in PUBLIC_TECH:
                acronyms[match] += 1
        for match in phrase_re.findall(text):
            if match not in PUBLIC_TECH and not match.startswith(("The ", "This ", "That ")):
                phrases[match] += 1

    return (
        {t: c for t, c in acronyms.items() if c >= min_count},
        {t: c for t, c in phrases.items() if c >= min_count},
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-count", type=int, default=8)
    args = parser.parse_args()

    if not RAW.exists():
        print("no corpus, run tools/mine-confluence.sh first", file=sys.stderr)
        return 1

    seeds = read_seed_terms()
    acronyms, phrases = mine_candidates(args.min_count)

    table, used = {}, 0
    for term in sorted(seeds | set(acronyms) | set(phrases),
                       key=lambda t: -len(t)):  # longest first so substitution nests correctly
        table[term] = {
            "replacement": PRODUCT_POOL[used % len(PRODUCT_POOL)],
            "source": "seed" if term in seeds else "mined",
            "count": acronyms.get(term) or phrases.get(term) or 0,
            "approved": term in seeds,
        }
        used += 1

    CORPUS.mkdir(exist_ok=True)
    out = CORPUS / "scrub-table.json"
    out.write_text(json.dumps({
        "person_pool": PERSON_POOL,
        "public_tech": sorted(PUBLIC_TECH),
        "terms": table,
    }, indent=2))

    approved = sum(1 for v in table.values() if v["approved"])
    print(f"wrote {out.relative_to(EVAL_ROOT)}")
    print(f"  {len(table)} terms, {approved} seeded and pre-approved, "
          f"{len(table) - approved} mined and awaiting review")
    print(f"  seeds from {GITCONFIG_WORK.name}, mined at min-count {args.min_count}")
    print()
    print("Every mined term defaults to approved=false. Nothing scrubs against an")
    print("unapproved term, and tools/scrub.py drops any candidate whose text still")
    print("matches one after substitution.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
