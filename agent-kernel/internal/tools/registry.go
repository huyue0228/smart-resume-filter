package tools

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"unicode"

	"smart-resume/agent-kernel/internal/protocol"
)

var allowed = map[string]struct{}{
	"case.read_constraints":  {},
	"job.read_fixed_context": {},
	"resume.read_sections":   {},
	"resume.search_evidence": {},
	"evidence.verify_quotes": {},
}

type Registry struct {
	envelope protocol.CaseEnvelopeV1
}

func New(envelope protocol.CaseEnvelopeV1) *Registry {
	return &Registry{envelope: envelope}
}

func Names() []string {
	return []string{
		"case.read_constraints",
		"job.read_fixed_context",
		"resume.read_sections",
		"resume.search_evidence",
		"evidence.verify_quotes",
	}
}

func (r *Registry) Execute(call protocol.ToolCall) (json.RawMessage, int, error) {
	if _, ok := allowed[call.Name]; !ok {
		return nil, 0, fmt.Errorf("tool %q is not allowlisted", call.Name)
	}
	var value any
	var count int
	switch call.Name {
	case "case.read_constraints":
		if err := validateArgumentKeys(call.Arguments); err != nil {
			return nil, 0, err
		}
		value = map[string]any{
			"constraints":         r.envelope.Constraints,
			"candidate_reference": r.envelope.Candidate,
			"current_volunteer":   r.envelope.CurrentVolunteer,
		}
		count = 1
	case "job.read_fixed_context":
		if err := validateArgumentKeys(call.Arguments); err != nil {
			return nil, 0, err
		}
		value = r.envelope.CurrentJob
		count = 1
	case "resume.read_sections":
		if err := validateArgumentKeys(call.Arguments, "start_line", "max_lines"); err != nil {
			return nil, 0, err
		}
		start, err := integerArg(call.Arguments, "start_line", 0)
		if err != nil || start < 0 {
			return nil, 0, errors.New("start_line must be a non-negative integer")
		}
		limit, err := integerArg(call.Arguments, "max_lines", 120)
		if err != nil || limit < 1 || limit > 200 {
			return nil, 0, errors.New("max_lines must be between 1 and 200")
		}
		lines := strings.Split(r.envelope.Resume.Text, "\n")
		if start > len(lines) {
			start = len(lines)
		}
		end := start + limit
		if end > len(lines) {
			end = len(lines)
		}
		selected := lines[start:end]
		value = map[string]any{"start_line": start, "next_line": end, "total_lines": len(lines), "lines": selected}
		count = len(selected)
	case "resume.search_evidence":
		if err := validateArgumentKeys(call.Arguments, "query"); err != nil {
			return nil, 0, err
		}
		query, _ := call.Arguments["query"].(string)
		query = strings.TrimSpace(query)
		if query == "" || len([]rune(query)) > 256 {
			return nil, 0, errors.New("query must contain 1 to 256 characters")
		}
		matches := searchWindows(r.envelope.Resume.Text, query, 5)
		value = map[string]any{"query": query, "matches": matches}
		count = len(matches)
	case "evidence.verify_quotes":
		if err := validateArgumentKeys(call.Arguments, "quotes"); err != nil {
			return nil, 0, err
		}
		rawQuotes, ok := call.Arguments["quotes"].([]any)
		if !ok || len(rawQuotes) == 0 || len(rawQuotes) > 20 {
			return nil, 0, errors.New("quotes must be an array containing 1 to 20 strings")
		}
		items := make([]map[string]any, 0, len(rawQuotes))
		verified := 0
		for _, raw := range rawQuotes {
			quote, ok := raw.(string)
			if !ok || strings.TrimSpace(quote) == "" || len([]rune(quote)) > 500 {
				return nil, 0, errors.New("each quote must contain 1 to 500 characters")
			}
			found := ContainsNormalized(r.envelope.Resume.Text, quote)
			if found {
				verified++
			}
			items = append(items, map[string]any{"quote": quote, "verified": found})
		}
		value = map[string]any{"items": items, "all_verified": verified == len(items)}
		count = len(items)
	}
	payload, err := json.Marshal(value)
	return payload, count, err
}

func validateArgumentKeys(args map[string]any, allowedKeys ...string) error {
	allowed := make(map[string]struct{}, len(allowedKeys))
	for _, key := range allowedKeys {
		allowed[key] = struct{}{}
	}
	for key := range args {
		if _, ok := allowed[key]; !ok {
			return fmt.Errorf("unexpected tool argument %q", key)
		}
	}
	return nil
}

func integerArg(args map[string]any, key string, fallback int) (int, error) {
	raw, ok := args[key]
	if !ok {
		return fallback, nil
	}
	value, ok := raw.(float64)
	if !ok || value != float64(int(value)) {
		return 0, errors.New("not an integer")
	}
	return int(value), nil
}

func normalize(value string) string {
	return strings.Map(func(r rune) rune {
		if unicode.IsSpace(r) {
			return -1
		}
		return unicode.ToLower(r)
	}, value)
}

func ContainsNormalized(text, quote string) bool {
	needle := normalize(quote)
	return len([]rune(needle)) >= 4 && strings.Contains(normalize(text), needle)
}

func searchWindows(text, query string, limit int) []map[string]any {
	textRunes := []rune(text)
	queryRunes := []rune(query)
	if len(queryRunes) == 0 {
		return nil
	}
	lowerText := []rune(strings.ToLower(text))
	lowerQuery := []rune(strings.ToLower(query))
	results := make([]map[string]any, 0, limit)
	for index := 0; index+len(lowerQuery) <= len(lowerText) && len(results) < limit; index++ {
		if string(lowerText[index:index+len(lowerQuery)]) != string(lowerQuery) {
			continue
		}
		start := index - 80
		if start < 0 {
			start = 0
		}
		end := index + len(queryRunes) + 80
		if end > len(textRunes) {
			end = len(textRunes)
		}
		results = append(results, map[string]any{"offset": index, "text": string(textRunes[start:end])})
		index += len(lowerQuery) - 1
	}
	return results
}
