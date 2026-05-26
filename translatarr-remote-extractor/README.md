# Translatarr Remote Extractor

Docker-first companion service for `service.translatarr`.

Purpose:
- provide embedded subtitle extraction for platforms where local tools are unavailable or impractical
- support Android / NVIDIA Shield clients through a remote HTTP API
- keep extraction logic separate from the Kodi addon runtime

Current API:
- `GET /health`
- `POST /probe`
- `POST /extract`

Current capabilities:
- bearer-token authentication
- path mapping from `smb://`, UNC, and `dav://` playback paths to server-mounted paths
- `MKV` extraction via `mkvinfo` + `mkvextract`
- `MP4` extraction via `ffprobe` + `ffmpeg`
- target-language embedded subtitle probing through `/probe`
- extracted subtitle caching
- request-driven timeout control from the Kodi add-on

Deployment targets:
- Docker Compose
- Portainer stacks

Current state:
- running production companion service for `service.translatarr`
- bearer-token authentication enabled
- path-mapping config enabled
- `MKV` extraction path enabled
- `MP4` extraction path enabled
- extracted subtitle cache enabled
- target-language embedded subtitle probe enabled
- timeout is supplied per request by `service.translatarr`

## Production-Validated Behavior

The current production workflow has been validated for:

- Docker / Portainer deployment
- symlink-backed media, as long as the container can resolve the real target path
- remote probing of embedded target-language subtitles through `/probe`
- remote extraction of embedded source subtitles through `/extract`
- path mapping from Kodi playback paths to real mounted filesystem paths inside the container

Important rule:

- path mapping only rewrites the request path
- the rewritten path must still exist inside the container and lead to a real readable media file

Examples of playback-path patterns that can work when mapped correctly:

- `smb://your-media-server/your-share/...`
- `\\\\your-media-server\\your-share\\...`
- `dav://your-server:3000/content/...`

Examples of what still fails even after path mapping:

- the mapped path points to a symlink whose real target is not mounted inside the container
- the container can see the top-level media folder but not the submount or remote filesystem behind it
- playback uses a non-filesystem path that has no meaningful local equivalent on the extractor host

## Published Image

Normal users should deploy the published container image:

```text
ghcr.io/addonniss/translatarr-remote-extractor:latest
```

The GitHub Actions workflow publishes this image automatically when the project changes.

## Docker Compose

1. Place this project on the server that can access your media files.
2. Review `docker-compose.yml`.
3. Set a real `EXTRACTOR_API_TOKEN`.
4. Mount your media into the container as read-only.
5. Adjust `EXTRACTOR_PATH_MAPS` so Kodi playback paths resolve to the mounted server paths.
6. Start the service:

```bash
docker compose up -d
```

For normal user deployment, the default compose file uses the published GHCR image.

For local development from source, use:

```bash
docker compose -f docker-compose.dev.yml up -d --build
```

Example media mount:

```yaml
volumes:
  - ./cache:/cache
  - ./work:/work
  - /data/media:/data/media:ro
```

Example path mapping:

```yaml
environment:
  EXTRACTOR_PATH_MAPS: >
    [
      {"from": "smb://your-media-server/your-share/", "to": "/data/media/"},
      {"from": "\\\\your-media-server\\your-share\\", "to": "/data/media/"},
      {"from": "dav://your-server:3000/content/", "to": "/data/remote/content/"}
    ]
```

Complete example stack:

```yaml
services:
  translatarr-remote-extractor:
    image: ghcr.io/addonniss/translatarr-remote-extractor:latest
    container_name: translatarr-remote-extractor
    restart: unless-stopped
    ports:
      - "8097:8097"
    environment:
      - EXTRACTOR_API_TOKEN=replace-with-your-token
      - EXTRACTOR_CACHE_DIR=/cache
      - EXTRACTOR_WORK_DIR=/work
      - EXTRACTOR_PATH_MAPS=[
          {"from":"smb://your-media-server/your-share/media/","to":"/data/media/"},
          {"from":"\\\\your-media-server\\your-share\\media\\","to":"/data/media/"},
          {"from":"dav://your-server:3000/content/","to":"/data/remote/content/"}
        ]
    volumes:
      - /path/to/translatarr-remote-extractor/cache:/cache
      - /path/to/translatarr-remote-extractor/work:/work
      - /path/to/your/media/root:/data:ro
```

In this example:

- Kodi sends playback paths such as `smb://your-media-server/your-share/media/...`
- the extractor maps them to `/data/media/...`
- the container can then open the real media file through the `/path/to/your/media/root:/data:ro` mount
- if Kodi sends `dav://your-server:3000/content/...`, the extractor can also map that to `/data/remote/content/...` as long as that remote-backed path is actually mounted and readable inside the container

Health check example:

```bash
curl http://SERVER_IP:8097/health
```

## Portainer

You can deploy the same service as a Portainer stack.

Recommended flow:

1. Open Portainer.
2. Go to `Stacks`.
3. Create a new stack named `translatarr-remote-extractor`.
4. Paste the contents of `docker-compose.yml`.
5. Edit:
   - `EXTRACTOR_API_TOKEN`
   - media volume mounts
   - `EXTRACTOR_PATH_MAPS`
6. Deploy the stack.

Portainer notes:
- keep media mounts read-only
- keep `cache` and `work` on writable storage
- if Kodi sends `smb://`, UNC, or `dav://` paths, make sure they are translated to paths that exist inside the container
- if your media relies on symlinks into another mounted path, the container must also be able to resolve that underlying target path

## Image Publishing

This project is set up to publish a container image to GHCR using:

- `.github/workflows/translatarr_remote_extractor_image.yml`

Published image name:

```text
ghcr.io/addonniss/translatarr-remote-extractor:latest
```

The workflow currently publishes:
- `latest`
- a commit-SHA tag

## Environment Variables

- `EXTRACTOR_API_TOKEN`
  - optional bearer token required by `/probe` and `/extract`
- `EXTRACTOR_CACHE_DIR`
  - writable cache directory inside the container
- `EXTRACTOR_WORK_DIR`
  - writable temporary extraction directory
- `EXTRACTOR_PATH_MAPS`
  - JSON array mapping Kodi playback paths to server-mounted paths

## Important Path Rule

The extractor host must be able to open the same video file that Translatarr requests.

That means one of these must be true:
- Kodi already provides a filesystem path the server can access directly
- path mapping converts `smb://`, UNC, or `dav://` playback paths into valid mounted container paths

## Timeouts And Slow Media

Extraction time depends on:

- container storage performance
- whether the file is local, network-backed, or symlink-backed
- whether the media ultimately resolves into a slower remote mount
- `mkvextract` / `ffmpeg` runtime for the selected subtitle track

Practical guidance:

- `service.translatarr` sends one timeout value per `/probe` and `/extract` request
- that same request timeout is used for both the HTTP wait on the Kodi side and the real extractor commands on the server side
- changing the `Remote Extractor Timeout` setting in Translatarr therefore changes the real probe and extraction timeout too

Important:

- the request timeout must be greater than `0`
- the extractor no longer uses a separate server-side extraction timeout setting for normal requests

If extraction works in principle but seems to fail after a long wait, compare:

- the timeout configured in Translatarr
- whether the mapped path resolves through a slower remote mount or symlink chain
