# Multi-role Temporal + mTLS

Production-shaped self-hosted stack. Three Temporal services run as
separate containers; every gRPC hop — internal and external — is mutual
TLS over a shared self-signed CA. No Azure AD authz is wired here; the
client certificate alone is the security boundary.

## What you get

| Layer | How it's secured |
|---|---|
| frontend ↔ history ↔ matching | Internode mTLS using the shared `cluster.pem` cert |
| External gRPC (`:7233`) | TLS, and the frontend **requires** a client cert signed by the project CA |
| Temporal UI → frontend | mTLS using `client.pem`; browser → UI still plain HTTP on `:8080` |
| admin-tools, SDK clients | mTLS using `client.pem` + `ca.pem` |

What's **not** here, and why:

- No `worker` service. Temporal's own worker calls frontend without a JWT
  and the authz interceptor would reject it; the custom-authorizer workaround
  needs a rebuild of the server binary. User-written SDK Workers are fine —
  only Temporal's own system workflows (scanner, archival) are missing.
- No Azure AD authz. Add it later by setting `TEMPORAL_AUTH_AUTHORIZER`,
  `TEMPORAL_AUTH_CLAIM_MAPPER`, `TEMPORAL_JWT_KEY_SOURCE1`,
  `TEMPORAL_JWT_PERMISSIONS_CLAIM` on `temporal-frontend` and the OIDC vars
  on `temporal-ui`. See `docker-compose-authz.yml` for the exact wiring.

## Files

- `tls/Dockerfile.mtls` — PKI generator (cfssl in a Go container)
- `tls/run-mtls.sh` — one-time bootstrap: build + volume + cert generation
- `docker-compose-mtls.yaml` — the stack
- `.pki/` (git-ignored) — host-side copies of `ca.pem`, `client.pem`,
  `client-key.pem` for SDK clients running outside Docker

## Usage

```bash
cd samples-server/compose

# 1) Bootstrap the PKI (one-time, re-run anytime to rotate certs)
./tls/run-mtls.sh

# 2) Start the stack
docker compose -f docker-compose-mtls.yaml up -d

# 3) Watch the frontend come up healthy
docker logs -f temporal-frontend
```

The UI is at <http://localhost:8080>. Namespaces `default/dev/uat/prod` are
created automatically by `temporal-create-namespace`.

### Running CLI commands against the stack

Inside Docker — admin-tools has the TLS env vars baked in:

```bash
docker exec -it temporal-admin-tools temporal operator cluster health
docker exec -it temporal-admin-tools temporal workflow list -n default
```

From the host — point the Temporal CLI at the host-side certs:

```bash
export TEMPORAL_ADDRESS=localhost:7233
export TEMPORAL_TLS=true
export TEMPORAL_TLS_CLIENT_CERT_PATH=./.pki/client.pem
export TEMPORAL_TLS_CLIENT_KEY_PATH=./.pki/client-key.pem
export TEMPORAL_TLS_SERVER_CA_CERT_PATH=./.pki/ca.pem
export TEMPORAL_TLS_SERVER_NAME=temporal-frontend

temporal operator cluster health
```

### SDK clients outside Docker

Point your SDK at `localhost:7233` and give it the three host-side files:

```python
from temporalio.client import Client, TLSConfig

client = await Client.connect(
    "localhost:7233",
    tls=TLSConfig(
        server_root_ca_cert=open(".pki/ca.pem", "rb").read(),
        client_cert=open(".pki/client.pem", "rb").read(),
        client_private_key=open(".pki/client-key.pem", "rb").read(),
        domain="temporal-frontend",   # SAN on the server cert
    ),
    namespace="default",
)
```

## Cert rotation

Everything is 5-year self-signed. To rotate, re-run `./tls/run-mtls.sh` —
the volume is dropped and recreated, so you must also recreate the running
containers:

```bash
./tls/run-mtls.sh
docker compose -f docker-compose-mtls.yaml up -d --force-recreate
```

Old client certs stop working after rotation.
