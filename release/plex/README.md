# Plex metadata provider

Run `docker compose up -d` in this directory, then register
`http://YOUR_SERVER:13230` in Plex Settings > Metadata Agents > Add Provider.
Create an agent with the provider as primary and select it in a test TV
library. The server address must be reachable from Plex.

This is a native Plex HTTP metadata provider, not a legacy Plex plugin bundle.
The service is unauthenticated: keep it on a trusted network and do not expose
it to the Internet. Docker stores its cache in a named volume.

The same backend can also serve the separate Jellyfin and Emby plugins.
