#!/usr/bin/env python3
"""Substitutes mustache variables in a prompt template and prints the result.

A file rather than an inline heredoc, because a multi-line python string nested
inside a shell command substitution has already failed silently once in this
directory.

Takes one or more VAR/FILE pairs, because the compliance judge needs both the
catalog and the passage in one prompt.

--set VAR=VALUE substitutes a literal instead of a file's contents, for a value that
is a path the model should write to rather than a file it should read.

Substitution runs against the template only, never against already-substituted
text, so a passage containing a literal {{catalog}} cannot inject the contract.

Usage
    tools/render-template.py TEMPLATE_PATH [--set VAR=VALUE]... (VAR_NAME TEXT_FILE)...
"""

import pathlib
import re
import sys

argv = sys.argv[1:]
literals = {}
args = []
i = 0
while i < len(argv):
    if argv[i] == "--set":
        if i + 1 >= len(argv) or "=" not in argv[i + 1]:
            print(__doc__, file=sys.stderr)
            raise SystemExit(2)
        name, _, value = argv[i + 1].partition("=")
        literals[name] = value
        i += 2
    else:
        args.append(argv[i])
        i += 1

if len(args) < 1 or len(args) % 2 == 0:
    print(__doc__, file=sys.stderr)
    raise SystemExit(2)

template = pathlib.Path(args[0]).read_text()
values = dict(literals)
values.update({
    args[i]: pathlib.Path(args[i + 1]).read_text()
    for i in range(1, len(args), 2)
})

missing = [k for k in values if "{{" + k + "}}" not in template]
if missing:
    print(f"template has no placeholder for {', '.join(missing)}", file=sys.stderr)
    raise SystemExit(2)

sys.stdout.write(
    re.sub(
        r"\{\{(\w+)\}\}",
        lambda m: values.get(m.group(1), m.group(0)),
        template,
    )
)
