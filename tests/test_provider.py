import copy
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sources import SourceError, parse_detail, parse_douban_search, parse_hongguo_search
from catalog import Cache, Catalog, merge, normalize
from server import dispatch


def record(source="douban", ident="123", **values):
    return dict(source=source, id=ident, title="Test", year=2024,
                summary="", cast=[], genres=[], episodes=[], episode_count=None,
                poster="", rating=None, url="", **values) if not values else {
                    **record(source, ident), **values}


class Parsers(unittest.TestCase):
    def test_hongguo_filters_non_series_and_preserves_unicode(self):
        data = {"suggestionList": [
            {"name": "query", "video_data": {}},
            {"name": "铁血信使", "video_data": {"series_id": "123",
             "series_title": "铁血信使", "episode_cnt": 75,
             "hot_score_data": {"score": 43879681}}}]}
        result = parse_hongguo_search(data)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "铁血信使")
        self.assertEqual(result[0]["episode_count"], 75)
        self.assertIsNone(result[0]["rating"])

    def test_bad_search_is_not_empty(self):
        for fn, data in [(parse_hongguo_search, {"code": "search_rejected"}),
                         (parse_douban_search, {"error": "blocked"})]:
            with self.assertRaises(SourceError):
                fn(data)

    def test_douban_tv_suggestions_only(self):
        result = parse_douban_search([
            {"id": "12", "title": "短剧", "episode": "18", "year": "2022"},
            {"id": "13", "title": "Movie", "episode": "", "year": "2022"}])
        self.assertEqual([r["id"] for r in result], ["12"])

    def test_jsonld_graph_and_partial_episodes(self):
        graph = {"@graph": [{"@type": "TVSeries", "name": "铁血信使",
                 "numberOfEpisodes": 75, "description": "简介",
                 "actor": [{"name": "蔡欣洋"}],
                 "episode": [{"episodeNumber": 1, "name": "第1集"}]}]}
        r = parse_detail("hongguo", "123", '<script type="application/ld+json">' +
                         json.dumps(graph) + '</script>')
        self.assertEqual(r["episode_count"], 75)
        self.assertEqual(len(r["episodes"]), 1)
        self.assertEqual(r["cast"], ["蔡欣洋"])

    def test_douban_rating_and_date(self):
        graph = {"@type": "TVSeries", "name": "短剧", "datePublished": "2022-04-02",
                 "aggregateRating": {"ratingValue": "6.8"}}
        r = parse_detail("douban", "12", '<script type="application/ld+json">' +
                         json.dumps(graph) + '</script>')
        self.assertEqual(r["rating"], 6.8)
        self.assertEqual(r["year"], 2022)

    def test_hongguo_season_release_and_nameless_series_group(self):
        graph = {"@graph": [
            {"@type": "TVSeason", "name": "家里家外", "numberOfEpisodes": 79,
             "actor": [{"name": "王道铁"}], "episode": [{"episodeNumber": 1, "name": "第1集"}]},
            {"@type": "TVSeries", "containsSeason": [{"@id": "season-ref"}]}]}
        r = parse_detail("hongguo", "123", '<script type="application/ld+json">' +
                         json.dumps(graph) + '</script>')
        self.assertEqual(r["cast"], ["王道铁"])
        self.assertEqual(r["episode_count"], 79)

    def test_challenge_is_failure_not_metadata(self):
        with self.assertRaises(SourceError):
            parse_detail("douban", "12", '<title>豆瓣</title><form id="sec"></form>')


class Policy(unittest.TestCase):
    def test_no_title_only_merge(self):
        self.assertIsNone(merge(record(), record("hongguo")))

    def test_douban_fields_win_missing_fields_fill_with_provenance(self):
        a = record(cast=["A"], summary="豆瓣简介")
        b = record("hongguo", cast=["A"], summary="红果简介", poster="https://example.com/p.jpg")
        result = merge(a, b)
        self.assertEqual(result["summary"], "豆瓣简介")
        self.assertEqual(result["poster"], b["poster"])
        self.assertEqual(result["provenance"]["poster"], "hongguo:123")
        self.assertEqual(a["poster"], "")

    def test_conflicts_block_linking(self):
        a = record(cast=["A"], episode_count=18)
        for update in [{"year": 2025}, {"cast": ["B"]}, {"episode_count": 20}]:
            b = record("hongguo", cast=["A"], episode_count=18)
            b.update(update)
            self.assertIsNone(merge(a, b))

    def test_normalization_preserves_season_words(self):
        self.assertNotEqual(normalize("铁血第二季"), normalize("铁血"))

    def test_cache_expiry_and_unicode(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = Cache(Path(tmp) / "cache.db", ttl=0.01)
            c.put("测试", {"title": "中文"})
            self.assertEqual(c.get("测试")["title"], "中文")
            time.sleep(0.02)
            self.assertIsNone(c.get("测试"))


class FakeSource:
    def __init__(self, name, results=None, fail=False):
        self.name, self.results, self.fail = name, results or [], fail

    def search(self, title):
        if self.fail:
            raise SourceError("blocked")
        return copy.deepcopy(self.results)

    def detail(self, ident):
        return next(copy.deepcopy(x) for x in self.results if x["id"] == ident)


class Protocol(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Cache(Path(self.tmp.name) / "cache.db")
        self.item = record("hongguo", episode_count=75,
                           episodes=[{"index": 1, "title": "第1集"}])
        self.cat = Catalog(self.cache, [FakeSource("douban"), FakeSource("hongguo", [self.item])])

    def tearDown(self):
        self.tmp.cleanup()

    def test_discovery_and_manual_match(self):
        provider = dispatch(self.cat, "GET", "/tv", {}, {})
        self.assertEqual(provider["MediaProvider"]["Types"][0]["type"], 2)
        self.assertEqual(provider["MediaProvider"]["title"], "短剧元数据")
        result = dispatch(self.cat, "POST", "/tv/library/metadata/matches", {},
                          {"type": 2, "title": "Test", "manual": 1})
        item = result["MediaContainer"]["Metadata"][0]
        self.assertEqual(item["ratingKey"], "hongguo-123")
        self.assertIn("show/", item["guid"])
        self.assertEqual(item["title"], "红果:123")
        self.assertTrue(item["summary"].startswith("Test"))
        self.assertEqual(item["score"], 80)

    def test_source_label_not_saved_as_formal_title(self):
        self.cat.search("Test")
        result = dispatch(self.cat, "GET", "/tv/library/metadata/hongguo-123", {}, {})
        self.assertEqual(result["MediaContainer"]["Metadata"][0]["title"], "Test")

    def test_platform_neutral_search_and_detail(self):
        result = dispatch(self.cat, "POST", "/v1/search", {}, {"title": "Test"})
        self.assertEqual(result["items"][0]["key"], "hongguo-123")
        self.assertEqual(result["items"][0]["title"], "Test")
        result = dispatch(self.cat, "GET", "/v1/metadata/hongguo-123", {}, {})
        self.assertEqual(result["item"]["title"], "Test")
        self.assertEqual(result["item"]["source"], "hongguo")

    def test_feature_paths_relative_to_provider_uri(self):
        provider = dispatch(self.cat, "GET", "/tv", {}, {})["MediaProvider"]
        self.assertEqual(provider["Feature"][1]["key"], "/library/metadata/matches")
        # PMS caches provider definitions; tolerate the initial duplicated base.
        result = dispatch(self.cat, "POST", "/tv/tv/library/metadata/matches", {},
                          {"type": 2, "title": "Test", "manual": 1})
        self.assertEqual(result["MediaContainer"]["size"], 1)

    def test_children_do_not_fabricate_75_episodes(self):
        self.cat.search("Test")
        result = dispatch(self.cat, "GET", "/tv/library/metadata/hongguo-123-s1/children", {}, {})
        self.assertEqual(result["MediaContainer"]["totalSize"], 1)

    def test_missing_episode_returns_404(self):
        self.cat.search("Test")
        with self.assertRaises(LookupError):
            dispatch(self.cat, "GET", "/tv/library/metadata/hongguo-123-s1-e75", {}, {})

    def test_ambiguous_auto_match_returns_no_match(self):
        self.cat.sources[1].results.append(record("hongguo", "124"))
        result = dispatch(self.cat, "POST", "/tv/library/metadata/matches", {},
                          {"type": 2, "title": "Test"})
        self.assertEqual(result["MediaContainer"]["size"], 0)

    def test_matching_score_not_source_order(self):
        self.cat.sources[0].results = [record(title="Another", year=2024)]
        self.cat.sources[1].results = [record("hongguo", title="Test", year=2024)]
        result = dispatch(self.cat, "POST", "/tv/library/metadata/matches", {},
                          {"type": 2, "title": "Test", "year": 2024, "manual": 1})
        items = result["MediaContainer"]["Metadata"]
        self.assertEqual(items[0]["ratingKey"], "hongguo-123")
        self.assertEqual(items[0]["score"], 90)

    def test_search_enriches_missing_year_from_detail(self):
        self.cat.sources[1].results = [record("hongguo", year=None)]
        self.cat.sources[1].detail = lambda ident: record("hongguo", year=2026)
        result = dispatch(self.cat, "POST", "/tv/library/metadata/matches", {},
                          {"type": 2, "title": "Test", "manual": 1})
        self.assertEqual(result["MediaContainer"]["Metadata"][0]["year"], 2026)

    def test_equal_exact_cross_source_matches_do_not_auto_select(self):
        self.cat.sources[0].results = [record()]
        result = dispatch(self.cat, "POST", "/tv/library/metadata/matches", {},
                          {"type": 2, "title": "Test"})
        self.assertEqual(result["MediaContainer"]["size"], 0)

    def test_source_failures_reported(self):
        self.cat.sources[0].fail = True
        results, errors = self.cat.search("Test")
        self.assertTrue(results)
        self.assertEqual(errors[0]["source"], "douban")

    def test_hongguo_failure_does_not_block_unique_douban_match(self):
        self.cat.sources[0].results = [record()]
        self.cat.sources[1].fail = True
        result = dispatch(self.cat, "POST", "/tv/library/metadata/matches", {},
                          {"type": 2, "title": "Test"})
        self.assertEqual(result["MediaContainer"]["size"], 1)

    def test_hierarchy_types(self):
        self.cat.search("Test")
        result = dispatch(self.cat, "GET", "/tv/library/metadata/hongguo-123-s1-e1", {}, {})
        item = result["MediaContainer"]["Metadata"][0]
        self.assertEqual(item["parentType"], "season")
        self.assertEqual(item["grandparentType"], "show")

    def test_no_unsupported_rating_badge(self):
        self.cat.sources[0].results = [record(rating=6.8)]
        result = dispatch(self.cat, "POST", "/tv/library/metadata/matches", {},
                          {"type": 2, "title": "Test", "manual": 1})
        self.assertNotIn("ratingImage", result["MediaContainer"]["Metadata"][0])

    def test_detail_retains_same_source_suggestion_genres(self):
        suggestion = dict(self.item, genres=["年代"])
        self.cache.put("suggestion:hongguo-123", suggestion)
        item, _ = self.cat.detail("hongguo-123")
        self.assertEqual(item["genres"], ["年代"])

    def test_secondary_detail_failure_keeps_primary(self):
        self.cat.sources[0].results = [record(cast=["A"])]
        self.cat.sources[1].results = [record("hongguo", cast=["A"])]
        self.cache.put("search:hongguo:test", self.cat.sources[1].results)
        def fail(ident):
            raise SourceError("blocked")
        self.cat.sources[1].detail = fail
        item, errors = self.cat.resolve("douban-123")
        self.assertEqual(item["source"], "douban")
        self.assertTrue(errors)

    def test_failure_cache_does_not_slide_on_reads(self):
        calls = []
        def fail(ident):
            calls.append(ident)
            raise SourceError("blocked")
        self.cat.sources[1].detail = fail
        self.cache.put("suggestion:hongguo-123", self.item)
        with patch("catalog.time.time", return_value=1000):
            self.cat.detail("hongguo-123")
        with patch("catalog.time.time", return_value=1050):
            self.cat.detail("hongguo-123")
        with patch("catalog.time.time", return_value=1061):
            self.cat.detail("hongguo-123")
        self.assertEqual(len(calls), 2)

    def test_invalid_id_and_negative_pagination_rejected(self):
        with self.assertRaises(ValueError):
            self.cat.detail("https://example.com")
        with self.assertRaises(ValueError):
            dispatch(self.cat, "GET", "/tv/library/metadata/hongguo-123/children",
                     {"X-Plex-Container-Start": "-1"}, {})


if __name__ == "__main__":
    unittest.main()
