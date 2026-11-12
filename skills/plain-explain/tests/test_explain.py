#!/usr/bin/env python3
"""Tiny suite for plain-explain: checks, collapse, vocab, determinism."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import explain as pe  # noqa: E402


def _model(**overrides):
    m = pe.scaffold_model()
    m.update(overrides)
    return m


def _issues(model, lens_id="engineer-new"):
    return pe.check(model, pe.load_lens(lens_id), pe.load_common_words())


def _errors(model, lens_id="engineer-new"):
    return pe.errors_only(_issues(model, lens_id))


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
        for lid, cap in (("product", 60), ("tech-lead", 80), ("engineer-new", 150)):
            view = pe.apply_lens(self.model, pe.load_lens(lid))
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
