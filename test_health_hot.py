#!/usr/bin/env python3
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import build
import collect


def valid_item():
    return {
        "_file": "fixture.json",
        "title": "fixture",
        "source_url": "https://pubmed.ncbi.nlm.nih.gov/123/",
        "slug": "fixture",
        "category": "运动",
        "evidence": "meta",
        "summary": "summary",
        "source": "PubMed fixture",
        "date": "2026-05-31",
        "reviewed_at": "2026-05-31",
        "status": "reviewed",
        "conclusion": "conclusion",
        "population": "population",
        "caveats": "caveats",
        "evidence_source_urls": ["https://pubmed.ncbi.nlm.nih.gov/123/"],
    }


class BuildValidationTests(unittest.TestCase):
    def assert_blocked(self, **patch):
        item = valid_item()
        item.update(patch)
        good, blocked = build.validate([item])
        self.assertFalse(good)
        self.assertTrue(blocked)

    def test_valid_item_passes(self):
        good, blocked = build.validate([valid_item()])
        self.assertEqual(len(good), 1)
        self.assertFalse(blocked)

    def test_structured_fields_are_required(self):
        for key in ("conclusion", "population", "caveats"):
            with self.subTest(key=key):
                self.assert_blocked(**{key: ""})

    def test_taxonomy_is_closed(self):
        self.assert_blocked(category="随便写")

    def test_evidence_urls_reject_discovery_sources(self):
        self.assert_blocked(evidence_source_urls=["https://www.youtube.com/watch?v=1"])

    def test_url_parser_rejects_spoofs(self):
        for url in ("https://?q=x", "https://good.example\\@evil.example/x", "https://user@evil.example/x"):
            with self.subTest(url=url):
                self.assertFalse(build._is_http_url(url))

    def test_official_guideline_page_is_an_evidence_anchor(self):
        url = "https://www.who.int/news-room/fact-sheets/detail/healthy-diet"
        self.assertTrue(build._is_study_url(url))


class FeedTrustTests(unittest.TestCase):
    def test_curated_feed_does_not_present_discovery_as_evidence(self):
        item = valid_item()
        item.update({
            "source_url": "https://www.youtube.com/watch?v=1",
            "discovery_source_url": "https://www.youtube.com/watch?v=1",
            "evidence_source_urls": [],
        })
        claim = build.claims_feed([item])["claims"][0]
        self.assertEqual(claim["verification_status"], "curated_pending_evidence")
        self.assertEqual(claim["evidence_source_urls"], [])
        self.assertEqual(claim["discovery_source_url"], "https://www.youtube.com/watch?v=1")

    def test_manual_verified_flag_cannot_bypass_missing_evidence(self):
        item = valid_item()
        item.update({
            "source_url": "https://www.youtube.com/watch?v=1",
            "evidence_source_urls": [],
            "verification_status": "verified",
        })
        self.assertEqual(build.verification_status(item), "curated_pending_evidence")


class RenderDesignTests(unittest.TestCase):
    def test_trust_badges_keep_verified_and_pending_distinct(self):
        self.assertIn('class="trust verified"', build.trust_badge("verified"))
        self.assertIn('class="trust pending"', build.trust_badge("curated_pending_evidence"))

    def test_strength_meter_uses_seven_bars_and_expected_fill(self):
        meter = build.strength_meter("expert")
        self.assertEqual(meter.count("<i"), 7)
        self.assertEqual(meter.count('class="on"'), 3)


class CollectTests(unittest.TestCase):
    def test_title_relevance_hint(self):
        source = {"title_terms": ["creatine"]}
        self.assertEqual(collect.relevance_hint(source, {"title": "Creatine supplementation review"}), "title_match")
        self.assertEqual(collect.relevance_hint(source, {"title": "Astaxanthin supplementation review"}), "query_match_only")

    def test_canonical_pubmed_key(self):
        entry = {"url": "https://pubmed.ncbi.nlm.nih.gov/42197030/"}
        self.assertEqual(collect.canonical_id(entry), "pmid:42197030")


class BuildFailSafeTests(unittest.TestCase):
    def test_blocked_item_does_not_replace_existing_docs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data = root / "items"
            docs = root / "docs"
            data.mkdir()
            docs.mkdir()
            (docs / "SENTINEL.txt").write_text("keep-old-site\n")
            item = valid_item()
            item["status"] = "draft"
            item.pop("_file")
            (data / "fixture.json").write_text(json.dumps(item, ensure_ascii=False))
            with mock.patch.object(build, "DATA", os.fspath(data)), \
                 mock.patch.object(build, "OUT", os.fspath(docs)), \
                 mock.patch.object(build, "CLAIMS", os.fspath(docs / "claims")), \
                 mock.patch.object(sys, "argv", ["build.py"]):
                with contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(SystemExit) as ex:
                        build.main()
            self.assertEqual(ex.exception.code, 1)
            self.assertEqual((docs / "SENTINEL.txt").read_text(), "keep-old-site\n")
            self.assertFalse(Path(os.fspath(docs) + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
