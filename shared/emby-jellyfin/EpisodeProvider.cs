using MediaBrowser.Controller.Entities.TV;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Model.Providers;
#if EMBY
using MediaBrowser.Common.Net;
#endif

namespace ShortDrama;

public sealed class EpisodeProvider : IRemoteMetadataProvider<Episode, EpisodeInfo>, IHasOrder
{
    public string Name => Plugin.ProviderName;
    public int Order => 1;
    public Task<IEnumerable<RemoteSearchResult>> GetSearchResults(EpisodeInfo info, CancellationToken ct)
        => Task.FromResult<IEnumerable<RemoteSearchResult>>(Array.Empty<RemoteSearchResult>());

    public async Task<MetadataResult<Episode>> GetMetadata(EpisodeInfo info, CancellationToken ct)
    {
        if (!info.SeriesProviderIds.TryGetValue(Name, out var key) || string.IsNullOrWhiteSpace(key) ||
            info.ParentIndexNumber != 1 || info.IndexNumber is not > 0)
            return new MetadataResult<Episode>();
        var show = await Backend.Detail(key, ct);
        var episode = show?.Episodes.FirstOrDefault(e => e.Index == info.IndexNumber);
        if (episode is null) return new MetadataResult<Episode>();
        return new MetadataResult<Episode> { HasMetadata = true, Item = new Episode {
            Name = episode.Title, Overview = episode.Summary,
            IndexNumber = episode.Index, ParentIndexNumber = 1 } };
    }
#if EMBY
    public async Task<HttpResponseInfo> GetImageResponse(string url, CancellationToken ct)
    {
        var response = await Backend.Image(url, ct);
        return new HttpResponseInfo { Content = await response.Content.ReadAsStreamAsync(ct),
            ContentLength = response.Content.Headers.ContentLength, ContentType = response.Content.Headers.ContentType?.ToString(),
            StatusCode = response.StatusCode, Headers = response.Content.Headers.ToDictionary(k => k.Key, v => string.Join(", ", v.Value)) };
    }
#else
    public Task<HttpResponseMessage> GetImageResponse(string url, CancellationToken ct) => Backend.Image(url, ct);
#endif
}
