package main

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"smart-resume/agent-kernel/internal/runtime"
	"smart-resume/agent-kernel/internal/server"
)

var build = "dev"

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
	address := valueOrDefault(os.Getenv("AGENT_KERNEL_ADDRESS"), ":8090")
	token := os.Getenv("AGENT_KERNEL_TOKEN")
	if token == "" {
		logger.Error("AGENT_KERNEL_TOKEN is required")
		os.Exit(2)
	}

	httpServer := &http.Server{
		Addr:              address,
		Handler:           server.New(runtime.NewService(build), token, build, logger),
		ReadHeaderTimeout: 5 * time.Second,
		ReadTimeout:       30 * time.Second,
		WriteTimeout:      31 * time.Minute,
		IdleTimeout:       60 * time.Second,
	}

	go func() {
		logger.Info("agent kernel listening", "address", address, "build", build)
		if err := httpServer.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Error("agent kernel stopped unexpectedly", "error_type", "listen_failed")
			os.Exit(1)
		}
	}()

	stop, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()
	<-stop.Done()
	shutdownContext, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()
	if err := httpServer.Shutdown(shutdownContext); err != nil {
		logger.Error("agent kernel shutdown failed", "error_type", "shutdown_timeout")
	}
}

func valueOrDefault(value, fallback string) string {
	if value == "" {
		return fallback
	}
	return value
}
