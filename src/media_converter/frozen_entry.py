"""Windowed distribution entry. Diagnostic modes always write an explicit report file."""

import os
import sys


def main():
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    if sys.argv[1:2] == ["--package-smoke"]:
        from media_converter.devtools.package_probe import main as probe

        return probe(sys.argv[2:])
    if sys.argv[1:2] == ["--devtools"]:
        from media_converter.devtools.__main__ import main as devtools

        return devtools(sys.argv[2:])
    from media_converter.__main__ import main as gui

    return gui()


if __name__ == "__main__":
    raise SystemExit(main())
