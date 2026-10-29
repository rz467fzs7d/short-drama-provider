using System.Net.Http.Json;
using System.Text.Json.Serialization;

namespace ShortDrama;

public sealed class Drama
{
    [JsonPropertyName("key")] public string Key { get; set; } = "";
    [JsonPropertyName("title")] public string Title { get; set; } = "";
    [JsonPropertyName("source")] public string Source { get; set; } = "";
    [JsonPropertyName("id")] public string Id { get; set; } = "";
    [JsonPropertyName("summary")] public string Summary { get; set; } = "";
    [JsonPropertyName("year")] public int? Year { get; set; }
    [JsonPropertyName("poster")] public string Poster { get; set; } = "";
    [JsonPropertyName("genres")] public string[] Genres { get; set; } = Array.Empty<string>();
    [JsonPropertyName("cast")] public string[] Cast { get; set; } = Array.Empty<string>();
    [JsonPropertyName("episodes")] public DramaEpisode[] Episodes { get; set; } = Array.Empty<DramaEpisode>();
    [JsonPropertyName("match_score")] public int Score { get; set; }
}
public sealed class DramaEpisode
{
    [JsonPropertyName("index")] public int Index { get; set; }
    [JsonPropertyName("title")] public string Title { get; set; } = "";
    [JsonPropertyName("summary")] public string Summary { get; set; } = "";
}
public sealed class SearchResponse
{
    [JsonPropertyName("items")] public Drama[] Items { get; set; } = Array.Empty<Drama>();
    [JsonPropertyName("source_errors")] public SearchError[] Errors { get; set; } = Array.Empty<SearchError>();
}
public sealed class SearchError
{
    [JsonPropertyName("source")] public string Source { get; set; } = "";
    [JsonPropertyName("stage")] public string Stage { get; set; } = "";
}
public sealed class DetailResponse
{
    [JsonPropertyName("item")] public Drama? Item { get; set; }
}

public static class Backend
{
    private static readonly HttpClient Client = new() { Timeout = TimeSpan.FromSeconds(90) };
    private static Uri Url(string path)
    {
        var baseUrl = Plugin.Instance.Settings.ServerUrl.Trim();
        if (!Uri.TryCreate(baseUrl, UriKind.Absolute, out var uri) ||
            (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps) ||
            !string.IsNullOrEmpty(uri.UserInfo))
            throw new InvalidOperationException("Configure a valid metadata server URL first.");
        return new Uri(uri.ToString().TrimEnd('/') + path);
    }
    public static async Task<SearchResponse> Search(string title, int? year, CancellationToken ct)
    {
        using var response = await Client.PostAsJsonAsync(Url("/v1/search"), new { title, year }, ct);
        response.EnsureSuccessStatusCode();
        return await response.Content.ReadFromJsonAsync<SearchResponse>(cancellationToken: ct) ?? new SearchResponse();
    }
    public static async Task<Drama?> Detail(string key, CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(key) || key.Length > 400 || key.Any(c => !char.IsAsciiLetterOrDigit(c) && c != '-'))
            throw new ArgumentException("Invalid metadata key", nameof(key));
        var response = await Client.GetFromJsonAsync<DetailResponse>(Url("/v1/metadata/" + key), ct);
        return response?.Item;
    }
    public static Task<HttpResponseMessage> Image(string url, CancellationToken ct)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri) ||
            (uri.Scheme != Uri.UriSchemeHttps && uri.Scheme != Uri.UriSchemeHttp))
            throw new ArgumentException("Invalid image URL", nameof(url));
        return Client.GetAsync(uri, HttpCompletionOption.ResponseHeadersRead, ct);
    }
}
