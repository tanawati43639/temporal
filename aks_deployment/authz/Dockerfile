# ──────────────────────────────────────────────────────────────────
# authz-server image สำหรับ AKS (build ขั้นเดียวจบ)
#
#   1) build binary temporal-authz-server (ฝัง Azure AD claim mapper + authorizer)
#   2) วางบน temporalio/server + ใส่ ENTRYPOINT ที่ตั้ง broadcast address แล้วรัน
#      temporal-authz-server (Helm chart ไม่มีช่อง override command จึงทำที่ image)
#
# build (ต้อง linux/amd64 สำหรับ node AKS):
#   docker build --platform linux/amd64 \
#     --build-arg TEMPORAL_VERSION=1.31.0 \
#     -t acrtemporal25243.azurecr.io/temporal-authz-aks:v1 \
#     authz
#
# TEMPORAL_VERSION ต้องตรงกับ go.temporal.io/server ใน authz/go.mod (1.31.0)
# ──────────────────────────────────────────────────────────────────
ARG TEMPORAL_VERSION=1.31.0

FROM golang:1.26-alpine AS build
ENV GOTOOLCHAIN=auto
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -o /out/temporal-authz-server .

FROM temporalio/server:${TEMPORAL_VERSION}
COPY --from=build /out/temporal-authz-server /usr/local/bin/temporal-authz-server
COPY --chmod=0755 entrypoint.sh /usr/local/bin/aks-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/aks-entrypoint.sh"]
