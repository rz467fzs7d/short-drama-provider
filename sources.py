"""Public catalog metadata only. No player requests, signatures, or video downloads."""

import json
import re
import threading
import time
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen


class SourceError(Exception):
    pass


SOURCE_NAMES = ("douban", "hongguo", "duanjubaike", "scenetrace")


def source_id(source, value):
    if source == "scenetrace":
        if not isinstance(value, str) or len(value) > 180 or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
            raise ValueError("Invalid SceneTrace slug")
        return value
    if source not in SOURCE_NAMES:
        raise ValueError("Unknown source")
    return numeric_id(value)


def catalog_key(item):
    ident = source_id(item["source"], item["id"])
    # Hex encoding keeps slug suffixes distinct from Plex season/episode keys.
    if item["source"] == "scenetrace":
        ident = ident.encode("ascii").hex()
    return item["source"] + "-" + ident


def parse_catalog_key(key):
    match = re.fullmatch(r"(douban|hongguo|duanjubaike|scenetrace)-([0-9a-f]{1,360})", key)
    if not match:
        raise ValueError("Invalid catalog key")
    name, ident = match.groups()
    if name == "scenetrace":
        try:
            ident = bytes.fromhex(ident).decode("ascii")
        except (ValueError, UnicodeError):
            raise ValueError("Invalid SceneTrace key") from None
    return name, source_id(name, ident)


def numeric_id(value):
    value = str(value)
    if not re.fullmatch(r"[0-9]{1,25}", value):
        raise ValueError("Invalid source ID")
    return value


def integer(value):
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def empty(source, ident, title):
    ident = source_id(source, ident)
    url = {"douban": f"https://movie.douban.com/subject/{ident}/",
           "hongguo": f"https://hongguoduanju.com/detail?series_id={ident}",
           "duanjubaike": f"https://duanjubaike.org/zh-Hans/drama/{ident}",
           "scenetrace": f"https://shortdramacast.com/zh-cn/dramas/{ident}"}[source]
    return dict(source=source, id=ident, title=title, year=None, summary="",
                cast=[], genres=[], episodes=[], episode_count=None, poster="",
                rating=None, url=url)


def parse_douban_search(data):
    if not isinstance(data, list):
        raise SourceError("Douban search schema unavailable")
    result = []
    for item in data:
        if not isinstance(item, dict) or not integer(item.get("episode")):
            continue
        r = empty("douban", item["id"], item["title"])
        r.update(year=integer(item.get("year")), poster=item.get("img", ""),
                 episode_count=integer(item.get("episode")))
        result.append(r)
    return result


def parse_hongguo_search(data):
    if not isinstance(data, dict) or not isinstance(data.get("suggestionList"), list):
        raise SourceError("Hongguo suggestions unavailable")
    result = {}
    for item in data["suggestionList"]:
        v = item.get("video_data") or {}
        if not v.get("series_id") or not v.get("series_title"):
            continue
        r = empty("hongguo", v["series_id"], v["series_title"])
        r.update(summary=v.get("series_intro", ""), poster=v.get("series_cover", ""),
                 episode_count=integer(v.get("episode_cnt")),
                 genres=[x["name"] for x in v.get("category_list", []) if x.get("name")])
        result[r["id"]] = r
    return list(result.values())


class Document(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.scripts, self.meta, self.text, self.links = [], {}, [], []
        self._link = None
        self._json, self._data = False, []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a":
            self._link = {"attrs": a, "text": [], "image": {}}
        if tag == "img" and self._link is not None:
            self._link["image"] = a
        if tag == "script" and a.get("type") == "application/ld+json":
            self._json, self._data = True, []
        if tag == "meta":
            self.meta[a.get("property") or a.get("name")] = a.get("content", "")

    def handle_endtag(self, tag):
        if tag == "a" and self._link is not None:
            self.links.append(self._link)
            self._link = None
        if tag == "script" and self._json:
            try:
                self.scripts.append(json.loads("".join(self._data)))
            except ValueError:
                pass
            self._json = False

    def handle_data(self, data):
        if self._link is not None:
            self._link["text"].append(data)
        if self._json:
            self._data.append(data)
        self.text.append(data)


def nodes(data):
    if isinstance(data, list):
        for item in data:
            yield from nodes(item)
    elif isinstance(data, dict):
        yield data
        if "@graph" in data:
            yield from nodes(data["@graph"])


def parse_detail(source, ident, html):
    doc = Document(html)
    types = ("TVSeries", "TVMiniSeries", "TVSeason") if source == "hongguo" else ("TVSeries", "TVMiniSeries")
    candidates = [x for s in doc.scripts for x in nodes(s)
                  if set(x.get("@type", []) if isinstance(x.get("@type"), list)
                         else [x.get("@type")]).intersection(types) and x.get("name")]
    if source == "hongguo":
        exact = [x for x in candidates if parse_qs(urlsplit(x.get("url") or x.get("@id") or "").query)
                 .get("series_id") == [str(ident)]]
        candidates = exact or candidates
    item = candidates[0] if candidates else None
    if not item or not item.get("name"):
        raise SourceError(f"{source} detail missing TVSeries JSON-LD (blocked or unsupported)")
    r = empty(source, ident, item["name"])
    date = item.get("datePublished") or ""
    poster = item.get("image") or ""
    if isinstance(poster, list):
        poster = poster[0] if poster else ""
    if isinstance(poster, dict):
        poster = poster.get("url", "")
    genre = item.get("genre") or []
    cast = item.get("actor") or []
    r.update(summary=item.get("description", ""), poster=poster,
             year=integer(date[:4]), genres=[genre] if isinstance(genre, str) else genre,
             cast=[x["name"] for x in cast if isinstance(x, dict) and x.get("name")],
             episode_count=integer(item.get("numberOfEpisodes")))
    aliases = item.get("alternateName") or []
    r["aliases"] = [aliases] if isinstance(aliases, str) else aliases
    # Preserve explicit upstream identity references, never infer IDs from titles.
    citations = item.get("citation") or []
    if isinstance(citations, str):
        citations = [citations]
    for citation in citations:
        if not isinstance(citation, str):
            continue
        parsed = urlsplit(citation)
        if parsed.hostname == "hongguoduanju.com":
            linked = parse_qs(parsed.query).get("series_id", [])
            if linked and re.fullmatch(r"[0-9]{1,25}", linked[0]):
                r.setdefault("linked_ids", {})["hongguo"] = linked[0]
    rating = (item.get("aggregateRating") or {}).get("ratingValue")
    if source == "douban" and rating not in (None, ""):
        try:
            score = float(rating)
            if 0 <= score <= 10:
                r["rating"] = score
        except (ValueError, TypeError):
            pass
    for e in item.get("episode") or []:
        index = integer(e.get("episodeNumber"))
        if index and index > 0:
            r["episodes"].append(dict(index=index, title=e.get("name") or f"第{index}集",
                                      summary=e.get("description") or ""))
    # Douban exposes episode count outside JSON-LD on some subject pages.
    if source == "douban" and not r["episode_count"]:
        match = re.search(r"集数\s*[:：]\s*(\d+)", " ".join(doc.text))
        if match:
            r["episode_count"] = int(match[1])
    return r


def parse_html_search(source, html):
    doc = Document(html)
    marker = '搜索' in html or 'data-analytics-search-results' in html
    if not marker or not doc.links:
        raise SourceError(f"{source} search missing page structure")
    result = {}
    host = "duanjubaike.org" if source == "duanjubaike" else "shortdramacast.com"
    for link in doc.links:
        attrs, img = link["attrs"], link["image"]
        url = urlsplit(urljoin("https://" + host, attrs.get("href", "")))
        if url.hostname != host:
            continue
        if source == "duanjubaike":
            match = re.fullmatch(r"/zh-Hans/drama/([0-9]+)", url.path)
            title = img.get("alt")
        else:
            match = re.fullmatch(r"/zh-cn/dramas/([a-z0-9-]+)", url.path)
            title = attrs.get("data-entity-title") if attrs.get("data-entity-type") == "work" else None
        if not match or not title:
            continue
        r = empty(source, match[1], title)
        r["poster"] = img.get("src", "")
        count = re.search(r"(\d+)\s*集", " ".join(link["text"]))
        r["episode_count"] = int(count[1]) if count else None
        result[r["id"]] = r
    return list(result.values())


class Source:
    def __init__(self, name, timeout=12):
        if name not in SOURCE_NAMES:
            raise ValueError("Unsupported source")
        self.name, self.timeout = name, timeout
        self._lock, self._last = threading.Lock(), 0.0

    def get(self, url):
        for attempt in range(2):
            with self._lock:
                time.sleep(max(0, 1 - (time.monotonic() - self._last)))
                self._last = time.monotonic()
            try:
                req = Request(url, headers={"User-Agent": "ShortDramaMetadata/0.1",
                                            "Accept-Language": "zh-CN,zh;q=0.9"})
                with urlopen(req, timeout=self.timeout) as response:
                    data = response.read(4 * 1024 * 1024 + 1)
                    if len(data) > 4 * 1024 * 1024:
                        raise SourceError("Upstream response exceeds limit")
                    return data.decode("utf-8")
            except HTTPError as exc:
                if exc.code not in (500, 502, 503, 504) or attempt:
                    raise SourceError(f"{self.name} HTTP {exc.code}") from None
            except (URLError, TimeoutError, OSError) as exc:
                if attempt:
                    raise SourceError(f"{self.name} transport failure: {type(exc).__name__}") from None
        raise SourceError("Source unavailable")

    def search(self, title):
        if self.name in ("duanjubaike", "scenetrace"):
            base = ("https://duanjubaike.org/zh-Hans/drama/search" if self.name == "duanjubaike"
                    else "https://shortdramacast.com/zh-cn/discover")
            return parse_html_search(self.name, self.get(base + "?" + urlencode({"q": title})))
        if self.name == "douban":
            url = "https://movie.douban.com/j/subject_suggest?" + urlencode({"q": title})
            parser = parse_douban_search
        else:
            url = "https://hongguoduanju.com/api/search/suggestion?" + urlencode({"query": title})
            parser = parse_hongguo_search
        try:
            return parser(json.loads(self.get(url)))
        except (ValueError, KeyError, TypeError) as exc:
            raise SourceError(f"{self.name} invalid search response") from exc

    def detail(self, ident):
        url = empty(self.name, ident, "")["url"]
        return parse_detail(self.name, ident, self.get(url))
