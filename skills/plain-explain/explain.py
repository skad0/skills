#!/usr/bin/env python3
"""plain-explain: check and render a content model through a lens and a template."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class YamlError(Exception):
    def __init__(self, message: str, line: int | None = None):
        self.line = line
        prefix = f"YAML line {line}: " if line is not None else "YAML: "
        super().__init__(prefix + message)


def _yaml_strip_comment(line: str) -> str:
    out = []
    quote = None
    i = 0
    while i < len(line):
        ch = line[i]
        if quote:
            out.append(ch)
            if ch == "\\" and quote == '"':
                if i + 1 < len(line):
                    out.append(line[i + 1])
                    i += 2
                    continue
            elif ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            continue
        if ch == "#":
            break
        out.append(ch)
        i += 1
    return "".join(out).rstrip()


def _yaml_scalar(raw: str):
    s = raw.strip()
    if s == "" or s == "~" or s == "null":
        return None
    if s == "true":
        return True
    if s == "false":
        return False
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if (s.startswith('"') and s.endswith('"') and len(s) >= 2) or (
        s.startswith("'") and s.endswith("'") and len(s) >= 2
    ):
        if s.startswith('"'):
            return bytes(s[1:-1], "utf-8").decode("unicode_escape")
        return s[1:-1]
    return s


class _YamlParser:
    def __init__(self, text: str):
        raw_lines = text.splitlines()
        self.lines: list[tuple[int, int, str]] = []  # lineno, indent, content
        for n, raw in enumerate(raw_lines, 1):
            if "\t" in raw:
                raise YamlError("tabs are not allowed", n)
            cut = _yaml_strip_comment(raw)
            if cut.strip() == "":
                continue
            indent = len(cut) - len(cut.lstrip(" "))
            self.lines.append((n, indent, cut[indent:]))
        self.i = 0

    def peek(self):
        if self.i >= len(self.lines):
            return None
        return self.lines[self.i]

    def parse_document(self):
        if not self.lines:
            return None
        _, indent, content = self.lines[0]
        if content.startswith("- "):
            return self.parse_list(indent)
        return self.parse_map(indent)

    def parse_map(self, indent: int) -> dict:
        result = {}
        while True:
            peeked = self.peek()
            if peeked is None:
                break
            n, ind, content = peeked
            if ind < indent:
                break
            if ind > indent:
                raise YamlError("unexpected indent", n)
            if content.startswith("- "):
                raise YamlError("list item where a key was expected", n)
            self.i += 1
            key, _, rest = content.partition(":")
            if not _:
                raise YamlError(f"expected 'key:' in {content!r}", n)
            key = key.strip()
            if (key.startswith('"') and key.endswith('"')) or (
                key.startswith("'") and key.endswith("'")
            ):
                key = key[1:-1]
            rest = rest.strip()
            result[key] = self._parse_value_after_key(n, indent, rest)
        return result

    def _parse_value_after_key(self, n: int, indent: int, rest: str):
        if rest in ("|", ">", "|-", ">-", "|+", ">+"):
            style = rest[0]
            return self._parse_block(indent, style)
        if rest != "":
            return _yaml_scalar(rest)
        peeked = self.peek()
        if peeked is None:
            return None
        _, next_ind, next_content = peeked
        if next_ind <= indent:
            return None
        if next_content.startswith("- "):
            return self.parse_list(next_ind)
        return self.parse_map(next_ind)

    def parse_list(self, indent: int) -> list:
        result = []
        while True:
            peeked = self.peek()
            if peeked is None:
                break
            n, ind, content = peeked
            if ind < indent:
                break
            if ind > indent:
                raise YamlError("unexpected indent in list", n)
            if not content.startswith("- ") and content != "-":
                break
            self.i += 1
            rest = "" if content == "-" else content[2:].strip()
            if rest == "":
                peeked = self.peek()
                if peeked is None or peeked[1] <= indent:
                    result.append(None)
                elif peeked[2].startswith("- "):
                    result.append(self.parse_list(peeked[1]))
                else:
                    result.append(self.parse_map(peeked[1]))
            elif rest.endswith(":") or (":" in rest and not _looks_like_scalar(rest)):
                # inline start of a map: "name: What can go wrong"
                # Push a synthetic line at indent+2 for the remainder, then parse a map.
                # Easier: parse this single line as a one-line map entry, then
                # continue a map if following lines are more indented.
                result.append(self._list_item_map(n, indent, rest))
            else:
                result.append(_yaml_scalar(rest))
        return result

    def _list_item_map(self, n: int, dash_indent: int, rest: str) -> dict:
        key, _, value = rest.partition(":")
        key = key.strip()
        value = value.strip()
        item = {}
        if value in ("|", ">", "|-", ">-", "|+", ">+"):
            item[key] = self._parse_block(dash_indent, value[0])
        elif value != "":
            item[key] = _yaml_scalar(value)
        else:
            peeked = self.peek()
            if peeked is None or peeked[1] <= dash_indent:
                item[key] = None
            elif peeked[2].startswith("- "):
                item[key] = self.parse_list(peeked[1])
            else:
                item[key] = self.parse_map(peeked[1])
        # Further keys of this list-item map sit at an indent greater than the dash.
        peeked = self.peek()
        if peeked is not None and peeked[1] > dash_indent and not peeked[2].startswith("- "):
            item.update(self.parse_map(peeked[1]))
        return item

    def _parse_block(self, parent_indent: int, style: str) -> str:
        chunks = []
        block_indent = None
        while True:
            peeked = self.peek()
            if peeked is None:
                break
            n, ind, content = peeked
            # Use the original indent from the stored line. Content is already
            # stripped of that indent, so restore by looking at raw we no longer
            # have — we only stored unindented content. For blocks we need the
            # text after the common indent. Reconstruct: if ind <= parent_indent,
            # the block ends. The first line sets block_indent. Subsequent lines
            # at that indent or more belong to the block. Because we stripped
            # leading spaces into `ind`, `content` is the text after `ind` spaces.
            # For folded/literal we want relative indent vs block_indent.
            if ind <= parent_indent:
                break
            self.i += 1
            if block_indent is None:
                block_indent = ind
            extra = " " * (ind - block_indent)
            chunks.append(extra + content)
        if style == "|":
            return "\n".join(chunks)
        # folded: newlines to spaces, blank lines to paragraph breaks
        paragraphs = []
        current = []
        for line in chunks:
            if line.strip() == "":
                if current:
                    paragraphs.append(" ".join(current))
                    current = []
                paragraphs.append("")
            else:
                current.append(line.strip())
        if current:
            paragraphs.append(" ".join(current))
        # drop trailing empty paragraphs, join with newline for blanks
        text = "\n".join(paragraphs) if any(p == "" for p in paragraphs) else " ".join(
            p for p in paragraphs if p
        )
        return text


def _looks_like_scalar(rest: str) -> bool:
    """True if 'key: value' should NOT be treated as a map start.

    In a list, `- name: What can go wrong` IS a map. `- "12:00"` is a scalar.
    A rest that starts with a quote is a scalar. A rest with ': ' or ending
    with ':' is a map start. A rest with ':' mid-word like '12:00' without
    a space after ':' is a scalar.
    """
    s = rest.strip()
    if s[:1] in ("'", '"'):
        return True
    if s.endswith(":"):
        return False
    if ": " in s:
        return False
    return True


def load_yaml(text: str):
    return _YamlParser(text).parse_document()


def load_yaml_file(path: Path):
    try:
        return load_yaml(path.read_text(encoding="utf-8"))
    except YamlError as exc:
        raise YamlError(f"{path}: {exc}") from exc

# ---------------------------------------------------------------------------
# Templates (Mustache subset)
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"\{\{\{([^{}]+)\}\}\}|\{\{([#^/]?)([^{}]+)\}\}")


def _lookup(stack: list, name: str):
    name = name.strip()
    if name in (".", "this"):
        return stack[-1] if stack else None
    parts = name.split(".")
    for ctx in reversed(stack):
        val = ctx
        ok = True
        for p in parts:
            if isinstance(val, dict) and p in val:
                val = val[p]
            else:
                ok = False
                break
        if ok:
            return val
    return None


def _is_truthy(val) -> bool:
    if val is None or val is False:
        return False
    if val == "" or val == [] or val == {}:
        return False
    return True


def _stringify(val, escape_html: bool, raw: bool) -> str:
    if val is None or val is False:
        return ""
    if val is True:
        s = "true"
    elif isinstance(val, (int, float)):
        s = str(val)
    elif isinstance(val, (list, dict)):
        s = ""
    else:
        s = str(val)
    if escape_html and not raw:
        return html.escape(s, quote=False)
    return s


def render_template(tmpl: str, ctx: dict, escape_html: bool = False) -> str:
    tokens = []
    pos = 0
    for m in _TAG_RE.finditer(tmpl):
        if m.start() > pos:
            tokens.append(("text", tmpl[pos : m.start()]))
        if m.group(1) is not None:
            tokens.append(("raw", m.group(1).strip()))
        else:
            sigil, name = m.group(2), m.group(3).strip()
            if sigil == "#":
                tokens.append(("open", name))
            elif sigil == "^":
                tokens.append(("inv", name))
            elif sigil == "/":
                tokens.append(("close", name))
            else:
                tokens.append(("var", name))
        pos = m.end()
    if pos < len(tmpl):
        tokens.append(("text", tmpl[pos:]))

    # Apply Mustache standalone-tag whitespace: if a section/close tag sits
    # alone on a line, drop the surrounding indent and the following newline
    # from adjacent text tokens. Only for open/inv/close, not for vars.
    tokens = _standalone(tokens)

    tree = _nest(tokens)
    return finalize(_eval(tree, [ctx], escape_html))


def _standalone(tokens: list[tuple]) -> list[tuple]:
    """Drop indent + newline around standalone section tags."""
    out = []
    i = 0
    n = len(tokens)
    while i < n:
        kind, val = tokens[i]
        if kind in ("open", "inv", "close"):
            prev_ok = True
            next_ok = True
            prev = out[-1] if out else None
            nxt = tokens[i + 1] if i + 1 < n else None
            if prev and prev[0] == "text":
                # prev must end with newline + optional spaces, or be only spaces at start
                if not re.search(r"(^|\n)[ \t]*$", prev[1]):
                    prev_ok = False
            if nxt and nxt[0] == "text":
                if not re.match(r"[ \t]*\n", nxt[1]):
                    next_ok = False
            elif nxt is not None:
                next_ok = False
            if prev_ok and next_ok:
                if prev and prev[0] == "text":
                    out[-1] = ("text", re.sub(r"[ \t]*$", "", prev[1]))
                if nxt and nxt[0] == "text":
                    tokens[i + 1] = ("text", re.sub(r"^[ \t]*\n", "", nxt[1]))
            out.append((kind, val))
            i += 1
            continue
        out.append((kind, val))
        i += 1
    return out


def _nest(tokens: list[tuple]) -> list:
    stack: list[list] = [[]]
    for kind, val in tokens:
        if kind in ("open", "inv"):
            node = [kind, val, []]
            stack[-1].append(node)
            stack.append(node[2])
        elif kind == "close":
            if len(stack) == 1:
                raise ValueError(f"unmatched closing tag {{{{{val}}}}}")
            stack.pop()
        else:
            stack[-1].append((kind, val))
    if len(stack) != 1:
        raise ValueError("unclosed section tag")
    return stack[0]


def _eval(tree: list, stack: list, escape_html: bool) -> str:
    parts = []
    for node in tree:
        if isinstance(node, tuple):
            kind, val = node
            if kind == "text":
                parts.append(val)
            elif kind == "var":
                parts.append(_stringify(_lookup(stack, val), escape_html, raw=False))
            elif kind == "raw":
                parts.append(_stringify(_lookup(stack, val), escape_html, raw=True))
            continue
        kind, name, body = node
        val = _lookup(stack, name)
        if kind == "open":
            if isinstance(val, list):
                for item in val:
                    parts.append(_eval(body, stack + [item], escape_html))
            elif _is_truthy(val):
                pushed = val if isinstance(val, dict) else stack[-1]
                parts.append(_eval(body, stack + [pushed], escape_html))
        elif kind == "inv":
            if not _is_truthy(val):
                parts.append(_eval(body, stack, escape_html))
    return "".join(parts)


def finalize(s: str) -> str:
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip(" ") for ln in s.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Word lists, lenses, synonyms
# ---------------------------------------------------------------------------


def _lines_file(path: Path) -> list[str]:
    items = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        items.append(line)
    return items


def load_common_words(path: Path | None = None) -> set[str]:
    path = path or (ROOT / "common-words.txt")
    return {w.lower() for w in _lines_file(path)}


def load_base_terms(path: Path | None = None) -> list[str]:
    path = path or (ROOT / "lenses" / "base-terms.txt")
    return _lines_file(path)


def load_synonyms(path: Path | None = None) -> dict[str, list[str]]:
    """Map unknown-word -> list of suggested replacements.

    File format, one per line:  word: replacement | other replacement
    """
    path = path or (ROOT / "synonyms.txt")
    if not path.exists():
        return {}
    out: dict[str, list[str]] = {}
    for line in _lines_file(path):
        if ":" not in line:
            continue
        key, _, rest = line.partition(":")
        key = key.strip().lower()
        alts = [a.strip() for a in rest.split("|") if a.strip()]
        if key and alts:
            out[key] = alts
    return out


_LENS_DEFAULTS = {
    "max_boxes": 7,
    "min_boxes": 1,
    "max_steps": 12,
    "show_internals": True,
    "show_details": False,
    "show_steps": False,
    "show_glossary": False,
    "show_skipped": False,
    "collapse": False,
    "max_level": None,
    "direction": "TB",
    "max_prose_words": None,
    "max_arrow_words": 5,
    "max_words_per_step": 25,
    "max_sentence_words": 22,
    "max_closing_items": 3,
}


def load_lens(lens_id: str, lenses_dir: Path | None = None) -> dict:
    lenses_dir = lenses_dir or (ROOT / "lenses")
    candidate = Path(lens_id)
    if candidate.suffix in {".yaml", ".yml"} and candidate.exists():
        path = candidate
    else:
        path = lenses_dir / f"{lens_id}.yaml"
        if not path.exists():
            path = lenses_dir / f"{lens_id}.yml"
    if not path.exists():
        raise FileNotFoundError(f"lens not found: {lens_id} (looked for {path})")
    data = load_yaml_file(path)
    if not isinstance(data, dict) or "id" not in data:
        raise ValueError(f"lens {path} is missing an id")
    for k, v in _LENS_DEFAULTS.items():
        data.setdefault(k, v)
    terms: list[str] = []
    if data.get("extends") == "base":
        terms.extend(load_base_terms(lenses_dir / "base-terms.txt"))
    for t in data.get("allowed_terms") or []:
        if t not in terms:
            terms.append(t)
    data["resolved_terms"] = terms
    data["source_path"] = str(path)
    return data


def list_lenses(lenses_dir: Path | None = None) -> list[str]:
    lenses_dir = lenses_dir or (ROOT / "lenses")
    preferred = ["product", "engineer-new", "tech-lead"]
    found = []
    for p in sorted(lenses_dir.glob("*.yaml")) + sorted(lenses_dir.glob("*.yml")):
        if p.stem not in found:
            found.append(p.stem)
    out = [i for i in preferred if i in found]
    out.extend(i for i in found if i not in out)
    return out


# ---------------------------------------------------------------------------
# Model load and lens apply (collapse, levels, aggregate boxes)
# ---------------------------------------------------------------------------

_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z]+)?")


def count_words(text: str) -> int:
    return len(_WORD_RE.findall(text or ""))


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [p for p in parts if p]


def load_model(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return data


def _visibility(item: dict) -> str:
    vis = item.get("visibility")
    if vis in ("always", "internal", "external"):
        return vis
    if item.get("internal") is True:
        return "internal"
    return "always"


def _kind(arrow: dict) -> str:
    k = arrow.get("kind") or "normal"
    if k not in ("normal", "optional", "failure", "query", "branch"):
        return "normal"
    return k


def _is_dashed(arrow: dict) -> bool:
    if arrow.get("style") == "dashed":
        return True
    return _kind(arrow) in ("optional", "failure")


def _box_level(box: dict) -> int:
    n = box.get("level", 1)
    return n if isinstance(n, int) and n >= 1 else 1


def _step_level(step: dict) -> int:
    n = step.get("level")
    if isinstance(n, int) and n >= 1:
        return n
    return 1


def is_visible_box(box: dict, lens: dict) -> bool:
    max_level = lens.get("max_level")
    collapse = bool(lens.get("collapse"))
    level = _box_level(box)
    if max_level is not None and level > int(max_level):
        return False
    if box.get("aggregate"):
        return collapse and (max_level is None or level <= int(max_level))
    vis = _visibility(box)
    show_int = bool(lens.get("show_internals"))
    if vis == "internal" and not show_int and not collapse:
        return False
    if vis == "external" and show_int and not collapse:
        return False
    return True


def _boxes_by_id(model: dict) -> dict:
    return {b["id"]: b for b in model.get("boxes") or [] if isinstance(b, dict) and b.get("id")}


def representative(box_id: str, by_id: dict, lens: dict, visible: set[str], _seen=None) -> str | None:
    """Visible id this box collapses into, or None if it is a hidden pass-through."""
    if box_id in visible:
        return box_id
    if _seen is None:
        _seen = set()
    if box_id in _seen:
        return None
    _seen.add(box_id)
    box = by_id.get(box_id)
    if not box:
        return None
    if not lens.get("collapse"):
        return None
    target = box.get("collapse_to")
    if not target:
        return None
    return representative(target, by_id, lens, visible, _seen)


def _route_id(box_id: str, by_id: dict, lens: dict, visible: set[str]) -> str:
    r = representative(box_id, by_id, lens, visible)
    return r if r is not None else box_id


def _collapse_arrows(model: dict, lens: dict, visible_ids: list[str]) -> list[dict]:
    """Rewrite arrows through collapse_to, bridge pass-through boxes, drop self-loops."""
    by_id = _boxes_by_id(model)
    visible = set(visible_ids)
    arrows = [a for a in (model.get("arrows") or []) if isinstance(a, dict) and a.get("id")]

    def route(i: str) -> str:
        return _route_id(i, by_id, lens, visible)

    # Direct rewrites (both ends resolve to visible boxes).
    direct = []
    # Arrows that still touch a hidden pass-through node (used for bridging).
    residual = []
    for a in arrows:
        frm = route(a.get("from", ""))
        to = route(a.get("to", ""))
        rewritten = dict(a)
        rewritten["from"] = frm
        rewritten["to"] = to
        rewritten["_origin"] = a["id"]
        if frm in visible and to in visible:
            if frm != to:
                direct.append(rewritten)
            # self-loops after collapse are dropped (intra-group hops)
        else:
            residual.append(rewritten)

    # Bridge: from each visible node, walk through hidden nodes to other visible nodes.
    adj: dict[str, list[dict]] = defaultdict(list)
    for a in arrows:
        adj[route(a.get("from", ""))].append(
            {**a, "from": route(a.get("from", "")), "to": route(a.get("to", "")), "_origin": a["id"]}
        )

    bridges = []
    seen_bridge = set()  # (from, to, kind, first_origin) to keep stable unique
    for u in visible_ids:
        for a0 in adj.get(u, []):
            if _kind(a0) == "query":
                continue
            kind0 = _kind(a0)
            queue = [(a0["to"], [a0], kind0)]
            walked = set()
            while queue:
                node, path, kind = queue.pop(0)
                if node in visible:
                    if node != u:
                        key = (u, node, kind, path[0]["_origin"])
                        if key not in seen_bridge:
                            seen_bridge.add(key)
                            # Prefer the failure/optional label when the path ends that way;
                            # otherwise the first hop's label (what the sender sent).
                            label_src = path[-1] if kind == "failure" else path[0]
                            bridges.append(
                                {
                                    "id": f"c_{path[0]['_origin']}_{node}",
                                    "from": u,
                                    "to": node,
                                    "label": label_src.get("label") or "",
                                    "kind": kind,
                                    "style": "dashed" if kind in ("failure", "optional") or any(_is_dashed(p) for p in path) else "solid",
                                    "step": path[0].get("step"),
                                    "_origin": path[0]["_origin"],
                                    "_path": [p["_origin"] for p in path],
                                }
                            )
                    continue
                if node in walked:
                    continue
                walked.add(node)
                for a in adj.get(node, []):
                    k = _kind(a)
                    if kind == "optional" and k in ("normal", "optional"):
                        queue.append((a["to"], path + [a], "optional"))
                    elif kind == "normal" and k in ("normal", "failure", "optional", "branch"):
                        nxt_kind = k if k != "normal" else kind
                        queue.append((a["to"], path + [a], nxt_kind))
                    elif k == kind:
                        queue.append((a["to"], path + [a], kind))

    # If collapse produced any bridges between a pair, prefer them over raw
    # rewritten arrows that skipped the middle (direct may already be complete
    # when collapse_to resolved both ends). Union, then drop duplicates.
    combined = []
    seen_pair = []

    def add(a):
        key = (a["from"], a["to"], _kind(a), (a.get("label") or "").strip())
        if key in seen_pair:
            return
        seen_pair.append(key)
        combined.append(a)

    # When collapsing, bridges are the meaningful derived hops; also keep
    # directs that were not superseded (already-visible endpoints).
    if lens.get("collapse") and bridges:
        for a in direct:
            add(a)
        for a in bridges:
            # Skip a bridge that duplicates a direct with the same ends and kind
            add(a)
    else:
        for a in direct:
            add(a)

    if lens.get("collapse"):
        combined = _merge_parallel_arrows(combined, lens.get("max_arrow_words") or 5)
    return combined



def _merge_parallel_arrows(arrows: list[dict], max_words: int) -> list[dict]:
    """Join same-from/to/kind arrows, keeping author order. Labels combined with commas."""
    groups: dict[tuple, list[dict]] = {}
    order: list[tuple] = []
    for a in arrows:
        key = (a["from"], a["to"], _kind(a))
        if key not in groups:
            order.append(key)
            groups[key] = []
        groups[key].append(a)
    out = []
    for key in order:
        group = groups[key]
        if len(group) == 1:
            out.append(group[0])
            continue
        labels = []
        origins = []
        for a in group:
            lab = (a.get("label") or "").strip()
            if lab and lab not in labels:
                labels.append(lab)
            origins.append(a.get("_origin"))
            origins.extend(a.get("_path") or [])
        joined = ", ".join(labels)
        # If the join is too long, keep the arrows separate so the label cap
        # can be decided by the author, not by a truncated merge.
        if count_words(joined) > max_words:
            out.extend(group)
            continue
        merged = dict(group[0])
        merged["label"] = joined
        merged["_origin"] = group[0].get("_origin")
        merged["_path"] = [o for o in origins if o]
        merged["_merged_from"] = [a["id"] for a in group]
        out.append(merged)
    return out


def apply_lens(model: dict, lens: dict) -> dict:
    boxes_all = [b for b in model.get("boxes") or [] if isinstance(b, dict) and b.get("id")]
    candidates = [b for b in boxes_all if is_visible_box(b, lens)]
    cand_ids = {b["id"] for b in candidates}
    by_id_all = {b["id"]: b for b in boxes_all}
    visible_boxes = []
    if lens.get("collapse"):
        for b in candidates:
            target = b.get("collapse_to")
            folded = False
            seen = set()
            while target and target not in seen:
                seen.add(target)
                if target in cand_ids and target != b["id"]:
                    folded = True
                    break
                target = (by_id_all.get(target) or {}).get("collapse_to")
            if not folded:
                visible_boxes.append(b)
    else:
        visible_boxes = candidates
    visible_ids = [b["id"] for b in visible_boxes]
    arrows = _collapse_arrows(model, lens, visible_ids)

    # Steps: keep those whose level is within max_level (default: keep all at
    # or below max_level; if step has no level, keep when its arrow is visible
    # or was an origin of a visible arrow). Then filter by show, renumber.
    max_level = lens.get("max_level")
    origins = {}
    for a in arrows:
        for key in [a.get("_origin"), a.get("id"), *(a.get("_path") or []), *(a.get("_merged_from") or [])]:
            if key:
                origins.setdefault(key, []).append(a)

    steps_kept = []
    for s in model.get("steps") or []:
        if not isinstance(s, dict):
            continue
        sl = s.get("level")
        if max_level is not None and isinstance(sl, int) and sl != int(max_level):
            continue
        if max_level is not None and sl is None:
            # Unleveled steps are treated as finest (only the highest lens).
            # Product/tech-lead authors should set level explicitly.
            if int(max_level) < 3:
                continue
        arrow_id = s.get("arrow")
        attached = origins.get(arrow_id) or [a for a in arrows if a.get("id") == arrow_id]
        if not attached:
            # Fine-only step with no surviving arrow: drop.
            if sl is not None and max_level is not None and sl > int(max_level):
                continue
            if sl is not None and (max_level is None or sl <= int(max_level)):
                # Level-appropriate step whose arrow vanished (became a self-loop):
                # drop rather than leave a dangling step.
                continue
            continue
        s2 = dict(s)
        s2["arrow"] = attached[0]["id"]
        s2["_orig_arrow"] = arrow_id
        steps_kept.append(s2)

    steps = []
    for i, s in enumerate(steps_kept, 1):
        steps.append(
            {
                "n": i,
                "text": s.get("text") or "",
                "arrow": s["arrow"],
                "_orig_n": s.get("n"),
                "level": s.get("level"),
            }
        )

    # Number arrows from the visible steps that point at them (lowest n).
    step_n_for_arrow: dict[str, int] = {}
    for s in steps:
        step_n_for_arrow.setdefault(s["arrow"], s["n"])
    for a in arrows:
        if a["id"] in step_n_for_arrow:
            a["step_n"] = step_n_for_arrow[a["id"]]
        else:
            # A merged/bridged arrow: take the lowest visible step that
            # pointed at any of its origin arrows.
            origins = [a.get("_origin"), a.get("id")] + list(a.get("_path") or []) + list(a.get("_merged_from") or [])
            ns = [step_n_for_arrow[o] for o in origins if o in step_n_for_arrow]
            if ns:
                a["step_n"] = min(ns)

    field = (lens.get("closing_section") or {}).get("field")
    closing_items = list(model.get(field) or []) if field else []
    max_close = lens.get("max_closing_items")
    if isinstance(max_close, int) and max_close >= 0:
        # Do not silently trim: the checker flags overflow. Still pass all
        # so the check can see them; the renderer will cut to the cap.
        pass
    closing_name = (lens.get("closing_section") or {}).get("name") or ""
    show_details = bool(lens.get("show_details"))
    details = model.get("details") if show_details else None
    if details is not None and not str(details).strip():
        details = None
    skipped = list(model.get("skipped") or []) if lens.get("show_skipped") else []
    glossary = list(model.get("glossary") or []) if lens.get("show_glossary") else list(model.get("glossary") or [])
    # glossary is still used for vocab (terms allowed) even if not shown;
    # the view flag show_glossary controls rendering.
    legend = model.get("legend") or ""
    return {
        "title": model.get("title") or "",
        "goal": model.get("goal") or "",
        "boxes": visible_boxes,
        "arrows": arrows,
        "steps": steps,
        "skipped": skipped,
        "closing_name": closing_name,
        "closing_items": closing_items,
        "glossary": list(model.get("glossary") or []),
        "show_glossary": bool(lens.get("show_glossary")),
        "show_skipped": bool(lens.get("show_skipped")),
        "show_steps": bool(lens.get("show_steps")),
        "details": details,
        "legend": legend,
        "direction": lens.get("direction") or model.get("direction") or "TB",
        "lens": lens,
        "max_closing_items": max_close,
    }


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


class Issue:
    def __init__(self, kind: str, message: str, location: str = "", level: str = "error"):
        self.kind = kind
        self.message = message
        self.location = location
        self.level = level  # "error" or "warn"

    def __str__(self) -> str:
        tag = "warn" if self.level == "warn" else self.kind
        if self.location:
            return f"{tag}: {self.message} ({self.location})"
        return f"{tag}: {self.message}"


def _schema_issues(model: dict) -> list[Issue]:
    issues: list[Issue] = []
    for key in ("title", "goal", "boxes", "arrows"):
        if key not in model or model[key] in (None, "", []):
            issues.append(Issue("schema", f"missing or empty '{key}'"))
    if not isinstance(model.get("title", ""), str):
        issues.append(Issue("schema", "title must be a string"))
    if not isinstance(model.get("goal", ""), str):
        issues.append(Issue("schema", "goal must be a string"))
    boxes = model.get("boxes") or []
    arrows = model.get("arrows") or []
    steps = model.get("steps") or []
    if not isinstance(boxes, list) or not isinstance(arrows, list):
        issues.append(Issue("schema", "boxes and arrows must be lists"))
        return issues
    if not isinstance(steps, list):
        issues.append(Issue("schema", "steps must be a list"))
        steps = []

    box_ids = []
    for i, b in enumerate(boxes):
        loc = f"boxes[{i}]"
        if not isinstance(b, dict):
            issues.append(Issue("schema", "box must be an object", loc))
            continue
        if not b.get("id"):
            issues.append(Issue("schema", "box is missing id", loc))
        elif not _ID_RE.match(b["id"]):
            issues.append(Issue("schema", f"box id {b['id']!r} is not Mermaid-safe", loc))
        if not (b.get("label") or "").strip():
            issues.append(Issue("schema", "box is missing a label", loc))
        box_ids.append(b.get("id"))
        if b.get("collapse_to") and b["collapse_to"] == b.get("id"):
            issues.append(Issue("schema", "collapse_to cannot be the box itself", loc))
    seen = set()
    for bid in box_ids:
        if bid and bid in seen:
            issues.append(Issue("schema", f"duplicate box id '{bid}'"))
        seen.add(bid)
    box_id_set = {b for b in box_ids if b}

    arrow_ids = []
    for i, a in enumerate(arrows):
        loc = f"arrows[{i}]"
        if not isinstance(a, dict):
            issues.append(Issue("schema", "arrow must be an object", loc))
            continue
        if not a.get("id"):
            issues.append(Issue("schema", "arrow is missing id", loc))
        elif not _ID_RE.match(str(a["id"])):
            issues.append(Issue("schema", f"arrow id {a['id']!r} is not Mermaid-safe", loc))
        if a.get("id"):
            arrow_ids.append(a["id"])
        if not (a.get("label") or "").strip():
            issues.append(Issue("schema", "arrow is missing a label (what moves)", loc))
        if "from" not in a or "to" not in a:
            issues.append(Issue("schema", "arrow is missing from or to", loc))
        else:
            if a["from"] not in box_id_set:
                issues.append(Issue("schema", f"arrow from '{a['from']}' is not a box", loc))
            if a["to"] not in box_id_set:
                issues.append(Issue("schema", f"arrow to '{a['to']}' is not a box", loc))
            # Self-loop ban on the authored (fine) graph — even before collapse.
            if a["from"] == a["to"]:
                issues.append(Issue("gap", "self-loop arrows are not allowed", loc))
        if a.get("step") is not None and (not isinstance(a.get("step"), int) or a["step"] < 1):
            issues.append(Issue("schema", "arrow.step must be a positive integer", loc))
        vis = a.get("visibility")
        if vis is not None and vis not in ("always", "internal", "external"):
            issues.append(Issue("schema", f"unknown visibility {vis!r}", loc))
        if a.get("kind") is not None and a["kind"] not in (
            "normal",
            "optional",
            "failure",
            "query",
            "branch",
        ):
            issues.append(Issue("schema", f"unknown kind {a['kind']!r}", loc))
    seen = set()
    for aid in arrow_ids:
        if aid in seen:
            issues.append(Issue("schema", f"duplicate arrow id '{aid}'"))
        seen.add(aid)
    arrow_id_set = set(arrow_ids)

    ns = []
    for i, s in enumerate(steps):
        loc = f"steps[{i}]"
        if not isinstance(s, dict):
            issues.append(Issue("schema", "step must be an object", loc))
            continue
        if not isinstance(s.get("n"), int) or s["n"] < 1:
            issues.append(Issue("schema", "step.n must be a positive integer", loc))
        else:
            ns.append(s["n"])
        if not (s.get("text") or "").strip():
            issues.append(Issue("schema", "step is missing text", loc))
        if not s.get("arrow"):
            issues.append(Issue("schema", "step is missing arrow", loc))
        elif s["arrow"] not in arrow_id_set:
            issues.append(Issue("schema", f"step references unknown arrow '{s['arrow']}'", loc))
    if ns:
        if len(ns) != len(set(ns)):
            issues.append(Issue("schema", f"duplicate step numbers: {ns}"))
        expected = list(range(1, len(ns) + 1))
        if sorted(ns) != expected:
            issues.append(
                Issue("schema", f"step numbers must be contiguous from 1 (got {sorted(ns)})")
            )

    step_by_arrow = {}
    for s in steps:
        if isinstance(s, dict) and s.get("arrow") and isinstance(s.get("n"), int):
            step_by_arrow.setdefault(s["arrow"], []).append(s["n"])
    for key in ("skipped", "risks", "user_impact", "tradeoffs"):
        val = model.get(key)
        if val is not None and not (
            isinstance(val, list) and all(isinstance(x, str) for x in val)
        ):
            issues.append(Issue("schema", f"{key} must be a list of strings"))
    gloss = model.get("glossary")
    if gloss is not None:
        if not isinstance(gloss, list):
            issues.append(Issue("schema", "glossary must be a list"))
        else:
            for i, g in enumerate(gloss):
                if not isinstance(g, dict) or not g.get("term") or not g.get("definition"):
                    issues.append(
                        Issue("schema", "glossary entry needs term and definition", f"glossary[{i}]")
                    )
    if "details" in model and model["details"] is not None and not isinstance(model["details"], str):
        issues.append(Issue("schema", "details must be a string"))
    return issues


def _gap_issues(view: dict) -> list[Issue]:
    issues: list[Issue] = []
    boxes = view["boxes"]
    arrows = view["arrows"]
    steps = view["steps"]
    box_ids = {b["id"] for b in boxes}
    arrow_ids = {a["id"] for a in arrows}
    referenced = set()
    steps_by_arrow: dict[str, list] = defaultdict(list)
    for s in steps:
        steps_by_arrow[s["arrow"]].append(s)
    for a in arrows:
        loc = f"arrows[{a.get('id')}]"
        if not a.get("from") or not a.get("to"):
            issues.append(Issue("gap", "arrow is missing from or to", loc))
        else:
            if a["from"] not in box_ids:
                issues.append(Issue("gap", f"from '{a['from']}' is not a visible box", loc))
            if a["to"] not in box_ids:
                issues.append(Issue("gap", f"to '{a['to']}' is not a visible box", loc))
            if a["from"] == a["to"]:
                issues.append(Issue("gap", "self-loop arrows are not allowed", loc))
            referenced.add(a["from"])
            referenced.add(a["to"])
        if not (a.get("label") or "").strip():
            issues.append(Issue("gap", "arrow has an empty label", loc))
        # Optional/failure arrows may exist without a numbered step.
        if _kind(a) in ("normal", "branch") and a["id"] not in steps_by_arrow and not a.get("_origin"):
            # After collapse, a derived arrow may inherit a step via step_n.
            if not a.get("step_n") and view["lens"].get("show_steps"):
                issues.append(Issue("gap", "arrow has no step", loc))
    for b in boxes:
        if b["id"] not in referenced and not b.get("aggregate"):
            # A legend/note node may be unreferenced on purpose.
            if b.get("shape") != "note":
                issues.append(
                    Issue("gap", f"box '{b['id']}' is not on any visible arrow", f"boxes[{b['id']}]")
                )
    ns = [s["n"] for s in steps]
    if ns and ns != list(range(1, len(ns) + 1)):
        issues.append(Issue("gap", f"visible steps are not contiguous (got {ns})"))
    for s in steps:
        if s["arrow"] not in arrow_ids:
            issues.append(
                Issue("gap", "step references an arrow that is not visible", f"steps[{s['n']}]")
            )

    # Connectivity: one weakly-connected component among boxes that sit on arrows.
    if box_ids and arrows:
        adj = defaultdict(set)
        used = set()
        for a in arrows:
            if a.get("from") in box_ids and a.get("to") in box_ids:
                adj[a["from"]].add(a["to"])
                adj[a["to"]].add(a["from"])
                used.add(a["from"])
                used.add(a["to"])
        if used:
            start = next(b["id"] for b in boxes if b["id"] in used)
            seen = set()
            stack = [start]
            while stack:
                n = stack.pop()
                if n in seen:
                    continue
                seen.add(n)
                stack.extend(adj[n] - seen)
            missing = used - seen
            if missing:
                issues.append(
                    Issue(
                        "gap",
                        "visible graph is disconnected; unreachable boxes: "
                        + ", ".join(sorted(missing)),
                    )
                )

    # Step order: each step's `from` was reached already, or is a source
    # (no incoming normal arrow among visible arrows).
    incoming = defaultdict(set)
    for a in arrows:
        if a.get("to"):
            incoming[a["to"]].add(a.get("from"))
    reached = set()
    sources = set(box_ids)
    for a in arrows:
        if a.get("to") in sources and _kind(a) in ("normal", "branch"):
            sources.discard(a["to"])
    # A box with only failure/optional incoming can still be a source of the main path.
    reached |= sources
    arrow_by_id = {a["id"]: a for a in arrows}
    for s in steps:
        a = arrow_by_id.get(s["arrow"])
        if not a:
            continue
        frm = a["from"]
        if _kind(a) == "query":
            # A new actor starts asking (e.g. the map page). It is a source of this phase.
            reached.add(frm)
        elif frm not in reached and frm not in sources:
            issues.append(
                Issue(
                    "gap",
                    f"step {s['n']} starts at '{frm}', which has not been reached yet",
                    f"steps[{s['n']}]",
                )
            )
        reached.add(frm)
        reached.add(a["to"])
    return issues


def _limit_issues(view: dict, lens: dict) -> list[Issue]:
    issues = []
    n_boxes = len([b for b in view["boxes"] if b.get("shape") != "note"])
    n_steps = len(view["steps"])
    max_boxes = lens.get("max_boxes")
    min_boxes = lens.get("min_boxes")
    max_steps = lens.get("max_steps")
    if isinstance(max_boxes, int) and n_boxes > max_boxes:
        issues.append(Issue("limits", f"{n_boxes} visible boxes exceeds max_boxes {max_boxes}"))
    if isinstance(min_boxes, int) and n_boxes < min_boxes:
        issues.append(Issue("limits", f"{n_boxes} visible boxes is below min_boxes {min_boxes}"))
    if isinstance(max_steps, int) and n_steps > max_steps:
        issues.append(Issue("limits", f"{n_steps} visible steps exceeds max_steps {max_steps}"))

    max_arrow = lens.get("max_arrow_words") or 5
    for a in view["arrows"]:
        n = count_words(a.get("label") or "")
        if n > max_arrow:
            issues.append(
                Issue(
                    "limits",
                    f"arrow label has {n} words (max {max_arrow}): {a.get('label')!r}",
                    f"arrows[{a['id']}]",
                )
            )
    max_w = lens.get("max_words_per_step")
    max_s = lens.get("max_sentence_words")
    if view.get("show_steps"):
        for s in view["steps"]:
            w = count_words(s.get("text") or "")
            if isinstance(max_w, int) and w > max_w:
                issues.append(
                    Issue("limits", f"step has {w} words (max {max_w})", f"steps[{s['n']}]")
                )
            for sent in sentences(s.get("text") or ""):
                sw = count_words(sent)
                if isinstance(max_s, int) and sw > max_s:
                    issues.append(
                        Issue(
                            "limits",
                            f"sentence has {sw} words (max {max_s}): {sent[:60]}",
                            f"steps[{s['n']}]",
                        )
                    )
    max_close = lens.get("max_closing_items")
    if isinstance(max_close, int) and len(view.get("closing_items") or []) > max_close:
        issues.append(
            Issue(
                "limits",
                f"{len(view['closing_items'])} closing items exceeds max_closing_items {max_close}",
            )
        )
    # Prose budget: words that will actually appear outside the diagram.
    prose = _prose_text(view)
    n_prose = count_words(prose)
    cap = lens.get("max_prose_words")
    if isinstance(cap, int) and n_prose > cap:
        issues.append(Issue("limits", f"{n_prose} prose words exceeds max_prose_words {cap}"))
    return issues


def _prose_text(view: dict) -> str:
    """Visible prose outside the Mermaid block (matches what the template shows)."""
    parts = [view.get("title") or "", "For: " + (view["lens"].get("name") or ""), "Goal. " + (view.get("goal") or "")]
    if view.get("show_steps"):
        for s in view["steps"]:
            parts.append(s.get("text") or "")
    items = view.get("closing_items") or []
    cap = view.get("max_closing_items")
    if isinstance(cap, int):
        items = items[:cap]
    if items and (view.get("closing_name") or items):
        parts.extend(items)
    if view.get("show_glossary"):
        for g in _used_glossary(view):
            parts.append(f"{g.get('term','')} {g.get('definition','')}")
    if view.get("show_skipped"):
        parts.extend(view.get("skipped") or [])
    if view.get("details"):
        parts.append(view["details"])
    return "\n".join(parts)


def prose_word_count(view: dict) -> int:
    return count_words(_prose_text(view))


# Vocabulary ----------------------------------------------------------------

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:['’][A-Za-z]+)?")

# Past/participle and a few comparatives that suffix rules miss.
_IRREGULAR = {
    "hidden": "hide",
    "hid": "hide",
    "held": "hold",
    "shown": "show",
    "sent": "send",
    "stored": "store",
    "wrote": "write",
    "written": "write",
    "took": "take",
    "taken": "take",
    "made": "make",
    "kept": "keep",
    "left": "leave",
    "built": "build",
    "gave": "give",
    "given": "give",
    "saw": "see",
    "seen": "see",
    "came": "come",
    "became": "become",
    "did": "do",
    "done": "do",
    "went": "go",
    "gone": "go",
    "ran": "run",
    "led": "lead",
    "safer": "safe",
    "easier": "easy",
    "harder": "hard",
    "simpler": "simple",
    "later": "late",
    "better": "good",
    "worse": "bad",
    "best": "good",
    "worst": "bad",
    "further": "far",
    "farther": "far",
}


def _stems(word: str) -> list[str]:
    w = word.lower()
    out = [w]
    if w.endswith("'s") or w.endswith("’s"):
        out.append(w[:-2])
    if len(w) > 4 and w.endswith("ies"):
        out.append(w[:-3] + "y")
    if len(w) > 4 and w.endswith("ied"):
        out.append(w[:-3] + "y")
    if len(w) > 3 and w.endswith("es"):
        out.append(w[:-2])
        out.append(w[:-1])
    if len(w) > 2 and w.endswith("s") and not w.endswith("ss"):
        out.append(w[:-1])
    if len(w) > 5 and w.endswith("ing"):
        stem = w[:-3]
        out.append(stem)
        out.append(stem + "e")
        if len(stem) >= 2 and stem[-1] == stem[-2]:
            out.append(stem[:-1])
    if len(w) > 4 and w.endswith("ed"):
        stem = w[:-2]
        out.append(stem)
        out.append(stem + "e")
        if len(stem) >= 2 and stem[-1] == stem[-2]:
            out.append(stem[:-1])
    if len(w) > 4 and w.endswith("ly"):
        out.append(w[:-2])
        if w.endswith("ily"):
            out.append(w[:-3] + "y")
    seen = set()
    unique = []
    for s in out:
        if s and s not in seen:
            seen.add(s)
            unique.append(s)
    return unique


def _allowed(token: str, lexicon: set[str]) -> bool:
    for stem in _stems(token):
        if stem in lexicon:
            return True
        irreg = _IRREGULAR.get(stem)
        if irreg and irreg in lexicon:
            return True
    return False


def _phrase_spans(text: str, phrases: list[str]) -> list[bool]:
    covered = [False] * len(text)
    lower = text.lower()
    for phrase in phrases:
        start = 0
        while True:
            i = lower.find(phrase, start)
            if i < 0:
                break
            j = i + len(phrase)
            left_ok = i == 0 or not lower[i - 1].isalnum()
            right_ok = j == len(lower) or not lower[j].isalnum()
            if left_ok and right_ok:
                for k in range(i, j):
                    covered[k] = True
            start = i + 1
    return covered


def unknown_words(text: str, lexicon: set[str], phrases: list[str]) -> list[tuple[str, int]]:
    if not text:
        return []
    # Hyphenated compounds: if the whole is allowed, cover the span; else the
    # parts are checked individually (already happens because the token regex
    # stops at the hyphen). Also try the whole lowercased compound.
    covered = _phrase_spans(text, phrases) if phrases else [False] * len(text)
    # Cover hyphenated wholes that are in the lexicon.
    for m in re.finditer(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z][A-Za-z0-9]*)+", text):
        whole = m.group(0).lower()
        if _allowed(whole.replace("-", ""), lexicon) or whole in lexicon or _allowed(whole, lexicon):
            for k in range(m.start(), m.end()):
                covered[k] = True
        else:
            # If every hyphen-part is allowed, accept the compound.
            parts = whole.split("-")
            if parts and all(_allowed(p, lexicon) for p in parts):
                for k in range(m.start(), m.end()):
                    covered[k] = True
    found = []
    for m in _TOKEN_RE.finditer(text):
        if any(covered[k] for k in range(m.start(), m.end())):
            continue
        tok = m.group(0)
        if _allowed(tok, lexicon):
            continue
        found.append((tok, m.start()))
    return found


def _used_glossary(view: dict) -> list[dict]:
    entries = view.get("glossary") or []
    if not entries:
        return []
    chunks = _vocab_chunks(view, include_glossary=False)
    blob = "\n".join(text for _, text in chunks).lower()
    used = []
    for g in entries:
        term = (g.get("term") or "").strip()
        if not term:
            continue
        forms = set(_stems(term))
        forms.add(term.lower())
        irreg = _IRREGULAR.get(term.lower())
        if irreg:
            forms.add(irreg)
        # Also generate common suffix forms so "blurs"/"blurred" match "blur".
        base = term.lower()
        forms.update({base + "s", base + "es", base + "ed", base + "ing", base + "red", base + "red"})
        if any(re.search(r"\b" + re.escape(f) + r"\b", blob) for f in forms if f):
            used.append(g)
    return used


def _vocab_chunks(view: dict, include_glossary: bool = True) -> list[tuple[str, str]]:
    chunks = [
        ("title", view["title"]),
        ("goal", view["goal"]),
    ]
    if view.get("legend"):
        chunks.append(("legend", view["legend"]))
    for b in view["boxes"]:
        chunks.append((f"boxes[{b['id']}].label", b.get("label") or ""))
        if b.get("note"):
            chunks.append((f"boxes[{b['id']}].note", b["note"]))
    for a in view["arrows"]:
        chunks.append((f"arrows[{a['id']}].label", a.get("label") or ""))
    if view.get("show_steps"):
        for s in view["steps"]:
            chunks.append((f"steps[{s['n']}].text", s.get("text") or ""))
    items = view.get("closing_items") or []
    cap = view.get("max_closing_items")
    if isinstance(cap, int):
        items = items[:cap]
    for i, item in enumerate(items):
        chunks.append((f"closing[{i}]", item))
    if view.get("show_skipped"):
        for i, item in enumerate(view.get("skipped") or []):
            chunks.append((f"skipped[{i}]", item))
    if include_glossary and view.get("show_glossary"):
        for g in _used_glossary(view):
            chunks.append((f"glossary[{g.get('term','')}].definition", g.get("definition") or ""))
    if view.get("details"):
        chunks.append(("details", view["details"]))
    return chunks


def _lexicon_for(view: dict, lens: dict, common: set[str]) -> tuple[set[str], list[str]]:
    terms = list(lens.get("resolved_terms") or [])
    for g in view.get("glossary") or []:
        t = (g.get("term") or "").strip()
        if t and t not in terms:
            terms.append(t)
    lexicon = {t.lower() for t in terms} | {w.lower() for w in common}
    phrases = sorted((t.lower() for t in terms if " " in t.lower()), key=len, reverse=True)
    return lexicon, phrases


def _vocab_issues(view: dict, lens: dict, common: set[str]) -> list[Issue]:
    lexicon, phrases = _lexicon_for(view, lens, common)
    issues = []
    for loc, text in _vocab_chunks(view, include_glossary=True):
        for word, pos in unknown_words(text, lexicon, phrases):
            issues.append(
                Issue(
                    "vocabulary",
                    f"{word!r} is not in allowed terms, glossary, or common words",
                    loc,
                )
            )
        # Proper-noun warnings: mid-sentence Capitalized words not in the lexicon
        # and not at the start of the string or after a sentence break.
        for m in re.finditer(r"\b[A-Z][A-Za-z0-9]*\b", text or ""):
            if m.start() == 0:
                continue
            prev = text[: m.start()].rstrip()
            if not prev or prev[-1] in ".!?:\n":
                continue
            tok = m.group(0)
            if _allowed(tok, lexicon):
                continue
            # Already reported as a vocabulary error? Still warn.
            issues.append(
                Issue(
                    "vocabulary",
                    f"proper noun {tok!r} is not in the glossary",
                    loc,
                    level="warn",
                )
            )
    return issues


def check(model: dict, lens: dict, common: set[str] | None = None) -> list[Issue]:
    common = common if common is not None else load_common_words()
    issues = _schema_issues(model)
    view = apply_lens(model, lens)
    issues.extend(_gap_issues(view))
    issues.extend(_limit_issues(view, lens))
    issues.extend(_vocab_issues(view, lens, common))
    return issues


def errors_only(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.level != "warn"]


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------


def suggest(model: dict, lens: dict, common: set[str] | None = None, synonyms: dict | None = None) -> list[str]:
    """Human-readable replacement hints for vocabulary errors."""
    common = common if common is not None else load_common_words()
    synonyms = synonyms if synonyms is not None else load_synonyms()
    view = apply_lens(model, lens)
    lexicon, phrases = _lexicon_for(view, lens, common)
    lines = []
    seen = set()
    for loc, text in _vocab_chunks(view, include_glossary=True):
        for word, _pos in unknown_words(text, lexicon, phrases):
            key = (word.lower(), loc)
            if key in seen:
                continue
            seen.add(key)
            alts = synonyms.get(word.lower()) or []
            # Also try stems as synonym keys.
            for st in _stems(word):
                for a in synonyms.get(st) or []:
                    if a not in alts:
                        alts.append(a)
            usable = []
            for a in alts:
                # A suggestion is usable if every word in it is allowed.
                if not unknown_words(a, lexicon, phrases):
                    usable.append(a)
            if usable:
                lines.append(f"{loc}: {word!r} → try {', '.join(repr(u) for u in usable)}")
            elif alts:
                lines.append(
                    f"{loc}: {word!r} → synonym {', '.join(repr(a) for a in alts)} "
                    f"(check that those words are allowed under this lens)"
                )
            else:
                lines.append(
                    f"{loc}: {word!r} → no synonym on file; replace with allowed words "
                    f"or add a one-line glossary entry"
                )
    return lines


# ---------------------------------------------------------------------------
# Mermaid (diagram-first)
# ---------------------------------------------------------------------------


def _esc_mermaid_label(label: str) -> str:
    s = " ".join((label or "").split())
    s = s.replace('"', "'").replace("|", "/")
    s = s.replace("[", "(").replace("]", ")")
    s = s.replace("{", "(").replace("}", ")")
    s = s.replace("<", "(").replace(">", ")")
    s = s.replace("\n", " ")
    return s


def _box_mermaid(box: dict) -> str:
    bid = box["id"]
    label = _esc_mermaid_label(box.get("label") or bid)
    note = (box.get("note") or "").strip()
    if note:
        label = f"{label} ({_esc_mermaid_label(note)})"
    shape = box.get("shape") or "box"
    if shape == "decision":
        return f'  {bid}{{"{label}"}}'
    if shape == "note":
        return f'  {bid}["{label}"]'
    if shape == "round":
        return f'  {bid}("{label}")'
    return f'  {bid}["{label}"]'


def _arrow_label(arrow: dict) -> str:
    raw = (arrow.get("label") or "").strip()
    n = arrow.get("step_n")
    if isinstance(n, int) and _kind(arrow) in ("normal", "branch", "query"):
        # Don't double-prefix if the author already numbered it.
        if not re.match(r"^\d+\.\s", raw):
            raw = f"{n}. {raw}"
    return _esc_mermaid_label(raw)


def mermaid_source(view: dict) -> str:
    boxes = view["boxes"]
    arrows = view["arrows"]
    direction = (view.get("direction") or "TB").upper()
    if direction not in ("TB", "TD", "LR", "RL", "BT"):
        direction = "TB"
    if direction == "TD":
        direction = "TB"
    lines = [f"flowchart {direction}"]
    # Declare boxes in model order. Open a subgraph when a group starts,
    # close it when the group ends, so layout follows the path.
    open_group = None
    for b in boxes:
        g = (b.get("group") or "").strip() or None
        if g != open_group:
            if open_group is not None:
                lines.append("  end")
            if g is not None:
                gid = "g_" + re.sub(r"[^A-Za-z0-9_]", "_", g)
                lines.append(f'  subgraph {gid}["{_esc_mermaid_label(g)}"]')
            open_group = g
        prefix = "  " if open_group else ""
        lines.append(prefix + _box_mermaid(b))
    if open_group is not None:
        lines.append("  end")
    if view.get("legend"):
        lines.append(f'  legend["{_esc_mermaid_label(view["legend"])}"]')
    for a in arrows:
        frm, to = a["from"], a["to"]
        lab = _arrow_label(a)
        if _is_dashed(a):
            lines.append(f'  {frm} -.->|"{lab}"| {to}')
        else:
            lines.append(f'  {frm} -->|"{lab}"| {to}')
    return "\n".join(lines)


def mermaid_sanity(source: str) -> list[str]:
    errors = []
    lines = source.splitlines()
    if not lines or not lines[0].startswith("flowchart "):
        errors.append("mermaid must start with 'flowchart '")
    return errors


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def _rendered_closing(view: dict):
    items = list(view.get("closing_items") or [])
    cap = view.get("max_closing_items")
    if isinstance(cap, int):
        items = items[:cap]
    name = view.get("closing_name") or ""
    if name and items:
        return {"name": name, "items": items}
    return False


def build_context(view: dict) -> dict:
    glossary_entries = _used_glossary(view) if view.get("show_glossary") else []
    skipped = view.get("skipped") or [] if view.get("show_skipped") else []
    details = view.get("details")
    lens = view["lens"]
    steps = [{"n": s["n"], "text": s["text"]} for s in view["steps"]] if view.get("show_steps") else []
    return {
        "title": view["title"],
        "goal": view["goal"],
        "lens_id": lens.get("id") or "",
        "lens_name": lens.get("name") or lens.get("id") or "",
        "mermaid": mermaid_source(view),
        "steps": steps,
        "show_steps": bool(steps),
        "closing": _rendered_closing(view),
        "glossary": {"entries": glossary_entries} if glossary_entries else False,
        "skipped": {"items": skipped} if skipped else False,
        "details": details if details else False,
        "legend": view.get("legend") or False,
    }


def load_template(fmt: str, templates_dir: Path | None = None) -> tuple[str, Path]:
    templates_dir = templates_dir or (ROOT / "templates")
    path = templates_dir / f"{fmt}.tmpl"
    if not path.exists():
        known = sorted(p.stem for p in templates_dir.glob("*.tmpl"))
        raise FileNotFoundError(
            f"no template for format {fmt!r} (looked for {path}; have {known})"
        )
    return path.read_text(encoding="utf-8"), path


def render(model: dict, lens: dict, fmt: str, templates_dir: Path | None = None) -> str:
    view = apply_lens(model, lens)
    tmpl, path = load_template(fmt, templates_dir)
    ctx = build_context(view)
    escape = fmt in ("html", "html-tabs") or path.name.endswith(".html.tmpl") or "html" in path.stem
    return render_template(tmpl, ctx, escape_html=escape)


def render_tabs(model: dict, lenses: list[dict], templates_dir: Path | None = None) -> str:
    """Combined HTML with one tab per lens. Deterministic tab order is `lenses`."""
    tmpl, path = load_template("html-tabs", templates_dir)
    panels = []
    title = model.get("title") or ""
    for i, lens in enumerate(lenses):
        view = apply_lens(model, lens)
        ctx = build_context(view)
        ctx["active"] = "active" if i == 0 else ""
        ctx["checked"] = "checked" if i == 0 else ""
        panels.append(ctx)
        if not title:
            title = ctx["title"]
    outer = {
        "title": title,
        "panels": panels,
        "goal": "",  # per-panel
    }
    return render_template(tmpl, outer, escape_html=True)


def scaffold_model() -> dict:
    """A blank model an author can fill in. Stable key order."""
    return {
        "title": "Title of the path",
        "goal": "One sentence: who does what, and what is shown at the end.",
        "boxes": [
            {"id": "start", "label": "Start", "level": 1},
            {"id": "middle", "label": "Middle", "level": 1},
            {"id": "end", "label": "End", "level": 1},
        ],
        "arrows": [
            {"id": "a1", "from": "start", "to": "middle", "label": "what moves", "step": 1, "kind": "normal"},
            {"id": "a2", "from": "middle", "to": "end", "label": "the result", "step": 2, "kind": "normal"},
        ],
        "steps": [
            {"n": 1, "arrow": "a1", "text": "Short one-line step.", "level": 1},
            {"n": 2, "arrow": "a2", "text": "Short one-line step.", "level": 1},
        ],
        "risks": ["One risk, one line."],
        "user_impact": ["One impact, one line."],
        "tradeoffs": ["One tradeoff, one line."],
        "glossary": [],
        "legend": "A broken arrow is another path or a failure.",
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_issues(issues: list[Issue], stream) -> None:
    for iss in issues:
        print(str(iss), file=stream)


def _run_check(model_path: Path, lens: dict, common: set[str], stream=None) -> list[Issue]:
    stream = stream or sys.stdout
    model = load_model(model_path)
    issues = check(model, lens, common)
    view = apply_lens(model, lens)
    errs = errors_only(issues)
    warns = [i for i in issues if i.level == "warn"]
    n_prose = prose_word_count(view)
    status = "FAIL" if errs else "OK"
    print(
        f"{status}  {model_path}  lens={lens.get('id')}  "
        f"boxes={len(view['boxes'])}  steps={len(view['steps'])}  "
        f"prose={n_prose}"
        + (f"  issues={len(errs)}" if errs else "")
        + (f"  warnings={len(warns)}" if warns else ""),
        file=stream,
    )
    _print_issues(issues, stream)
    return issues


def _write_out(text: str, output: Path | None) -> None:
    if output is None:
        sys.stdout.write(text)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8", newline="\n")


def _render_checked(model: dict, lens: dict, fmt: str, force: bool, common: set[str], stream=None) -> tuple[str | None, int]:
    stream = stream or sys.stderr
    issues = check(model, lens, common)
    errs = errors_only(issues)
    if errs and not force:
        print(
            f"FAIL  lens={lens.get('id')}  "
            f"refusing to render ({len(errs)} issues); pass --force to override",
            file=stream,
        )
        _print_issues(issues, stream)
        return None, 1
    try:
        text = render(model, lens, fmt)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=stream)
        return None, 2
    return text, 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="explain.py",
        description="Check or render a plain-explain model through a lens.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="Run schema, gap, limit, and vocabulary checks.")
    p_check.add_argument("model", type=Path)
    p_check.add_argument("--lens", required=True, help="Lens id or path to a YAML lens.")

    p_suggest = sub.add_parser(
        "suggest",
        help="Print synonym-based replacements for vocabulary errors (also: lint).",
    )
    p_suggest.add_argument("model", type=Path)
    p_suggest.add_argument("--lens", required=True)
    p_suggest.add_argument("--synonyms", type=Path, default=None)

    # lint is an alias
    p_lint = sub.add_parser("lint", help="Same as check, then suggest replacements.")
    p_lint.add_argument("model", type=Path)
    p_lint.add_argument("--lens", required=True)
    p_lint.add_argument("--synonyms", type=Path, default=None)

    p_render = sub.add_parser("render", help="Render a model through a lens and a template.")
    p_render.add_argument("model", type=Path)
    p_render.add_argument("--lens", default=None)
    p_render.add_argument(
        "--format",
        dest="fmt",
        default=None,
        help="Template name: templates/<format>.tmpl (md, html, html-tabs, ...).",
    )
    p_render.add_argument("-o", "--output", type=Path, default=None)
    p_render.add_argument("--force", action="store_true", help="Render even if checks fail.")
    p_render.add_argument(
        "--all",
        action="store_true",
        dest="all_lenses",
        help="Render every lens in every bundled format (md, html) plus html-tabs. -o is a directory.",
    )

    p_scaf = sub.add_parser("scaffold", help="Write a blank model JSON to fill in.")
    p_scaf.add_argument("-o", "--output", type=Path, default=None)

    args = parser.parse_args(argv)

    if args.cmd == "scaffold":
        text = json.dumps(scaffold_model(), indent=2, ensure_ascii=False) + "\n"
        _write_out(text, args.output)
        return 0

    try:
        common = load_common_words()
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.cmd in ("check", "suggest", "lint", "render"):
        if args.cmd == "render" and args.all_lenses:
            pass  # lens optional
        elif getattr(args, "lens", None) is None and not (
            args.cmd == "render" and args.all_lenses
        ):
            if args.cmd != "render":
                print("error: --lens is required", file=sys.stderr)
                return 2

    if args.cmd == "render" and args.all_lenses:
        if not args.model.exists():
            print(f"error: model not found: {args.model}", file=sys.stderr)
            return 2
        model = load_model(args.model)
        out_dir = args.output or Path("out")
        if out_dir.exists() and out_dir.is_file():
            print("error: --all expects -o to be a directory", file=sys.stderr)
            return 2
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = args.model.stem
        rc = 0
        lenses = []
        for lid in list_lenses():
            try:
                lenses.append(load_lens(lid))
            except (FileNotFoundError, ValueError, YamlError) as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
        for lens in lenses:
            for fmt in ("md", "html"):
                text, code = _render_checked(model, lens, fmt, args.force, common)
                if text is None:
                    rc = code or rc
                    continue
                _write_out(text, out_dir / f"{stem}.{lens['id']}.{fmt}")
        # Combined tabs
        try:
            tabs = render_tabs(model, lenses)
            # Still refuse if any lens fails, unless --force
            any_fail = False
            if not args.force:
                for lens in lenses:
                    if errors_only(check(model, lens, common)):
                        any_fail = True
                        break
            if not any_fail or args.force:
                _write_out(tabs, out_dir / f"{stem}.tabs.html")
        except FileNotFoundError as exc:
            print(f"note: {exc}", file=sys.stderr)
        return rc

    # Commands that need a single lens
    try:
        lens = load_lens(args.lens)
    except (FileNotFoundError, ValueError, YamlError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not args.model.exists():
        print(f"error: model not found: {args.model}", file=sys.stderr)
        return 2

    if args.cmd == "check":
        issues = _run_check(args.model, lens, common)
        return 1 if errors_only(issues) else 0

    if args.cmd in ("suggest", "lint"):
        if args.cmd == "lint":
            issues = _run_check(args.model, lens, common)
        model = load_model(args.model)
        syn = load_synonyms(args.synonyms) if getattr(args, "synonyms", None) else load_synonyms()
        lines = suggest(model, lens, common, syn)
        if lines:
            print("suggestions:")
            for ln in lines:
                print("  " + ln)
        else:
            print("suggestions: none")
        if args.cmd == "lint":
            return 1 if errors_only(issues) else 0
        return 0

    if args.cmd == "render":
        if not args.fmt:
            print("error: --format is required (or use --all)", file=sys.stderr)
            return 2
        model = load_model(args.model)
        if args.fmt == "html-tabs":
            issues = check(model, lens, common)
            if errors_only(issues) and not args.force:
                print("FAIL  refusing to render; pass --force to override", file=sys.stderr)
                _print_issues(issues, sys.stderr)
                return 1
            text = render_tabs(model, [lens])
            _write_out(text, args.output)
            return 0
        text, code = _render_checked(model, lens, args.fmt, args.force, common)
        if text is None:
            return code
        _write_out(text, args.output)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
