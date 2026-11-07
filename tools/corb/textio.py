"""MT5 writes some text files (presets, origin.txt, journals) as UTF-16 with a BOM and others as UTF-8 / ANSI."""


def read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    return raw.decode("utf-8-sig", errors="replace")
