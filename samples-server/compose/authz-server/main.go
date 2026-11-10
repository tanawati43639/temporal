package main

import (
	"os"
	"strings"

	"go.temporal.io/server/common/config"
	"go.temporal.io/server/common/log"
	"go.temporal.io/server/common/log/tag"
	"go.temporal.io/server/temporal"
)

// servicesFromEnv parses TEMPORAL_SERVICES (comma separated). The server
// library never reads it, so the stock binary's behaviour is reproduced here.
// Falls back to temporal.DefaultServices when nothing usable is set.
func servicesFromEnv() []string {
	var services []string
	for _, s := range strings.Split(os.Getenv("TEMPORAL_SERVICES"), ",") {
		if s = strings.TrimSpace(s); s != "" {
			services = append(services, s)
		}
	}
	if len(services) == 0 {
		return temporal.DefaultServices
	}
	return services
}

func newServer(logger log.Logger) (temporal.Server, error) {
	cfg, err := config.Load(config.WithEmbedded())
	if err != nil {
		return nil, err
	}
	return temporal.NewServer(
		temporal.ForServices(servicesFromEnv()),
		temporal.WithConfig(cfg),
		temporal.WithLogger(logger),
		temporal.InterruptOn(temporal.InterruptCh()),
	)
}

func main() {
	logger := log.NewCLILogger()
	s, err := newServer(logger)
	if err != nil {
		logger.Fatal("Unable to create server", tag.Error(err))
	}
	if err := s.Start(); err != nil {
		logger.Fatal("Unable to start server", tag.Error(err))
	}
}
