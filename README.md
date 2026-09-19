<div align="center">

# 🐈‍⬛ milo

**An offline-first, agentic coding CLI for your local LLM.**

One command. Runs entirely in your terminal. Frees your GPU when you're done.

![License](https://img.shields.io/badge/license-MIT-3b6ea5)
![Python](https://img.shields.io/badge/python-3.10%2B-3b6ea5)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-informational)
![Cloud](https://img.shields.io/badge/cloud-zero%20dependencies-success)
![Backend](https://img.shields.io/badge/backend-LM%20Studio%20%7C%20Ollama%20%7C%20vLLM-blueviolet)

[**⚡ Install in one command**](#-install-in-one-command) · [**🚀 Usage**](#-usage) · [**🎮 Commands**](#-in-session-slash-commands)

</div>

```text
┌───────────────────────────────────────────────────┐
│          ✦ milo   offline coding agent             │
│   /\_/\                                             │
│  ( o.o )       folder  my-project                  │
│   > ^ <      endpoint  http://localhost:1234       │
│             approvals  confirm · asks before edits │
└───────────────────────────────────────────────────┘
  /help for commands · type a task · 'exit' to quit

▸ my-project  refactor the auth module and add tests

  📖 read_file  src/auth.py
  ✏️  replace_file_content  src/auth.py
  ⚡ run_command  pytest -q

● milo
  Done — extracted the token check into `verify_token()` and
  added 4 tests. All green ✓
```

**milo** is a high-performance, offline autonomous coding agent for local LLM inference engines
(**LM Studio**, **Ollama**, **vLLM**). It runs on **Windows, macOS (Apple Silicon), and Linux** with
**zero cloud dependencies** — perfect for airplanes, remote travel, or any environment with no quota
or internet. Launch `milo` in any folder and it brings up your model, drops you into an agentic REPL,
and **releases your GPU automatically on exit**.

---

## ✨ Highlights

- 🚀 **One command, anywhere** — `milo` auto-starts the server, loads the model, and targets your current directory.
- 🔌 **100% offline** — talks only to your local OpenAI-compatible endpoint; no data ever leaves your machine.
- 🧠 **Model-agnostic** — auto-detects whatever model you've loaded (Gemma, Qwen Coder, DeepSeek, …).
- 🛡️ **Safe by default** — path jail, a destructive-command blocklist (incl. Windows commands), and `[y/n/always]` approvals.
- 🎨 **Beautiful TUI** — markdown answers, a thinking spinner, and syntax-highlighted edit/approval panels.
- 🔋 **GPU-friendly** — unloads the model and stops the server when you quit, so nothing idles on your GPU.
- 🖥️ **Truly cross-platform** — Windows shell commands route through Git Bash; UTF-8 output everywhere.

---

## ⚡ Install in one command

**Windows** (PowerShell):

```powershell
irm https://raw.githubusercontent.com/AnseedX/milo/main/install.ps1 | iex
```

**macOS / Linux**:

```bash
curl -fsSL https://raw.githubusercontent.com/AnseedX/milo/main/install.sh | bash
```

The installer sets up prerequisites (Git, Python), clones milo, installs its Python
dependencies, and puts `milo` on your **PATH** — so you can run it from *any* terminal.
**Open a new terminal afterward** so it picks up the PATH change.

> The one remaining prerequisite is [**LM Studio**](https://lmstudio.ai) with a model downloaded
> (e.g. `google/gemma-4-e4b`). The installer tells you if it's missing. milo starts the server and
> loads the model for you.

## 🚀 Usage

From **any** project directory:

```bash
milo                                  # interactive REPL in the current folder
milo "add unit tests to main.py"      # one-shot autonomous task
```

Every time you run it, `milo` will:
1. Start the LM Studio local server if it isn't running
2. Load the model into the GPU if it isn't already loaded
3. Launch the harness against your **current directory**
4. **Unload the model and stop the server on exit** — so your GPU isn't held while idle

Override the model with an environment variable:

```bash
# Windows (PowerShell):  $env:MILO_MODEL = "qwen/qwen2.5-coder-7b"
# macOS/Linux:           export MILO_MODEL="qwen/qwen2.5-coder-7b"
```

---

## 🌟 Universal Model Compatibility

While originally engineered for **Google Gemma 4**, the harness dynamically auto-detects and binds to **any active model** hosted on your local OpenAI-compatible endpoint (`/v1/models`):

| Model Family | Recommended Quantization | Memory (RAM) | Context Window | Best For |
| :--- | :--- | :--- | :--- | :--- |
| **Gemma 4 12B** | QAT / GGUF Q4_K_M | ~7.15 GB | **262,144 tokens** (256k) | Lightweight, massive context, all-day battery |
| **Qwen 2.5 Coder 14B** | GGUF Q4_K_M / Q8_0 | ~9.0 GB | **32,768 tokens** (32k) | State-of-the-art coding, precise AST refactoring |
| **Gemma 4 26B (MoE A4B)** | GGUF Q4_K_M | ~14.0 GB | **16k - 32k tokens** | High parameter density with 4-expert speed |
| **Qwen 2.5 Coder 32B** | GGUF Q4_K_M | ~19.5 GB | **8k - 16k tokens** | Frontier coding reasoning on 24GB+ Macs |
| **DeepSeek Coder V2 Lite** | GGUF Q4_K_M | ~11.0 GB | **32k - 64k tokens** | Multi-file architectural reasoning |

> [!TIP]
> You can switch models anytime inside LM Studio—the CLI automatically detects the new model on startup without needing to restart flags or update configuration files.

---

## 🏛️ System Architecture

```
                          ┌────────────────────────────┐
                          │    User CLI / REPL (Go)    │
                          │   or Python (agent.py)     │
                          └─────────────┬──────────────┘
                                        │
                         Shallow Tree (~150 tokens)
                         & Compact System Prompt
                                        │
                                        ▼
                          ┌────────────────────────────┐
                          │    Local Inference Server  │
                          │   (LM Studio / Port 1234)  │
                          │  (Gemma 4, Qwen, DeepSeek) │
                          └─────────────┬──────────────┘
                                        │
                        Tool Calls (Dual-Mode Unmarshal)
                                        │
                                        ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │                       Multi-Layer Safety Engine                        │
   │                                                                        │
   │  🔒 Layer 1 Sandbox: Strict Path Jail (Blocks ../ or out-of-repo paths)│
   │  🛡️ Layer 2 Interceptor: Regex Blocklist (Blocks rm -rf /, sudo, dd)   │
   │  🚦 Layer 3 Gating: Interactive Approvals ([y/n/always] on bash/write) │
   └───────────────────────────────────┬────────────────────────────────────┘
                                       │
                                       ▼
                     ┌───────────────────────────────────┐
                     │     Target Project Repository     │
                     │  (read, write, test, git commit)  │
                     └───────────────────────────────────┘
```

---

## 🚀 Key Features

1. **Dual Implementation**:
   - **Go Native Binary (`gemma`)**: Standalone, compiled binary with zero runtime dependencies. Sub-millisecond startup, native JSON streaming, and ad-hoc code-signed for macOS Gatekeeper.
   - **Python Harness (`agent.py`)**: Hackable, extensible engine built with `httpx` and `pydantic`.
2. **Context-Optimized Shallow Repo Tree**:
   - Rather than overwhelming the model's context window with thousands of tokens of deep AST symbols, the harness generates a **shallow depth-1/2 directory overview (~150 tokens)**.
   - The model discovers files, code blocks, and symbols autonomously on-demand using `list_dir`, `read_file`, and `grep_search`.
3. **Dual-Mode Argument Unmarshaling**:
   - Automatically parses both standard JSON object parameters and JSON-escaped string arguments (OpenAI tool calling specification).
4. **On-Demand Offline Skill Engine**:
   - Discovers all local Antigravity and team skills from `~/.gemini/skills/` and `~/.gemini/config/skills/`.
   - Skills are **not** injected into the system prompt by default, keeping context runway completely clean.
   - Explicitly inject skills on-demand during chat using `/skill <name>` (e.g. `/skill hld-lld`, `/skill dead-code-pruner`).
5. **Interactive Safety Sandboxing (`-confirm`)**:
   - Safe read-only discovery (`read_file`, `list_dir`, `grep_search`) executes without interruptions.
   - Destructive operations (`write_file`, `replace_file_content`, `run_command`) prompt for approval (`[y/n/always]`) before execution.
6. **Multi-Repo Targeting (`-repo`)**:
   - Point the harness at any codebase on your computer:
     ```bash
     gemma -repo /path/to/any/project -confirm
     ```
7. **Autonomous Git Integration**:
   - Auto-detects modified files, generates structured Conventional Commits, and offers a 1-second `/undo` rollback command.

---

## 📦 Quickstart & Installation

### Option 1: Native Go Binary (Recommended)

The compiled `gemma` binary is already built and placed in your system PATH (`/usr/local/bin/gemma` and `~/.lmstudio/bin/gemma`):

```bash
# Verify installation
gemma -help

# Launch in your current working directory with interactive confirmation
gemma -confirm

# Launch against a specific target repository
gemma -repo /path/to/any/project -confirm

# Run a one-shot autonomous task
gemma -repo /path/to/project "Inspect main.go and add unit tests"
```

To recompile from source:
```bash
cd gemma-go
go test -v ./...
go build -o /usr/local/bin/gemma .
codesign -s - --force /usr/local/bin/gemma
```

---

### Option 2: Python Engine (`agent.py`) directly

If you'd rather not use the `milo` launcher, run the harness directly (you'll manage the LM Studio server yourself).

**macOS / Linux:**
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install httpx openai rich

python3 agent.py --confirm                       # current directory
python3 agent.py --repo /path/to/project --confirm
```

**Windows (PowerShell):**
```powershell
py -m venv .venv; .\.venv\Scripts\Activate.ps1
py -m pip install httpx openai rich

py agent.py --confirm                            # current directory
py agent.py --repo C:\path\to\project --confirm
```

> On Windows, shell commands issued by the model are routed through **Git Bash** automatically (install [Git for Windows](https://git-scm.com/download/win)), so Unix-style commands behave the same as on macOS/Linux.

---

## 🎮 In-Session Slash Commands

| Command | Description | Example |
| :--- | :--- | :--- |
| `/skills` | Browse all offline skills indexed from your machine | `/skills` |
| `/skill <name>` | Inject specific domain rules into context | `/skill hld-lld` |
| `/confirm` | Toggle interactive approval mode on or off | `/confirm off` |
| `/map` | Print the shallow directory overview | `/map` |
| `/diff` | View active git diff of modifications | `/diff` |
| `/commit <msg>`| Manually commit all changes with message | `/commit feat: update parser` |
| `/undo` | Rollback the last commit created by the agent | `/undo` |
| `!<cmd>` | Execute a raw shell command directly | `!pytest -v` |
| `exit` | Quit the harness | `exit` |

---

## 🛠️ Offline Tool Inventory

The agent autonomously uses the following sandboxed tools:

- **`read_file(path, start_line, end_line)`**: Read code with line-numbered output. Rejects directory paths with actionable guidance.
- **`replace_file_content(path, target_content, replacement_content)`**: Surgical, exact block replacement without rewriting untouched code.
- **`write_file(path, content)`**: Author or rewrite complete files (automatically creates missing directories).
- **`run_command(command)`**: Execute shell commands, test runners, build pipelines, and formatters.
- **`list_dir(path)`**: List directories with file count and metadata.
- **`grep_search(query, path)`**: High-speed search for symbols, regex patterns, or function definitions across the project.

---

## 🛫 Setup LM Studio for Flight Mode

1. **Install LM Studio**:
   ```bash
   # macOS
   brew install --cask lm-studio
   # Windows
   winget install ElementLabs.LMStudio
   # Linux: download the AppImage from https://lmstudio.ai
   ```
2. **Download a model** (any works — milo auto-detects it):
   - Balanced & GPU-friendly: `google/gemma-4-e4b`
   - Max coding accuracy: `Qwen/Qwen2.5-Coder-7B-Instruct-GGUF` (Q4_K_M)
   - Bigger reasoning: `Qwen/Qwen2.5-Coder-14B-Instruct-GGUF` (Q4_K_M)
3. **Let `milo` handle the rest** — it starts the server (port `1234`) and loads the model for you.
   (Or start it manually from LM Studio's **Developer** tab.)
4. **Disconnect Wi-Fi and code anywhere.** ✈️

---

## 🤝 Contributing

Issues and PRs are welcome! Whether it's a new tool, a backend adapter, or a UI tweak — open an issue to
discuss, or send a pull request.

## 📄 License

Released under the [MIT License](LICENSE) — free to use, modify, and distribute.

<div align="center">
<sub>Named after a very good black cat. 🐈‍⬛</sub>
</div>
