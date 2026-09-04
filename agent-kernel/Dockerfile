ARG GO_IMAGE=golang:1.23-alpine
ARG RUNTIME_IMAGE=alpine:3.20
ARG APP_VERSION=dev

FROM ${GO_IMAGE} AS builder
ARG APP_VERSION
WORKDIR /src
COPY go.mod ./
COPY cmd ./cmd
COPY internal ./internal
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w -X main.build=${APP_VERSION}" -o /out/agent-kernel ./cmd/agent-kernel

FROM ${RUNTIME_IMAGE}
RUN addgroup -S agent && adduser -S -G agent agent
COPY --from=builder /out/agent-kernel /usr/local/bin/agent-kernel
USER agent
EXPOSE 8090
ENTRYPOINT ["/usr/local/bin/agent-kernel"]
