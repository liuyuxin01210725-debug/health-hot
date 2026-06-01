#!/usr/bin/env python3
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
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

    def test_detail_distinguishes_collection_date_from_source_date(self):
        item = valid_item()
        page = build.detail_page(item, [])
        self.assertIn("本站收录 2026-05-31", page)
        self.assertNotIn("原文日期 2026-05-31", page)
        item["source_published_at"] = "2026-05-01"
        page = build.detail_page(item, [])
        self.assertIn("原文日期 2026-05-01", page)


class CollectTests(unittest.TestCase):
    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def geturl(self):
            return "https://example.com/feed"

        def read(self, _):
            return b"ok"

    def test_title_relevance_hint(self):
        source = {"title_terms": ["creatine"]}
        self.assertEqual(collect.relevance_hint(source, {"title": "Creatine supplementation review"}), "title_match")
        self.assertEqual(collect.relevance_hint(source, {"title": "Astaxanthin supplementation review"}), "query_match_only")

    def test_canonical_pubmed_key(self):
        entry = {"url": "https://pubmed.ncbi.nlm.nih.gov/42197030/"}
        self.assertEqual(collect.canonical_id(entry), "pmid:42197030")

    def test_official_catalog_accepts_whitelisted_specific_page(self):
        entries = collect.official_catalog_entries({
            "role": "anchor",
            "entries": [{
                "title": "Physical activity",
                "url": "https://www.who.int/news-room/fact-sheets/detail/physical-activity",
                "desc": "WHO fact sheet",
                "category": "运动",
            }],
        })
        self.assertEqual(entries[0]["evidence"], "guideline")
        self.assertEqual(entries[0]["category"], "运动")

    def test_official_catalog_rejects_untrusted_or_spoofed_page(self):
        for url in (
            "https://example.com/news-room/fact-sheets/detail/physical-activity",
            "https://evil.example@www.who.int/news-room/fact-sheets/detail/physical-activity",
            "https://www.who.int/",
        ):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    collect.official_catalog_entries({
                        "role": "anchor",
                        "entries": [{"title": "fixture", "url": url, "desc": "fixture"}],
                    })

    def test_configured_official_catalogs_are_whitelisted(self):
        with open(collect.SRC, encoding="utf-8") as fh:
            sources = json.load(fh)["sources"]
        catalogs = [source for source in sources if source.get("type") == "official_catalog"]
        self.assertGreaterEqual(len(catalogs), 1)
        for source in catalogs:
            with self.subTest(source=source.get("name")):
                self.assertTrue(collect.official_catalog_entries(source))

    def test_default_collection_excludes_opt_in_discovery_sources(self):
        sources = [
            {"name": "WHO", "type": "official_catalog"},
            {"name": "Huberman", "type": "youtube", "default_enabled": False},
        ]
        self.assertEqual([s["name"] for s in collect.select_sources(sources, [])], ["WHO"])
        self.assertEqual([s["name"] for s in collect.select_sources(sources, ["--include-discovery"])],
                         ["WHO", "Huberman"])
        self.assertEqual([s["name"] for s in collect.select_sources(sources, ["Huberman"])], ["Huberman"])

    def test_fetch_retries_transient_rate_limit(self):
        rate_limit = urllib.error.HTTPError(
            "https://example.com/feed", 429, "Too Many Requests", {"Retry-After": "0"}, None
        )
        with mock.patch.object(collect, "_last_fetch", [-10.0]), \
             mock.patch.object(collect.time, "monotonic", side_effect=[0.0, 0.0, 10.0, 10.0]), \
             mock.patch.object(collect.time, "sleep") as sleep, \
             mock.patch.object(collect.urllib.request, "urlopen", side_effect=[rate_limit, self._Response()]) as urlopen:
            self.assertEqual(collect.fetch("https://example.com/feed"), b"ok")
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(2.0)


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
