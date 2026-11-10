# Azure AD Claim Mapper + Authorizer for Self-Hosted Temporal

**Date:** 2026-11-10
**Status:** Design — approved, pending implementation plan
**Supersedes the "give up on namespace RBAC" conclusion recorded in project memory `project-temporal-rbac` (2026-10-21).**

## Goal

Namespace-level RBAC that actually works on self-hosted Temporal, with roles
driven by Microsoft Entra ID (Azure AD) app roles. A user holding
`dev:writer` can act in the `dev` namespace and nowhere else; a user holding
`uat:reader` can read `uat` only; the Temporal UI loads for both.

## Scope

**In scope:** localhost `docker-compose` only.

**Out of scope:** AKS deployment, Temporal Cloud, production hardening,
filtering the `ListNamespaces` *response*.

## Decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | Write both a custom `ClaimMapper` **and** a custom `Authorizer` | The default authorizer treats `ListNamespaces` as cluster-scoped; that cannot be changed by configuration |
| 2 | Build our own server binary that imports `go.temporal.io/server` as a library | Official extension pattern; no source patching |
| 3 | Map roles from the `roles` claim only | Matches the app roles already defined on the `TemporalUI` registration |
| 4 | Issue a dedicated `CN=temporal-admin` client cert for admin tooling | Lets tokenless admin callers be identified by certificate instead of granting admin to every tokenless caller |
| 5 | Read-only cluster-scoped APIs: allow when the caller holds a role in at least one namespace | UI loads; the cost is that namespace *names*, cluster identity and the search-attribute schema are visible to every signed-in user |
| 6 | Normalize role words in our mapper rather than renaming Azure app roles | No Azure changes needed; the table is small and directly testable |
| 7 | Target `docker-compose-mtls.yaml`, not the currently-running single-container stack | Decision 4 requires mTLS so that `AuthInfo.TLSSubject` is populated |

## Verified findings

All citations are against `go.temporal.io/server@v1.31.0` in the local module
cache, matching `TEMPORAL_VERSION=1.31.0` in `samples-server/compose/.env`.
Every API below was confirmed present at v1.31.0, not just v1.32.0.

### The extension points exist and are public

| API | Location |
|---|---|
| `temporal.WithAuthorizer(authorization.Authorizer)` | `temporal/server_option.go:96` |
| `temporal.WithClaimMapper(func(*config.Config) authorization.ClaimMapper)` | `temporal/server_option.go:110` |
| `config.WithEmbedded()` | `common/config/loader.go:113` |
| `authorization.NewDefaultTokenKeyProvider(*config.Authorization, log.Logger)` | `common/authorization/default_token_key_provider.go:34` |
| `authorization.NewInternalClaimMapper()` | `common/authorization/claim_mapper.go:68` |

`config.WithEmbedded()` is the critical one. The `temporalio/server` image
holds no config YAML at all — confirmed by inspecting the running container:
`/etc/temporal/config/` contains only `dynamicconfig/`, and the entrypoint is
simply `exec temporal-server start`. The binary renders
`common/config/config_template_embedded.yaml` from environment variables, and
logs `Loading configuration from environment variables only`.

Calling `config.Load(config.WithEmbedded())` from our own `main.go` reproduces
that behaviour exactly, so **every `TEMPORAL_*`, `DB`, `POSTGRES_*` and
`ENABLE_ES` variable already in the compose file keeps working untouched.**
Without it we would have to hand-write and maintain a full server config YAML.

### Two latent bugs in the existing Azure app roles

The app roles on the `TemporalUI` registration cannot work with Temporal's
permission parser as written:

| Problem | Current app role value | What the code requires | Effect |
|---|---|---|---|
| Role word | `uat:reader`, `dev:writer` | `permissionRead = "read"`, `permissionWrite = "write"`, `permissionAdmin = "admin"`, `permissionWorker = "worker"` — `common/authorization/default_jwt_claim_mapper.go:21-24` | `permissionToRole("reader")` falls through the switch and returns `RoleUndefined` — no permission at all |
| System scope | `system:admin` | `permissionScopeSystem = primitives.SystemLocalNamespace`, and `SystemLocalNamespace = "temporal-system"` — `common/primitives/namespaces.go:11` | Parsed as a namespace literally named `system`, never as a cluster-level role |

This revises the root cause recorded in project memory and in the comment at
`docker-compose-mtls.yaml:217-229`. The token genuinely did carry
`"roles": ["uat:reader"]` as verified via jwt.ms, but Temporal could not
translate that string into any role. `ListNamespaces` being cluster-scoped was
a real second obstacle, not the whole story.

Per decision 6 we absorb both in our mapper instead of editing Azure.

### The internal frontend is the supported fix for the tokenless-worker problem

Temporal's own services do not carry a JWT, which is why enabling the default
authorizer previously killed the server. The upstream answer is a second
frontend dedicated to internal traffic:

- `USE_INTERNAL_FRONTEND` adds an `internal-frontend` service on gRPC port
  `7236`, membership port `6936` — `config_template_embedded.yaml:283-290`
- The internal frontend uses `NewInternalClaimMapper()`, which returns
  `Claims{System: RoleAdmin, AuthType: InternalPrincipalType, Subject: InternalPrincipalName}`
  unconditionally — `common/authorization/claim_mapper.go:68`
- `config_template_embedded.yaml:351` emits `publicClient` **only** when an
  authorizer or claim mapper is configured *and* the internal frontend is not
  in use. `publicClient` is how the internal worker service finds a frontend,
  so in the previous attempt it was pointed at the external frontend, where our
  authorizer would reject it.

Consequences: no admin-for-tokenless-callers hack is needed, and the `worker`
service can be restored to the compose stack, bringing back the scanner and
archival workflows that were lost when it was omitted.

### JWT validation can be mostly reused, parsing cannot

`NewDefaultTokenKeyProvider` handles JWKS fetching and periodic key refresh, and
satisfies the public `TokenKeyProvider` interface
(`EcdsaKey` / `HmacKey` / `RsaKey` / `SupportedMethods` / `Close`).

`parseJWT` itself is unexported, so roughly 30 lines must be replicated in our
module, following `common/authorization/default_jwt_claim_mapper.go:149-200`:
build a `jwt.NewParser(jwt.WithValidMethods(provider.SupportedMethods()))`,
resolve the key by `kid` and signing method, then validate claims. The
`RawTokenKeyProvider` branch should be kept for forward compatibility.

`AuthInfo.AuthToken` arrives with a `Bearer ` prefix and must be split on the
first space, as the default mapper does at line 86.

The dependency is `github.com/golang-jwt/jwt/v4 v4.5.2`, per the server's own
`go.mod:28`.

### Current runtime state

The running stack is **not** the mTLS stack. `docker ps` shows `temporal`
(single `temporalio/server:1.31.0` container), `temporal-ui` and
`temporal-postgresql` — this is `docker-compose.yml`. Project memory describing
`docker-compose-mtls.yaml` as live is out of date. Server logs confirm authz is
off: *"Not using any authorizer and flag `--allow-no-auth` not detected."*

PKI common names currently issued by `tls/Dockerfile.mtls`:

| CN | Purpose |
|---|---|
| `temporal-ca` | Root CA |
| `temporal-cluster` | Internode, shared by frontend/history/matching, server + client auth |
| `temporal-frontend` | External gRPC server cert on :7233 |
| `temporal-client` | Every external caller — UI, admin-tools, SDK clients |

## Architecture

### Module layout

```
samples-server/compose/authz-server/
├── go.mod              go.temporal.io/server v1.31.0 (pinned to TEMPORAL_VERSION)
├── jwt.go              replicated parseJWT over TokenKeyProvider
├── roles.go            role-word + system-scope normalization
├── claimmapper.go      AzureClaimMapper
├── authorizer.go       AzureAuthorizer
├── main.go             config.WithEmbedded + WithClaimMapper + WithAuthorizer
├── *_test.go           table-driven unit tests
└── Dockerfile          FROM temporalio/server:1.31.0, adds our binary
```

Five small files, each with one job, so each can be read and tested on its own.

### `roles.go` — normalization

One exported function, `ParsePermission(s string) (namespace string, role authorization.Role, ok bool)`.

Splits on the first `:`, then:

| Input role word | Result |
|---|---|
| `read`, `reader` | `RoleReader` |
| `write`, `writer` | `RoleWriter` |
| `admin` | `RoleAdmin` |
| `worker` | `RoleWorker` |
| anything else | `ok == false` |

Namespace `system` is rewritten to `temporal-system` so both spellings land on
the cluster-level role. Matching is case-insensitive, mirroring
`permissionToRole`'s `strings.ToLower`.

### `claimmapper.go` — `AzureClaimMapper`

```
GetClaims(authInfo) →
  1. TLSSubject.CN == "temporal-admin"  → Claims{System: RoleAdmin}
  2. AuthToken != ""                    → strip "Bearer ", validate via
                                          TokenKeyProvider, read `roles`,
                                          map each entry through ParsePermission
  3. otherwise                          → Claims{} (empty → authorizer denies)
```

`Claims.Subject` is set from the token's `preferred_username`, falling back to
`sub`, so denials are traceable in logs. A `roles` entry that fails to parse is
logged at warn level and skipped rather than failing the whole request.

Internal traffic is **not** handled here — the internal frontend and
`NewInternalClaimMapper` cover it. `CN=temporal-cluster` is deliberately given
no special case, keeping this mapper's surface as small as possible.

### `authorizer.go` — `AzureAuthorizer`

**Delegates to the default authorizer**, intercepting one class of call.

```
Authorize(ctx, claims, target) →
  1. target is a read-only cluster-scoped API
     and the caller holds any non-zero namespace role  → allow   ← the one change
  2. otherwise → default authorizer's decision, verbatim
```

Step 1 is what lets the UI load for a namespace-scoped user, per decision 5.
Everything else — the health-check allowance, the nil-claims denial, the
scope/role model — comes from `authorization.NewDefaultAuthorizer()` for free,
so this file does not restate it and cannot drift from it.

The intercepted class is `{Scope: ScopeCluster, Access: AccessReadOnly}`,
tested with `api.GetMethodMetadata(target.APIName)`. In v1.31.0 that class is
exactly four APIs:

| API | Why the caller needs it |
|---|---|
| `GetSystemInfo` | already allowed — it is in Temporal's health-check allowlist |
| `ListNamespaces` | the namespace dropdown |
| `GetClusterInfo` | the UI refuses to render without it |
| `GetSearchAttributes` | the search-attribute schema, needed to open a namespace |

**This is deliberately a class and not a list of names.** An earlier revision
intercepted `ListNamespaces` alone, on the belief — carried over from the
2026-10 POC — that it was the UI's first and only blocking call. Integration
testing disproved that: `ListNamespaces` returned 200 while `GetClusterInfo`
returned 403 in the same browser session, and the UI bounced to `/login`.

The tradeoff is explicit and bounded. A namespace-scoped user can read every
namespace *name*, the cluster's identity and version, and the names and types
of search attributes. None of that exposes workflow data or namespace contents.
Every cluster-scoped *mutating* API — `AddOrUpdateRemoteCluster`,
`RemoveRemoteCluster`, `ListClusters` and the Nexus endpoint operations —
stays denied, because those require a `System` role and a namespace-scoped
caller has `claims.System == 0`.

### `main.go` — wiring

```go
cfg, err := config.Load(config.WithEmbedded())
// ...
temporal.NewServer(
    temporal.ForServices(servicesFromEnv()),
    temporal.WithConfig(cfg),
    temporal.WithClaimMapper(func(c *config.Config) authorization.ClaimMapper {
        return NewAzureClaimMapper(c, logger)
    }),
    temporal.WithAuthorizer(NewAzureAuthorizer()),
    temporal.InterruptOn(temporal.InterruptCh()),
)
```

**The service list must be read from the environment by us.**
`temporal.ForServices(names []string)` takes an explicit list and the library
never consults `TEMPORAL_SERVICES` — `temporal/server_option.go:55`. In the
stock binary that variable is a urfave/cli flag on `cmd/server`, which passes
the parsed value to `ForServices` at `cmd/server/main.go:223`. A custom
`main.go` that hardcodes `temporal.DefaultServices` would therefore start
frontend, history, matching *and* worker inside **every** container, silently
destroying the multirole split — and each container would appear to work.

`servicesFromEnv()` reads `TEMPORAL_SERVICES`, splits on commas, trims
whitespace, discards empty entries, and falls back to `temporal.DefaultServices`
when the variable is unset or yields nothing. It carries a unit test, because
the failure mode is silent.

### Container integration

`Dockerfile` is multi-stage: build our binary, then
`FROM temporalio/server:1.31.0` and copy it to
`/usr/local/bin/temporal-authz-server`, **alongside** the stock
`temporal-server` rather than replacing it. Keeping the original binary means
the stock entrypoint and any admin subcommands still work, and the swap is
visible in the compose file instead of hidden in the image.

Each Temporal service's compose `command` changes its final line from
`exec temporal-server start --service=<role>` to
`exec temporal-authz-server`, with `TEMPORAL_SERVICES=<role>` in the
environment. The `BIND_ON_IP` / `TEMPORAL_BROADCAST_ADDRESS` preamble already
in those inline scripts is unchanged.

## Changes to existing files

| File | Change |
|---|---|
| `tls/Dockerfile.mtls` | Add one `cfssl gencert` block issuing `CN=temporal-admin`, signed by the same CA with the same profile as the client cert |
| `tls/run-mtls.sh` | Copy `admin.pem` / `admin-key.pem` out to `.pki/` next to the existing client files |
| `docker-compose-mtls.yaml` | Custom image + `exec temporal-authz-server` for frontend/history/matching; uncomment and correct the authz env block at lines 226-229; add `USE_INTERNAL_FRONTEND=true`; add the `internal-frontend` and `worker` services; point `temporal-admin-tools` and `temporal-create-namespace` at the new admin cert |
| `.env` | Unchanged — `TEMPORAL_VERSION=1.31.0` is the single source of truth for both the image and the Go module pin |
| `.env.local` | Already holds `TEMPORAL_JWT_KEY_SOURCE1`; no new values needed |
| `authz-poc/` | Delete. The source-patching approach it documents is replaced by this design, and leaving it invites someone to build the admin-granting image by mistake |

Authz environment variables on the frontend, replacing the commented block:

```
TEMPORAL_JWT_PERMISSIONS_CLAIM=roles
TEMPORAL_JWT_KEY_REFRESH=1h
USE_INTERNAL_FRONTEND=true
```

**`TEMPORAL_AUTH_AUTHORIZER` and `TEMPORAL_AUTH_CLAIM_MAPPER` must be left
unset**, which is why the commented block is replaced rather than merely
uncommented. Two independent reasons:

1. Those config fields are consumed only by `GetAuthorizerFromConfig` and
   `GetClaimMapperFromConfig`, and the only non-test callers of those functions
   are `cmd/server/main.go:197` and `:212` — the *stock* binary. Our `main.go`
   never calls them, so the values are inert for us. Worse, both functions
   return `unknown authorizer: %s` for any value other than `""` or `"default"`
   (`common/authorization/authorizer.go:72`, `claim_mapper.go:88`), so the
   plausible-looking value `custom` is a trap for anyone who later reaches for
   the stock binary.
2. The only other thing those variables affect is the template's `publicClient`
   decision at line 351 — and `USE_INTERNAL_FRONTEND` already satisfies the
   first disjunct of that condition on its own.

The compose file should carry a short comment to this effect, because the
natural assumption is the opposite: that enabling authorization requires
setting them.

`TEMPORAL_JWT_PERMISSIONS_CLAIM` is still read, because our claim mapper takes
the claim name from `cfg.Global.Authorization.PermissionsClaimName` rather than
hardcoding `roles`.

## Testing

**Unit tests** are the primary gate and need no running stack:

- `roles_test.go` — every row of the normalization table, plus `system` →
  `temporal-system`, unknown words, missing colon, mixed case
- `claimmapper_test.go` — the CN × token matrix: admin CN, client CN with a
  valid token, client CN with no token, no TLS subject at all, malformed
  `Bearer` prefix, `roles` claim absent, `roles` containing an unparseable entry
- `authorizer_test.go` — each branch of `Authorize`, with `ListNamespaces`
  covered for a namespace-scoped caller, a caller with no namespaces, and a
  system admin

Signed tokens for the mapper tests are generated in-test with a throwaway RSA
key and a stub `TokenKeyProvider`, so no Azure round-trip is required.

**Integration check** once the stack is up, three personas:

| Persona | Credential | Expected |
|---|---|---|
| `qa-user@ttriyoteeoutlook.onmicrosoft.com` | UI login, holds `uat:reader` | UI loads; `uat` readable; writes to `uat` denied; `dev` denied |
| admin tooling | `CN=temporal-admin` cert, no token | `temporal operator namespace list` succeeds |
| rogue SDK client | `CN=temporal-client` cert, no token | `PermissionDenied` |

Server startup must no longer log *"Not using any authorizer"*, and the
`worker` service must stay up rather than exiting.

## Risks and open items

| Risk | Handling |
|---|---|
| `go build` against `go.temporal.io/server v1.31.0` may pull a large dependency tree and need a specific Go toolchain (server `go.mod` wants a recent Go; local toolchain is 1.27.3) | First implementation step is a bare `go build` of a stub `main.go`. Treat a failure here as a version-alignment task before any logic is written |
| `AuthInfo.TLSSubject` populated only under mTLS with `REQUIRE_CLIENT_AUTH` | Already set at `docker-compose-mtls.yaml:211`. The claim mapper must still handle a nil `TLSSubject` without panicking, and a unit test covers it |
| Guest account `ttriyotee@outlook.com` still emits no `roles` | Known and accepted; test with `qa-user` as before. Decision 3 keeps this out of scope |
| The internal frontend is new to this stack and may need its own TLS entries | Verify during implementation; it is an internode listener, so the existing `temporal-cluster` cert should cover it |
| `docker build` and `docker compose down` have been blocked by the harness in past sessions | The user runs those commands; the plan should surface them explicitly rather than assuming they can be executed |

## Non-goals

- Filtering the `ListNamespaces` response. That needs a frontend gRPC
  interceptor via `temporal.WithChainedFrontendGrpcInterceptors`
  (`temporal/server_option.go:204`) and is deliberately deferred.
- Mapping roles from `groups`, `oid` or email.
- Any AKS or Helm change.
