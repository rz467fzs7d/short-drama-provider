import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sources import SourceError, parse_detail, parse_html_search, parse_catalog_key
from catalog import Catalog, merge
from server import parse_key


class Websites(unittest.TestCase):
    def test_baike_image_card_search(self):
        html = '<title>搜索</title><a href="https://duanjubaike.org/zh-Hans/drama/71208"><img src="https://cdn.duanjubaike.org/p.jpg" alt="备用联系人（完）"><span>106集</span></a>'
        r = parse_html_search("duanjubaike", html)
        self.assertEqual((r[0]["id"], r[0]["episode_count"]), ("71208", 106))
        self.assertEqual(r[0]["title"], "备用联系人（完）")

    def test_scenetrace_search_rejects_actor_cards_and_external_urls(self):
        html = '<title>搜索</title><a href="/zh-cn/dramas/jia-li-jia-wai" data-entity-type="work" data-entity-title="家里家外"><span>79 集</span></a><a href="/zh-cn/actors/wang" data-entity-type="actor">演员</a><a href="https://evil.test/zh-cn/dramas/wrong" data-entity-type="work" data-entity-title="Wrong">Wrong</a>'
        r = parse_html_search("scenetrace", html)
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0]["id"], "jia-li-jia-wai")

    def test_jsonld_type_array_and_source_links(self):
        item = {"@type": ["TVSeries", "CreativeWork"], "name": "归路", "alternateName": ["gui lu"],
                "citation": ["https://hongguoduanju.com/detail?series_id=123"],
                "numberOfEpisodes": 78, "actor": [{"name": "王小亿"}]}
        r = parse_detail("scenetrace", "gui-lu", '<script type="application/ld+json">'+json.dumps(item)+'</script>')
        self.assertEqual(r["cast"], ["王小亿"])
        self.assertEqual(r["linked_ids"]["hongguo"], "123")

    def test_slug_key_roundtrip_does_not_collide_with_episode_suffix(self):
        key = Catalog.key({"source": "scenetrace", "id": "drama-s1-e1"})
        self.assertEqual(parse_catalog_key(key), ("scenetrace", "drama-s1-e1"))
        self.assertEqual(parse_key(key + "-s1-e2"), (key, 1, 2))

    def test_empty_page_not_mistaken_for_empty_search(self):
        with self.assertRaises(SourceError):
            parse_html_search("scenetrace", '<title>Just a moment...</title>')

    def test_correlated_scenetrace_record_fills_but_does_not_replace(self):
        a = {"source": "douban", "id": "12", "title": "归路", "cast": ["王小亿"], "summary": "豆瓣简介"}
        b = {"source": "scenetrace", "id": "gui-lu", "title": "归路", "cast": ["王小亿"], "summary": "别的简介", "poster": "https://example.com/p.jpg"}
        r = merge(a, b)
        self.assertEqual(r["summary"], "豆瓣简介")
        self.assertEqual(r["linked_ids"]["scenetrace"], "gui-lu")


if __name__ == "__main__":
    unittest.main()
