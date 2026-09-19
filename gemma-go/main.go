package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"time"
)

// =============================================================================
// Constants & Configuration
// =============================================================================

const (
	DefaultHost      = "http://localhost:1234"
	DefaultGemma4    = "google/gemma-4-26B-A4B-it"
	MaxRepoMapFiles  = 25
	MaxTurnRetries   = 12
)

var (
	ignoreDirs = map[string]bool{
		".git": true, ".venv": true, "venv": true, "node_modules": true,
		"__pycache__": true, "dist": true, "build": true, "target": true,
		".idea": true, ".vscode": true, ".next": true, ".cache": true,
		".pytest_cache": true, "coverage": true,
	}

	ignoreExts = map[string]bool{
		".pyc": true, ".pyo": true, ".pyd": true, ".png": true, ".jpg": true,
		".jpeg": true, ".gif": true, ".ico": true, ".svg": true, ".zip": true,
		".tar": true, ".gz": true, ".bz2": true, ".7z": true, ".pdf": true,
		".mp4": true, ".mp3": true, ".wav": true, ".ttf": true, ".woff": true,
		".woff2": true, ".eot": true, ".lock": true, ".DS_Store": true,
	}

	dangerousCommandPatterns = []struct {
		pattern *regexp.Regexp
		reason  string
	}{
		{regexp.MustCompile(`\brm\s+-[rfRF]{1,4}\s+([/~]|\$HOME|\.\.?/?)(\s|$)`), "Broad root or home directory recursive deletion"},
		{regexp.MustCompile(`\brm\s+-[rfRF]{1,4}\s+\*(\s|$)`), "Unscoped wildcard recursive deletion"},
		{regexp.MustCompile(`\b(sudo|su|doas)\b`), "Privilege escalation"},
		{regexp.MustCompile(`\b(mkfs|diskutil\s+(erase|partition)|dd\s+if=)\b`), "Raw disk modification or volume formatting"},
		{regexp.MustCompile(`\b(shutdown|reboot|halt|init\s+0)\b`), "System power manipulation or reboot"},
		{regexp.MustCompile(`:\(\)\s*\{\s*:\|:&\s*\};:`), "Fork bomb injection"},
		{regexp.MustCompile(`\bchmod\s+-[rR]\s+777\s+([/~]|\$HOME)(\s|$)`), "Broad recursive permission wiping"},
	}
)

// =============================================================================
// 1. Multi-Language Repository Mapping Engine
// =============================================================================

type RepoMap struct {
	rootDir string
}

func NewRepoMap(dir string) *RepoMap {
	abs, err := filepath.Abs(dir)
	if err != nil {
		abs = dir
	}
	return &RepoMap{rootDir: abs}
}

func (rm *RepoMap) GenerateMap() string {
	var sb strings.Builder
	sb.WriteString(fmt.Sprintf("=== REPOSITORY MAP: %s ===\n", filepath.Base(rm.rootDir)))

	count := 0
	_ = filepath.WalkDir(rm.rootDir, func(path string, d os.DirEntry, err error) error {
		if err != nil {
			return nil
		}
		if d.IsDir() {
			if ignoreDirs[d.Name()] {
				return filepath.SkipDir
			}
			return nil
		}

		ext := strings.ToLower(filepath.Ext(path))
		if ignoreExts[ext] {
			return nil
		}

		rel, err := filepath.Rel(rm.rootDir, path)
		if err != nil {
			return nil
		}

		count++
		if count > MaxRepoMapFiles {
			return nil
		}

		sigs := rm.extractSignatures(path, ext)
		if len(sigs) > 0 {
			sb.WriteString(fmt.Sprintf("\n📄 %s\n", rel))
			for _, sig := range sigs {
				sb.WriteString(fmt.Sprintf("    %s\n", sig))
			}
		} else {
			sb.WriteString(fmt.Sprintf("📄 %s\n", rel))
		}
		return nil
	})

	if count > MaxRepoMapFiles {
		sb.WriteString(fmt.Sprintf("\n... [Repository map capped at %d files]\n", MaxRepoMapFiles))
	}
	sb.WriteString("==========================================\n")
	return sb.String()
}

func (rm *RepoMap) GenerateShallowTree() string {
	var sb strings.Builder
	sb.WriteString(fmt.Sprintf("%s/\n", filepath.Base(rm.rootDir)))

	entries, err := os.ReadDir(rm.rootDir)
	if err != nil {
		return fmt.Sprintf("(error listing %s: %v)", rm.rootDir, err)
	}

	count := 0
	for _, e := range entries {
		name := e.Name()
		if strings.HasPrefix(name, ".") || ignoreDirs[name] {
			continue
		}
		if e.IsDir() {
			sb.WriteString(fmt.Sprintf("  📁 %s/\n", name))
			subEntries, _ := os.ReadDir(filepath.Join(rm.rootDir, name))
			subCount := 0
			for _, sub := range subEntries {
				subName := sub.Name()
				if strings.HasPrefix(subName, ".") || ignoreDirs[subName] {
					continue
				}
				prefix := "📄 "
				if sub.IsDir() {
					prefix = "📁 "
				}
				sb.WriteString(fmt.Sprintf("    %s%s\n", prefix, subName))
				subCount++
				if subCount >= 3 {
					break
				}
			}
		} else {
			ext := strings.ToLower(filepath.Ext(name))
			if !ignoreExts[ext] {
				sb.WriteString(fmt.Sprintf("  📄 %s\n", name))
			}
		}
		count++
		if count >= 20 {
			sb.WriteString("  ... (explore more with list_dir)\n")
			break
		}
	}
	return sb.String()
}

func (rm *RepoMap) extractSignatures(path, ext string) []string {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	content := string(data)
	lines := strings.Split(content, "\n")
	var sigs []string

	switch ext {
	case ".go":
		re := regexp.MustCompile(`^(func\s+(\([^)]+\)\s+)?[A-Za-z0-9_]+\([^)]*\)|type\s+[A-Za-z0-9_]+\s+(struct|interface))`)
		for _, l := range lines {
			lTrim := strings.TrimSpace(l)
			if re.MatchString(lTrim) {
				sigs = append(sigs, lTrim)
				if len(sigs) >= 15 {
					break
				}
			}
		}
	case ".py":
		re := regexp.MustCompile(`^(def\s+[A-Za-z0-9_]+\([^)]*\)|class\s+[A-Za-z0-9_]+)`)
		for _, l := range lines {
			lTrim := strings.TrimSpace(l)
			if re.MatchString(lTrim) {
				sigs = append(sigs, lTrim)
				if len(sigs) >= 15 {
					break
				}
			}
		}
	case ".ts", ".js", ".tsx", ".jsx":
		re := regexp.MustCompile(`^(export\s+)?(function\s+[A-Za-z0-9_]+|class\s+[A-Za-z0-9_]+|interface\s+[A-Za-z0-9_]+|const\s+[A-Za-z0-9_]+\s*=\s*(async\s+)?\([^)]*\)\s*=>)`)
		for _, l := range lines {
			lTrim := strings.TrimSpace(l)
			if re.MatchString(lTrim) {
				sigs = append(sigs, lTrim)
				if len(sigs) >= 15 {
					break
				}
			}
		}
	case ".rs":
		re := regexp.MustCompile(`^(pub\s+)?(fn\s+[A-Za-z0-9_]+|struct\s+[A-Za-z0-9_]+|enum\s+[A-Za-z0-9_]+|trait\s+[A-Za-z0-9_]+)`)
		for _, l := range lines {
			lTrim := strings.TrimSpace(l)
			if re.MatchString(lTrim) {
				sigs = append(sigs, lTrim)
				if len(sigs) >= 15 {
					break
				}
			}
		}
	}
	return sigs
}

// =============================================================================
// 2. Local Skill Management Engine
// =============================================================================

type Skill struct {
	Name        string
	Description string
	Path        string
}

type SkillManager struct {
	Skills map[string]Skill
}

func NewSkillManager() *SkillManager {
	sm := &SkillManager{Skills: make(map[string]Skill)}
	home, _ := os.UserHomeDir()
	searchPaths := []string{
		filepath.Join(home, ".gemini", "skills"),
		filepath.Join(home, ".gemini", "config", "skills"),
		filepath.Join(home, ".gemini", "config", "plugins"),
		filepath.Join(home, ".gemini", "antigravity-cli", "builtin", "skills"),
	}

	for _, base := range searchPaths {
		if fi, err := os.Stat(base); err != nil || !fi.IsDir() {
			continue
		}
		_ = filepath.Walk(base, func(path string, info os.FileInfo, err error) error {
			if err != nil {
				return nil
			}
			if strings.EqualFold(info.Name(), "SKILL.md") {
				sm.parseSkill(path)
			}
			return nil
		})
	}
	return sm
}

func (sm *SkillManager) parseSkill(filePath string) {
	data, err := os.ReadFile(filePath)
	if err != nil {
		return
	}
	content := string(data)
	dirName := filepath.Base(filepath.Dir(filePath))
	name := dirName
	desc := ""

	if strings.HasPrefix(content, "---") {
		parts := strings.SplitN(content, "---", 3)
		if len(parts) >= 3 {
			lines := strings.Split(parts[1], "\n")
			for _, l := range lines {
				l = strings.TrimSpace(l)
				if strings.HasPrefix(l, "name:") {
					name = strings.Trim(strings.TrimPrefix(l, "name:"), ` "'`)
				} else if strings.HasPrefix(l, "description:") {
					desc = strings.Trim(strings.TrimPrefix(l, "description:"), ` "'`)
				}
			}
		}
	}

	if desc == "" {
		lines := strings.Split(content, "\n")
		for _, l := range lines {
			if strings.HasPrefix(l, "# ") {
				desc = strings.TrimSpace(strings.TrimPrefix(l, "# "))
				break
			}
		}
	}

	sm.Skills[strings.ToLower(name)] = Skill{
		Name:        name,
		Description: desc,
		Path:        filePath,
	}
}

func (sm *SkillManager) GetCatalog(maxItems int) string {
	if len(sm.Skills) == 0 {
		return "(No local skills found)"
	}
	var names []string
	for k := range sm.Skills {
		names = append(names, k)
	}
	sort.Strings(names)

	var sb strings.Builder
	for i, k := range names {
		if i >= maxItems {
			sb.WriteString(fmt.Sprintf("... and %d more skills (type /skills to view all)\n", len(names)-maxItems))
			break
		}
		s := sm.Skills[k]
		firstLine := strings.Split(s.Description, "\n")[0]
		if len(firstLine) > 90 {
			firstLine = firstLine[:90] + "..."
		}
		sb.WriteString(fmt.Sprintf("- %s: %s\n", s.Name, firstLine))
	}
	return sb.String()
}

func (sm *SkillManager) LoadSkillContent(name string) (string, error) {
	key := strings.ToLower(strings.TrimSpace(name))
	if s, ok := sm.Skills[key]; ok {
		data, err := os.ReadFile(s.Path)
		return string(data), err
	}
	for k, s := range sm.Skills {
		if strings.Contains(k, key) || strings.Contains(key, k) {
			data, err := os.ReadFile(s.Path)
			return string(data), err
		}
	}
	return "", fmt.Errorf("skill '%s' not found", name)
}

// =============================================================================
// 3. Tool Execution Engine & Multi-Layer Sandboxing
// =============================================================================

type ToolKit struct {
	RepoDir       string
	ModifiedFiles map[string]bool
}

func NewToolKit(dir string) *ToolKit {
	abs, err := filepath.Abs(dir)
	if err != nil {
		abs = dir
	}
	return &ToolKit{
		RepoDir:       abs,
		ModifiedFiles: make(map[string]bool),
	}
}

// 🔒 Layer 1 Sandbox: Strict Path Traversal Jail
func (tk *ToolKit) resolvePath(fileRel string) (string, error) {
	cleanRel := strings.TrimSpace(fileRel)
	if cleanRel == "" {
		return "", fmt.Errorf("empty file path provided")
	}
	target := cleanRel
	if !filepath.IsAbs(target) {
		target = filepath.Join(tk.RepoDir, target)
	}
	cleanTarget := filepath.Clean(target)

	// Verify target is strictly within RepoDir
	rel, err := filepath.Rel(tk.RepoDir, cleanTarget)
	if err != nil || strings.HasPrefix(rel, "..") || strings.HasPrefix(cleanTarget, "/etc") {
		return "", fmt.Errorf("Security Violation (Layer 1 Sandbox): Access to '%s' denied. Paths must stay strictly inside repository (%s)", fileRel, tk.RepoDir)
	}
	return cleanTarget, nil
}

func (tk *ToolKit) ReadFile(path string, startLine, endLine int) (string, error) {
	resolved, err := tk.resolvePath(path)
	if err != nil {
		return "", err
	}
	fi, err := os.Stat(resolved)
	if err != nil {
		return "", err
	}
	if fi.IsDir() {
		return "", fmt.Errorf("'%s' is a directory, not a file. Use 'list_dir' to inspect directories", path)
	}
	data, err := os.ReadFile(resolved)
	if err != nil {
		return "", err
	}
	lines := strings.Split(string(data), "\n")
	total := len(lines)
	s := 1
	if startLine > 0 {
		s = startLine
	}
	e := total
	if endLine > 0 && endLine <= total {
		e = endLine
	}

	var sb strings.Builder
	for i := s; i <= e && i <= total; i++ {
		sb.WriteString(fmt.Sprintf("%4d: %s\n", i, lines[i-1]))
	}
	return sb.String(), nil
}

func (tk *ToolKit) WriteFile(path, content string) (string, error) {
	resolved, err := tk.resolvePath(path)
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(filepath.Dir(resolved), 0755); err != nil {
		return "", err
	}
	if err := os.WriteFile(resolved, []byte(content), 0644); err != nil {
		return "", err
	}
	tk.ModifiedFiles[resolved] = true
	lines := len(strings.Split(content, "\n"))
	return fmt.Sprintf("✅ Successfully wrote %d lines to '%s'.", lines, path), nil
}

func (tk *ToolKit) ReplaceFileContent(path, targetContent, replacementContent string) (string, error) {
	resolved, err := tk.resolvePath(path)
	if err != nil {
		return "", err
	}
	data, err := os.ReadFile(resolved)
	if err != nil {
		return "", err
	}
	orig := string(data)
	if !strings.Contains(orig, targetContent) {
		return "", fmt.Errorf("target content not found in '%s'. Ensure exact whitespace match", path)
	}
	count := strings.Count(orig, targetContent)
	if count > 1 {
		return "", fmt.Errorf("target content matches %d occurrences in '%s'. Provide more context", count, path)
	}

	updated := strings.Replace(orig, targetContent, replacementContent, 1)
	if err := os.WriteFile(resolved, []byte(updated), 0644); err != nil {
		return "", err
	}
	tk.ModifiedFiles[resolved] = true
	return fmt.Sprintf("✅ Successfully updated '%s'.", path), nil
}

// 🛡️ Layer 2 Sandbox: Destructive Bash Deny-List
func (tk *ToolKit) RunCommand(command string) (string, error) {
	for _, guard := range dangerousCommandPatterns {
		if guard.pattern.MatchString(command) {
			return "", fmt.Errorf("Security Violation (Layer 2 Sandbox): Command blocked by safety guardrail (%s). Command: '%s'", guard.reason, command)
		}
	}

	fmt.Printf("\n⚡ Executing bash: %s\n", command)
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	cmd := exec.CommandContext(ctx, "bash", "-c", command)
	cmd.Dir = tk.RepoDir

	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	err := cmd.Run()
	var sb strings.Builder
	if stdout.Len() > 0 {
		sb.WriteString(fmt.Sprintf("[stdout]\n%s\n", stdout.String()))
	}
	if stderr.Len() > 0 {
		sb.WriteString(fmt.Sprintf("[stderr]\n%s\n", stderr.String()))
	}
	if err != nil {
		sb.WriteString(fmt.Sprintf("[Exit status: %v]\n", err))
	} else {
		sb.WriteString("[Exit code: 0]\n")
	}
	return sb.String(), nil
}

func (tk *ToolKit) ListDir(relPath string) (string, error) {
	resolved, err := tk.resolvePath(relPath)
	if err != nil {
		return "", err
	}
	entries, err := os.ReadDir(resolved)
	if err != nil {
		return "", err
	}
	var items []string
	for _, e := range entries {
		prefix := "📄 "
		if e.IsDir() {
			prefix = "📁 "
		}
		items = append(items, prefix+e.Name())
	}
	if len(items) == 0 {
		return "(empty directory)", nil
	}
	return strings.Join(items, "\n"), nil
}

func (tk *ToolKit) GitDiff() string {
	cmd := exec.Command("git", "diff")
	cmd.Dir = tk.RepoDir
	out, err := cmd.Output()
	if err != nil {
		return fmt.Sprintf("git diff error: %v", err)
	}
	str := strings.TrimSpace(string(out))
	if str == "" {
		return "(No unstaged changes)"
	}
	return str
}

func (tk *ToolKit) GitCommit(msg string) string {
	addCmd := exec.Command("git", "add", "-A")
	addCmd.Dir = tk.RepoDir
	if err := addCmd.Run(); err != nil {
		return fmt.Sprintf("git add error: %v", err)
	}

	commitCmd := exec.Command("git", "commit", "-m", msg)
	commitCmd.Dir = tk.RepoDir
	out, err := commitCmd.CombinedOutput()
	if err != nil {
		return fmt.Sprintf("git commit warning: %s", string(out))
	}
	tk.ModifiedFiles = make(map[string]bool)
	return fmt.Sprintf("✅ Git Commit Successful:\n%s", strings.TrimSpace(string(out)))
}

func (tk *ToolKit) GitUndo() string {
	cmd := exec.Command("git", "reset", "--hard", "HEAD~1")
	cmd.Dir = tk.RepoDir
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Sprintf("git undo error: %s", string(out))
	}
	return fmt.Sprintf("⏪ Rolled back last commit:\n%s", strings.TrimSpace(string(out)))
}

// =============================================================================
// 4. Autonomous Agent Loop & LLM Client
// =============================================================================

type ToolCall struct {
	ID       string `json:"id"`
	Type     string `json:"type"`
	Function struct {
		Name      string          `json:"name"`
		Arguments json.RawMessage `json:"arguments"`
	} `json:"function"`
}

type Message struct {
	Role       string     `json:"role"`
	Content    string     `json:"content,omitempty"`
	Name       string     `json:"name,omitempty"`
	ToolCallID string     `json:"tool_call_id,omitempty"`
	ToolCalls  []ToolCall `json:"tool_calls,omitempty"`
}

type GemmaAgent struct {
	repoDir       string
	apiURL        string
	modelID       string
	confirm       bool
	toolkit       *ToolKit
	repomap       *RepoMap
	skillMgr      *SkillManager
	messages      []Message
	httpClient    *http.Client
	alwaysApprove bool
}

func detectModelID(apiURL string) string {
	client := &http.Client{Timeout: 4 * time.Second}
	resp, err := client.Get(fmt.Sprintf("%s/v1/models", strings.TrimRight(apiURL, "/")))
	if err == nil && resp.StatusCode == http.StatusOK {
		defer resp.Body.Close()
		var res struct {
			Data []struct {
				ID string `json:"id"`
			} `json:"data"`
		}
		if err := json.NewDecoder(resp.Body).Decode(&res); err == nil && len(res.Data) > 0 {
			return res.Data[0].ID
		}
	}
	return DefaultGemma4
}

func NewGemmaAgent(repoDir, apiURL string, confirm bool) *GemmaAgent {
	detectedModel := detectModelID(apiURL)
	agent := &GemmaAgent{
		repoDir:    repoDir,
		apiURL:     apiURL,
		modelID:    detectedModel,
		confirm:    confirm,
		toolkit:    NewToolKit(repoDir),
		repomap:    NewRepoMap(repoDir),
		skillMgr:   NewSkillManager(),
		httpClient: &http.Client{Timeout: 240 * time.Second},
	}
	agent.initSystemPrompt()
	return agent
}

func (a *GemmaAgent) initSystemPrompt() {
	shallowTree := a.repomap.GenerateShallowTree()

	systemPrompt := fmt.Sprintf(`You are Gemma 4, an autonomous expert coding agent running locally on Apple Silicon.
Working Directory: %s

Directory Overview:
%s

Rules:
1. Inspect files and directories on-demand using 'list_dir', 'read_file', and 'run_command'.
2. For edits, use 'replace_file_content' with exact whitespace matching, or 'write_file'.
3. For bash testing and verification, use 'run_command'.
4. Security: File edits are sandboxed to repo. Broad destructive bash commands are blocked.
5. Be concise and prioritize working, robust code.
`, a.repoDir, shallowTree)

	a.messages = []Message{
		{Role: "system", Content: systemPrompt},
	}
}

func (a *GemmaAgent) RunTurn(userInput string) {
	a.messages = append(a.messages, Message{Role: "user", Content: userInput})

	for turn := 0; turn < MaxTurnRetries; turn++ {
		fmt.Printf("🤔 [Gemma 4 Thinking] (step %d/%d)...\n", turn+1, MaxTurnRetries)
		respMsg, err := a.callLLM()
		if err != nil {
			fmt.Printf("❌ LLM API Error: %v\n", err)
			return
		}

		a.messages = append(a.messages, *respMsg)

		if len(respMsg.ToolCalls) == 0 {
			fmt.Printf("\n🤖 Gemma 4:\n%s\n\n", respMsg.Content)
			break
		}

		for _, tc := range respMsg.ToolCalls {
			fnName := tc.Function.Name
			var argsJSON string
			var s string
			if err := json.Unmarshal(tc.Function.Arguments, &s); err == nil {
				argsJSON = s
			} else {
				argsJSON = string(tc.Function.Arguments)
			}
			fmt.Printf("🔧 Tool Call: %s(%s)\n", fnName, argsJSON)

			// 🚦 Layer 3: Interactive Permission Gating
			if !a.promptApproval(fnName, argsJSON) {
				declinedMsg := "Action declined by user."
				a.messages = append(a.messages, Message{
					Role:       "tool",
					Name:       fnName,
					ToolCallID: tc.ID,
					Content:    "❌ User rejected this operation. Please choose a different approach.",
				})
				fmt.Printf("⚠️ %s\n", declinedMsg)
				continue
			}

			output := a.executeTool(fnName, tc.Function.Arguments)
			preview := output
			if len(preview) > 200 {
				preview = preview[:200] + "... [truncated]"
			}
			fmt.Printf("  ↳ Result: %s\n", strings.TrimSpace(preview))

			a.messages = append(a.messages, Message{
				Role:       "tool",
				Name:       fnName,
				ToolCallID: tc.ID,
				Content:    output,
			})
		}
	}

	// Auto-commit if files were modified
	if len(a.toolkit.ModifiedFiles) > 0 {
		fmt.Printf("\n📦 Auto-committing %d modified files...\n", len(a.toolkit.ModifiedFiles))
		commitRes := a.toolkit.GitCommit("feat(gemma): autonomous updates by gemma 4")
		fmt.Println(commitRes)
	}
}

func (a *GemmaAgent) promptApproval(fnName, argsJSON string) bool {
	if !a.confirm || a.alwaysApprove {
		return true
	}
	if fnName == "read_file" || fnName == "list_dir" || fnName == "grep_search" || fnName == "load_skill" {
		return true
	}

	fmt.Println("\n" + strings.Repeat("=", 65))
	fmt.Printf("🔒 APPROVAL REQUIRED: Gemma 4 wants to execute tool '%s'\n", fnName)
	fmt.Printf("Arguments: %s\n", argsJSON)
	fmt.Print("Approve? [y/n/always] (default: y): ")

	reader := bufio.NewReader(os.Stdin)
	ans, _ := reader.ReadString('\n')
	ans = strings.TrimSpace(strings.ToLower(ans))

	if ans == "" || ans == "y" || ans == "yes" {
		return true
	} else if ans == "always" {
		a.alwaysApprove = true
		return true
	}
	return false
}

func unmarshalArgs(raw json.RawMessage, target interface{}) error {
	// 1. Direct unmarshal (if already JSON object)
	if err := json.Unmarshal(raw, target); err == nil {
		return nil
	}
	// 2. Unmarshal as string if it was JSON string-encoded (OpenAI / LM Studio standard)
	var str string
	if err := json.Unmarshal(raw, &str); err == nil {
		return json.Unmarshal([]byte(str), target)
	}
	// 3. Fallback: string unquote
	trimmed := strings.Trim(string(raw), "\"")
	return json.Unmarshal([]byte(trimmed), target)
}

func (a *GemmaAgent) executeTool(name string, argsRaw json.RawMessage) string {
	switch name {
	case "read_file":
		var p struct {
			Path      string `json:"path"`
			StartLine int    `json:"start_line"`
			EndLine   int    `json:"end_line"`
		}
		if err := unmarshalArgs(argsRaw, &p); err != nil {
			return fmt.Sprintf("❌ Invalid arguments: %v", err)
		}
		res, err := a.toolkit.ReadFile(p.Path, p.StartLine, p.EndLine)
		if err != nil {
			return fmt.Sprintf("❌ %v", err)
		}
		return res

	case "write_file":
		var p struct {
			Path    string `json:"path"`
			Content string `json:"content"`
		}
		if err := unmarshalArgs(argsRaw, &p); err != nil {
			return fmt.Sprintf("❌ Invalid arguments: %v", err)
		}
		res, err := a.toolkit.WriteFile(p.Path, p.Content)
		if err != nil {
			return fmt.Sprintf("❌ %v", err)
		}
		return res

	case "replace_file_content":
		var p struct {
			Path               string `json:"path"`
			TargetContent      string `json:"target_content"`
			ReplacementContent string `json:"replacement_content"`
		}
		if err := unmarshalArgs(argsRaw, &p); err != nil {
			return fmt.Sprintf("❌ Invalid arguments: %v", err)
		}
		res, err := a.toolkit.ReplaceFileContent(p.Path, p.TargetContent, p.ReplacementContent)
		if err != nil {
			return fmt.Sprintf("❌ %v", err)
		}
		return res

	case "run_command":
		var p struct {
			Command string `json:"command"`
		}
		if err := unmarshalArgs(argsRaw, &p); err != nil {
			return fmt.Sprintf("❌ Invalid arguments: %v", err)
		}
		res, err := a.toolkit.RunCommand(p.Command)
		if err != nil {
			return fmt.Sprintf("❌ %v", err)
		}
		return res

	case "list_dir":
		var p struct {
			Path string `json:"path"`
		}
		if err := unmarshalArgs(argsRaw, &p); err != nil {
			return fmt.Sprintf("❌ Invalid arguments: %v", err)
		}
		if p.Path == "" {
			p.Path = "."
		}
		res, err := a.toolkit.ListDir(p.Path)
		if err != nil {
			return fmt.Sprintf("❌ %v", err)
		}
		return res

	case "load_skill":
		var p struct {
			SkillName string `json:"skill_name"`
		}
		if err := unmarshalArgs(argsRaw, &p); err != nil {
			return fmt.Sprintf("❌ Invalid arguments: %v", err)
		}
		content, err := a.skillMgr.LoadSkillContent(p.SkillName)
		if err != nil {
			return fmt.Sprintf("❌ %v", err)
		}
		return fmt.Sprintf("📖 Loaded skill instructions for '%s':\n\n%s", p.SkillName, content)

	default:
		return fmt.Sprintf("❌ Unknown tool '%s'", name)
	}
}

func (a *GemmaAgent) callLLM() (*Message, error) {
	tools := getToolDefinitions()
	payload := map[string]interface{}{
		"model":       a.modelID,
		"messages":    a.messages,
		"tools":       tools,
		"temperature": 0.2,
	}

	data, err := json.Marshal(payload)
	if err != nil {
		return nil, err
	}

	endpoint := fmt.Sprintf("%s/v1/chat/completions", strings.TrimRight(a.apiURL, "/"))
	req, err := http.NewRequest("POST", endpoint, bytes.NewBuffer(data))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := a.httpClient.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("HTTP %d: %s", resp.StatusCode, string(body))
	}

	var chatResp struct {
		Choices []struct {
			Message Message `json:"message"`
		} `json:"choices"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&chatResp); err != nil {
		return nil, err
	}
	if len(chatResp.Choices) == 0 {
		return nil, fmt.Errorf("empty choices from LM Studio")
	}
	return &chatResp.Choices[0].Message, nil
}

func getToolDefinitions() []map[string]interface{} {
	return []map[string]interface{}{
		{
			"type": "function",
			"function": map[string]interface{}{
				"name":        "read_file",
				"description": "Read file contents with line numbers.",
				"parameters": map[string]interface{}{
					"type": "object",
					"properties": map[string]interface{}{
						"path":       map[string]string{"type": "string", "description": "Relative path to file"},
						"start_line": map[string]string{"type": "integer", "description": "Start line (optional)"},
						"end_line":   map[string]string{"type": "integer", "description": "End line (optional)"},
					},
					"required": []string{"path"},
				},
			},
		},
		{
			"type": "function",
			"function": map[string]interface{}{
				"name":        "write_file",
				"description": "Create or overwrite a file with contents.",
				"parameters": map[string]interface{}{
					"type": "object",
					"properties": map[string]interface{}{
						"path":    map[string]string{"type": "string", "description": "Relative path"},
						"content": map[string]string{"type": "string", "description": "File content"},
					},
					"required": []string{"path", "content"},
				},
			},
		},
		{
			"type": "function",
			"function": map[string]interface{}{
				"name":        "replace_file_content",
				"description": "Replace an exact target block of code with replacement code.",
				"parameters": map[string]interface{}{
					"type": "object",
					"properties": map[string]interface{}{
						"path":                map[string]string{"type": "string", "description": "Relative path"},
						"target_content":      map[string]string{"type": "string", "description": "Exact text to replace"},
						"replacement_content": map[string]string{"type": "string", "description": "New replacement text"},
					},
					"required": []string{"path", "target_content", "replacement_content"},
				},
			},
		},
		{
			"type": "function",
			"function": map[string]interface{}{
				"name":        "run_command",
				"description": "Execute bash commands in the workspace.",
				"parameters": map[string]interface{}{
					"type": "object",
					"properties": map[string]interface{}{
						"command": map[string]string{"type": "string", "description": "Bash command"},
					},
					"required": []string{"command"},
				},
			},
		},
		{
			"type": "function",
			"function": map[string]interface{}{
				"name":        "list_dir",
				"description": "List directory contents.",
				"parameters": map[string]interface{}{
					"type": "object",
					"properties": map[string]interface{}{
						"path": map[string]string{"type": "string", "description": "Directory path (default: .)"},
					},
				},
			},
		},
	}
}

// =============================================================================
// 5. Main Entrypoint & Interactive REPL
// =============================================================================

func main() {
	repoFlag := flag.String("repo", ".", "Target repository directory")
	urlFlag := flag.String("url", DefaultHost, "LM Studio API endpoint")
	confirmFlag := flag.Bool("confirm", false, "Prompt for approval before executing bash or modifying files")
	flag.Parse()

	targetRepo, err := filepath.Abs(*repoFlag)
	if err != nil {
		targetRepo = *repoFlag
	}

	agent := NewGemmaAgent(targetRepo, *urlFlag, *confirmFlag)

	confirmStatus := "DISABLED (Auto-approve)"
	if agent.confirm {
		confirmStatus = "ENABLED (Interactive Prompts)"
	}

	fmt.Println("=" + strings.Repeat("=", 64))
	fmt.Println("🚀 Gemma 4 Autonomous Offline Coding Agent (Go Native)")
	fmt.Printf("📁 Target Repo:     %s\n", targetRepo)
	fmt.Printf("🤖 Target Model:    %s\n", agent.modelID)
	fmt.Printf("📡 API Endpoint:    %s\n", *urlFlag)
	fmt.Printf("🔒 Approval Mode:   %s\n", confirmStatus)
	fmt.Printf("📚 Local Skills:    %d discovered offline\n", len(agent.skillMgr.Skills))
	fmt.Println("Commands: /map, /skills, /skill <name>, /diff, /commit, /undo, /confirm, !<cmd>, exit")
	fmt.Println("=" + strings.Repeat("=", 64) + "\n")

	// If positional arg provided
	if flag.NArg() > 0 {
		task := strings.Join(flag.Args(), " ")
		agent.RunTurn(task)
		return
	}

	scanner := bufio.NewScanner(os.Stdin)
	for {
		fmt.Printf("👤 [%s] > ", filepath.Base(targetRepo))
		if !scanner.Scan() {
			break
		}
		cmd := strings.TrimSpace(scanner.Text())
		if cmd == "" {
			continue
		}

		switch {
		case cmd == "exit" || cmd == "quit":
			fmt.Println("👋 Happy coding on your flight!")
			return

		case cmd == "/map":
			fmt.Println(agent.repomap.GenerateMap())

		case cmd == "/skills":
			fmt.Println("\n📚 Available Local Skills:")
			fmt.Println(strings.Repeat("-", 65))
			var names []string
			for k := range agent.skillMgr.Skills {
				names = append(names, k)
			}
			sort.Strings(names)
			for _, k := range names {
				s := agent.skillMgr.Skills[k]
				desc := strings.Split(s.Description, "\n")[0]
				if len(desc) > 80 {
					desc = desc[:80] + "..."
				}
				fmt.Printf("  • %-30s %s\n", s.Name, desc)
			}
			fmt.Println(strings.Repeat("-", 65))
			fmt.Printf("Total: %d skills found offline.\n\n", len(agent.skillMgr.Skills))

		case strings.HasPrefix(cmd, "/skill"):
			parts := strings.SplitN(cmd, " ", 2)
			if len(parts) < 2 {
				fmt.Println("Usage: /skill <name>  (e.g. /skill hld-lld)")
				continue
			}
			sName := strings.TrimSpace(parts[1])
			content, err := agent.skillMgr.LoadSkillContent(sName)
			if err != nil {
				fmt.Printf("❌ %v. Type /skills to see available names.\n", err)
				continue
			}
			agent.messages = append(agent.messages, Message{
				Role:    "user",
				Content: fmt.Sprintf("[INSTRUCTION]: Activate and follow the guidelines of skill '%s':\n\n%s", sName, content),
			})
			agent.messages = append(agent.messages, Message{
				Role:    "assistant",
				Content: fmt.Sprintf("Understood. I have activated and reviewed the '%s' skill guidelines. I will follow them.", sName),
			})
			lines := len(strings.Split(content, "\n"))
			fmt.Printf("✅ Activated skill '%s' (%d lines). Gemma 4 will follow these rules!\n", sName, lines)

		case cmd == "/diff":
			fmt.Println(agent.toolkit.GitDiff())

		case strings.HasPrefix(cmd, "/confirm"):
			parts := strings.Fields(cmd)
			if len(parts) > 1 {
				agent.confirm = parts[1] == "on" || parts[1] == "true" || parts[1] == "1" || parts[1] == "yes"
			} else {
				agent.confirm = !agent.confirm
			}
			status := "DISABLED (Auto-approves tool actions)"
			if agent.confirm {
				status = "ENABLED (Prompts before bash / file edits)"
			}
			fmt.Printf("🔒 Approval Mode: %s\n", status)

		case strings.HasPrefix(cmd, "/commit"):
			parts := strings.SplitN(cmd, " ", 2)
			msg := "chore: save work"
			if len(parts) > 1 {
				msg = parts[1]
			}
			fmt.Println(agent.toolkit.GitCommit(msg))

		case cmd == "/undo":
			fmt.Println(agent.toolkit.GitUndo())

		case strings.HasPrefix(cmd, "/run ") || strings.HasPrefix(cmd, "!"):
			var shellCmd string
			if strings.HasPrefix(cmd, "/run ") {
				shellCmd = strings.TrimPrefix(cmd, "/run ")
			} else {
				shellCmd = strings.TrimPrefix(cmd, "!")
			}
			out, err := agent.toolkit.RunCommand(shellCmd)
			if err != nil {
				fmt.Printf("❌ %v\n", err)
			} else {
				fmt.Println(out)
			}

		default:
			agent.RunTurn(cmd)
		}
	}
}
