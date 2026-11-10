# temporal-authz-server

A custom Temporal server binary that imports `go.temporal.io/server` as a
library and plugs in an Azure AD (Entra ID) `ClaimMapper` and `Authorizer`,
giving namespace-level RBAC from the token's `roles` claim (for example
`dev:writer`, `uat:reader`). It is built into an image based on
`temporalio/server` (see `ARG TEMPORAL_VERSION` in the `Dockerfile`, which must
equal `TEMPORAL_VERSION` in `../.env`).

Only `docker-compose-mtls.yaml` uses this image.

## Stock binary is preserved

The image adds `/usr/local/bin/temporal-authz-server` next to the stock
`/usr/local/bin/temporal-server`. The entrypoint is unchanged, so the stock
binary stays available (for example via a different `command`).

## Keep `TEMPORAL_AUTH_AUTHORIZER` and `TEMPORAL_AUTH_CLAIM_MAPPER` unset

Leave both variables unset. They are read only by the stock `cmd/server`
binary, which this is not, so they do nothing here. Any value other than empty
or `default` makes Temporal's own `GetAuthorizerFromConfig` fail with
`unknown authorizer`, so a plausible-looking value such as `custom` is a trap
for anyone who later runs the stock binary against the same compose file.

## Role word normalization

Role values have the form `<namespace>:<word>`, split on the first colon.
Words are matched case-insensitively; namespaces are never case-folded.

| Input role word | Result |
|---|---|
| `read`, `reader` | `RoleReader` |
| `write`, `writer` | `RoleWriter` |
| `admin` | `RoleAdmin` |
| `worker` | `RoleWorker` |
| anything else | rejected |

The namespace `system` is rewritten to `temporal-system`, so `system:admin`
grants the cluster-level admin role.
