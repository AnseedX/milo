package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestUnmarshalArgs(t *testing.T) {
	// Test case 1: raw JSON string (as returned by OpenAI/LM Studio API)
	rawStr := json.RawMessage(`"{\"path\":\"README.md\",\"start_line\":1,\"end_line\":5}"`)
	var p struct {
		Path      string `json:"path"`
		StartLine int    `json:"start_line"`
		EndLine   int    `json:"end_line"`
	}

	if err := unmarshalArgs(rawStr, &p); err != nil {
		t.Fatalf("unmarshalArgs failed on string: %v", err)
	}
	if p.Path != "README.md" {
		t.Fatalf("expected 'README.md', got '%s'", p.Path)
	}
	if p.StartLine != 1 || p.EndLine != 5 {
		t.Fatalf("expected start=1, end=5, got %d, %d", p.StartLine, p.EndLine)
	}

	// Test case 2: raw JSON object
	rawObj := json.RawMessage(`{"path":"agent.py","start_line":10,"end_line":20}`)
	var p2 struct {
		Path      string `json:"path"`
		StartLine int    `json:"start_line"`
		EndLine   int    `json:"end_line"`
	}
	if err := unmarshalArgs(rawObj, &p2); err != nil {
		t.Fatalf("unmarshalArgs failed on object: %v", err)
	}
	if p2.Path != "agent.py" {
		t.Fatalf("expected 'agent.py', got '%s'", p2.Path)
	}
}

func TestReadFileDirectoryRejection(t *testing.T) {
	wd, _ := os.Getwd()
	parent := filepath.Dir(wd)
	tk := NewToolKit(parent)

	// Attempting to read directory should return error, not directory read error
	_, err := tk.ReadFile("", 0, 0)
	if err == nil {
		t.Fatal("expected error reading empty path, got nil")
	}

	_, errDir := tk.ReadFile("gemma-go", 0, 0)
	if errDir == nil {
		t.Fatal("expected error reading directory, got nil")
	}
}
