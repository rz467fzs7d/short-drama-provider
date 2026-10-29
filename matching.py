from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor
from catalog import normalize
from sources import SourceError

def match_score(title, item, year=None):
    query = normalize(title)
    titles = [item.get("title", "")] + (item.get("aliases") or [])
    similarity = max((SequenceMatcher(None, query, normalize(t)).ratio() for t in titles if t), default=0)
    score = round(80 * similarity)
    if year and item.get("year"):
        score += 10 if item["year"] == year else -30
    return max(0, min(100, score))


def search_catalog(catalog, title, year):
    records, errors = catalog.search(title)
    candidates = sorted((r for r in records if not r.get("year") and
                         match_score(title, r) >= 60),
                        key=lambda r: match_score(title, r), reverse=True)[:8]
    def enrich(record):
        try:
            detail, detail_errors = catalog.detail(catalog.key(record))
            return detail, detail_errors
        except SourceError as exc:
            return record, [{"source": record["source"], "stage": "detail", "message": str(exc)}]
    if candidates:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for original, (detail, detail_errors) in zip(candidates, pool.map(enrich, candidates)):
                original.update(detail)
                errors.extend(detail_errors)
    return sorted(records, key=lambda r: match_score(title, r, year), reverse=True), errors


