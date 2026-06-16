#!/usr/bin/env python3
import contextlib
import datetime
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
import audit_library


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
        self.assertTrue(build._is_evidence_url(url))
        self.assertTrue(build._is_official_url(url))
        self.assertFalse(build._is_research_url(url))


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

    def test_feed_distinguishes_research_official_and_frontier_basis(self):
        research = build.claims_feed([valid_item()])["claims"][0]
        self.assertEqual(research["verification_basis"], "study_supported")
        self.assertEqual(research["verification_basis_label"], "研究支持")

        official_item = valid_item()
        official_item.update({
            "source_url": "https://www.who.int/news-room/fact-sheets/detail/healthy-diet",
            "evidence_source_urls": ["https://www.who.int/news-room/fact-sheets/detail/healthy-diet"],
        })
        official = build.claims_feed([official_item])["claims"][0]
        self.assertEqual(official["verification_basis"], "official_basis")
        self.assertEqual(official["verification_basis_label"], "官方依据")

        frontier_item = valid_item()
        frontier_item.update({
            "source_url": "https://www.youtube.com/watch?v=1",
            "evidence_source_urls": [],
        })
        frontier = build.claims_feed([frontier_item])["claims"][0]
        self.assertEqual(frontier["verification_basis"], "frontier_pending")
        self.assertEqual(frontier["verification_basis_label"], "前沿待核")


class RenderDesignTests(unittest.TestCase):
    def test_trust_badges_keep_three_basis_types_distinct(self):
        self.assertIn('class="trust verified"', build.trust_badge("study_supported"))
        self.assertIn("研究支持", build.trust_badge("study_supported"))
        self.assertIn('class="trust official"', build.trust_badge("official_basis"))
        self.assertIn("官方依据", build.trust_badge("official_basis"))
        self.assertIn('class="trust pending"', build.trust_badge("frontier_pending"))
        self.assertIn("前沿待核", build.trust_badge("frontier_pending"))

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

    def test_empty_search_can_use_real_submit_endpoint(self):
        with mock.patch.object(build, "SUBMIT_ENDPOINT", "https://submit.example/submit"):
            page = build.render_all([valid_item()])
        self.assertIn('const SUBMIT_ENDPOINT="https://submit.example/submit";', page)
        self.assertIn("提交这条说法待核", page)
        self.assertIn("只有点击提交才会发送", page)

    def test_empty_search_does_not_fake_local_submission(self):
        with mock.patch.object(build, "SUBMIT_ENDPOINT", ""):
            page = build.render_all([valid_item()])
        self.assertNotIn("已记在本机", page)
        self.assertNotIn("localStorage", page)
        self.assertIn("未配置一键提交接收端", page)

    def test_default_empty_search_uses_deployed_submit_endpoint(self):
        page = build.render_all([valid_item()])
        self.assertIn(build.DEFAULT_SUBMIT_ENDPOINT, page)
        self.assertIn("提交这条说法待核", page)
        self.assertNotIn("未配置一键提交接收端", page)

    def test_cloudflare_analytics_is_silent_without_token(self):
        with mock.patch.object(build, "CF_ANALYTICS_TOKEN", ""):
            self.assertEqual(build.cf_analytics_tag(), "")
            page = build.shell("fixture", "精选", "<p>body</p>")
        self.assertNotIn("cloudflareinsights.com", page)
        self.assertNotIn("data-cf-beacon", page)

    def test_cloudflare_analytics_escapes_token(self):
        tag = build.cf_analytics_tag("abc'</script><b>")
        self.assertIn("https://static.cloudflareinsights.com/beacon.min.js", tag)
        self.assertIn("data-cf-beacon='", tag)
        self.assertIn("abc&#39;<\\/script><b>", tag)
        self.assertNotIn("abc'</script><b>", tag)


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

    def test_feed_extracts_citation_urls_for_review(self):
        raw = b"""<rss><channel><item><title>fixture</title><link>https://example.com/post</link>
        <description><![CDATA[Read <a href="https://pubmed.ncbi.nlm.nih.gov/123/">study</a>
        and https://doi.org/10.1000/example.]]></description></item></channel></rss>"""
        item = collect.parse_feed(raw)[0]
        self.assertEqual(item["citation_urls"], [
            "https://pubmed.ncbi.nlm.nih.gov/123/",
            "https://doi.org/10.1000/example",
        ])
        self.assertTrue(collect.likely_reference_url("https://pubmed.ncbi.nlm.nih.gov/123/"))
        self.assertTrue(collect.likely_reference_url("https://doi.org/10.1000/example"))
        self.assertFalse(collect.likely_reference_url("https://drinkag1.com/huberman"))

    def test_expert_page_enrichment_only_keeps_likely_references(self):
        source = {"reference_page_hosts": ["expert.example"]}
        entry = {"url": "https://youtube.example/watch", "citation_urls": ["https://expert.example/episode/1"]}
        page = b"""<a href="https://pubmed.ncbi.nlm.nih.gov/123/">study</a>
        <a href="https://sponsor.example/sale">sponsor</a>"""
        with mock.patch.object(collect, "fetch", return_value=page) as fetch:
            detail, citations, error = collect.enrich_reference_urls(source, entry)
        self.assertEqual(detail, "https://expert.example/episode/1")
        self.assertEqual(citations, ["https://pubmed.ncbi.nlm.nih.gov/123/"])
        self.assertEqual(error, "")
        fetch.assert_called_once_with(
            "https://expert.example/episode/1",
            attempts=1,
            timeout=12,
            allowed_final_hosts={"expert.example"},
        )

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

    def test_china_cdc_guideline_page_is_an_evidence_anchor(self):
        url = "https://en.chinacdc.cn/health_topics/nutrition_health/202206/t20220616_259702.html"
        entries = collect.official_catalog_entries({
            "role": "anchor",
            "entries": [{"title": "Dietary guidelines", "url": url, "desc": "China CDC guideline"}],
        })
        self.assertEqual(entries[0]["evidence"], "guideline")
        self.assertTrue(build._is_evidence_url(url))
        self.assertTrue(build._is_official_url(url))

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

    def test_default_collection_includes_trusted_experts_but_excludes_opt_in_radar(self):
        sources = [
            {"name": "WHO", "type": "official_catalog"},
            {"name": "Huberman", "type": "youtube", "role": "discovery", "default_enabled": True},
            {"name": "Bryan", "type": "youtube", "role": "radar", "default_enabled": False},
        ]
        self.assertEqual([s["name"] for s in collect.select_sources(sources, [])], ["WHO", "Huberman"])
        self.assertEqual([s["name"] for s in collect.select_sources(sources, ["--include-discovery"])],
                         ["WHO", "Huberman", "Bryan"])
        self.assertEqual([s["name"] for s in collect.select_sources(sources, ["Huberman"])], ["Huberman"])

    def test_only_discovery_and_radar_failures_can_be_non_blocking(self):
        self.assertTrue(collect.failure_is_warning({"role": "discovery", "failure_policy": "warn"}))
        self.assertTrue(collect.failure_is_warning({"role": "radar", "failure_policy": "warn"}))
        self.assertFalse(collect.failure_is_warning({"role": "anchor", "failure_policy": "warn"}))

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

    def test_pending_claims_read_label_and_title_fallback(self):
        def fake_run(command, **_):
            if "--label" in command:
                payload = [
                    {"number": 1, "title": "待核说法：肌酸伤肾吗", "body": "from label", "url": "https://github.test/1"},
                    {"number": 2, "title": "待核说法：酵素排毒吗", "body": "dupe", "url": "https://github.test/2"},
                ]
            else:
                payload = [
                    {"number": 2, "title": "待核说法：酵素排毒吗", "body": "dupe", "url": "https://github.test/2"},
                    {"number": 3, "title": "待核说法：酸碱体质是真的吗", "body": "from title", "url": "https://github.test/3"},
                ]
            return mock.Mock(stdout=json.dumps(payload, ensure_ascii=False))

        with mock.patch("shutil.which", return_value="/usr/bin/gh"), \
             mock.patch("subprocess.run", side_effect=fake_run):
            claims = collect.fetch_pending_claims()
        self.assertEqual([claim["title"] for claim in claims], ["肌酸伤肾吗", "酵素排毒吗", "酸碱体质是真的吗"])
        self.assertTrue(all(claim["needs_semantic_filter"] for claim in claims))


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


class LibraryAuditTests(unittest.TestCase):
    def test_audit_treats_official_site_antibot_codes_as_restricted(self):
        for code in (412, 445):
            with self.subTest(code=code), mock.patch.object(
                audit_library.urllib.request,
                "urlopen",
                side_effect=urllib.error.HTTPError("https://example.com", code, "restricted", {}, None),
            ):
                self.assertEqual(audit_library.check_url("https://example.com")["status"], "restricted")

    def test_audit_reports_pending_official_and_review_due(self):
        item = valid_item()
        item["reviewed_at"] = "2026-01-01"
        pending = valid_item()
        pending.update({
            "slug": "pending",
            "title": "pending",
            "source_url": "https://example.com/article",
            "evidence_source_urls": [],
            "reviewed_at": "2026-06-01",
        })
        audit = audit_library.audit_items(
            [item, pending],
            today=datetime.date(2026, 8, 1),
            stale_days=180,
        )
        self.assertEqual(audit["counts"]["items"], 2)
        self.assertEqual(audit["counts"]["verified"], 1)
        self.assertEqual(audit["counts"]["pending_evidence"], 1)
        self.assertEqual(audit["counts"]["official_source_items"], 0)
        self.assertEqual(audit["counts"]["review_due"], 1)

    def test_audit_counts_official_guideline_item(self):
        item = valid_item()
        item.update({
            "source_url": "https://www.who.int/news-room/fact-sheets/detail/healthy-diet",
            "evidence_source_urls": ["https://www.who.int/news-room/fact-sheets/detail/healthy-diet"],
        })
        audit = audit_library.audit_items([item], today=datetime.date(2026, 6, 1))
        self.assertEqual(audit["counts"]["official_source_items"], 1)


class StrongReviewGateTests(unittest.TestCase):
    """部署闸门第二段——强审硬锁（build.strong_review_gate）。
    覆盖 = PASS 记录(sha 匹配) 或 grandfather 固化(sha 匹配)；其余一律拦下。"""

    def item(self, slug="x", sha="sha-cur"):
        it = valid_item()
        it.update({"slug": slug, "_file": slug + ".json", "_content_sha": sha})
        return it

    def test_grandfathered_unchanged_passes(self):
        it = self.item(sha="sha-cur")
        self.assertIsNone(build.strong_review_status(it, {}, {"x": "sha-cur"}))
        self.assertEqual(build.strong_review_gate([it], {}, {"x": "sha-cur"}), [])

    def test_new_item_is_blocked(self):
        it = self.item(slug="brand-new", sha="sha-cur")
        self.assertIsNotNone(build.strong_review_status(it, {}, {}))
        self.assertEqual(len(build.strong_review_gate([it], {}, {})), 1)

    def test_edited_grandfathered_item_is_blocked(self):
        # 固化时 sha 是 sha-old，正文改后变 sha-new → 脱离 grandfather → 必须重审
        it = self.item(sha="sha-new")
        why = build.strong_review_status(it, {}, {"x": "sha-old"})
        self.assertIsNotNone(why)
        self.assertIn("已变更", why)

    def test_passed_review_with_matching_sha_passes(self):
        it = self.item(sha="sha-cur")
        audit = {"x": {"verdict": "PASS", "content_sha": "sha-cur"}}
        self.assertIsNone(build.strong_review_status(it, audit, {}))

    def test_passed_review_but_edited_afterwards_is_blocked(self):
        it = self.item(sha="sha-new")
        audit = {"x": {"verdict": "PASS", "content_sha": "sha-old"}}
        why = build.strong_review_status(it, audit, {})
        self.assertIsNotNone(why)
        self.assertIn("已变更", why)

    def test_non_pass_verdict_is_blocked(self):
        it = self.item(sha="sha-cur")
        audit = {"x": {"verdict": "FIX", "content_sha": "sha-cur"}}
        why = build.strong_review_status(it, audit, {})
        self.assertIsNotNone(why)
        self.assertIn("FIX", why)

    def test_empty_state_fails_closed(self):
        # 两个账本都空（缺失/损坏）→ 不静默放行，全部拦下
        items = [self.item(slug="a", sha="s1"), self.item(slug="b", sha="s2")]
        self.assertEqual(len(build.strong_review_gate(items, {}, {})), 2)

    def test_audit_verdict_overrides_grandfather(self):
        # 回归：固化条目后来被标 FIX/BLOCK，即便正文没变，也必须拦——audit 权威，grandfather 不得洗白。
        it = self.item(slug="x", sha="sha-cur")
        gf = {"x": "sha-cur"}  # 固化命中（正文未变）
        for verdict in ("FIX", "BLOCK"):
            with self.subTest(verdict=verdict):
                audit = {"x": {"verdict": verdict, "content_sha": "sha-cur"}}
                why = build.strong_review_status(it, audit, gf)
                self.assertIsNotNone(why, f"{verdict}+grandfather 命中竟被放行")
                self.assertIn(verdict, why)

    def test_stale_pass_not_laundered_by_grandfather(self):
        # 回归：PASS 记录是旧 sha，正文已改成 grandfather 当前 sha——audit 先判定，必须拦。
        it = self.item(slug="x", sha="sha-cur")
        audit = {"x": {"verdict": "PASS", "content_sha": "sha-old"}}
        gf = {"x": "sha-cur"}
        why = build.strong_review_status(it, audit, gf)
        self.assertIsNotNone(why)
        self.assertIn("已变更", why)


class WorkerCorsConfigTests(unittest.TestCase):
    """离线回归：提交端 CORS 白名单必须含正式站 Origin，
    否则正式站（health-hot.vercel.app）的「搜索无结果→一键提交」会被浏览器 CORS 拦死。"""
    PROD_ORIGIN = "https://health-hot.vercel.app"
    ROOT = Path(__file__).resolve().parent

    def test_wrangler_vars_allow_production_origin(self):
        import tomllib
        with open(self.ROOT / "submit-worker" / "wrangler.toml", "rb") as fh:
            cfg = tomllib.load(fh)
        origins = [o.strip() for o in cfg["vars"]["ALLOWED_ORIGINS"].split(",")]
        self.assertIn(self.PROD_ORIGIN, origins,
                      "wrangler.toml ALLOWED_ORIGINS 缺正式站，部署后正式站提交会被 CORS 拦")

    def test_worker_default_allowlist_has_production_origin(self):
        # DEFAULT_ALLOWED_ORIGINS 是 env 未设时的兜底，也必须含正式站
        src = (self.ROOT / "submit-worker" / "src" / "worker.js").read_text(encoding="utf-8")
        self.assertIn(self.PROD_ORIGIN, src)

    def test_worker_env_allowlist_extends_defaults_not_replaces_them(self):
        # 回归：Cloudflare Pages 面板里的旧 ALLOWED_ORIGINS 不应覆盖掉代码里的生产默认源。
        # 允许 env 扩展白名单，但 DEFAULT_ALLOWED_ORIGINS 必须始终并入。
        src = (self.ROOT / "submit-worker" / "src" / "worker.js").read_text(encoding="utf-8")
        self.assertIn("...DEFAULT_ALLOWED_ORIGINS", src)
        self.assertIn("...configured", src)
        self.assertNotIn("return configured.length ? configured : DEFAULT_ALLOWED_ORIGINS;", src)


class SkillDataSourceTests(unittest.TestCase):
    """Skill 数据源必须指向受 build.py 闸门保护的 Vercel，而非直接 serve docs/ 的 GitHub Pages。"""
    ROOT = Path(__file__).resolve().parent

    def test_skill_points_to_gated_vercel_feed(self):
        text = (self.ROOT / "skill" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("https://health-hot.vercel.app/claims.json", text)
        self.assertNotIn("github.io/health-hot/claims.json", text,
                         "Skill 仍指向 GitHub Pages（不过 build.py 闸门）")


sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
import pending_dashboard as pd  # noqa: E402


class PendingDashboardTests(unittest.TestCase):
    """待核管理面板的纯解析函数（不依赖 gh）。"""

    BODY = ("用户在站内搜索无结果后主动提交了这条待核说法。\n"
            "- 说法：维生素C 长结石吗\n"
            "- 来源页面：https://health-hot.vercel.app/all.html?q=%E7%BB%B4%E7%94%9F%E7%B4%A0C\n"
            "- 提交时间：2026-06-05T12:33:46.932Z\n"
            "隐私边界：……")

    def test_parse_body_extracts_fields(self):
        p = pd.parse_body(self.BODY)
        self.assertEqual(p["claim"], "维生素C 长结石吗")
        self.assertEqual(p["submitted_at"], "2026-06-05T12:33:46.932Z")
        self.assertIn("q=", p["source_page"])

    def test_parse_body_tolerates_missing_source_page(self):
        body = "用户……。\n- 说法：只有说法没有来源\n- 提交时间：2026-06-04T00:00:00Z\n隐私边界：…"
        p = pd.parse_body(body)
        self.assertEqual(p["claim"], "只有说法没有来源")
        self.assertEqual(p["source_page"], "")

    def test_missed_query_decodes_q_param(self):
        self.assertEqual(pd.missed_query("https://x/all.html?q=Vc%E9%95%BF%E7%BB%93%E7%9F%B3"),
                         "Vc长结石")
        self.assertEqual(pd.missed_query(""), "")
        self.assertEqual(pd.missed_query("https://x/all.html"), "")

    def test_classify_status_label_beats_state(self):
        self.assertEqual(pd.classify_status("OPEN", []), pd.STATUS_PENDING)
        self.assertEqual(pd.classify_status("CLOSED", []), pd.STATUS_CLOSED_UNMARKED)
        self.assertEqual(pd.classify_status("CLOSED", ["待核说法", "已入库"]), pd.STATUS_INGESTED)
        self.assertEqual(pd.classify_status("OPEN", ["已拒绝"]), pd.STATUS_REJECTED)

    def test_resubmit_count_only_marker_comments(self):
        comments = [{"body": "🔁 同一说法再次提交 · 2026-…"}, {"body": "普通讨论"},
                    {"body": " 🔁 又一次"}]
        self.assertEqual(pd.resubmit_count(comments), 2)
        self.assertEqual(pd.resubmit_count([]), 0)

    def test_group_key_normalizes_variants(self):
        self.assertEqual(pd.group_key("维生素C，长结石吗？"), pd.group_key("维生素c长结石吗"))
        self.assertEqual(pd.group_key("Creatine  Safe?"), pd.group_key("creatinesafe"))

    def test_build_groups_sums_count_across_regimes(self):
        # 同一归一化说法的两条 issue：去重前的两条独立 + 其中一条带 1 个 🔁 → 合计 1 + (1+1) = 3
        issues = [
            {"number": 1, "title": "待核说法：钙片补钙", "body": "- 说法：钙片补钙",
             "state": "OPEN", "labels": [], "comments": [], "url": "u1", "createdAt": "2026-06-01"},
            {"number": 2, "title": "待核说法：钙片，补钙！", "body": "- 说法：钙片，补钙！",
             "state": "OPEN", "labels": [], "comments": [{"body": "🔁 再次提交"}],
             "url": "u2", "createdAt": "2026-06-02"},
        ]
        rows = pd.build_groups([pd.enrich(i) for i in issues])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["count"], 3)
        self.assertEqual(rows[0]["status"], pd.STATUS_PENDING)


if __name__ == "__main__":
    unittest.main()
