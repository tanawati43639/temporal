# Azure AD Claim Mapper + Authorizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Namespace-level RBAC on self-hosted Temporal, with roles read from Microsoft Entra ID app roles, running on the localhost mTLS compose stack.

**Architecture:** A new Go module builds a server binary that imports `go.temporal.io/server` as a library and injects a custom `ClaimMapper` and `Authorizer` through `temporal.WithClaimMapper` / `temporal.WithAuthorizer`. Server configuration comes from `config.Load(config.WithEmbedded())`, which reproduces the stock image's environment-variable-driven config, so the existing compose environment is reused unchanged. Internal server traffic is routed to an internal frontend rather than being granted admin.

**Tech Stack:** Go, `go.temporal.io/server v1.31.0`, `github.com/golang-jwt/jwt/v4 v4.5.2`, Docker Compose, cfssl.

**Spec:** `docs/superpowers/specs/2026-11-10-temporal-azure-claim-mapper-design.md`

## Global Constraints

- Pin `go.temporal.io/server v1.31.0` — must equal `TEMPORAL_VERSION` in `samples-server/compose/.env`.
- JWT library is `github.com/golang-jwt/jwt/v4 v4.5.2`, matching the server's own `go.mod:28`.
- Module lives at `samples-server/compose/authz-server/`, package `main`, module path `temporal-azure-authz`.
- Build with `CGO_ENABLED=0` and `-trimpath`.
- Image base is `temporalio/server:1.31.0`. Our binary installs to `/usr/local/bin/temporal-authz-server`; the stock `temporal-server` binary must remain in the image.
- Admin certificate common name is exactly `temporal-admin`.
- `TEMPORAL_AUTH_AUTHORIZER` and `TEMPORAL_AUTH_CLAIM_MAPPER` must remain **unset** in every compose service. See the spec's reasoning; they are inert for our binary and a trap for the stock one.
- Cluster scope string is `primitives.SystemLocalNamespace` (`"temporal-system"`). Use the constant, never a literal.
- Never case-fold a namespace. Only the exact literal `system` is rewritten to the cluster scope. Role words are matched case-insensitively.

## Review Focus

These inputs are implied by the spec but not named by any of its own test
tables. Each has a test assigned to the task that owns the code.

1. `GetClaims` receives a nil `authInfo`, or an `authInfo` whose `TLSSubject` is nil (no client certificate) — must return empty claims, never panic. → Task 4.
2. The `roles` claim is present but is not a JSON array (a bare string, or a number) — must be ignored like an absent claim, not crash. → Task 4.
3. A token with a valid signature but an expired `exp` — must be rejected. → Task 3.
4. A `roles` entry with no colon (`uatreader`), an empty namespace (`:read`), or an empty role (`uat:`) — must be skipped, and must never be treated as a cluster-level grant. → Task 2.
5. A claims object whose `Namespaces` map exists but holds only a zero role — must **not** unlock `ListNamespaces`. → Task 5.

---

### Task 1: Go module and build gate

Closes the spec's top risk before any logic is written: the dependency tree and toolchain must resolve against v1.31.0.

**Files:**
- Create: `samples-server/compose/authz-server/go.mod`
- Create: `samples-server/compose/authz-server/main.go`

**Interfaces:**
- Consumes: nothing.
- Produces: a buildable `package main` in module `temporal-azure-authz`, plus
  - `servicesFromEnv() []string`
  - `newServer(logger log.Logger) (temporal.Server, error)`, which later tasks extend with server options.

- [ ] **Step 1: Initialise the module and add the pinned dependencies**

```bash
cd samples-server/compose/authz-server
go mod init temporal-azure-authz
go get go.temporal.io/server@v1.31.0
go get github.com/golang-jwt/jwt/v4@v4.5.2
```

- [ ] **Step 2: Write the failing test for `servicesFromEnv`**

The library never reads `TEMPORAL_SERVICES` (`temporal/server_option.go:55`); the stock binary parses it and passes the result to `ForServices` (`cmd/server/main.go:223`). Hardcoding `temporal.DefaultServices` would start all four services in every container, so this helper is tested first.

```go
func TestServicesFromEnv(t *testing.T) {
	// unset              -> temporal.DefaultServices
	// ""                 -> temporal.DefaultServices
	// "frontend"         -> ["frontend"]
	// "frontend,worker"  -> ["frontend", "worker"]
	// " frontend , worker " -> ["frontend", "worker"]   (trimmed)
	// "frontend,,worker" -> ["frontend", "worker"]      (empties dropped)
	// ","                -> temporal.DefaultServices    (nothing usable)
	// use t.Setenv for each case
}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd samples-server/compose/authz-server && go test ./... -run TestServicesFromEnv -v`
Expected: FAIL — `undefined: servicesFromEnv`.

- [ ] **Step 4: Write `main.go`**

`servicesFromEnv() []string` implements the table above.

`newServer(logger log.Logger) (temporal.Server, error)` loads config with `config.Load(config.WithEmbedded())` and returns `temporal.NewServer` with `temporal.ForServices(servicesFromEnv())`, `temporal.WithConfig(cfg)`, `temporal.WithLogger(logger)` and `temporal.InterruptOn(temporal.InterruptCh())`. `main()` calls it, calls `Start()`, and `log.Fatal`s on error.

Use `go.temporal.io/server/common/log` for the logger (`log.NewCLILogger()`).

- [ ] **Step 5: Verify it builds, vets clean, and the test passes**

Run: `cd samples-server/compose/authz-server && go build ./... && go vet ./... && go test ./... -run TestServicesFromEnv -v`
Expected: build and vet silent with exit 0; test PASS.

If the build fails on the Go toolchain version or a dependency, stop and resolve version alignment before continuing — do not work around it by changing the pin.

- [ ] **Step 6: Commit**

```bash
git add samples-server/compose/authz-server/
git commit -m "feat(authz): add authz-server Go module skeleton"
```

---

### Task 2: Permission string parsing

**Files:**
- Create: `samples-server/compose/authz-server/roles.go`
- Test: `samples-server/compose/authz-server/roles_test.go`

**Interfaces:**
- Consumes: nothing.
- Produces: `ParsePermission(s string) (namespace string, role authorization.Role, ok bool)`.

- [ ] **Step 1: Write the failing table-driven test**

```go
func TestParsePermission(t *testing.T) {
	cases := []struct {
		in        string
		namespace string
		role      authorization.Role
		ok        bool
	}{
		{"uat:reader", "uat", authorization.RoleReader, true},
		{"uat:read", "uat", authorization.RoleReader, true},
		{"dev:writer", "dev", authorization.RoleWriter, true},
		{"dev:write", "dev", authorization.RoleWriter, true},
		{"default:admin", "default", authorization.RoleAdmin, true},
		{"foo:worker", "foo", authorization.RoleWorker, true},
		{"uat:READER", "uat", authorization.RoleReader, true},
		{"system:admin", primitives.SystemLocalNamespace, authorization.RoleAdmin, true},
		{"temporal-system:admin", primitives.SystemLocalNamespace, authorization.RoleAdmin, true},
		{"Prod:reader", "Prod", authorization.RoleReader, true},
		{"dev:write:extra", "", authorization.RoleUndefined, false},
		{"uatreader", "", authorization.RoleUndefined, false},
		{":read", "", authorization.RoleUndefined, false},
		{"uat:", "", authorization.RoleUndefined, false},
		{"uat:bogus", "", authorization.RoleUndefined, false},
		{"", "", authorization.RoleUndefined, false},
	}
	// assert each field for every case
}
```

`{"dev:write:extra", ...}` pins splitting on the *first* colon only, matching the server's `strings.SplitN(p, ":", 2)`: the role segment is then the whole string `write:extra`, which is not one of the six accepted words, so the entry is rejected. Do **not** strip trailing colon-separated segments to make this parse — the spec authorizes exactly two divergences from Temporal's parser (role-word spelling and the `system` scope alias), and silently accepting a malformed role string would let an Azure typo grant real permissions. `{"Prod:reader", ...}` pins that namespaces are not case-folded.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd samples-server/compose/authz-server && go test ./... -run TestParsePermission -v`
Expected: FAIL — `undefined: ParsePermission`.

- [ ] **Step 3: Implement `ParsePermission` in `roles.go`**

Split on the first colon. Map the role word case-insensitively: `read`/`reader` → `RoleReader`, `write`/`writer` → `RoleWriter`, `admin` → `RoleAdmin`, `worker` → `RoleWorker`; anything else returns `ok == false`. Reject an empty namespace or empty role word. Rewrite the exact namespace `system` to `primitives.SystemLocalNamespace`. On `ok == false` return zero values for the other two results.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd samples-server/compose/authz-server && go test ./... -run TestParsePermission -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add samples-server/compose/authz-server/roles.go samples-server/compose/authz-server/roles_test.go
git commit -m "feat(authz): parse Entra ID app-role values into Temporal roles"
```

---

### Task 3: JWT validation

Replicates the server's unexported `parseJWT` over the public `TokenKeyProvider` interface, following `common/authorization/default_jwt_claim_mapper.go:149-200`.

**Files:**
- Create: `samples-server/compose/authz-server/jwt.go`
- Test: `samples-server/compose/authz-server/jwt_test.go`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `StripBearer(authToken string) (string, error)`
  - `ParseAndValidate(tokenString string, provider authorization.TokenKeyProvider) (jwt.MapClaims, error)`

- [ ] **Step 1: Write the failing tests**

A test helper generates a 2048-bit RSA key once and returns a stub implementing `authorization.TokenKeyProvider`: `RsaKey` returns the public key, `SupportedMethods` returns `[]string{"RS256"}`, `EcdsaKey` and `HmacKey` return errors, `Close` is a no-op. A second helper signs `jwt.MapClaims` with that key and a `kid` header.

```go
func TestStripBearer(t *testing.T) {
	// "Bearer abc"  -> "abc", nil
	// "bearer abc"  -> "abc", nil   (case-insensitive, per EqualFold in the server)
	// "abc"         -> "",    error (no space)
	// "Basic abc"   -> "",    error (wrong scheme)
	// ""            -> "",    error
}

func TestParseAndValidate(t *testing.T) {
	// valid RS256 token with sub+exp in the future -> claims returned, claims["sub"] == "user-1"
	// token expired one hour ago                   -> error            (Review Focus 3)
	// token signed by a different RSA key          -> error
	// token with alg=none                          -> error
	// garbage string                               -> error
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd samples-server/compose/authz-server && go test ./... -run 'TestStripBearer|TestParseAndValidate' -v`
Expected: FAIL — `undefined: StripBearer`, `undefined: ParseAndValidate`.

- [ ] **Step 3: Implement both functions in `jwt.go`**

`StripBearer` splits on the first space with `strings.SplitN(authToken, " ", 2)`, requires two parts, and requires `strings.EqualFold(parts[0], "bearer")`.

`ParseAndValidate` builds `jwt.NewParser(jwt.WithValidMethods(provider.SupportedMethods()))`. Its `jwt.Keyfunc` prefers `authorization.RawTokenKeyProvider` when the provider implements it (calling `GetKey(context.Background(), token)`); otherwise it reads the `kid` and `alg` headers and dispatches on the token's signing method to `RsaKey`, `EcdsaKey` or `HmacKey`, erroring on any other method or a missing `kid`. After parsing, assert the claims are `jwt.MapClaims` and call their `Valid()`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd samples-server/compose/authz-server && go test ./... -run 'TestStripBearer|TestParseAndValidate' -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add samples-server/compose/authz-server/jwt.go samples-server/compose/authz-server/jwt_test.go
git commit -m "feat(authz): validate Azure AD JWTs via Temporal's TokenKeyProvider"
```

---

### Task 4: `AzureClaimMapper`

**Files:**
- Create: `samples-server/compose/authz-server/claimmapper.go`
- Test: `samples-server/compose/authz-server/claimmapper_test.go`

**Interfaces:**
- Consumes: `ParsePermission` (Task 2), `StripBearer` and `ParseAndValidate` (Task 3).
- Produces: `NewAzureClaimMapper(cfg *config.Config, logger log.Logger) authorization.ClaimMapper`, implementing `GetClaims(*authorization.AuthInfo) (*authorization.Claims, error)` and `AuthInfoRequired() bool`.

The constructor reads the permissions claim name from `cfg.Global.Authorization.PermissionsClaimName`, defaulting to `"roles"` when empty, and builds its key provider with `authorization.NewDefaultTokenKeyProvider(&cfg.Global.Authorization, logger)`. For testability the struct also carries an injectable `authorization.TokenKeyProvider` field that tests set directly.

- [ ] **Step 1: Write the failing tests**

Reuse Task 3's RSA key and stub provider helpers.

```go
func TestAzureClaimMapper(t *testing.T) {
	// admin cert, no token:
	//   AuthInfo{TLSSubject: &pkix.Name{CommonName: "temporal-admin"}}
	//   -> Claims{System: RoleAdmin}, AuthType "mtls", Subject "temporal-admin"
	//
	// client cert + valid token with roles ["uat:reader","dev:writer"]:
	//   -> Namespaces{"uat": RoleReader, "dev": RoleWriter}, System == RoleUndefined
	//
	// valid token with roles ["system:admin"]:
	//   -> System == RoleAdmin, Namespaces empty
	//
	// valid token with roles ["dev:read","dev:write"]:
	//   -> Namespaces{"dev": RoleReader | RoleWriter}        (OR-ed, like the server)
	//
	// valid token with roles ["uat:reader","uat:bogus"]:
	//   -> Namespaces{"uat": RoleReader}, no error           (bad entry skipped)
	//
	// client cert, no token:            -> empty Claims, no error
	// nil authInfo:                     -> empty Claims, no error   (Review Focus 1)
	// authInfo with nil TLSSubject and no token:
	//                                   -> empty Claims, no error   (Review Focus 1)
	// token present, roles claim is the string "uat:reader" not an array:
	//                                   -> empty Namespaces, no error (Review Focus 2)
	// token present, roles claim absent: -> empty Namespaces, no error
	// malformed "Bearer" prefix:        -> error
	// expired token:                    -> error
	// admin cert AND a token:           -> Claims{System: RoleAdmin} (cert wins, token not parsed)
}

func TestAzureClaimMapperAuthInfoRequired(t *testing.T) {
	// AuthInfoRequired() == false
}
```

Zero-role entries must never be written into `Namespaces`; the "bogus" case above pins that.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd samples-server/compose/authz-server && go test ./... -run TestAzureClaimMapper -v`
Expected: FAIL — `undefined: NewAzureClaimMapper`.

- [ ] **Step 3: Implement `claimmapper.go`**

Declare `const adminCertCommonName = "temporal-admin"`.

`GetClaims` order of precedence:
1. `authInfo == nil` → return `&authorization.Claims{}`.
2. `authInfo.TLSSubject != nil && authInfo.TLSSubject.CommonName == adminCertCommonName` → return `&authorization.Claims{System: authorization.RoleAdmin, AuthType: "mtls", Subject: adminCertCommonName}`.
3. `authInfo.AuthToken != ""` → `StripBearer`, then `ParseAndValidate` with the mapper's provider, propagating errors. Set `AuthType: "jwt"`; set `Subject` from `preferred_username` falling back to `sub`. Read the permissions claim, type-assert to `[]any`, and for each entry that is a string run `ParsePermission`, OR-ing successes into `Namespaces` (allocated lazily) or into `System` when the namespace equals `primitives.SystemLocalNamespace`. Log skipped entries at warn level with the subject.
4. Otherwise → `&authorization.Claims{}`.

`AuthInfoRequired()` returns `false` so the mapper is always consulted and always produces explicit claims.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd samples-server/compose/authz-server && go test ./... -run TestAzureClaimMapper -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add samples-server/compose/authz-server/claimmapper.go samples-server/compose/authz-server/claimmapper_test.go
git commit -m "feat(authz): map Azure AD certs and tokens to Temporal claims"
```

---

### Task 5: `AzureAuthorizer`

Mirrors `common/authorization/default_authorizer.go` with one deliberate difference, so that a namespace-scoped user can load the UI.

**Files:**
- Create: `samples-server/compose/authz-server/authorizer.go`
- Test: `samples-server/compose/authz-server/authorizer_test.go`

**Interfaces:**
- Consumes: nothing.
- Produces: `NewAzureAuthorizer() authorization.Authorizer`.

- [ ] **Step 1: Write the failing tests**

`listNamespacesAPI` is `"/temporal.api.workflowservice.v1.WorkflowService/ListNamespaces"`. `api.GetMethodMetadata` reports it as `{Scope: ScopeCluster, Access: AccessReadOnly}` (`common/api/metadata.go:73`), which is why the default authorizer denies it to a namespace-only caller.

```go
func TestAzureAuthorizer(t *testing.T) {
	// nil claims, any API                                   -> DecisionDeny
	// health check API, nil claims                          -> DecisionAllow
	// System RoleAdmin, UpdateNamespace on "dev"            -> DecisionAllow
	//
	// ListNamespaces, claims.Namespaces{"uat": RoleReader}  -> DecisionAllow   <- the change
	// ListNamespaces, claims.Namespaces empty, System zero  -> DecisionDeny
	// ListNamespaces, claims.Namespaces{"uat": RoleUndefined}
	//                                                       -> DecisionDeny   (Review Focus 5)
	//
	// StartWorkflowExecution on "dev", Namespaces{"dev": RoleWriter} -> DecisionAllow
	// StartWorkflowExecution on "dev", Namespaces{"dev": RoleReader} -> DecisionDeny
	// StartWorkflowExecution on "dev", Namespaces{"uat": RoleWriter} -> DecisionDeny
	// DescribeNamespace on "uat",      Namespaces{"uat": RoleReader} -> DecisionAllow
	// UpdateNamespace on "dev",        Namespaces{"dev": RoleWriter} -> DecisionDeny (needs admin)
	//
	// allowed results carry Principal.Name == claims.Subject
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd samples-server/compose/authz-server && go test ./... -run TestAzureAuthorizer -v`
Expected: FAIL — `undefined: NewAzureAuthorizer`.

- [ ] **Step 3: Implement `authorizer.go`**

**Delegate; do not reimplement.** The struct holds an `authorization.Authorizer` field set to `authorization.NewDefaultAuthorizer()`. `Authorize` is then two branches:

1. If `target.APIName == listNamespacesAPI` **and** `hasAnyNamespaceRole(claims)`, allow, setting `Principal: &commonpb.Principal{Type: claims.AuthType, Name: claims.Subject}` on the result.
2. Otherwise return `a.delegate.Authorize(ctx, claims, target)` unchanged.

Add an unexported `hasAnyNamespaceRole(claims *authorization.Claims) bool` that returns false for nil claims and ignores zero-valued map entries.

Do **not** copy the default authorizer's scope switch, its `requiredRole` mapping, its health-check branch, or its nil-claims branch. Delegation preserves all of them: a nil-claims `ListNamespaces` call fails `hasAnyNamespaceRole` and reaches the delegate, which denies it, and health-check APIs never match `listNamespacesAPI` so they reach the delegate's own allow. Reimplementing that logic would duplicate upstream code, silently pin this authorizer to v1.31.0's API metadata, and is what the quality rubric flags as avoidable duplication — the spec's only stated difference from the default authorizer is the `ListNamespaces` branch, so that is the only thing this file should contain.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd samples-server/compose/authz-server && go test ./... -run TestAzureAuthorizer -v`
Expected: PASS

- [ ] **Step 5: Run the whole suite and commit**

Run: `cd samples-server/compose/authz-server && go test ./... -v`
Expected: PASS

```bash
git add samples-server/compose/authz-server/authorizer.go samples-server/compose/authz-server/authorizer_test.go
git commit -m "feat(authz): authorize by namespace role, allowing ListNamespaces"
```

---

### Task 6: Wire the components in and build the image

**Files:**
- Modify: `samples-server/compose/authz-server/main.go`
- Create: `samples-server/compose/authz-server/Dockerfile`
- Create: `samples-server/compose/authz-server/README.md`

**Interfaces:**
- Consumes: `NewAzureClaimMapper` (Task 4), `NewAzureAuthorizer` (Task 5).
- Produces: image-local binary `/usr/local/bin/temporal-authz-server`.

- [ ] **Step 1: Add the server options to `newServer`**

Append `temporal.WithClaimMapper(func(c *config.Config) authorization.ClaimMapper { return NewAzureClaimMapper(c, logger) })` and `temporal.WithAuthorizer(NewAzureAuthorizer())` to the options built in Task 1. Leave the `temporal.ForServices(servicesFromEnv())` line from Task 1 untouched.

- [ ] **Step 2: Verify it still builds and the suite passes**

Run: `cd samples-server/compose/authz-server && go build ./... && go vet ./... && go test ./...`
Expected: exit 0, tests PASS.

- [ ] **Step 3: Write the `Dockerfile`**

Multi-stage. Builder stage `FROM golang:1.26-alpine` with `ENV GOTOOLCHAIN=auto`, copying the module and running `CGO_ENABLED=0 go build -trimpath -o /out/temporal-authz-server .`. Final stage `FROM temporalio/server:${TEMPORAL_VERSION}` with `ARG TEMPORAL_VERSION=1.31.0`, copying the binary to `/usr/local/bin/temporal-authz-server`. Do not touch the existing `temporal-server` binary or the entrypoint.

- [ ] **Step 4: Write `README.md`**

Explain what the binary is, that the stock binary is preserved, that `TEMPORAL_AUTH_AUTHORIZER` / `TEMPORAL_AUTH_CLAIM_MAPPER` must stay unset and why, and the role-word normalization table from the spec. State that only `docker-compose-mtls.yaml` uses this image.

- [ ] **Step 5: Build the image**

Run: `cd samples-server/compose && docker build -t temporal-authz:dev -f authz-server/Dockerfile authz-server`
Expected: build succeeds.

This command and every later `docker` command may need to be run by the user — the harness has refused `docker build` in past sessions. If refused, hand the exact command over rather than working around it.

- [ ] **Step 6: Verify both binaries exist in the image**

Run: `docker run --rm --entrypoint sh temporal-authz:dev -c 'ls -la /usr/local/bin/temporal-server /usr/local/bin/temporal-authz-server'`
Expected: both listed.

- [ ] **Step 7: Commit**

```bash
git add samples-server/compose/authz-server/
git commit -m "feat(authz): wire custom claim mapper and authorizer, add image build"
```

---

### Task 7: Issue the admin client certificate

**Files:**
- Modify: `samples-server/compose/tls/Dockerfile.mtls`
- Modify: `samples-server/compose/tls/run-mtls.sh:28-36`

**Interfaces:**
- Consumes: nothing.
- Produces: `admin.pem` / `admin-key.pem` in the `temporal_mtls_pki` volume and in `.pki/`, with `CN=temporal-admin`.

- [ ] **Step 1: Add the certificate block to `Dockerfile.mtls`**

After the existing client-cert block, add a fifth `cfssl gencert` invocation mirroring it exactly but with `{"CN":"temporal-admin",...}`, `-hostname="temporal-admin"`, and `cfssljson -bare admin`. It uses the same CA and the same `ca-config.json` profile, which already carries both `server auth` and `client auth`.

- [ ] **Step 2: Extend the entrypoint's copy-out list**

The `ENTRYPOINT` line copies files to `/pki-out`. Add `admin.pem` and `admin-key.pem`.

- [ ] **Step 3: Regenerate the PKI**

Run: `cd samples-server/compose && ./tls/run-mtls.sh`
Expected: completes, and `.pki/` now lists `admin.pem` and `admin-key.pem` alongside the existing files.

This drops and recreates the `temporal_mtls_pki` volume, invalidating previously issued client certs — expected, and the reason this task precedes the compose change.

- [ ] **Step 4: Verify the new certificate's subject and that it chains to the CA**

Run:
```bash
cd samples-server/compose
openssl x509 -noout -subject -in .pki/admin.pem
openssl verify -CAfile .pki/ca.pem .pki/admin.pem
```
Expected: `subject=CN=temporal-admin`, and `.pki/admin.pem: OK`.

- [ ] **Step 5: Update `run-mtls.sh`'s closing help text**

The heredoc lists the files an external SDK client uses. Add a short line that `admin.pem` / `admin-key.pem` are the admin-tools credential and grant cluster admin without a token.

- [ ] **Step 6: Commit**

```bash
git add samples-server/compose/tls/
git commit -m "feat(authz): issue a temporal-admin client certificate"
```

---

### Task 8: Compose wiring

**Files:**
- Modify: `samples-server/compose/docker-compose-mtls.yaml`
- Delete: `samples-server/compose/authz-poc/`

**Interfaces:**
- Consumes: the `temporal-authz:dev` image (Task 6) and the admin certificate (Task 7).
- Produces: a stack whose frontend enforces Azure-AD-backed RBAC.

- [ ] **Step 1: Point the three Temporal services at the custom image**

For `temporal-history`, `temporal-matching` and `temporal-frontend`: replace `image: temporalio/server:${TEMPORAL_VERSION}` with a `build` stanza (context `./authz-server`, `TEMPORAL_VERSION` arg) plus `image: temporal-authz:dev`, and change each inline command's last line from `exec temporal-server start --service=<role>` to `exec temporal-authz-server`, adding `TEMPORAL_SERVICES=<role>` to that service's environment. Leave the `BIND_ON_IP` / `TEMPORAL_BROADCAST_ADDRESS` preamble untouched.

- [ ] **Step 2: Replace the commented authz block at lines 217-229**

Delete the stale comment and the four commented variables. Add, with a comment recording that the two `TEMPORAL_AUTH_*` selector variables are deliberately absent:

```
- TEMPORAL_JWT_PERMISSIONS_CLAIM=roles
- TEMPORAL_JWT_KEY_REFRESH=1h
- USE_INTERNAL_FRONTEND=true
```

`TEMPORAL_JWT_KEY_SOURCE1` already arrives from `.env.local`.

- [ ] **Step 3: Add the `internal-frontend` and `worker` services**

`internal-frontend` runs the custom binary with `TEMPORAL_SERVICES=internal-frontend`, the same `USE_INTERNAL_FRONTEND=true`, the same DB/ES/TLS environment and `temporal_mtls_pki` mount as the frontend, and exposes gRPC `7236` on the compose network only — not to the host. `worker` is identical but with `TEMPORAL_SERVICES=worker`, and depends on `internal-frontend`.

Both get the same internode TLS variables the other services use; the `temporal-cluster` certificate already covers them.

- [ ] **Step 4: Switch the admin tooling to the admin certificate**

In `temporal-create-namespace` and `temporal-admin-tools`, change the client cert and key from `client.pem` / `client-key.pem` to `admin.pem` / `admin-key.pem`. Leave `temporal-ui` on the client certificate — it authenticates its users by token.

- [ ] **Step 5: Delete the superseded POC**

```bash
git rm -r samples-server/compose/authz-poc
```

Its Dockerfile patches Temporal to grant admin to every tokenless caller; the internal frontend replaces it, and leaving it invites someone to build that image.

- [ ] **Step 6: Bring the stack up**

Run:
```bash
cd samples-server/compose
docker compose -f docker-compose.yml down
docker compose -f docker-compose-mtls.yaml up -d --build
```
Expected: all services reach healthy. The currently-running single-container stack must be stopped first — both bind port 7233.

These commands are for the user to run if the harness refuses them.

- [ ] **Step 7: Verify authorization is active and the worker survives**

Run:
```bash
docker compose -f docker-compose-mtls.yaml logs temporal-frontend | grep -i "authoriz" || echo "no authorizer warning - good"
docker compose -f docker-compose-mtls.yaml ps temporal-worker
```
Expected: the startup warning *"Not using any authorizer"* is absent, and `temporal-worker` is `Up`, not restarting or exited. A restarting worker means internal traffic is still reaching the external frontend — re-check `USE_INTERNAL_FRONTEND`.

- [ ] **Step 8: Commit**

```bash
git add samples-server/compose/docker-compose-mtls.yaml
git commit -m "feat(authz): enable Azure AD RBAC on the mTLS compose stack"
```

---

### Task 9: End-to-end verification

**Files:**
- Create: `samples-server/compose/scripts/verify-authz.sh`

**Interfaces:**
- Consumes: the running stack from Task 8.
- Produces: a repeatable check of the three personas in the spec.

- [ ] **Step 1: Write `verify-authz.sh`**

A script taking an optional JWT as `$1`. It runs, against `localhost:7233` with the project CA:

| Check | Credential | Expected |
|---|---|---|
| `operator namespace list` | `admin.pem` | succeeds |
| `operator namespace list` | `client.pem`, no token | `PermissionDenied` |
| `workflow list -n uat` | `client.pem` + `$1` | succeeds |
| `workflow list -n dev` | `client.pem` + `$1` | `PermissionDenied` |

Use `temporal` CLI flags `--tls-cert-path`, `--tls-key-path`, `--tls-ca-path`, `--tls-server-name temporal-frontend`, and `--grpc-meta authorization="Bearer $1"` for the token cases. Each check prints `PASS` or `FAIL` with the command's error, and the script exits non-zero if any check fails. Skip the token checks with a notice when `$1` is absent.

- [ ] **Step 2: Run the certificate-only checks**

Run: `cd samples-server/compose && ./scripts/verify-authz.sh`
Expected: both certificate checks PASS; token checks reported as skipped.

- [ ] **Step 3: Run the full check with a real token**

Obtain a token by signing into the UI at <http://localhost:8080> as `qa-user@ttriyoteeoutlook.onmicrosoft.com` (which holds `uat:reader`) and copying the ID token, then:

Run: `./scripts/verify-authz.sh "<token>"`
Expected: all four checks PASS.

A `uat` read that fails here while the unit tests pass points at the token's claim content — compare it against <https://jwt.ms> before changing code.

- [ ] **Step 4: Confirm the UI loads for a namespace-scoped user**

Sign in at <http://localhost:8080> as the same user.
Expected: the UI loads rather than returning 403, `uat` is browsable, and `dev` returns a permission error when selected. Every namespace *name* is visible in the dropdown — the accepted tradeoff from the spec's decision 5.

- [ ] **Step 5: Commit**

```bash
git add samples-server/compose/scripts/verify-authz.sh
git commit -m "test(authz): add end-to-end RBAC verification script"
```

---

## Done when

- `go test ./...` passes in `samples-server/compose/authz-server/`.
- The mTLS stack runs with no *"Not using any authorizer"* warning and a stable `temporal-worker`.
- `verify-authz.sh` passes all four checks with a `qa-user` token.
- The UI loads for a namespace-scoped user.
- `authz-poc/` is gone.
