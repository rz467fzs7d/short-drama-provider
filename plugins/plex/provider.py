import logging
import re
from urllib.parse import urlsplit
from sources import SourceError, parse_catalog_key
from matching import match_score, search_catalog

IDENTIFIER = "tv.plex.agents.custom.homelab.shortdrama"
PREFIX = "/library/metadata"
SOURCE_LABELS = {"douban": "豆瓣", "hongguo": "红果", "duanjubaike": "短剧百科", "scenetrace": "SceneTrace"}


def container(items, errors=None, total=None, offset=0, field="Metadata"):
    result = {"offset": offset, "totalSize": len(items) if total is None else total,
              "identifier": IDENTIFIER, "size": len(items), field: items}
    if errors:
        result["sourceErrors"] = errors
    return {"MediaContainer": result}


def descriptor():
    return {"MediaProvider": {
        "identifier": IDENTIFIER, "title": "短剧元数据",
        "version": "0.1.0",
        "Types": [{"type": t, "Scheme": [{"scheme": IDENTIFIER}]} for t in (2, 3, 4)],
        "Feature": [{"type": "metadata", "key": PREFIX},
                    {"type": "match", "key": PREFIX + "/matches"}]}}


def parse_key(key):
    match = re.fullmatch(r"((?:douban|hongguo|duanjubaike|scenetrace)-[0-9a-f]{1,360})(?:-s([1-9][0-9]*))?(?:-e([1-9][0-9]*))?", key)
    if not match or (match[3] and not match[2]):
        raise ValueError("Invalid metadata key")
    parse_catalog_key(match[1])
    return match[1], int(match[2]) if match[2] else None, int(match[3]) if match[3] else None


def safe_image(url):
    return url if isinstance(url, str) and urlsplit(url).scheme in ("http", "https") else None


def metadata(item, key, season=None, episode=None):
    base = key.split("-s")[0]
    kind = "episode" if episode else "season" if season else "show"
    result = {"ratingKey": key, "key": PREFIX + "/" + key,
              "guid": f"{IDENTIFIER}://{kind}/{key}", "type": kind,
              "title": item["title"], "summary": item.get("summary") or "",
              "Guid": [{"id": f'{item["source"]}://{item["id"]}'}]}
    image = safe_image(item.get("poster"))
    if image:
        result["thumb"] = image
        result["Image"] = [{"type": "coverPoster", "url": image}]
    if item.get("year"):
        result["year"] = item["year"]
    # Preserve Douban scores in the catalog, not an unsupported Plex badge.
    for field, target in [("cast", "Role"), ("genres", "Genre")]:
        if item.get(field):
            result[target] = [{"tag": x} for x in item[field]]
    if season:
        if season != 1:
            raise LookupError("No verified metadata for this season")
        result.update(index=season, parentRatingKey=base, parentKey=PREFIX + "/" + base,
                      parentTitle=item["title"], parentType="show", parentGuid=f"{IDENTIFIER}://show/{base}",
                      title="Season 1", summary="")
    if episode:
        e = next((e for e in item.get("episodes", []) if e["index"] == episode), None)
        if not e:
            raise LookupError("No public metadata for this episode")
        result.update(index=episode, parentIndex=1, title=e["title"],
                      summary=e.get("summary") or "", parentRatingKey=base + "-s1",
                      parentKey=PREFIX + "/" + base + "-s1", parentTitle="Season 1", parentType="season",
                      parentGuid=f"{IDENTIFIER}://season/{base}-s1",
                      grandparentRatingKey=base, grandparentTitle=item["title"], grandparentType="show",
                      grandparentKey=PREFIX + "/" + base,
                      grandparentGuid=f"{IDENTIFIER}://show/{base}")
        # A show-level score is not an episode rating.
        result.pop("rating", None)
        result.pop("ratingImage", None)
    else:
        result["leafCount"] = item.get("episode_count") or len(item.get("episodes", []))
        if not season:
            result["childCount"] = 1 if item.get("episode_count") or item.get("episodes") else 0
    return result


def children(item, base, season=None):
    if season is None:
        return [metadata(item, base + "-s1", 1)] if item.get("episode_count") or item.get("episodes") else []
    if season != 1:
        raise LookupError("Unknown season")
    return [metadata(item, f'{base}-s1-e{e["index"]}', 1, e["index"])
            for e in item.get("episodes", [])]


def dispatch_plex(catalog, method, path, query, body):
    if method == "POST" and path == PREFIX + "/matches":
        kind = int(body.get("type", 2))
        if kind not in (2, 3, 4):
            raise ValueError("Only television metadata is supported")
        guid = body.get("guid") or ""
        if not isinstance(guid, str):
            raise ValueError("GUID must be a string")
        if guid.startswith(IDENTIFIER + "://"):
            key = guid.rsplit("/", 1)[-1]
            base, season, episode = parse_key(key)
            item, errors = catalog.resolve(base)
            return container([metadata(item, key, season, episode)], errors)
        title = body.get("title") if kind == 2 else body.get("parentTitle") if kind == 3 else body.get("grandparentTitle")
        logging.info("match type=%s title=%r manual=%s", kind, title, body.get("manual", 0))
        year = int(body["year"]) if body.get("year") else None
        manual = str(body.get("manual", "0")).lower() in ("1", "true")
        ranked, errors = search_catalog(catalog, title, year)
        scores = [match_score(title, r, year) for r in ranked]
        selected = ranked if manual else ranked[:1]
        logging.info("match candidates=%s errors=%s", len(ranked), [(e["source"], e["stage"]) for e in errors])
        blocking_errors = [e for e in errors if e["stage"] == "search" and
                           (not selected or e["source"] == selected[0]["source"] or e["source"] == "douban")]
        if not manual and (not selected or scores[0] < 80 or
                           (len(scores) > 1 and scores[0] - scores[1] < 10) or blocking_errors):
            return container([], errors)
        results = []
        for r in selected:
            key = catalog.key(r)
            if kind != 2:
                r, detail_errors = catalog.resolve(key)
                errors.extend(detail_errors)
                season = int(body.get("index", 1)) if kind == 3 else int(body.get("parentIndex", 1))
                episode = int(body.get("index", 0)) if kind == 4 else None
                if season < 1 or (kind == 4 and not episode):
                    raise ValueError("Invalid season or episode")
                key += f"-s{season}" + (f"-e{episode}" if episode else "")
            else:
                season = episode = None
            try:
                candidate = metadata(r, key, season, episode)
                if manual:
                    candidate["title"] = SOURCE_LABELS[r["source"]] + ":" + r["id"]
                    candidate["summary"] = r["title"] + (" | " + r["summary"] if r.get("summary") else "")
                    candidate["score"] = match_score(title, r, year)
                results.append(candidate)
            except LookupError:
                continue
        return container(results, errors)
    if method == "GET" and path.startswith(PREFIX + "/"):
        parts = path[len(PREFIX) + 1:].split("/")
        key = parts[0]
        base, season, episode = parse_key(key)
        action = parts[1] if len(parts) == 2 else None
        if len(parts) > 2 or action not in (None, "children", "grandchildren", "images"):
            raise LookupError("Unknown metadata route")
        start = int(query.get("X-Plex-Container-Start", "0"))
        size = int(query.get("X-Plex-Container-Size", "100"))
        if start < 0 or not 1 <= size <= 500:
            raise ValueError("Invalid pagination")
        item, errors = catalog.resolve(base)
        if action == "images":
            image = safe_image(item.get("poster"))
            return container([{"type": "coverPoster", "url": image}] if image else [], errors, field="Image")
        if action in ("children", "grandchildren"):
            if episode:
                result = []
            else:
                result = children(item, base, 1 if action == "grandchildren" else season)
            return container(result[start:start + size], errors, len(result), start)
        result = metadata(item, key, season, episode)
        if query.get("includeChildren") == "1" and not episode:
            result["Children"] = container(children(item, base, season))["MediaContainer"]
        return container([result], errors)
    raise LookupError("Unknown route")

