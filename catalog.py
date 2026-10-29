"""Persistent catalog and conservative cross-source identity resolution."""

import copy
from contextlib import contextmanager
import json
from pathlib import Path
import re
import sqlite3
import time
import unicodedata

from sources import SourceError, catalog_key, parse_catalog_key


def normalize(title):
    return "".join(c for c in unicodedata.normalize("NFKC", title).casefold() if c.isalnum())


def merge(douban, hongguo):
    if normalize(douban["title"]) != normalize(hongguo["title"]):
        return None
    for field in ("year", "episode_count"):
        if douban.get(field) and hongguo.get(field) and douban[field] != hongguo[field]:
            return None
    cast_a, cast_b = set(douban.get("cast") or []), set(hongguo.get("cast") or [])
    if cast_a and cast_b and not cast_a.intersection(cast_b):
        return None
    # Require cast corroboration or BOTH year and episode-count corroboration.
    corroborated = bool(cast_a.intersection(cast_b)) or all(
        douban.get(f) and douban.get(f) == hongguo.get(f) for f in ("year", "episode_count"))
    if not corroborated:
        return None
    result = copy.deepcopy(douban)
    result["provenance"] = {}
    for field in ("title", "year", "summary", "cast", "genres", "poster", "rating",
                  "episode_count", "episodes"):
        source = douban if douban.get(field) not in (None, "", []) else hongguo
        # Hongguo episode numbering must not be imported into a different cut.
        if field == "episodes" and not (douban.get("episode_count") and
                                       douban.get("episode_count") == hongguo.get("episode_count")):
            source = douban
        result[field] = copy.deepcopy(source.get(field))
        if result[field] not in (None, "", []):
            result["provenance"][field] = f'{source["source"]}:{source["id"]}'
    result["linked_ids"] = {**douban.get("linked_ids", {}), douban["source"]: douban["id"],
                            hongguo["source"]: hongguo["id"]}
    return result


class Cache:
    def __init__(self, path, ttl=86400):
        self.path, self.ttl = str(path), ttl
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, expires REAL)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, key):
        with self.connect() as db:
            row = db.execute("SELECT value FROM cache WHERE key=? AND expires>?", (key, time.time())).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key, value, ttl=None):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO cache VALUES (?,?,?)",
                       (key, json.dumps(value, ensure_ascii=False),
                        time.time() + (self.ttl if ttl is None else ttl)))


class Catalog:
    def __init__(self, cache, sources):
        self.cache, self.sources = cache, sources

    @staticmethod
    def key(item):
        return catalog_key(item)

    def search(self, title):
        if not isinstance(title, str) or not title.strip() or len(title) > 200:
            raise ValueError("Title must contain 1-200 characters")
        records, errors = [], []
        for source in self.sources:
            search_key = "search:" + source.name + ":" + normalize(title)
            cached = self.cache.get(search_key)
            if cached is None:
                try:
                    cached = source.search(title)
                    # Empty suggestions may mean incomplete coverage; cache briefly.
                    self.cache.put(search_key, cached, ttl=3600 if cached else 300)
                except SourceError as exc:
                    errors.append(dict(source=source.name, stage="search", message=str(exc)))
                    continue
            for record in cached:
                self.cache.put("suggestion:" + self.key(record), record)
            records.extend(cached)
        return records, errors

    def detail(self, key):
        name, ident = parse_catalog_key(key)
        cached = self.cache.get("detail:" + key)
        if cached is not None:
            return cached, []
        source = next(s for s in self.sources if s.name == name)
        errors = []
        recent_failure = self.cache.get("failure:" + key)
        try:
            if recent_failure:
                raise SourceError(recent_failure["message"])
            result = source.detail(ident)
            suggestion = self.cache.get("suggestion:" + key) or {}
            for field, value in suggestion.items():
                if result.get(field) in (None, "", []):
                    result[field] = value
            self.cache.put("detail:" + key, result)
        except SourceError as exc:
            if not recent_failure:
                self.cache.put("failure:" + key, {"message": str(exc)}, ttl=60)
            errors.append(dict(source=source.name, stage="detail", message=str(exc)))
            result = self.cache.get("suggestion:" + key)
            if result is None:
                raise
        result["provenance"] = {f: key.replace("-", ":", 1) for f, v in result.items()
                                if f not in ("provenance", "source", "id") and v not in (None, "", [])}
        return result, errors

    def resolve(self, key):
        primary, errors = self.detail(key)
        if primary["source"] != "douban":
            return primary, errors
        candidates, search_errors = self.search(primary["title"])
        errors.extend(search_errors)
        linked = []
        for item in candidates:
            if item["source"] != "hongguo" or normalize(item["title"]) != normalize(primary["title"]):
                continue
            try:
                detail, detail_errors = self.detail(self.key(item))
            except SourceError as exc:
                errors.append(dict(source="hongguo", stage="detail", message=str(exc)))
                continue
            errors.extend(detail_errors)
            combined = merge(primary, detail)
            if combined:
                linked.append(combined)
        return (linked[0] if len(linked) == 1 else primary), errors
