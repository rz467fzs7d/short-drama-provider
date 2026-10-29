using MediaBrowser.Controller.Entities.TV;
using MediaBrowser.Controller.Providers;
using MediaBrowser.Model.Entities;
using MediaBrowser.Model.Providers;
#if EMBY
using MediaBrowser.Common.Net;
using MediaBrowser.Model.Configuration;
#else
using Jellyfin.Data.Enums;
#endif

namespace ShortDrama;

public sealed class SeriesProvider : IRemoteMetadataProvider<Series, SeriesInfo>, IHasOrder
{
    public string Name => Plugin.ProviderName;
    public int Order => 1;

    public async Task<IEnumerable<RemoteSearchResult>> GetSearchResults(SeriesInfo info, CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(info.Name)) return Array.Empty<RemoteSearchResult>();
        var data = await Backend.Search(info.Name, info.Year, ct);
        return data.Items.Select(item => {
            var result = new RemoteSearchResult {
                Name = $"[{item.Source}] {item.Title}", SearchProviderName = Name,
                ProductionYear = item.Year, ImageUrl = item.Poster
            };
            result.SetProviderId(Name, item.Key);
            return result;
        }).ToArray();
    }

    public async Task<MetadataResult<Series>> GetMetadata(SeriesInfo info, CancellationToken ct)
    {
        var key = info.GetProviderId(Name);
        if (string.IsNullOrWhiteSpace(key))
        {
            if (string.IsNullOrWhiteSpace(info.Name)) return new MetadataResult<Series>();
            var results = await Backend.Search(info.Name, info.Year, ct);
            if (results.Errors.Length > 0 || results.Items.Length == 0 || results.Items[0].Score < 80 ||
                (results.Items.Length > 1 && results.Items[0].Score - results.Items[1].Score < 10))
                return new MetadataResult<Series>();
            key = results.Items[0].Key;
        }
        var item = await Backend.Detail(key, ct);
        if (item is null) return new MetadataResult<Series>();
        var series = new Series { Name = item.Title, Overview = item.Summary,
                                  ProductionYear = item.Year, Genres = item.Genres };
        series.SetProviderId(Name, item.Key);
        var result = new MetadataResult<Series> { Item = series, HasMetadata = true };
        foreach (var actor in item.Cast.Where(name => !string.IsNullOrWhiteSpace(name)))
            result.AddPerson(new PersonInfo { Name = actor,
#if EMBY
                Type = PersonType.Actor
#else
                Type = PersonKind.Actor
#endif
            });
        return result;
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

public sealed class SeriesImageProvider : IRemoteImageProvider, IHasOrder
{
    public string Name => Plugin.ProviderName;
    public int Order => 1;
    public bool Supports(MediaBrowser.Controller.Entities.BaseItem item) => item is Series;
    public IEnumerable<ImageType> GetSupportedImages(MediaBrowser.Controller.Entities.BaseItem item) => new[] { ImageType.Primary };
#if EMBY
    public async Task<IEnumerable<RemoteImageInfo>> GetImages(MediaBrowser.Controller.Entities.BaseItem item, LibraryOptions options, CancellationToken ct)
#else
    public async Task<IEnumerable<RemoteImageInfo>> GetImages(MediaBrowser.Controller.Entities.BaseItem item, CancellationToken ct)
#endif
    {
        var key = item.GetProviderId(Name);
        if (string.IsNullOrWhiteSpace(key)) return Array.Empty<RemoteImageInfo>();
        var drama = await Backend.Detail(key, ct);
        if (string.IsNullOrWhiteSpace(drama?.Poster)) return Array.Empty<RemoteImageInfo>();
        return new[] { new RemoteImageInfo { ProviderName = Name, Type = ImageType.Primary, Url = drama.Poster } };
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
