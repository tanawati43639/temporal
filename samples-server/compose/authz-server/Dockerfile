# Must stay equal to TEMPORAL_VERSION in ../.env and to the go.temporal.io/server
# version in go.mod.
ARG TEMPORAL_VERSION=1.31.0

FROM golang:1.26-alpine AS build
ENV GOTOOLCHAIN=auto
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -trimpath -o /out/temporal-authz-server .

FROM temporalio/server:${TEMPORAL_VERSION}
# Added alongside the stock temporal-server binary; entrypoint is unchanged.
COPY --from=build /out/temporal-authz-server /usr/local/bin/temporal-authz-server
