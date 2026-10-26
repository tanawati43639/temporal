# ──────────────────────────────────────────────────────────────────
# Custom Temporal server image for localhost RBAC POC.
#
# The upstream default JWT claim mapper returns empty claims for
# callers with no token, which blocks Temporal's own internal workers
# (frontend ↔ history ↔ matching ↔ worker gRPC calls carry no JWT).
#
# This image applies a 1-line patch that grants `System: RoleAdmin`
# to no-token callers so internal services can start, while callers
# that DO present a JWT still go through normal role parsing.
#
# ⚠️  Security tradeoff: anyone who can reach the frontend's gRPC
#     port (default 7233) without a JWT becomes admin. Mitigate by
#     binding to 127.0.0.1 only (see docker-compose-authz.yml).
#     Not suitable for production.
# ──────────────────────────────────────────────────────────────────

ARG TEMPORAL_VERSION=1.31.0

# Temporal 1.31 requires Go >= 1.26.2 per its go.mod.
FROM golang:1.26-alpine AS builder

ARG TEMPORAL_VERSION
# GOTOOLCHAIN=auto lets `go build` fetch a newer toolchain on the fly if
# the pinned base image is still behind what Temporal's go.mod demands.
ENV GOTOOLCHAIN=auto
RUN apk add --no-cache git make bash gcc musl-dev
WORKDIR /src
RUN git clone --depth 1 --branch v${TEMPORAL_VERSION} https://github.com/temporalio/temporal.git .

# Patch 1: in common/authorization/default_jwt_claim_mapper.go, after the
# `if authInfo.AuthToken == "" {` line, insert `claims.System = RoleAdmin`.
# This grants system admin to any caller that provides no Bearer token,
# which is how Temporal's own internal workers reach the frontend.
RUN FILE=common/authorization/default_jwt_claim_mapper.go && \
    awk '/if authInfo\.AuthToken == "" \{/{print; print "\t\tclaims.System = RoleAdmin"; next}1' \
        $FILE > $FILE.new && mv $FILE.new $FILE && \
    echo "─── Patch 1 applied: default_jwt_claim_mapper.go ───" && \
    grep -A 3 'authInfo.AuthToken == ""' $FILE && \
    grep -q 'claims.System = RoleAdmin' $FILE || (echo "PATCH 1 FAILED" && exit 1)

# Patch 2 (THE critical one): in common/authorization/default_authorizer.go,
# allow calls with nil claims. Temporal's authz interceptor returns nil
# AuthInfo (and therefore nil claims) when the caller has no TLS cert
# AND no Authorization header — which is exactly how Temporal's own
# internal worker-to-frontend gRPC calls look. The default authorizer
# denies nil claims, so we replace that denial with an allow.
RUN FILE=common/authorization/default_authorizer.go && \
    awk '/^func \(a \*defaultAuthorizer\) Authorize/{print; print "\tif claims == nil { return Result{Decision: DecisionAllow}, nil }"; next}1' \
        $FILE > $FILE.new && mv $FILE.new $FILE && \
    echo "─── Patch 2 applied: default_authorizer.go ───" && \
    grep -A 3 'defaultAuthorizer) Authorize' $FILE && \
    grep -q 'claims == nil { return Result{Decision: DecisionAllow}' $FILE || (echo "PATCH 2 FAILED" && exit 1)

# Build the server binary with the patches compiled in.
RUN CGO_ENABLED=0 go build -trimpath -o /out/temporal-server ./cmd/server && \
    echo "─── Built binary size ───" && \
    ls -la /out/temporal-server

# ──────────────────────────────────────────────────────────────────
FROM temporalio/server:${TEMPORAL_VERSION}
COPY --from=builder /out/temporal-server /usr/local/bin/temporal-server
