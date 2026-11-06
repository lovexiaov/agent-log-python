"""Hand-rolled JSON serializer and parser (standard library only).

The *production* wire format MUST be produced by :func:`dumps` so that we keep
full control over escaping and guarantee a closed top-level key set. The
*parser* :func:`loads` is provided for :class:`LoggingConfig` parsing and for
any test-side parsing needs; tests may also use :mod:`json` for convenience.
"""

import re


# --------------------------------------------------------------------------- #
# Serializer
# --------------------------------------------------------------------------- #
def _dump_str(s: str) -> str:
    out = ['"']
    for ch in s:
        o = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\b":
            out.append("\\b")
        elif ch == "\f":
            out.append("\\f")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif o < 0x20:
            out.append("\\u%04x" % o)
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _dump_float(f: float) -> str:
    if f != f:  # nan
        raise ValueError("cannot serialize NaN")
    if f in (float("inf"), float("-inf")):
        raise ValueError("cannot serialize infinity")
    # Produce a compact, JSON-valid representation.
    if f == int(f) and abs(f) < 1e16:
        return repr(f)
    return repr(f)


def dumps(obj) -> str:
    """Serialize ``obj`` to a JSON string with controlled escaping."""
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, float):
        return _dump_float(obj)
    if isinstance(obj, str):
        return _dump_str(obj)
    if isinstance(obj, dict):
        return "{" + ",".join(_dump_str(str(k)) + ":" + dumps(v) for k, v in obj.items()) + "}"
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(dumps(v) for v in obj) + "]"
    # Best-effort fallback (e.g. None already handled).
    return _dump_str(str(obj))


# --------------------------------------------------------------------------- #
# Parser (minimal, recursive descent)
# --------------------------------------------------------------------------- #
_TOKEN_RE = re.compile(r"\s*(\{|\}|\[|\]|,|:|true|false|null|\"(?:[^\"\\]|\\.)*\"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\S)")


class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.n = len(text)

    def _peek(self):
        return self.text[self.pos] if self.pos < self.n else None

    def _skip_ws(self):
        while self.pos < self.n and self.text[self.pos] in " \t\r\n":
            self.pos += 1

    def parse(self):
        self._skip_ws()
        val = self._parse_value()
        self._skip_ws()
        if self.pos != self.n:
            raise ValueError("trailing characters at %d: %r" % (self.pos, self.text[self.pos:]))
        return val

    def _parse_value(self):
        c = self._peek()
        if c is None:
            raise ValueError("unexpected end of input")
        if c == "{":
            return self._parse_object()
        if c == "[":
            return self._parse_array()
        if c == '"':
            return self._parse_string()
        if c == "t" or c == "f":
            return self._parse_bool()
        if c == "n":
            return self._parse_null()
        if c == "-" or c.isdigit():
            return self._parse_number()
        raise ValueError("unexpected character %r at %d" % (c, self.pos))

    def _parse_object(self):
        self.pos += 1  # consume {
        obj = {}
        self._skip_ws()
        if self._peek() == "}":
            self.pos += 1
            return obj
        while True:
            self._skip_ws()
            if self._peek() != '"':
                raise ValueError("expected string key at %d" % self.pos)
            key = self._parse_string()
            self._skip_ws()
            if self._peek() != ":":
                raise ValueError("expected ':' at %d" % self.pos)
            self.pos += 1
            self._skip_ws()
            val = self._parse_value()
            obj[key] = val
            self._skip_ws()
            c = self._peek()
            if c == ",":
                self.pos += 1
                continue
            if c == "}":
                self.pos += 1
                return obj
            raise ValueError("expected ',' or '}' at %d" % self.pos)

    def _parse_array(self):
        self.pos += 1  # consume [
        arr = []
        self._skip_ws()
        if self._peek() == "]":
            self.pos += 1
            return arr
        while True:
            self._skip_ws()
            arr.append(self._parse_value())
            self._skip_ws()
            c = self._peek()
            if c == ",":
                self.pos += 1
                continue
            if c == "]":
                self.pos += 1
                return arr
            raise ValueError("expected ',' or ']' at %d" % self.pos)

    def _parse_string(self):
        # self._peek() == '"'
        self.pos += 1
        buf = []
        while self.pos < self.n:
            ch = self.text[self.pos]
            if ch == '"':
                self.pos += 1
                return "".join(buf)
            if ch == "\\":
                self.pos += 1
                if self.pos >= self.n:
                    raise ValueError("unterminated escape")
                e = self.text[self.pos]
                self.pos += 1
                if e == '"':
                    buf.append('"')
                elif e == "\\":
                    buf.append("\\")
                elif e == "/":
                    buf.append("/")
                elif e == "b":
                    buf.append("\b")
                elif e == "f":
                    buf.append("\f")
                elif e == "n":
                    buf.append("\n")
                elif e == "r":
                    buf.append("\r")
                elif e == "t":
                    buf.append("\t")
                elif e == "u":
                    hex4 = self.text[self.pos:self.pos + 4]
                    if len(hex4) != 4:
                        raise ValueError("bad \\u escape")
                    buf.append(chr(int(hex4, 16)))
                    self.pos += 4
                else:
                    raise ValueError("bad escape \\%s" % e)
            else:
                buf.append(ch)
                self.pos += 1
        raise ValueError("unterminated string")

    def _parse_bool(self):
        if self.text.startswith("true", self.pos):
            self.pos += 4
            return True
        if self.text.startswith("false", self.pos):
            self.pos += 5
            return False
        raise ValueError("invalid literal at %d" % self.pos)

    def _parse_null(self):
        if self.text.startswith("null", self.pos):
            self.pos += 4
            return None
        raise ValueError("invalid literal at %d" % self.pos)

    def _parse_number(self):
        m = re.match(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?", self.text[self.pos:])
        if not m:
            raise ValueError("invalid number at %d" % self.pos)
        tok = m.group(0)
        self.pos += len(tok)
        if "." in tok or "e" in tok or "E" in tok:
            return float(tok)
        return int(tok)


def loads(text: str):
    """Parse a JSON document into Python objects (hand-rolled)."""
    return _Parser(text).parse()
