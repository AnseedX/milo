#!/usr/bin/env python3
"""
agent.py - Offline Autonomous AI Coding Agent for Gemma 4 on LM Studio
Features:
- Multi-language AST & regex repository map (Python, TS/JS, Go, Rust, Bash, etc.)
- Autonomous tool execution (file read, file write, block patch, shell command execution)
- Multi-repo support (--repo flag to target any project on the machine)
- Structured Conventional Git commits for every change + /undo rollback
- Zero cloud dependencies, 100% offline for airplane mode.
"""

import os
import sys
import re
import ast
import json
import time
import shutil
import argparse
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional

import httpx

# Windows consoles default to a legacy code page (e.g. cp1252) that cannot encode
# the emoji this harness prints, which would crash on the first tool output.
# Force UTF-8 on stdout/stderr so it behaves like a macOS/Linux terminal.
if os.name == "nt":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

try:
    import readline
    HISTFILE = Path.home() / ".gemma_agent_history"
    if HISTFILE.exists():
        try:
            readline.read_history_file(str(HISTFILE))
        except Exception:
            pass
    import atexit
    atexit.register(lambda: readline.write_history_file(str(HISTFILE)) if HISTFILE else None)
except (ImportError, OSError):
    pass

DEFAULT_HOST = os.environ.get("LM_STUDIO_URL", "http://localhost:1234")


def _find_bash() -> Optional[str]:
    """Locate a POSIX bash (Git Bash) on Windows.

    The model emits Unix-style shell commands (ls, cat, grep, rm, &&-chaining).
    On Windows the default `shell=True` runs cmd.exe, which does not understand
    those. Routing through Git Bash makes command execution behave the same as
    on macOS/Linux. Returns None on POSIX (native shell is already correct) or
    if no bash is found on Windows.
    """
    if os.name != "nt":
        return None
    # Honor an explicit override first, then anything already on PATH.
    override = os.environ.get("GEMMA_BASH_PATH")
    if override and Path(override).exists():
        return override
    found = shutil.which("bash")
    if found:
        return found
    # Common Git for Windows install locations.
    candidates = [
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\bin\bash.exe"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None


# Resolved once at startup; None means "use the platform's native shell".
BASH_PATH = _find_bash()

# ==============================================================================
# UI Layer — rich-based pretty terminal output (Claude-style), plain fallback
# ==============================================================================
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.markdown import Markdown
    from rich.syntax import Syntax
    from rich.text import Text
    from rich.table import Table
    from rich.box import ROUNDED
    console = Console()
    _RICH = True
except Exception:
    console = None
    _RICH = False

# Accent palette
C_ACCENT = "#3b6ea5"   # navy blue
C_DIM = "grey50"
C_OK = "green"
C_WARN = "yellow"
C_ERR = "red3"
C_TOOL = "cyan"

# A little black cat to greet you at launch 🐈‍⬛
CAT_ART = r"""
 /\_/\
( o.o )
 > ^ <
""".strip("\n")

# Per-tool glyph + how to summarize its args in one line
_TOOL_ICONS = {
    "read_file": "📖", "write_file": "✍️", "replace_file_content": "✏️",
    "run_command": "⚡", "list_dir": "📂", "grep_search": "🔍", "load_skill": "📚",
}


def _ext_of(path: str) -> str:
    return (Path(path).suffix.lstrip(".") or "text")


def ui_notify(msg: str, style: str = None, prefix: str = ""):
    """Single styled status line (falls back to plain print)."""
    if _RICH:
        console.print(f"{prefix}{msg}", style=style)
    else:
        print(f"{prefix}{msg}")


def render_banner(model_id: str, endpoint: str, repo: str, confirm: bool):
    if not _RICH:
        print("=" * 65)
        for line in CAT_ART.splitlines():
            print("   " + line)
        print("milo — local offline coding agent")
        print(f"  folder:    {repo}")
        print(f"  endpoint:  {endpoint}")
        print(f"  approvals: {'confirm' if confirm else 'auto'}")
        print("Commands: /map /skills /diff /commit /undo /confirm !<cmd> exit")
        print("=" * 65 + "\n")
        return
    mode = "[green]confirm[/] · asks before edits" if confirm else "[yellow]auto[/] · no prompts"

    # right-hand info column
    info = Table.grid(padding=(0, 2))
    info.add_column(style=C_DIM, justify="right")
    info.add_column()
    info.add_row("folder", repo)
    info.add_row("endpoint", endpoint)
    info.add_row("approvals", mode)

    # cat on the left, title + info on the right
    header = Table.grid(padding=(0, 3))
    header.add_column(justify="center", vertical="middle")
    header.add_column()
    cat = Text(CAT_ART, style=f"bold {C_ACCENT}")
    right = Table.grid()
    right.add_column()
    right.add_row(f"[bold {C_ACCENT}]✦ milo[/]  [dim]offline coding agent[/]")
    right.add_row("")
    right.add_row(info)
    header.add_row(cat, right)

    console.print(Panel(
        header,
        border_style=C_ACCENT, box=ROUNDED, padding=(1, 2),
    ))
    console.print("[dim]  /help for commands · type a task · 'exit' to quit[/]\n")


def render_agent(text: str):
    text = (text or "").strip()
    if not text:
        return
    if _RICH:
        console.print(f"\n[bold {C_ACCENT}]●[/] [bold]milo[/]")
        console.print(Markdown(text))
        console.print()
    else:
        print(f"\nmilo:\n{text}\n")


def render_tool(name: str, args: Dict[str, Any]):
    icon = _TOOL_ICONS.get(name, "⚙")
    if name == "run_command":
        summary = args.get("command", "")
    elif name in ("read_file", "write_file", "replace_file_content", "list_dir"):
        summary = args.get("path", "")
    elif name == "grep_search":
        summary = f'"{args.get("query", "")}"' + (f' in {args.get("path")}' if args.get("path") else "")
    elif name == "load_skill":
        summary = args.get("skill_name", "")
    else:
        summary = json.dumps(args, ensure_ascii=False)[:80]
    if _RICH:
        console.print(f"  [dim]{icon}[/] [{C_TOOL}]{name}[/] [dim]{summary}[/]")
    else:
        print(f"  {icon} {name} {summary}")


def render_permission(name: str, args: Dict[str, Any], repo: str) -> str:
    """Render an approval request panel; returns the user's raw input."""
    if not _RICH:
        print("\n" + "=" * 65)
        print(f"🔒 PERMISSION REQUIRED: {name}")
        if name == "run_command":
            print(f"  $ {args.get('command','')}")
        elif name == "write_file":
            print(f"  write {args.get('path','')}")
        elif name == "replace_file_content":
            print(f"  edit {args.get('path','')}")
        print("=" * 65)
        try:
            return input("Approve? [y/n/always] (or type feedback): ").strip()
        except (KeyboardInterrupt, EOFError):
            return "n"

    if name == "run_command":
        body = Syntax(args.get("command", ""), "bash", theme="ansi_dark", word_wrap=True)
        subtitle = f"[dim]in {repo}[/]"
    elif name == "write_file":
        path = args.get("path", "")
        content = args.get("content", "")
        preview = "\n".join(content.splitlines()[:20])
        if len(content.splitlines()) > 20:
            preview += "\n…"
        body = Syntax(preview, _ext_of(path), theme="ansi_dark", line_numbers=True, word_wrap=True)
        subtitle = f"[dim]{path} · {len(content.splitlines())} lines[/]"
    elif name == "replace_file_content":
        path = args.get("path", "")
        diff = Text()
        for line in args.get("target_content", "").splitlines():
            diff.append(f"- {line}\n", style="red")
        for line in args.get("replacement_content", "").splitlines():
            diff.append(f"+ {line}\n", style="green")
        body = diff
        subtitle = f"[dim]{path}[/]"
    else:
        body = Text(json.dumps(args, ensure_ascii=False, indent=2))
        subtitle = ""

    console.print(Panel(
        body,
        title=f"[bold {C_WARN}]🔒 permission required[/] · [{C_TOOL}]{name}[/]",
        subtitle=subtitle, title_align="left", subtitle_align="right",
        border_style=C_WARN, box=ROUNDED, padding=(1, 2),
    ))
    try:
        return console.input(f"  [bold]approve?[/] [dim][y/n/always, or type feedback][/] ").strip()
    except (KeyboardInterrupt, EOFError):
        return "n"

# ==============================================================================
# 1. Multi-Language Repository Mapping Engine
# ==============================================================================

IGNORE_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build",
    "target", ".idea", ".vscode", ".next", ".cache", ".pytest_cache", "coverage"
}

IGNORE_EXTENSIONS = {
    ".pyc", ".pyo", ".pyd", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".pdf", ".mp4", ".mp3", ".wav",
    ".ttf", ".woff", ".woff2", ".eot", ".lock", ".DS_Store"
}

class RepoMap:
    def __init__(self, root_dir: str, max_files: int = 25):
        self.root = Path(root_dir).resolve()
        self.max_files = max_files

    def _should_ignore(self, path: Path) -> bool:
        for part in path.parts:
            if part in IGNORE_DIRS:
                return True
        if path.suffix.lower() in IGNORE_EXTENSIONS:
            return True
        return False

    def _extract_python_symbols(self, content: str) -> List[str]:
        symbols = []
        try:
            tree = ast.parse(content)
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    methods = [n.name for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                    method_str = f"({', '.join(methods[:5])})" if methods else ""
                    symbols.append(f"class {node.name}{method_str}")
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbols.append(f"def {node.name}()")
        except Exception:
            pass
        return symbols

    def _extract_ts_js_symbols(self, content: str) -> List[str]:
        symbols = []
        patterns = [
            r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)",
            r"^(?:export\s+)?(?:const|let|var)\s+([A-Za-z0-9_]+)\s*=\s*(?:async\s*)?\([^)]*\)\s*=>",
            r"^(?:export\s+)?class\s+([A-Za-z0-9_]+)",
            r"^(?:export\s+)?interface\s+([A-Za-z0-9_]+)",
            r"^(?:export\s+)?type\s+([A-Za-z0-9_]+)\s*="
        ]
        for line in content.splitlines():
            line_s = line.strip()
            for pat in patterns:
                m = re.match(pat, line_s)
                if m:
                    symbols.append(m.group(0)[:60])
                    break
            if len(symbols) >= 10:
                break
        return symbols

    def _extract_go_symbols(self, content: str) -> List[str]:
        symbols = []
        patterns = [
            r"^type\s+([A-Za-z0-9_]+)\s+(?:struct|interface)",
            r"^func\s+(?:\([^)]+\)\s+)?([A-Za-z0-9_]+)\("
        ]
        for line in content.splitlines():
            line_s = line.strip()
            for pat in patterns:
                m = re.match(pat, line_s)
                if m:
                    symbols.append(m.group(0)[:60])
                    break
            if len(symbols) >= 10:
                break
        return symbols

    def _extract_rust_symbols(self, content: str) -> List[str]:
        symbols = []
        patterns = [
            r"^(?:pub\s+)?(?:async\s+)?fn\s+([A-Za-z0-9_]+)",
            r"^(?:pub\s+)?struct\s+([A-Za-z0-9_]+)",
            r"^(?:pub\s+)?enum\s+([A-Za-z0-9_]+)",
            r"^(?:pub\s+)?trait\s+([A-Za-z0-9_]+)"
        ]
        for line in content.splitlines():
            line_s = line.strip()
            for pat in patterns:
                m = re.match(pat, line_s)
                if m:
                    symbols.append(m.group(0)[:60])
                    break
            if len(symbols) >= 10:
                break
        return symbols

    def _extract_bash_symbols(self, content: str) -> List[str]:
        symbols = []
        patterns = [
            r"^function\s+([A-Za-z0-9_-]+)",
            r"^([A-Za-z0-9_-]+)\s*\(\)\s*\{"
        ]
        for line in content.splitlines():
            line_s = line.strip()
            for pat in patterns:
                m = re.match(pat, line_s)
                if m:
                    symbols.append(f"{m.group(1)}()")
                    break
        return symbols

    def generate_map(self) -> str:
        lines = [f"Repository Map: {self.root.name}/"]
        file_count = 0

        for path in sorted(self.root.rglob("*")):
            if file_count >= self.max_files:
                lines.append("... [more files truncated]")
                break
            if path.is_file() and not self._should_ignore(path):
                file_count += 1
                rel_path = path.relative_to(self.root)
                ext = path.suffix.lower()

                try:
                    content = path.read_text(encoding="utf-8", errors="ignore")
                    symbols = []
                    if ext == ".py":
                        symbols = self._extract_python_symbols(content)
                    elif ext in (".ts", ".tsx", ".js", ".jsx"):
                        symbols = self._extract_ts_js_symbols(content)
                    elif ext == ".go":
                        symbols = self._extract_go_symbols(content)
                    elif ext == ".rs":
                        symbols = self._extract_rust_symbols(content)
                    elif ext in (".sh", ".bash", ".zsh"):
                        symbols = self._extract_bash_symbols(content)

                    if symbols:
                        lines.append(f"  {rel_path}:")
                        for s in symbols[:6]:
                            lines.append(f"    - {s}")
                    else:
                        lines.append(f"  {rel_path} ({len(content.splitlines())} lines)")
                except Exception:
                    lines.append(f"  {rel_path}")

        return "\n".join(lines)

    def generate_shallow_tree(self, max_items: int = 25) -> str:
        """Generates a shallow depth=1/2 tree for ultra-low token consumption."""
        lines = [f"{self.root.name}/"]
        items = []
        try:
            for entry in sorted(self.root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if entry.name.startswith(".") or entry.name in IGNORE_DIRS:
                    continue
                if entry.is_dir():
                    items.append(f"  📁 {entry.name}/")
                    try:
                        sub_entries = [sub for sub in entry.iterdir() if not sub.name.startswith(".") and sub.name not in IGNORE_DIRS][:3]
                        for sub in sub_entries:
                            icon = "📁 " if sub.is_dir() else "📄 "
                            items.append(f"    {icon}{sub.name}")
                    except Exception:
                        pass
                else:
                    if entry.suffix.lower() not in IGNORE_EXTENSIONS:
                        items.append(f"  📄 {entry.name}")
                if len(items) >= max_items:
                    items.append("  ... (explore more with list_dir)")
                    break
        except Exception as e:
            items.append(f"  (error listing tree: {e})")
        lines.extend(items)
        return "\n".join(lines)

# ==============================================================================
# 2. Local Skill Management Engine
# ==============================================================================

class SkillManager:
    def __init__(self, extra_dirs: Optional[List[Path]] = None):
        home = Path.home()
        self.search_paths = [
            home / ".gemini/skills",
            home / ".gemini/config/skills",
            home / ".gemini/config/plugins",
            home / ".gemini/antigravity-cli/builtin/skills"
        ]
        if extra_dirs:
            self.search_paths.extend(extra_dirs)
        self.skills: Dict[str, Dict[str, Any]] = {}
        self.discover_skills()

    def discover_skills(self):
        for base in self.search_paths:
            if not base.exists():
                continue
            for root, _, files in os.walk(str(base), followlinks=True):
                for f in files:
                    if f.lower() == "skill.md":
                        skill_file = Path(root) / f
                        try:
                            content = skill_file.read_text(encoding="utf-8", errors="ignore")
                            name = skill_file.parent.name
                            desc = ""
                            if content.startswith("---"):
                                parts = content.split("---", 2)
                                if len(parts) >= 3:
                                    fm = parts[1]
                                    for line in fm.splitlines():
                                        line_s = line.strip()
                                        if line_s.startswith("name:"):
                                            name = line_s.split(":", 1)[1].strip().strip('"').strip("'")
                                        elif line_s.startswith("description:"):
                                            desc = line_s.split(":", 1)[1].strip().strip('"').strip("'")
                            if not desc:
                                for line in content.splitlines():
                                    if line.startswith("# "):
                                        desc = line[2:].strip()
                                        break
                            self.skills[name.lower()] = {
                                "name": name,
                                "description": desc or "No description provided.",
                                "path": skill_file
                            }
                        except Exception:
                            continue

    def get_catalog(self, max_items: int = 40) -> str:
        if not self.skills:
            return "(No local skills found)"
        lines = []
        for name in sorted(self.skills.keys())[:max_items]:
            item = self.skills[name]
            first_line = item["description"].splitlines()[0][:100]
            lines.append(f"- {item['name']}: {first_line}")
        if len(self.skills) > max_items:
            lines.append(f"... and {len(self.skills) - max_items} more skills (type /skills to view all)")
        return "\n".join(lines)

    def load_skill_content(self, skill_name: str) -> Optional[str]:
        key = skill_name.strip().lower()
        if key in self.skills:
            return self.skills[key]["path"].read_text(encoding="utf-8", errors="replace")
        for k, v in self.skills.items():
            if key == k or key in k or k in key:
                return v["path"].read_text(encoding="utf-8", errors="replace")
        return None

DANGEROUS_COMMAND_PATTERNS = [
    (r"\brm\s+-[rfRF]{1,4}\s+([/~]|\$HOME|\.\.?/?)(\s|$)", "Broad root or home directory recursive deletion"),
    (r"\brm\s+-[rfRF]{1,4}\s+\*(\s|$)", "Unscoped wildcard recursive deletion"),
    (r"\b(sudo|su|doas)\b", "Privilege escalation"),
    (r"\b(mkfs|diskutil\s+(erase|partition)|dd\s+if=)\b", "Raw disk modification or volume formatting"),
    (r"\b(shutdown|reboot|halt|init\s+0)\b", "System power manipulation or reboot"),
    (r":\(\)\s*\{\s*:\|:&\s*\};:", "Fork bomb injection"),
    (r"\bchmod\s+-[rR]\s+777\s+([/~]|\$HOME)(\s|$)", "Broad recursive permission wiping"),
    # --- Windows: cmd.exe / PowerShell destructive commands (case-insensitive) ---
    (r"(?i)\b(del|erase)\b.*\s(/s|/q)\b", "Windows recursive/quiet file deletion (del /s /q)"),
    (r"(?i)\b(rmdir|rd)\b.*\s/s\b", "Windows recursive directory deletion (rmdir /s)"),
    (r"(?i)\bformat\s+[a-z]:", "Windows volume format"),
    (r"(?i)\bRemove-Item\b.*-(Recurse|r)\b.*-(Force|f)\b", "PowerShell recursive force deletion (Remove-Item -Recurse -Force)"),
    (r"(?i)\b(Stop-Computer|Restart-Computer)\b", "Windows power manipulation (PowerShell)"),
    (r"(?i)\bcmd\b.*\s/c\b.*\b(del|rmdir|rd|format)\b", "Windows destructive command via cmd /c"),
]

# ==============================================================================
# 3. Tool Execution Engine
# ==============================================================================

class ToolKit:
    def __init__(self, repo_dir: str):
        self.repo = Path(repo_dir).resolve()
        self.modified_files = set()

    def _resolve(self, file_path: str) -> Path:
        if not file_path or not str(file_path).strip():
            raise ValueError("File path cannot be empty.")
        p = Path(str(file_path).strip())
        if not p.is_absolute():
            resolved = (self.repo / p).resolve()
        else:
            resolved = p.resolve()

        # 🔒 Layer 1 Sandbox: Strict Path Traversal Jail
        try:
            resolved.relative_to(self.repo)
        except ValueError:
            raise PermissionError(
                f"Security Violation (Layer 1 Sandbox): Access to '{file_path}' denied. "
                f"Paths must stay strictly inside the project repository ({self.repo})."
            )
        return resolved

    def read_file(self, path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
        try:
            target = self._resolve(path)
        except (PermissionError, ValueError) as err:
            return f"❌ {err}"
        if not target.exists():
            return f"❌ Error: File '{path}' does not exist."
        if target.is_dir():
            return f"❌ Error: '{path}' is a directory, not a file. Use 'list_dir' to inspect directories."
        try:
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            total = len(lines)
            s = max(1, start_line or 1)
            e = min(total, end_line or total)
            output = []
            for i in range(s, e + 1):
                output.append(f"{i:4d}: {lines[i - 1]}")
            return "\n".join(output)
        except Exception as e:
            return f"❌ Error reading '{path}': {e}"

    def write_file(self, path: str, content: str) -> str:
        try:
            target = self._resolve(path)
        except PermissionError as pe:
            return f"❌ {pe}"
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            self.modified_files.add(str(target))
            return f"✅ Successfully wrote {len(content.splitlines())} lines to '{path}'."
        except Exception as e:
            return f"❌ Error writing to '{path}': {e}"

    def replace_file_content(self, path: str, target_content: str, replacement_content: str) -> str:
        try:
            target = self._resolve(path)
        except PermissionError as pe:
            return f"❌ {pe}"
        if not target.exists():
            return f"❌ Error: File '{path}' does not exist."
        try:
            original = target.read_text(encoding="utf-8")
            if target_content not in original:
                return f"❌ Error: Target content not found in '{path}'. Please ensure exact match including whitespace."
            count = original.count(target_content)
            if count > 1:
                return f"❌ Error: Target content matches {count} occurrences in '{path}'. Provide more surrounding context."
            new_text = original.replace(target_content, replacement_content, 1)
            target.write_text(new_text, encoding="utf-8")
            self.modified_files.add(str(target))
            return f"✅ Successfully updated '{path}'."
        except Exception as e:
            return f"❌ Error replacing content in '{path}': {e}"

    def run_command(self, command: str, timeout: int = 60) -> str:
        # 🛡️ Layer 2 Sandbox: Destructive Bash Deny-List & Guardrails
        for pattern, reason in DANGEROUS_COMMAND_PATTERNS:
            if re.search(pattern, command):
                msg = (
                    f"Security Violation (Layer 2 Sandbox): Command blocked by safety guardrail ({reason}).\n"
                    f"Command: '{command}'\n"
                    f"If you intentionally want to run this, execute it directly in the REPL using '!<cmd>'."
                )
                print(f"\n🚫 {msg}")
                return f"❌ {msg}"

        shell_label = "Git Bash" if BASH_PATH else "bash"
        print(f"\n⚡ Executing {shell_label}: {command}")
        try:
            if BASH_PATH:
                # Windows: run through Git Bash so Unix commands behave like macOS/Linux.
                run_kwargs = dict(args=[BASH_PATH, "-c", command], shell=False)
            else:
                # POSIX: the native shell is already bash/sh-compatible.
                run_kwargs = dict(args=command, shell=True)
            proc = subprocess.run(
                cwd=str(self.repo),
                capture_output=True,
                text=True,
                timeout=timeout,
                **run_kwargs
            )
            out = proc.stdout.strip()
            err = proc.stderr.strip()
            result = []
            if out:
                result.append(f"[stdout]\n{out}")
            if err:
                result.append(f"[stderr]\n{err}")
            result.append(f"[Exit code: {proc.returncode}]")
            return "\n".join(result)
        except subprocess.TimeoutExpired:
            return f"❌ Command timed out after {timeout} seconds."
        except Exception as e:
            return f"❌ Execution failed: {e}"

    def list_dir(self, path: str = ".") -> str:
        try:
            target = self._resolve(path)
        except PermissionError as pe:
            return f"❌ {pe}"
        if not target.exists():
            return f"❌ Directory '{path}' not found."
        try:
            entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            items = []
            for item in entries:
                prefix = "📁 " if item.is_dir() else "📄 "
                items.append(f"{prefix}{item.name}")
            return "\n".join(items) if items else "(empty directory)"
        except Exception as e:
            return f"❌ Error listing directory: {e}"

    def grep_search(self, query: str, path: str = ".") -> str:
        try:
            target = self._resolve(path)
        except PermissionError as pe:
            return f"❌ {pe}"
        results = []
        try:
            for p in sorted(target.rglob("*")):
                if p.is_file() and not any(part in IGNORE_DIRS for part in p.parts):
                    try:
                        content = p.read_text(encoding="utf-8", errors="ignore")
                        for idx, line in enumerate(content.splitlines(), 1):
                            if query.lower() in line.lower():
                                rel = p.relative_to(self.repo)
                                results.append(f"{rel}:{idx}: {line.strip()[:100]}")
                                if len(results) >= 30:
                                    break
                    except Exception:
                        continue
                if len(results) >= 30:
                    results.append("... [capped at 30 matches]")
                    break
            return "\n".join(results) if results else f"No matches found for '{query}'."
        except Exception as e:
            return f"❌ Error during grep: {e}"

    def git_diff(self) -> str:
        try:
            out = subprocess.check_output(["git", "diff"], cwd=str(self.repo), text=True).strip()
            return out if out else "(No unstaged changes)"
        except Exception as e:
            return f"Git diff error: {e}"

    def git_commit(self, message: str) -> str:
        try:
            subprocess.check_call(["git", "add", "-A"], cwd=str(self.repo))
            proc = subprocess.run(["git", "commit", "-m", message], cwd=str(self.repo), capture_output=True, text=True)
            if proc.returncode == 0:
                self.modified_files.clear()
                return f"✅ Git Commit Successful:\n{proc.stdout.strip()}"
            else:
                return f"⚠️ Git Commit Warning:\n{proc.stderr.strip()}"
        except Exception as e:
            return f"❌ Git Commit failed: {e}"

    def git_undo(self) -> str:
        try:
            subprocess.check_call(["git", "reset", "--hard", "HEAD~1"], cwd=str(self.repo))
            return "✅ Rolled back last commit (git reset --hard HEAD~1)."
        except Exception as e:
            return f"❌ Git rollback failed: {e}"

# ==============================================================================
# 3. Tool Definitions for OpenAI-compatible schema
# ==============================================================================

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read file contents with line numbers. Use to inspect code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file"},
                    "start_line": {"type": "integer", "description": "Optional start line (1-indexed)"},
                    "end_line": {"type": "integer", "description": "Optional end line (inclusive)"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "replace_file_content",
            "description": "Replace a single contiguous block of text in a file. Exact match required.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file"},
                    "target_content": {"type": "string", "description": "Exact text to find and replace"},
                    "replacement_content": {"type": "string", "description": "Replacement text"}
                },
                "required": ["path", "target_content", "replacement_content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create a new file or overwrite an existing file with complete content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative path to the file"},
                    "content": {"type": "string", "description": "Full file content"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Execute a bash / zsh command in the repository workspace (e.g. pytest, npm test, git).",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "The exact shell command line string to run"}
                },
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List contents of a directory in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory relative path (default: '.')"}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "grep_search",
            "description": "Search across repository files for a regex or string query.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term"},
                    "path": {"type": "string", "description": "Directory to search within"}
                },
                "required": ["query"]
            }
        }
    }
]

# ==============================================================================
# 4. Autonomous Agent Loop
# ==============================================================================

class GemmaAgent:
    def __init__(self, repo_dir: str, base_url: str = DEFAULT_HOST, confirm: bool = False):
        self.repo_dir = repo_dir
        self.base_url = base_url
        self.confirm = confirm
        self.toolkit = ToolKit(repo_dir)
        self.repomap = RepoMap(repo_dir)
        self.skill_manager = SkillManager(extra_dirs=[Path(repo_dir) / "skills", Path(repo_dir) / ".skills"])
        self.model_id = self._detect_model()
        self.messages = []
        self._init_system_prompt()

    def _detect_model(self) -> str:
        try:
            with httpx.Client(timeout=4.0) as client:
                res = client.get(f"{self.base_url}/v1/models")
                if res.status_code == 200:
                    models = res.json().get("data", [])
                    if models:
                        return models[0]["id"]
        except Exception:
            pass
        return "local-model"

    def _init_system_prompt(self):
        shallow_tree = self.repomap.generate_shallow_tree()
        system_content = f"""You are Gemma 4, an autonomous expert coding agent.
Working Directory: {self.repo_dir}

Directory Overview:
```
{shallow_tree}
```

Rules:
1. Inspect files and directories on-demand using `list_dir`, `read_file`, and `grep_search`.
2. Make surgical edits using `replace_file_content` or `write_file`.
3. Run test and verify commands using `run_command`.
4. Be concise and prioritize working, robust code.
"""
        self.messages = [{"role": "system", "content": system_content}]

    def _prompt_user_approval(self, name: str, args: Dict[str, Any]) -> tuple:
        """Prompts user to confirm modifying actions (bash, file write, block patch)."""
        choice = render_permission(name, args, self.repo_dir)

        if not choice or choice.lower() in ("y", "yes"):
            return True, None
        elif choice.lower() in ("a", "always"):
            ui_notify("Auto-approval enabled for the rest of this session.", style=C_OK, prefix="  🔓 ")
            self.confirm = False
            return True, None
        elif choice.lower() in ("n", "no"):
            return False, "User declined action."
        else:
            # User gave specific feedback / instructions
            return False, f"User declined action with note: '{choice}'"

    def _execute_tool_call(self, name: str, args: Dict[str, Any]) -> str:
        render_tool(name, args)

        # Permission gating for mutating or shell execution tools
        if self.confirm and name in ("run_command", "replace_file_content", "write_file"):
            approved, feedback = self._prompt_user_approval(name, args)
            if not approved:
                ui_notify(feedback, style=C_ERR, prefix="  🛑 ")
                return f"❌ Action aborted by user. {feedback}. Please adjust your plan or propose an alternative."

        if name == "read_file":
            return self.toolkit.read_file(args.get("path"), args.get("start_line"), args.get("end_line"))
        elif name == "replace_file_content":
            return self.toolkit.replace_file_content(args.get("path"), args.get("target_content"), args.get("replacement_content"))
        elif name == "write_file":
            return self.toolkit.write_file(args.get("path"), args.get("content"))
        elif name == "run_command":
            return self.toolkit.run_command(args.get("command"))
        elif name == "list_dir":
            return self.toolkit.list_dir(args.get("path", "."))
        elif name == "grep_search":
            return self.toolkit.grep_search(args.get("query"), args.get("path", "."))
        elif name == "load_skill":
            skill_name = args.get("skill_name", "")
            content = self.skill_manager.load_skill_content(skill_name)
            if content:
                print(f"📖 Skill '{skill_name}' activated and loaded into context.")
                return f"✅ Loaded skill '{skill_name}':\n\n{content}"
            return f"❌ Skill '{skill_name}' not found. Check available skills using /skills."
        return f"Unknown tool: {name}"

    def auto_commit_changes(self):
        """Generates a conventional commit message from diff and commits."""
        diff = self.toolkit.git_diff()
        if not diff or diff == "(No unstaged changes)":
            return

        print("\n📦 Generating structured Git commit for changes...")
        commit_prompt = f"Write a single concise Conventional Commit message (e.g. 'feat(auth): add login', 'fix(cli): resolve path') for this diff:\n\n{diff[:1500]}"
        payload = {
            "model": self.model_id,
            "messages": [
                {"role": "system", "content": "You generate concise Conventional Commit messages. Reply with ONLY the commit message."},
                {"role": "user", "content": commit_prompt}
            ],
            "temperature": 0.2
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                res = client.post(f"{self.base_url}/v1/chat/completions", json=payload)
                if res.status_code == 200:
                    msg = res.json()["choices"][0]["message"]["content"].strip().strip('"').strip("'")
                    first_line = msg.splitlines()[0]
                    commit_res = self.toolkit.git_commit(first_line)
                    print(commit_res)
        except Exception as e:
            print(f"⚠️ Auto-commit generation failed: {e}")

    def run_turn(self, user_prompt: str, max_steps: int = 10):
        self.messages.append({"role": "user", "content": user_prompt})

        for step in range(1, max_steps + 1):
            payload = {
                "model": self.model_id,
                "messages": self.messages,
                "tools": TOOL_DEFINITIONS,
                "tool_choice": "auto",
                "temperature": 0.4
            }

            try:
                with httpx.Client(timeout=240.0) as client:
                    if _RICH:
                        with console.status(f"[{C_ACCENT}]milo is thinking…[/]", spinner="dots"):
                            resp = client.post(f"{self.base_url}/v1/chat/completions", json=payload)
                    else:
                        print("… thinking")
                        resp = client.post(f"{self.base_url}/v1/chat/completions", json=payload)
                    resp.raise_for_status()
                    data = resp.json()
                    choice = data["choices"][0]
                    message = choice["message"]
                    self.messages.append(message)

                    # Check for tool calls
                    tool_calls = message.get("tool_calls", [])
                    if tool_calls:
                        for tool in tool_calls:
                            func = tool.get("function", {})
                            name = func.get("name")
                            raw_args = func.get("arguments", "{}")
                            if isinstance(raw_args, str):
                                try:
                                    args = json.loads(raw_args)
                                except Exception:
                                    args = {}
                            elif isinstance(raw_args, dict):
                                args = raw_args
                            else:
                                args = {}

                            tool_output = self._execute_tool_call(name, args)
                            self.messages.append({
                                "role": "tool",
                                "tool_call_id": tool.get("id", f"call_{int(time.time())}"),
                                "name": name,
                                "content": tool_output
                            })
                        continue # Continue loop with tool results

                    # If model returned text output and finished
                    content = message.get("content", "")
                    if content:
                        render_agent(content)
                    break

            except httpx.ConnectError:
                ui_notify(f"LM Studio is not reachable at {self.base_url}.", style=C_ERR, prefix="  ❌ ")
                ui_notify("Start the server:  lms server start", style=C_DIM, prefix="  👉 ")
                return
            except Exception as e:
                ui_notify(f"Error during agent step {step}: {e}", style=C_ERR, prefix="  ❌ ")
                return

        # Auto-commit if files were modified
        if self.toolkit.modified_files:
            self.auto_commit_changes()

# ==============================================================================
# 5. CLI REPL Interface
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(description="Gemma 4 Autonomous Offline Coding Agent.")
    parser.add_argument("task", nargs="?", default=None, help="Optional single prompt to execute autonomously.")
    parser.add_argument("--repo", default=".", help="Target repository directory (default: current directory)")
    parser.add_argument("--url", default=DEFAULT_HOST, help=f"LM Studio local API host (default: {DEFAULT_HOST})")
    parser.add_argument("--confirm", action="store_true", help="Prompt for approval [y/n] before executing bash commands or modifying files.")
    args = parser.parse_args()

    target_repo = str(Path(args.repo).resolve())
    agent = GemmaAgent(repo_dir=target_repo, base_url=args.url, confirm=args.confirm)

    render_banner(agent.model_id, args.url, target_repo, agent.confirm)

    if args.task:
        agent.run_turn(args.task)
        return

    repo_name = Path(target_repo).name
    while True:
        try:
            if _RICH:
                cmd = console.input(f"[bold {C_ACCENT}]▸[/] [dim]{repo_name}[/] ").strip()
            else:
                cmd = input(f"▸ {repo_name} > ").strip()
            if not cmd:
                continue
            if cmd.lower() in ("exit", "quit"):
                ui_notify("see you next time 👋", style=C_ACCENT, prefix="\n  ")
                break
            elif cmd == "/map":
                print(agent.repomap.generate_map())
            elif cmd == "/skills":
                skills = sorted(agent.skill_manager.skills.keys())
                if _RICH:
                    tbl = Table(box=ROUNDED, border_style=C_DIM, show_header=True, header_style=f"bold {C_ACCENT}")
                    tbl.add_column("skill", style=C_TOOL, no_wrap=True)
                    tbl.add_column("description", style="default")
                    for name in skills:
                        item = agent.skill_manager.skills[name]
                        tbl.add_row(item["name"], item["description"].splitlines()[0][:90])
                    console.print(tbl)
                    console.print(f"[dim]  {len(skills)} skills offline · use [/][{C_TOOL}]/skill <name>[/][dim] to activate[/]\n")
                else:
                    print("\nAvailable Local Skills:")
                    for name in skills:
                        item = agent.skill_manager.skills[name]
                        print(f"  • {item['name']:<30} {item['description'].splitlines()[0][:90]}")
                    print(f"Total: {len(skills)} skills. Use /skill <name> to activate.\n")
            elif cmd.startswith("/skill"):
                parts = cmd.split(maxsplit=1)
                if len(parts) < 2:
                    print("Usage: /skill <skill_name>  (e.g. /skill hld-lld)")
                    continue
                skill_name = parts[1].strip()
                content = agent.skill_manager.load_skill_content(skill_name)
                if content:
                    agent.messages.append({
                        "role": "user",
                        "content": f"[INSTRUCTION]: Activate and follow the guidelines of skill '{skill_name}':\n\n{content}"
                    })
                    agent.messages.append({
                        "role": "assistant",
                        "content": f"Understood. I have activated and reviewed the '{skill_name}' skill instructions. I will follow its workflow and guidelines."
                    })
                    print(f"✅ Activated skill '{skill_name}' ({len(content.splitlines())} lines). Gemma 4 will follow these rules!")
                else:
                    print(f"❌ Skill '{skill_name}' not found. Type `/skills` to see available names.")
            elif cmd == "/diff":
                print(agent.toolkit.git_diff())
            elif cmd.startswith("/confirm"):
                parts = cmd.split()
                if len(parts) > 1:
                    agent.confirm = parts[1].lower() in ("on", "true", "1", "yes")
                else:
                    agent.confirm = not agent.confirm
                status_str = "ENABLED (Prompts for approval before bash / file edits)" if agent.confirm else "DISABLED (Auto-approves tool actions)"
                print(f"🔒 Approval Mode: {status_str}")
            elif cmd.startswith("/commit"):
                parts = cmd.split(maxsplit=1)
                msg = parts[1] if len(parts) > 1 else "chore: save work"
                print(agent.toolkit.git_commit(msg))
            elif cmd == "/undo":
                print(agent.toolkit.git_undo())
            elif cmd.startswith("/run ") or cmd.startswith("!"):
                shell_cmd = cmd[5:] if cmd.startswith("/run ") else cmd[1:]
                print(agent.toolkit.run_command(shell_cmd))
            elif cmd == "/help":
                print("Slash Commands:")
                print("  /map              - Display repository structure and symbols")
                print("  /skills           - List all available local skills")
                print("  /skill <name>     - Manually activate a specialized skill into this chat")
                print("  /diff             - Show current git diff")
                print("  /confirm [on/off] - Toggle approval prompt before bash commands or file edits")
                print("  /commit <msg>     - Stage all files and create git commit")
                print("  /undo             - Roll back last commit (git reset --hard HEAD~1)")
                print("  /run <cmd>        - Run a direct bash command (alias: !<cmd>)")
                print("  exit              - Exit the agent")
            else:
                agent.run_turn(cmd)
        except KeyboardInterrupt:
            ui_notify("interrupted — see you next time 👋", style=C_ACCENT, prefix="\n  ")
            break

if __name__ == "__main__":
    main()
