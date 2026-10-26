# Azure AD RBAC POC for self-hosted Temporal

Namespace-level authorization with Azure AD app roles on a localhost
single-container `temporalio/server`, built by applying a 1-line patch
to Temporal's default JWT claim mapper.

## ⚠️ Security tradeoff — read before using

The patch grants `System: RoleAdmin` to callers with **no JWT**, so
Temporal's own internal workers can keep running. The cost: anyone
who reaches the gRPC port (`7233`) without a token becomes admin.

Mitigations wired into `docker-compose-authz.yml`:
- Frontend binds to **`127.0.0.1:7233`** — unreachable from other hosts
- UI's OIDC login is mandatory; every browser request carries a JWT
- SDK clients outside the container must present a JWT or they get admin anyway

For production, use mTLS between separated services (helm chart) or
Temporal Cloud. This image is for demos.

## Files

- `Dockerfile` — multi-stage: clones Temporal v1.31.0, patches the
  claim mapper, replaces the binary in the upstream image.
- `../docker-compose-authz.yml` — compose variant that uses this
  custom image + full authz env vars.

## Build & run

From `samples-server/compose/`:

```bash
docker compose -f docker-compose-authz.yml build       # ~5–10 min
docker compose -f docker-compose-authz.yml up -d
```

Verify authz is live:
```bash
docker logs temporal 2>&1 | grep -i authoriz
# Should NOT say "Not using any authorizer"
```

Login at <http://localhost:8080> and your Azure AD role determines
which namespaces you see.

## How the patch works

Original `common/authorization/default_jwt_claim_mapper.go`:
```go
claims := Claims{AuthType: "jwt"}
if authInfo.AuthToken == "" {
    return &claims, nil   // empty claims → authorizer denies
}
```

Patched:
```go
claims := Claims{AuthType: "jwt"}
if authInfo.AuthToken == "" {
    claims.System = RoleAdmin   // ← added
    return &claims, nil
}
```

A caller with a valid JWT still goes through normal role parsing from
the `roles` claim.
