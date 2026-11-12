#!/usr/bin/env python3
"""Tiny suite for plain-explain: checks, collapse, vocab, determinism."""

from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from io import StringIO
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import explain as pe  # noqa: E402

EXAMPLE = ROOT / "examples" / "street-reports-report-flow.json"


def _model(**overrides):
    m = pe.scaffold_model()
    m.update(overrides)
    return m


def _issues(model, lens_id="engineer-new"):
    return pe.check(model, pe.load_lens(lens_id), pe.load_common_words())


def _errors(model, lens_id="engineer-new"):
    return pe.errors_only(_issues(model, lens_id))


def _run(argv):
    out, err = StringIO(), StringIO()
    with patch("sys.stdout", out), patch("sys.stderr", err):
        rc = pe.main(argv)
    return rc, out.getvalue(), err.getvalue()


def _write_model(directory: Path, model: dict) -> Path:
    path = directory / "model.json"
    path.write_text(json.dumps(model), encoding="utf-8")
    return path


class SelfLoopAndGaps(unittest.TestCase):
    def test_self_loop_banned(self):
        m = _model(
            boxes=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
            arrows=[
                {"id": "x", "from": "a", "to": "a", "label": "loop", "step": 1},
                {"id": "y", "from": "a", "to": "b", "label": "go", "step": 2},
            ],
            steps=[
                {"n": 1, "arrow": "x", "text": "A does a loop.", "level": 3},
                {"n": 2, "arrow": "y", "text": "A sends to B.", "level": 3},
            ],
        )
        kinds = [i.kind + ":" + i.message for i in _errors(m)]
        self.assertTrue(any("self-loop" in k for k in kinds), kinds)

    def test_min_boxes_product(self):
        # Two visible boxes should fail product min_boxes=3.
        m = _model(
            title="A path",
            goal="A user sends a photo and the report is shown.",
            boxes=[{"id": "a", "label": "Phone", "level": 1}, {"id": "b", "label": "Map", "level": 1}],
            arrows=[{"id": "x", "from": "a", "to": "b", "label": "new report", "step": 1}],
            steps=[{"n": 1, "arrow": "x", "text": "The user sends a report.", "level": 1}],
            user_impact=["No account is needed."],
            legend="",
        )
        errs = _errors(m, "product")
        self.assertTrue(any("min_boxes" in i.message for i in errs), [i.message for i in errs])


class Collapse(unittest.TestCase):
    def setUp(self):
        self.model = pe.load_model(ROOT / "examples" / "street-reports-report-flow.json")

    def test_product_has_a_real_picture(self):
        view = pe.apply_lens(self.model, pe.load_lens("product"))
        ids = {b["id"] for b in view["boxes"]}
        self.assertGreaterEqual(len(ids), 3)
        self.assertIn("phone", ids)
        self.assertIn("page", ids)
        self.assertIn("map", ids)
        self.assertNotIn("server", ids)
        self.assertFalse(any(a["from"] == a["to"] for a in view["arrows"]))
        labels = {(a["from"], a["to"], a["label"]) for a in view["arrows"]}
        self.assertIn(("phone", "page", "photo and place"), labels)
        self.assertIn(("page", "map", "new report"), labels)
        dashed = [a for a in view["arrows"] if pe._is_dashed(a)]
        self.assertTrue(any("Telegram" in (a["label"] or "") for a in dashed))
        self.assertTrue(any(a["to"] == "held" for a in dashed))

    def test_tech_lead_is_coarser_than_engineer(self):
        eng = pe.apply_lens(self.model, pe.load_lens("engineer-new"))
        tl = pe.apply_lens(self.model, pe.load_lens("tech-lead"))
        self.assertLess(len(tl["boxes"]), len(eng["boxes"]))
        tl_ids = {b["id"] for b in tl["boxes"]}
        self.assertEqual(tl_ids, {"client", "service", "storage", "map", "held"})
        self.assertIn("server", {b["id"] for b in eng["boxes"]})
        self.assertNotEqual(pe.mermaid_source(eng), pe.mermaid_source(tl))

    def test_prose_under_caps(self):
        caps = {"product": 45, "tech-lead": 50, "engineer-new": 100}
        for lid, cap in caps.items():
            lens = pe.load_lens(lid)
            self.assertEqual(lens["max_prose_words"], cap)
            self.assertEqual(lens["max_sentences_per_step"], 1)
            view = pe.apply_lens(self.model, lens)
            n = pe.prose_word_count(view)
            self.assertLessEqual(n, cap, f"{lid} prose {n} > {cap}")


class Vocab(unittest.TestCase):
    def test_inflections_and_hyphens_and_numbers(self):
        lex = {"hide", "safe", "photo", "check", "day"} | pe.load_common_words()
        phrases = []
        self.assertEqual(pe.unknown_words("The photo is hidden and safer.", lex, phrases), [])
        self.assertEqual(pe.unknown_words("a photo-check on day 30", lex, phrases), [])
        self.assertEqual(pe.unknown_words("there are 12 reports", lex, phrases), [])
        unknown = pe.unknown_words("uses Kubernetes here", lex, phrases)
        self.assertTrue(any(w == "Kubernetes" for w, _ in unknown), unknown)

    def test_suggest_uses_synonyms(self):
        m = pe.load_model(ROOT / "examples" / "street-reports-report-flow.json")
        m = dict(m)
        m["goal"] = "A user sends a photo and the check fails."
        lines = pe.suggest(m, pe.load_lens("product"))
        blob = "\n".join(lines)
        self.assertIn("fails", blob)
        self.assertIn("does not work", blob)


class Determinism(unittest.TestCase):
    def test_render_twice_identical(self):
        model = pe.load_model(ROOT / "examples" / "street-reports-report-flow.json")
        for lid in ("product", "engineer-new", "tech-lead"):
            lens = pe.load_lens(lid)
            for fmt in ("md", "html"):
                a = pe.render(model, lens, fmt)
                b = pe.render(model, lens, fmt)
                self.assertEqual(a, b, f"{lid} {fmt}")
        tabs_a = pe.render_tabs(model, [pe.load_lens(i) for i in pe.list_lenses()])
        tabs_b = pe.render_tabs(model, [pe.load_lens(i) for i in pe.list_lenses()])
        self.assertEqual(tabs_a, tabs_b)

    def test_example_checks_clean(self):
        model = pe.load_model(ROOT / "examples" / "street-reports-report-flow.json")
        common = pe.load_common_words()
        for lid in ("product", "engineer-new", "tech-lead"):
            errs = pe.errors_only(pe.check(model, pe.load_lens(lid), common))
            self.assertEqual(errs, [], [str(e) for e in errs])


class ScaffoldAndCli(unittest.TestCase):
    def test_scaffold_is_json(self):
        m = pe.scaffold_model()
        json.dumps(m)
        self.assertGreaterEqual(len(m["boxes"]), 3)
        for arrow in m["arrows"]:
            self.assertTrue(arrow.get("actor"), arrow)
            self.assertTrue(arrow.get("action"), arrow)


class ConcreteActors(unittest.TestCase):
    def test_abstract_labels_and_missing_actor_warn(self):
        bad = _model(
            title="A path",
            goal="A user sends a photo.",
            legend="",
        )
        bad["boxes"][0]["label"] = "Export step"
        bad["boxes"][1]["label"] = "Service"
        bad["boxes"][2]["label"] = "Renderer"
        bad["boxes"].append({"id": "menu", "label": "Menu data", "level": 1})
        for arrow in bad["arrows"]:
            arrow.pop("actor", None)
            arrow.pop("action", None)
        issues = _issues(bad)
        warns = [i for i in issues if i.level == "warn" and i.kind == "actors"]
        blob = "\n".join(i.message for i in warns)
        for label in ("Export step", "Service", "Renderer", "Menu data"):
            self.assertIn(label, blob, blob)
        self.assertIn("visitor's browser", blob)
        self.assertIn("GET /about", blob)
        self.assertTrue(any("no actor" in i.message for i in warns), blob)
        self.assertTrue(any("no action" in i.message for i in warns), blob)

        good = _model(
            title="About page",
            goal="A user sends a photo.",
            legend="",
            boxes=[
                {"id": "browser", "label": "Visitor browser", "level": 1},
                {"id": "site", "label": "About page", "level": 1},
                {"id": "owner", "label": "Site owner", "level": 1},
            ],
            arrows=[
                {
                    "id": "a1",
                    "from": "browser",
                    "to": "site",
                    "label": "GET /about",
                    "actor": "visitor's browser",
                    "action": "GET /about",
                    "kind": "normal",
                },
                {
                    "id": "a2",
                    "from": "site",
                    "to": "owner",
                    "label": "HTML coming back",
                    "actor": "about page",
                    "action": "HTML coming back",
                    "kind": "normal",
                },
            ],
            steps=[
                {"n": 1, "arrow": "a1", "text": "The user sends a photo.", "level": 3},
                {"n": 2, "arrow": "a2", "text": "The page shows the report.", "level": 3},
            ],
        )
        good_warns = [i for i in _issues(good) if i.kind == "actors"]
        self.assertEqual(good_warns, [], [str(i) for i in good_warns])

    def test_example_names_concrete_actors(self):
        model = pe.load_model(EXAMPLE)
        for box in model["boxes"]:
            label = box["label"].lower()
            words = label.split()
            self.assertFalse(label.endswith(" step"), box["label"])
            self.assertFalse(any(w in {"service", "renderer", "data"} for w in words), box["label"])
        for arrow in model["arrows"]:
            self.assertTrue((arrow.get("actor") or "").strip(), arrow["id"])
            self.assertTrue((arrow.get("action") or "").strip(), arrow["id"])
        for lid in ("product", "engineer-new", "tech-lead"):
            warns = [i for i in _issues(model, lid) if i.kind == "actors"]
            self.assertEqual(warns, [], [str(i) for i in warns])


class AudienceTerms(unittest.TestCase):
    def _picture(self, **extra):
        m = _model(
            title="A photo",
            goal="A user sends a photo with frobnicate ZXQ.",
            legend="",
            boxes=[
                {"id": "a", "label": "Phone", "level": 1},
                {"id": "b", "label": "Page", "level": 1},
                {"id": "c", "label": "Map", "level": 1},
            ],
            arrows=[
                {
                    "id": "a1",
                    "from": "a",
                    "to": "b",
                    "label": "photo",
                    "actor": "user",
                    "action": "sends photo",
                    "kind": "normal",
                },
                {
                    "id": "a2",
                    "from": "b",
                    "to": "c",
                    "label": "report",
                    "actor": "page",
                    "action": "shows report",
                    "kind": "normal",
                },
            ],
            steps=[
                {"n": 1, "arrow": "a1", "text": "The user sends a photo.", "level": 1},
                {"n": 2, "arrow": "a2", "text": "The page shows the report.", "level": 1},
            ],
            glossary=[],
        )
        m.update(extra)
        return m

    def test_audience_terms_need_no_glossary(self):
        bare = self._picture()
        product = [i for i in _errors(bare, "product") if i.kind == "vocabulary"]
        blob = "\n".join(i.message for i in product)
        self.assertIn("frobnicate", blob)
        self.assertIn("ZXQ", blob)

        allowed = self._picture(audiences={"product": ["frobnicate", "ZXQ"]})
        product_ok = [i for i in _errors(allowed, "product") if i.kind == "vocabulary"]
        ok_blob = "\n".join(i.message for i in product_ok)
        self.assertNotIn("frobnicate", ok_blob, ok_blob)
        self.assertNotIn("ZXQ", ok_blob, ok_blob)
        self.assertEqual(allowed.get("glossary"), [])

        other = [i for i in _errors(allowed, "engineer-new") if i.kind == "vocabulary"]
        self.assertTrue(any("frobnicate" in i.message for i in other), [str(i) for i in other])

    def test_default_tech_words_need_no_glossary(self):
        model = self._picture(goal="A browser sends a cache API request through a queue.")
        blob = "\n".join(i.message for i in _errors(model, "product") if i.kind == "vocabulary")
        for word in ("browser", "cache", "API", "queue", "request"):
            self.assertNotIn(repr(word), blob, blob)
        self.assertEqual(model.get("glossary"), [])
        listed = (ROOT / "tech-words.txt").read_text(encoding="utf-8").lower()
        for banned in ("thunderbolt", "experiment", "\ndm\n", "\nslot\n"):
            self.assertNotIn(banned, "\n" + listed + "\n")

    def test_cli_audience_flag(self):
        model = self._picture(
            goal="A user sends a photo with frobnicate.",
            audiences={"internal": ["frobnicate"]},
        )
        with tempfile.TemporaryDirectory() as d:
            path = _write_model(Path(d), model)
            rc, out, _err = _run(
                ["check", str(path), "--lens", "product", "--audience", "internal"]
            )
        self.assertEqual(rc, 0, out)
        self.assertNotIn("frobnicate", out)


class OneOutput(unittest.TestCase):
    def test_default_render_is_one_lens_with_a_table(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "out.md"
            rc, _stdout, err = _run(["render", str(EXAMPLE), "-o", str(out)])
            self.assertEqual(rc, 0, err)
            text = out.read_text(encoding="utf-8")
            self.assertEqual(text.count("```mermaid"), 1)
            self.assertIn("For: New engineer", text)
            self.assertNotIn("For: Product", text)
            self.assertNotIn("For: Tech lead", text)
            self.assertLess(text.index("| Failure |"), text.index("**Goal.**"))
            self.assertIn("| What can go wrong |", text)
            self.assertIn("Report held for review → Not shown on the map", text)
            self.assertNotIn("not public: not public", text.lower())
            self.assertNotIn("tablist", text)
            self.assertIn("kept:", err)
            self.assertIn("collapsed:", err)
            names = sorted(p.name for p in Path(d).iterdir())
            self.assertEqual(names, ["out.md"])

    def test_tabs_are_opt_in(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            rc, _stdout, err = _run(["render", str(EXAMPLE), "--all", "-o", str(out)])
            self.assertEqual(rc, 0, err)
            tabs = out / "street-reports-report-flow.tabs.html"
            self.assertTrue(tabs.exists(), list(out.iterdir()))
            self.assertIn("tablist", tabs.read_text(encoding="utf-8"))


class CollapsePreview(unittest.TestCase):
    def test_check_prints_each_lens_before_the_verdict(self):
        rc, out, _err = _run(["check", str(EXAMPLE), "--lens", "product"])
        self.assertEqual(rc, 0, out)
        for lid in ("product", "engineer-new", "tech-lead"):
            self.assertIn(f"lens {lid}:", out)
        self.assertLess(out.index("lens tech-lead:"), out.index("OK"))
        self.assertIn("kept:", out)
        self.assertIn("phone -> client", out)
        self.assertIn("collapsed:", out)

    def test_level_filter_does_not_cry_step_not_reached(self):
        model = _model(
            title="A photo",
            goal="A user sends a photo.",
            legend="",
            boxes=[
                {"id": "a", "label": "Phone", "level": 1},
                {"id": "b", "label": "Page", "level": 1},
                {"id": "c", "label": "Map", "level": 1},
            ],
            arrows=[
                {
                    "id": "ab",
                    "from": "a",
                    "to": "b",
                    "label": "photo",
                    "actor": "user",
                    "action": "sends photo",
                    "kind": "normal",
                },
                {
                    "id": "bc",
                    "from": "b",
                    "to": "c",
                    "label": "report",
                    "actor": "page",
                    "action": "shows report",
                    "kind": "normal",
                },
            ],
            steps=[
                {"n": 1, "arrow": "ab", "text": "The user sends a photo.", "level": 3},
                {"n": 2, "arrow": "bc", "text": "The page shows the report.", "level": 1},
            ],
        )
        messages = [i.message for i in _errors(model, "product")]
        self.assertFalse(
            any("not been reached" in m for m in messages),
            messages,
        )

    def test_filtered_step_error_names_the_lens(self):
        model = _model(
            title="A photo",
            goal="A user sends a photo.",
            legend="",
            boxes=[
                {"id": "phone", "label": "Phone", "level": 1},
                {"id": "page", "label": "Page", "level": 1},
                {"id": "map", "label": "Map", "level": 1},
                {"id": "hidden", "label": "Server", "level": 3},
            ],
            arrows=[
                {
                    "id": "open",
                    "from": "phone",
                    "to": "page",
                    "label": "photo",
                    "actor": "user",
                    "action": "sends photo",
                    "kind": "normal",
                },
                {
                    "id": "show",
                    "from": "page",
                    "to": "map",
                    "label": "report",
                    "actor": "page",
                    "action": "shows report",
                    "kind": "normal",
                },
                {
                    "id": "side",
                    "from": "phone",
                    "to": "hidden",
                    "label": "photo",
                    "actor": "user",
                    "action": "stores photo",
                    "kind": "normal",
                },
            ],
            steps=[
                {"n": 1, "arrow": "side", "text": "The user sends a photo.", "level": 3},
                {"n": 2, "arrow": "show", "text": "The page shows the report.", "level": 1},
            ],
        )
        messages = [i.message for i in _errors(model, "product")]
        hit = [m for m in messages if "not been reached" in m]
        self.assertEqual(len(hit), 1, messages)
        self.assertIn("lens product", hit[0])
        self.assertIn("filtered", hit[0])
        self.assertIn("step 1", hit[0])
        self.assertIn("max_level", hit[0])

    def test_collapse_below_useful_size_warns(self):
        model = _model(
            title="A photo",
            goal="A user sends a photo.",
            legend="",
            boxes=[
                {"id": "phone", "label": "Phone", "level": 3, "collapse_to": "client"},
                {"id": "page", "label": "Page", "level": 3, "collapse_to": "client"},
                {"id": "client", "label": "User", "level": 2, "aggregate": True},
                {"id": "map", "label": "Map", "level": 1},
            ],
            arrows=[
                {
                    "id": "a1",
                    "from": "phone",
                    "to": "page",
                    "label": "photo",
                    "actor": "user",
                    "action": "sends photo",
                    "kind": "normal",
                },
                {
                    "id": "a2",
                    "from": "page",
                    "to": "map",
                    "label": "report",
                    "actor": "page",
                    "action": "shows report",
                    "kind": "normal",
                },
            ],
            steps=[
                {"n": 1, "arrow": "a1", "text": "The user sends a photo.", "level": 2},
                {"n": 2, "arrow": "a2", "text": "The page shows the report.", "level": 2},
            ],
        )
        warns = [i for i in _issues(model, "tech-lead") if i.level == "warn"]
        blob = "\n".join(i.message for i in warns)
        self.assertIn("useful size", blob, blob)
        self.assertIn("phone -> client", blob, blob)


class ReusableExport(unittest.TestCase):
    def test_svg_is_standalone_and_deterministic(self):
        with tempfile.TemporaryDirectory() as d:
            first = Path(d) / "one.svg"
            second = Path(d) / "two.svg"
            rc1, _, err1 = _run(
                ["render", str(EXAMPLE), "--lens", "engineer-new", "--format", "svg", "-o", str(first)]
            )
            rc2, _, err2 = _run(
                ["render", str(EXAMPLE), "--lens", "engineer-new", "--format", "svg", "-o", str(second)]
            )
            self.assertEqual(rc1, 0, err1)
            self.assertEqual(rc2, 0, err2)
            text = first.read_text(encoding="utf-8")
            self.assertEqual(text, second.read_text(encoding="utf-8"))
            root = ET.fromstring(text)
            self.assertTrue(root.tag.endswith("svg"))
            self.assertNotIn("mermaid", text.lower())
            self.assertNotIn("<script", text.lower())
            self.assertIn("stroke-dasharray", text)
            self.assertIn("user: photo and place", text)
            self.assertIn("server: Report held for review", text)
            self.assertIn("Report held for review → Not shown on the map", text)
            self.assertNotIn("not public: not public", text.lower())
            width = float(root.get("width"))
            height = float(root.get("height"))
            self.assertGreater(width, 200)
            self.assertGreater(height, 120)

    def test_structure_is_the_lens_picture(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "picture.json"
            rc, _, err = _run(
                [
                    "render",
                    str(EXAMPLE),
                    "--lens",
                    "product",
                    "--format",
                    "structure",
                    "-o",
                    str(out),
                ]
            )
            self.assertEqual(rc, 0, err)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["lens_id"], "product")
            ids = [b["id"] for b in data["boxes"]]
            self.assertIn("phone", ids)
            self.assertIn("page", ids)
            self.assertIn("map", ids)
            self.assertNotIn("server", ids)
            self.assertNotIn("service", ids)
            self.assertTrue(data["arrows"])
            self.assertTrue(data["steps"])
            self.assertLessEqual(len(data["steps"]), 3)
            for arrow in data["arrows"]:
                self.assertIn("from", arrow)
                self.assertIn("to", arrow)
                self.assertIn("actor", arrow)
                self.assertTrue(arrow["action"])
                self.assertIn("kind", arrow)
            kinds = {a["kind"] for a in data["arrows"]}
            self.assertIn("failure", kinds)


def _svg_segments(d: str):
    nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", d)]
    if "Q" in d:
        x1, y1, cx, cy, x2, y2 = nums[:6]
        pts = []
        steps = 8
        for i in range(steps + 1):
            t = i / steps
            u = 1 - t
            pts.append(
                (
                    u * u * x1 + 2 * u * t * cx + t * t * x2,
                    u * u * y1 + 2 * u * t * cy + t * t * y2,
                )
            )
        return list(zip(pts, pts[1:]))
    return [((nums[0], nums[1]), (nums[2], nums[3]))]


def _rects_overlap(a, b) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return min(ax + aw, bx + bw) - max(ax, bx) > 0.5 and min(ay + ah, by + bh) - max(ay, by) > 0.5


def _seg_hits_rect(x1, y1, x2, y2, rect) -> bool:
    rx, ry, rw, rh = rect

    def inside(px, py):
        return rx < px < rx + rw and ry < py < ry + rh

    if inside(x1, y1) or inside(x2, y2):
        return True

    def crosses(ax, ay, bx, by, cx, cy, dx, dy):
        def orient(px, py, qx, qy, sx, sy):
            return (qy - py) * (sx - qx) - (qx - px) * (sy - qy)

        return (
            orient(ax, ay, bx, by, cx, cy) * orient(ax, ay, bx, by, dx, dy) < 0
            and orient(cx, cy, dx, dy, ax, ay) * orient(cx, cy, dx, dy, bx, by) < 0
        )

    corners = ((rx, ry), (rx + rw, ry), (rx + rw, ry + rh), (rx, ry + rh))
    for i in range(4):
        ax, ay = corners[i]
        bx, by = corners[(i + 1) % 4]
        if crosses(x1, y1, x2, y2, ax, ay, bx, by):
            return True
    return False


class SvgLayout(unittest.TestCase):
    def test_labels_do_not_cover_lines_or_each_other(self):
        model = pe.load_model(EXAMPLE)
        svg = pe.render(model, pe.load_lens("engineer-new"), "svg")
        root = ET.fromstring(svg)
        ns = "{http://www.w3.org/2000/svg}"
        labels = []
        for el in root.iter(ns + "rect"):
            if el.get("fill") == "#f4f0e7" and el.get("height") == "16":
                labels.append(
                    (float(el.get("x")), float(el.get("y")), float(el.get("width")), float(el.get("height")))
                )
        self.assertGreaterEqual(len(labels), 4)
        for i, a in enumerate(labels):
            for b in labels[i + 1 :]:
                self.assertFalse(_rects_overlap(a, b), (a, b))
        segments = []
        for el in root.iter(ns + "path"):
            if not el.get("stroke"):
                continue
            segments.extend(_svg_segments(el.get("d")))
        for rect in labels:
            for (x1, y1), (x2, y2) in segments:
                self.assertFalse(_seg_hits_rect(x1, y1, x2, y2, rect), rect)


class FailureLine(unittest.TestCase):
    def test_action_that_repeats_the_box_is_shown_once(self):
        model = _model(
            title="A photo",
            goal="A user sends a photo.",
            legend="",
            boxes=[
                {"id": "phone", "label": "Phone", "level": 1},
                {"id": "page", "label": "Page", "level": 1},
                {"id": "held", "label": "Not public", "level": 1},
            ],
            arrows=[
                {
                    "id": "go",
                    "from": "phone",
                    "to": "page",
                    "label": "photo",
                    "actor": "user",
                    "action": "sends photo",
                    "kind": "normal",
                },
                {
                    "id": "stop",
                    "from": "page",
                    "to": "held",
                    "label": "not public",
                    "actor": "page",
                    "action": "not public",
                    "kind": "failure",
                },
            ],
            steps=[
                {"n": 1, "arrow": "go", "text": "The user sends a photo.", "level": 1},
            ],
            user_impact=["The photo is not public."],
            risks=[],
            tradeoffs=[],
        )
        text = pe.render(model, pe.load_lens("product"), "md")
        self.assertIn("Page → Not public", text)
        self.assertNotIn("not public: not public", text.lower())


class ProseDensity(unittest.TestCase):
    def _at_cap(self, step_text: str) -> tuple[dict, dict]:
        lens = pe.load_lens("engineer-new")
        model = _model(
            title="Photo report",
            goal="A user sends a photo.",
            legend="",
            boxes=[
                {"id": "a", "label": "Phone", "level": 1},
                {"id": "b", "label": "Page", "level": 1},
                {"id": "c", "label": "Map", "level": 1},
            ],
            arrows=[
                {
                    "id": "a1",
                    "from": "a",
                    "to": "b",
                    "label": "photo",
                    "actor": "user",
                    "action": "sends photo",
                    "kind": "normal",
                },
                {
                    "id": "a2",
                    "from": "b",
                    "to": "c",
                    "label": "report",
                    "actor": "page",
                    "action": "shows report",
                    "kind": "normal",
                },
            ],
            steps=[
                {"n": 1, "arrow": "a1", "text": step_text, "level": 3},
                {"n": 2, "arrow": "a2", "text": "The page shows the report.", "level": 3},
            ],
            risks=["The photo is not public."],
            user_impact=[],
            tradeoffs=[],
        )
        cap = lens["max_prose_words"]
        for _ in range(cap + 5):
            n = pe.prose_word_count(pe.apply_lens(model, lens))
            if n == cap:
                break
            if n > cap:
                raise AssertionError(f"prose {n} overshot cap {cap}")
            model["goal"] += " photo"
        else:
            raise AssertionError("could not pad prose to the cap")
        self.assertEqual(pe.prose_word_count(pe.apply_lens(model, lens)), cap)
        return model, lens

    def test_word_cap_is_not_a_pass_for_two_sentences(self):
        dense, lens = self._at_cap("The user sends a photo. The page takes it.")
        messages = [i.message for i in pe.errors_only(pe.check(dense, lens, pe.load_common_words()))]
        self.assertTrue(any("sentence" in m and "not a pass" in m for m in messages), messages)

        tight, lens = self._at_cap("The user sends a photo and the page takes it.")
        tight_msgs = [i.message for i in pe.errors_only(pe.check(tight, lens, pe.load_common_words()))]
        self.assertFalse(any("sentence" in m for m in tight_msgs), tight_msgs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
