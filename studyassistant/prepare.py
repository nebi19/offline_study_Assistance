"""Write the unit summaries ahead of time: ``python -m studyassistant.prepare``.

A summary takes a few minutes to write on a CPU, so setup does it once for
every unit. Students then open summaries instantly. Units that already have
a summary are skipped; ``--force`` writes them again.
"""

from __future__ import annotations

import argparse
import sys
import time

from .app import load_assistant
from .assistant import GenerationFailed
from .config import get_settings
from .llm import ModelUnavailable


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="rewrite summaries that already exist")
    parser.add_argument("units", nargs="*", help="unit ids (default: every unit)")
    args = parser.parse_args(argv)

    assistant = load_assistant(get_settings())
    languages = ["en"] + (["am"] if assistant.translator else [])
    failed = 0
    for unit_id in args.units or list(assistant.index.units):
        # Rewriting the Amharic summary rewrites the English one it is translated from.
        for language in languages[-1:] if args.force else languages:
            started = time.time()
            try:
                assistant.summary(unit_id, language, refresh=args.force)
            except GenerationFailed as exc:
                failed += 1
                print(f"- {unit_id} [{language}]: failed ({exc})")
            except ModelUnavailable as exc:
                print(f"Cannot reach the AI model: {exc}", file=sys.stderr)
                return 1
            else:
                print(f"- {unit_id} [{language}]: ready ({time.time() - started:.0f}s)", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
