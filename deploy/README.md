# GEDCOM on Rivendell for ChatGPT

Connect ChatGPT using OAuth to **https://gedcom-mcp.matta.family/mcp**.
Sign in through Cloudflare Access as `stephenjmatta@gmail.com`. The portal exposes
22 genealogy tools; the separate Claude-powered `query` fallback is hidden so
ChatGPT can reason using the structured tools without another model API key.
No Codex MCP configuration is required or created.

## Traffic and authentication

ChatGPT → Cloudflare MCP portal (owner-only OAuth) → dedicated Access service
credential → `gedcom-mcp-backend.matta.family` → existing `rivendell_host` tunnel
→ `127.0.0.1:8768` → GEDCOM container.

The backend accepts only its dedicated service token through Access. Both
cloudflared and the application validate the origin-specific signed Access JWT.
The application rejects missing, forged, expired, wrong-issuer and wrong-audience
tokens, unexpected Host headers, and browser Origin headers. `/healthz` reveals
only process readiness. No inbound router port is required.

The source GEDCOM and its derived caches remain on Rivendell; selected tool
arguments/results transit Cloudflare and ChatGPT when queried. Application
telemetry and HTTP access logging are disabled. Cloudflare account logging still
applies. Semantic embeddings run locally on CPU. GIS may send place strings to
Nominatim; geocoding coverage is partial and reported with search results.

## Host layout

- Source: `/home/sjmatta/docker/services/gedcom-mcp`
- Private tree/caches: `/home/sjmatta/.local/share/gedcom-mcp/data` (directory 700, files 600)
- Model cache: `/home/sjmatta/.local/share/gedcom-mcp/cache`
- Home person: `/home/sjmatta/.config/gedcom-mcp/home-person.env` (600), containing
  `GEDCOM_HOME_PERSON_ID` for the selected GEDCOM record. This server-wide setting
  is shared by all clients; restart the service after changing it.
- Access issuer/audience: `/home/sjmatta/.config/gedcom-mcp/cf-access.json` (600)
- Container: `gedcom-mcp`, image `gedcom-mcp:chatgpt-1`

The isolated Compose project uses a non-root UID, read-only root filesystem,
dropped capabilities, loopback-only published port, 2 GiB memory and 1.5 CPU limits.
Linux dependencies use the explicit PyTorch CPU index rather than CUDA packages.
The existing `docker-compose.yml` in the repository is the old optional Phoenix
stack; **use `deploy/compose.yaml` for this service**.

```sh
ssh -p 2222 sjmatta@rivendell
cd /home/sjmatta/docker/services/gedcom-mcp
docker compose -f deploy/compose.yaml ps
docker compose -f deploy/compose.yaml logs --tail 50
curl --fail http://127.0.0.1:8768/healthz
# Expected 401, never genealogy data:
curl -i http://127.0.0.1:8768/mcp
```

Update source, then build and recreate only this service:

```sh
docker compose -f deploy/compose.yaml build
docker compose -f deploy/compose.yaml up -d --no-build
```

Back up the private data before replacing a tree. Restart to load the replacement;
cache hashes are checked against the GEDCOM. Preserve the private data and model
cache during rollback. To stop service, use `docker compose -f deploy/compose.yaml stop`;
do not operate the unrelated parent Compose project.

## Cloudflare inventory and rotation

- Account: `05c47112ad2fb4ac022e2ddffe7bc581`
- Zone: `24369131a58295242a4370297029f64c`
- Portal/server ID: `gedcom`
- Portal Access app: `3b0a9ec6-efe4-49d7-a409-569d0272ae39`
- Server Access app: `4bba197d-3f00-4e2c-862d-4a1269ae0abd`
- Backend Access app: `2a2c5394-8146-492d-8b42-b33a66e832ba`
- Backend service policy: `7ab4a471-e9df-42d3-8ec0-e4667c5f9dac`
- Backend service token: `acb4ca1d-39ce-4cdf-a97a-67bd59e8de9e`
- Shared owner-only policy: `3a6af140-0999-4a9b-85af-80e242381f3f` (do not modify for this service)
- Tunnel: `1e650b7d-5162-4630-9081-9ac193ed6890`

The dedicated service token expires **2027-09-09 00:36 UTC**. Rotate it in
Cloudflare and update the server's stored `cf-access-client-id` and
`cf-access-client-secret` static headers before expiry. Secrets are held by
Cloudflare, not in this repository or in ChatGPT settings.

The portal requires its own proxied CNAME to `gateway.agents.cloudflare.com`;
the backend CNAME points to the tunnel. After changes, sync the `gedcom` MCP
server catalog and refresh the ChatGPT connection. Keep the portal override
`query: enabled=false`. OAuth discovery must be reachable before registering
ChatGPT. Readiness in Cloudflare confirms its authenticated origin connection;
it does not by itself prove a ChatGPT account has completed OAuth.

References: [Cloudflare MCP portals](https://developers.cloudflare.com/cloudflare-one/access-controls/ai-controls/mcp-portals/),
[ChatGPT connection](https://developers.openai.com/plugins/deploy/connect-chatgpt),
[ChatGPT OAuth](https://developers.openai.com/plugins/build/auth).

## Deployment verification (2026-09-09 UTC)

- 490 local tests passed, including signed-JWT rejection tests.
- Container healthy with zero restarts; all 33 pre-existing container IDs unchanged.
- Source data and both transferred caches matched local SHA-256 checksums.
- Loaded 20,132 individuals and 6,273 families; semantic query returned results.
- GIS reported 6,192 of 8,495 places geocoded (72%); unresolved places remain.
- Cloudflare authenticated origin catalog sync: ready, 23 tools, with `query`
  disabled in the portal override.
- Public endpoint returns 401 plus OAuth resource metadata; discovery advertises
  authorization code, refresh tokens, dynamic registration, and S256 PKCE.
- ChatGPT account linking remains a separate user OAuth step; browser automation
  was blocked on the ChatGPT URL and no connection-complete claim has been made.

## OAuth discovery configuration

Use the MCP portal's own OAuth implementation. The portal Access application has
`oauth_configuration.enabled=false`: this disables the additional self-hosted
Access managed-OAuth interceptor, **not** portal authentication. The owner-only
Access policy remains attached. Enabling both layers caused discovery to point
at the team-domain issuer while the MCP gateway used its own portal token flow,
and ChatGPT reported a generic connection failure.

Expected public discovery:

- Resource: `https://gedcom-mcp.matta.family/mcp`
- Authorization server / issuer: `https://gedcom-mcp.matta.family`
- Authorization: `/authorize`; token: `/token`; registration: `/register`
- Unauthenticated MCP: HTTP 401 with `WWW-Authenticate` resource metadata

This configuration was compared directly with the working Places portal and
corrected on 2026-09-09 UTC. Do not re-enable the extra managed-OAuth layer without
an end-to-end client test. ChatGPT account connection still requires user OAuth.
