package tools

import (
	"encoding/json"
	"testing"

	"smart-resume/agent-kernel/internal/protocol"
)

func TestRegistryOnlyExecutesReadOnlyAllowlist(t *testing.T) {
	registry := New(protocol.CaseEnvelopeV1{Resume: protocol.ResumeContent{Text: "负责 Go 服务开发与性能优化"}})
	if _, _, err := registry.Execute(protocol.ToolCall{Name: "database.execute_sql"}); err == nil {
		t.Fatal("expected non-allowlisted tool to be rejected")
	}
}

func TestRegistryRejectsUnknownArguments(t *testing.T) {
	registry := New(protocol.CaseEnvelopeV1{})
	if _, _, err := registry.Execute(protocol.ToolCall{
		Name:      "case.read_constraints",
		Arguments: map[string]any{"candidate_id": float64(123)},
	}); err == nil {
		t.Fatal("expected unknown argument to be rejected")
	}
}

func TestVerifyQuotesUsesNormalizedExactEvidence(t *testing.T) {
	registry := New(protocol.CaseEnvelopeV1{Resume: protocol.ResumeContent{Text: "负责 Go 服务开发\n与性能优化"}})
	payload, count, err := registry.Execute(protocol.ToolCall{
		Name:      "evidence.verify_quotes",
		Arguments: map[string]any{"quotes": []any{"Go 服务开发 与性能优化"}},
	})
	if err != nil {
		t.Fatal(err)
	}
	if count != 1 {
		t.Fatalf("unexpected count: %d", count)
	}
	var result struct {
		AllVerified bool `json:"all_verified"`
	}
	if err := json.Unmarshal(payload, &result); err != nil {
		t.Fatal(err)
	}
	if !result.AllVerified {
		t.Fatal("expected normalized quote to be verified")
	}
}
