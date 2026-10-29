# Short-drama metadata provider

An independent, read-only short-drama metadata service for Plex, Jellyfin,
and Emby. Plex connects directly to the service's custom provider API;
Jellyfin and Emby use the platform-specific plugins in this repository.
Candidates from multiple sources are ranked by matching evidence, not a
fixed source preference. Cross-source fields fill gaps only when identity can
be corroborated. Formal metadata titles do not include source labels.

The visible Plex provider name is `短剧元数据`. Its manual-match candidates
show `来源:ID`, with the work title at the start of the summary. Jellyfin and
Emby search results show the source alongside the title.
No paid API, MoviePilot dependency, video acquisition, file movement, Plex
database edits, or third-party source patches.

## Run

```sh
mkdir -p data
chown 1026:100 data
chmod 750 data
docker compose build
docker image inspect homelab/short-drama-provider:0.1.0 --format '{{json .Config.Healthcheck}}'
docker compose up -d --no-build
```

Compose uses bridge networking, a read-only root filesystem, UID 1026/GID100,
256 MiB memory limit, and one writable state mount. There is no active
healthcheck. Application concurrency is limited to 12 requests. NAS kernels
that do not support PID limits do not require unsupported cgroup settings.

## Plex registration

Register the **origin**, e.g. `http://YOUR_SERVER:13230`.
Plex appends feature keys to the registered URI. Canonical feature paths are
`/library/metadata` and `/library/metadata/matches`. `/tv` entrypoints remain
supported, including the initial duplicated prefix cached by PMS; no Plex
restart is needed to recover that cached definition.

Plex Settings > Metadata Agents > Add Provider, then create an agent with
this provider as primary. Select it only in a dedicated test library before
considering an existing library.

Read-only endpoints:

- `GET /`: Plex provider discovery (also available at `/tv`).
- `POST /tv/library/metadata/matches`: native Plex match request.
- `GET /tv/library/metadata/{key}`: metadata, optional `includeChildren=1`.
- `GET /tv/library/metadata/{key}/children`: available seasons/episodes.
- `GET /tv/library/metadata/{key}/grandchildren`: available episodes.
- `GET /tv/library/metadata/{key}/images`: available poster.
- `GET /health`: process status, not upstream availability proof.

Example match body: `{"type":2,"title":"家里家外","manual":1}`.
Keys preserve source identity, e.g. `douban-37272987` and
`hongguo-7481108346636864536`; these must not be treated as TMDB IDs.

The service is unauthenticated because the native provider interface used here
does not supply custom authentication. Keep it on a trusted LAN; do not expose
the port to the Internet. Logs do not print request URLs or Plex tokens.

## Sources and limitations

- Douban public `j/subject_suggest` provides TV candidates, year, poster and
  episode count. Subject JSON-LD supplies fuller metadata when accessible.
  A challenge page is an explicit error, not an empty result or a bypass target.
- Hongguo public `/api/search/suggestion` returns series cards. Generic query,
  album and title-only suggestions without actual series data are excluded.
  `/detail?series_id=...` exposes TVSeries JSON-LD with summary, cast and poster.
- DuanjuBaike uses `/zh-Hans/drama/search?q=...` and
  `/zh-Hans/drama/{id}`. The old `/71208` path returns 404; the current page is
  `/zh-Hans/drama/71208`. Search reads actual cover cards; detail uses JSON-LD.
- SceneTrace (`shortdramacast.com`) uses `/zh-cn/discover?q=...` and
  `/zh-cn/dramas/{slug}`. Only work cards are accepted, not actor cards.
  Multi-type JSON-LD supplies cast, aliases and explicit Hongguo citations.
  Slug keys are hex-encoded to avoid conflicts with Plex season/episode suffixes.
- New sources remain distinct candidates; they are not silently merged merely
  because titles match. Existing corroborated Douban/Hongguo merging is unchanged.
- Full Hongguo `/api/search/result` rejected the unauthenticated test request;
  the adapter does not use it, generate signatures or bypass verification.
  Suggestion results are not an exhaustive search index.
- A series may declare 75 total episodes but expose only 3 episode records.
  Only actual records are returned. Episode plots and air dates are not invented.
  A separately titled release is mapped to its own Season 1; no automatic
  franchise/season regrouping or episode-offset rewriting is attempted.
- A title alone never links different sources. Conflicting year, count, or
  disjoint casts prevent merging. Corroboration requires shared cast or both
  matching year and episode count. Ambiguous links remain separate candidates.
- Results are ordered by normalized title/alias similarity (up to 80 points),
  with a matching supplied year adding 10 points and a conflicting known year
  subtracting 30. Scores are heuristic evidence, not measured probabilities;
  unavailable year adds nothing. Cast and episode counts are used only for
  corroborating cross-source records, not for this search score. Automatic
  matching requires a score of at least 80 and a lead of at least 10; a Douban
  search failure blocks automatic matching. Close candidates remain manual.
- Douban detail blocking may leave only suggestion metadata. Do not describe
  that as full scraping. Missing fields remain missing unless safely linked.
- Douban scores are retained in normalized records, but not serialized as a
  fabricated Plex rating badge: the published provider schema supports only
  specific built-in rating sources, not a Douban badge.

Successful search/detail responses are cached persistently; searches for one
hour, empty suggestions for five minutes, details for one day. Detail failures
have a fixed one-minute negative cache that does not slide on reads. Upstream
requests have a 12-second socket timeout, at most two transient attempts and
one request per second per source. No CAPTCHA bypass or TLS disabling.
DNS resolution is subject to the host resolver, so socket timeout is not a
strict wall-clock deadline for DNS.

## Tests

```sh
python3 -W error::ResourceWarning -m unittest discover -s tests -v
```

Protocol reference: https://github.com/plexinc/tmdb-example-provider

## Jellyfin and Emby plugin source

The shared plugin source is in `plugins/ShortDrama`. Build separate binaries:

```sh
dotnet build plugins/ShortDrama/ShortDrama.csproj -c Release -o artifacts/jellyfin
dotnet build plugins/ShortDrama/ShortDrama.csproj -c Release.Emby -o artifacts/emby
```

The initial targets follow MetaTube's SDK references: Jellyfin 10.11 / .NET 9
and Emby 4.9.1.80 / .NET 8. The resulting DLLs are platform-specific and must
not be interchanged. Both builds have been verified; installation and runtime
compatibility with a live Jellyfin or Emby server have not yet been verified.
The plugin must be configured with the backend URL and
enabled in a test TV library. It supports series search, series metadata,
poster, and available source episode metadata. It does not invent absent
episodes. The Plex-compatible API remains independent of these plugins.

The plugin uses the backend's `/v1/search` and `/v1/metadata/{key}` JSON APIs;
these endpoints are unauthenticated and intended only for a trusted network.
Plex integration is provided by this project's existing custom metadata
provider HTTP API, not a separate legacy Plex bundle.

## License

MIT. The license applies to this project's code, not upstream catalog content;
users are responsible for complying with each source's terms and applicable law.
