Creates a playlist containing every song from an artist, in order of release.

Supports multiple artists as arguments.

Run with 

```bash
uv run ./spotify_playlist.py "Drake" "Kendrick Lamar"
```

Requires a [Spotify Developer API information](https://developer.spotify.com/dashboard) in the environment (or a .env) file.

```bash
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
SPOTIFY_REDIRECT_URI=http://localhost:8888/callback
```
