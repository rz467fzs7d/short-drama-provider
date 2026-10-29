using MediaBrowser.Common.Plugins;
#if EMBY
using System.ComponentModel;
using Emby.Web.GenericEdit;
using MediaBrowser.Common;
using MediaBrowser.Controller.Plugins;
using MediaBrowser.Model.Attributes;
#else
using MediaBrowser.Common.Configuration;
using MediaBrowser.Model.Plugins;
using MediaBrowser.Model.Serialization;
#endif

namespace ShortDrama;

#if EMBY
public sealed class PluginOptions : EditableOptionsBase
{
    public override string EditorTitle => "短剧元数据";
    [DisplayName("Metadata server URL")]
    [Description("URL reachable from this server, for example http://host:13230")]
    [Required]
    public string ServerUrl { get; set; } = "";
}
public sealed class Plugin : BasePluginSimpleUI<PluginOptions>
{
    public Plugin(IApplicationHost host) : base(host) { Instance = this; }
    public PluginOptions Settings => GetOptions();
#else
public sealed class PluginOptions : BasePluginConfiguration
{
    public string ServerUrl { get; set; } = "";
}
public sealed class Plugin : BasePlugin<PluginOptions>, IHasWebPages
{
    public Plugin(IApplicationPaths paths, IXmlSerializer serializer) : base(paths, serializer) { Instance = this; }
    public PluginOptions Settings => Configuration;
    public IEnumerable<PluginPageInfo> GetPages() => new[] { new PluginPageInfo {
        Name = "ShortDrama", EmbeddedResourcePath = "ShortDrama.Configuration.html" } };
#endif
    public const string ProviderName = "ShortDrama";
    public static Plugin Instance { get; private set; } = null!;
    public override string Name => "短剧元数据";
    public override string Description => "Multi-source short drama metadata";
    public override Guid Id => Guid.Parse("83a6f764-ff80-4b35-99f6-742112efc544");
}
