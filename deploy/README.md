# GEDCOM on Rivendell for ChatGPT

Connect ChatGPT using OAuth to **https://gedcom-mcp.matta.family/mcp**.
Sign in through Cloudflare Access as `stephenjmatta@gmail.com`. The portal exposes
41 genealogy, evidence-research, audit and versioning tools. ChatGPT reasons
using the structured tools; the internal `query` agent has been removed.
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
- Revision store and current caches: `/home/sjmatta/.local/share/gedcom-mcp/store` (700)
- Container: `gedcom-mcp`, image `gedcom-mcp:versioned-writes-1`

The isolated Compose project uses a non-root UID, read-only root filesystem,
dropped capabilities, loopback-only published port, 2 GiB memory and 1.5 CPU limits.
Linux dependencies use the explicit PyTorch CPU index rather than CUDA packages.
The existing `docker-compose.yml` in the repository is the old optional Phoenix
stack; **use `deploy/compose.yaml` with `deploy/compose.writes.yaml` for this service**.

```sh
ssh -p 2222 sjmatta@rivendell
cd /home/sjmatta/docker/services/gedcom-mcp
docker compose -f deploy/compose.yaml -f deploy/compose.writes.yaml ps
docker compose -f deploy/compose.yaml -f deploy/compose.writes.yaml logs --tail 50
curl --fail http://127.0.0.1:8768/healthz
# Expected 401, never genealogy data:
curl -i http://127.0.0.1:8768/mcp
```

Update source, then build and recreate only this service:

```sh
docker compose -f deploy/compose.yaml -f deploy/compose.writes.yaml build
docker compose -f deploy/compose.yaml -f deploy/compose.writes.yaml up -d --no-build
```

Use prepared, reviewed proposals for family-data edits. The imported GEDCOM is
immutable; replacing it requires a deliberately separate store and import.
Preserve revision history, private data, and model caches during rollback. To stop
service, use `docker compose -f deploy/compose.yaml -f deploy/compose.writes.yaml stop`;
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


## Accuracy release and rollback

Before deploying `chatgpt-2`, retain the old image and a private copy of the data
and source directory. The semantic cache content version is now 3 and rebuilds
once; prebuild it using an isolated Compose run with GIS disabled before switching
the HTTP service. Geocache version 2 preserves successful full-query Nominatim
entries, discards legacy city-only coordinates, and rechecks the remainder in the
background. Coverage can decrease while more conservative matching runs.

For rollback, stop only `gedcom-mcp`, restore the saved data and source directory,
and run the saved Compose definition with its retained old image using `--no-build`.
Do not restore caches while the current service is writing them. The private
home-person configuration and Cloudflare authentication settings are unchanged.

### Accuracy release verification (2026-09-09 UTC)

- Runtime release: `c300fe0`, image `gedcom-mcp:chatgpt-2`.
- 514 tests passed locally and in GitHub CI on Python 3.12 and 3.13.
- Prebuilt content-version-3 semantic index: 20,129 nonempty records. The temporary
  build used six CPUs; production remains at 1.5 CPUs and 2 GiB memory.
- Deployed-image MCP smoke test: 25 tools, 20,132 people, 6,273 families; configured
  home person and parent relationship path verified; semantic search returned results.
- HTTP container healthy, zero restarts; missing/forged origin assertions return 401.
- Public backend returns 403; portal returns 401; OAuth discovery returns 200 with
  the expected portal issuer. Cloudflare authenticated catalog sync is ready and
  includes both new tools. The `query` override remains disabled (24 exposed tools).
- Original GEDCOM hash unchanged and all other pre-existing container IDs unchanged.
- Geocache version 2 written; background rechecking remains in progress. A verification
  snapshot contained 3,032 resolved entries; this is not a final coverage count.
- Rollback image: `gedcom-mcp:pre-accuracy-20260909`; source and data snapshot:
  `/home/sjmatta/.local/share/gedcom-mcp/rollback-accuracy-20260909`.

## Opt-in write deployment and independent backups

The implementation and recovery contract are in [WRITES.md](../WRITES.md).
Production uses this overlay as of September 30, 2026 (Eastern time):

```sh
install -d -m 700 /home/sjmatta/.local/share/gedcom-mcp/store
cd /home/sjmatta/docker/services/gedcom-mcp
# Review resolved mounts/environment before rebuilding/restarting.
docker compose -f deploy/compose.yaml -f deploy/compose.writes.yaml config
docker compose -f deploy/compose.yaml -f deploy/compose.writes.yaml up -d --build
```

The overlay mounts the imported data read-only and the new private store at
`/state`. Confirm the import matches the chosen immutable baseline before starting.
Update any MCP Portal tool allowlist to expose only the desired write tools to
trusted operators. Check the authenticated catalog, prepare a test proposal without
applying it, inspect `get_tree_context`, and exercise a separate restored instance
before accepting family-data edits. Version 2 advertises 9 read-only tools or 12
with writes enabled. Refresh portal/client capabilities after deploying this major
interface; discovery and dispatch must be allowed together. Check discovered
read execution and preparation through the actual authenticated client. Historical
deployment snapshots below describe earlier interfaces, not a version 2 deployment.

Rivendell's existing NAS and S3 Restic containers both mount the complete
`/home/sjmatta/.local/share/gedcom-mcp` directory. On 2026-09-30, live inspection
confirmed those mounts and a 03:00 America/New_York whole-stack schedule, but the
latest whole-stack snapshots were September 28. Its coverage audit currently
rejects an unrelated image-service bind mount. Do not treat that scheduler as
verified-current protection for the new store.

`deploy/backup-rivendell.sh` provides a scoped job using the same repositories and
host backup lock. It publishes a consistent SQLite snapshot through the running
GEDCOM container, backs up only that snapshot to S3 and NAS, and downloads and
compares it byte-for-byte from **each** destination before pruning staging files.
It checks the expected NFS mount before NAS writes and retains three recent,
30 daily, and 12 monthly tagged snapshots. Retention groups by host/tags, since
snapshot filenames change. Repository pack pruning remains with existing jobs.
The script fails on any unavailable destination or failed read-back. Replication
staging keeps at most three self-contained snapshots even during repeated failures;
snapshot creation also reserves free space before copying the database.

After deploying the write-enabled service, install one cron entry (host uses UTC):

```cron
30 8 * * * /bin/bash /home/sjmatta/docker/services/gedcom-mcp/deploy/backup-rivendell.sh 2>&1 | logger -t gedcom-backup
```

This runs daily at 04:30 Eastern daylight time / 03:30 standard time, after the
existing 03:00 backup slot. Run it once immediately and verify both tagged Restic
snapshots before enabling real writes. To recover, download a tagged snapshot,
run the deep verifier, restore to a new directory, and change the service mounts
only after verifying the restored tree. Never restore a raw live SQLite file from
a generic filesystem snapshot when a verified GEDCOM snapshot is available.

### Live write release verification (2026-10-01 UTC)

- Release: `e3887db`, image `gedcom-mcp:versioned-writes-1`, image ID
  `sha256:63760e6b56b66262d4e269a3ee7bf118132f1babdddc4adecd11f50b34d6fa22`.
- 579 tests, Ruff/format, mypy, dependency checks, and required GitHub CI passed.
  The real-tree pilot uncovered a fixed-width semantic-cache memory problem;
  UTF-8 text with validated offsets now keeps storage proportional to actual text.
- Isolated real-tree write, immediate read, restore, semantic refresh, and offline
  recovery passed under the 2 GiB memory limit. The production tree remains at
  revision 0, with 20,132 people and 6,273 families and its original checksum.
- Live container healthy; authenticated statistics, semantic search, and GIS
  returned results. Origin and portal reject unauthenticated MCP with 401, backend
  with 403, and OAuth discovery returns 200.
- Cloudflare catalog ready: 33 server tools, 32 exposed under the existing owner
  policy. The `query` override remains disabled. Refresh the Family Tree connection
  and start a new conversation to discover the additional tools.
- Daily scoped backup cron installed at 08:30 UTC. Immediate S3 snapshot
  `b6c6ba85` and NAS snapshot `39943e26` both read back byte-for-byte successfully.
  The independently replicated snapshot passed deep verification, restored into
  a separate store, and reloaded with the expected counts; preparation did not
  advance its revision.
- Other pre-existing container IDs unchanged. Rollback image
  `gedcom-mcp:pre-writes-20260930`; source/data/container/cron snapshot in
  `/home/sjmatta/.local/share/gedcom-mcp/rollback-writes-20260930`.

To return to the previous read-only service, stop only GEDCOM, restore its saved
source, and use the retained rollback image with the base Compose file and
`--no-build`. Preserve the new revision store and its backups; reverting the
application must never discard accepted family-data changes. Restore tree data
only through the separately verified recovery workflow described above.


### Structural and evidence release verification (2026-10-01 UTC)

- Deployed merged main `593008c`, including PRs #60 (structural edits), #61
  (evidence reads) and #62 (semantic retrieval). Their required GitHub CI passed;
  local validation passed 530 tests, Ruff lint/format, mypy and dependency checks.
- Built image `gedcom-mcp:593008c`, also tagged `versioned-writes-1`, with image ID
  `sha256:0ce19072601fe4c850c6ca1c58c01b195fbba8d88f92c32eee5ed896c8716eef`.
  The final container was healthy, with zero restarts and no OOM kill; observed
  idle memory was approximately 492 MiB under the existing 2 GiB limit.
- Prebuilt 86,665 passages from the exact current-tree checksum and pinned BGE
  model using local MPS. The 125,469,937-byte index transferred with SHA-256
  `bf95e9e363dce83da30af04fb357772bf83f0cd349dcfea38dfdd815166090c4`.
  Preserve this prebuild step before starting the serving image; the initial
  cold-start attempt was stopped and the previous image served during preparation.
- Authenticated `get_tree_revision` returned revision 0 with semantic search
  ready and the unchanged baseline checksum. A read-only whole-tree audit found
  no structural errors. Evidence warnings remain research tasks, not automatic
  corrections. No live genealogy edits were applied.
- Cloudflare capability sync returned Ready with 41 tools. Refreshed Family Tree
  in ChatGPT and verified `audit_tree`, `plan_tree_prune`, and the structural
  relationship, delete and merge operations in `prepare_tree_change`. ChatGPT
  shows 44 tools including the three portal-management tools. Start a new chat
  with Family Tree selected to load these definitions.
- All other running container IDs were unchanged. Rollback image is
  `gedcom-mcp:pre-structural-20261001`; source, prior semantic cache, container
  inventory and original source commit are retained in
  `/home/sjmatta/.local/share/gedcom-mcp/rollback-structural-20261001`. A consistent
  predeployment SQLite snapshot in the store's replication directory passed deep
  verification. Existing independent-backup configuration was preserved.
- The deployment directory belongs to the homelab repository, not this repository.
  Installed the verified main archive into only that service directory after
  preserving its source; do not merge GEDCOM repository history into homelab.
