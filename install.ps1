# ============================================================
#  milo installer (Windows)
#  One-liner:
#    irm https://raw.githubusercontent.com/AnseedX/milo/main/install.ps1 | iex
#
#  Installs prerequisites (Git, Python) if missing, clones milo,
#  installs Python deps, and puts `milo` on your PATH so you can
#  run it from any terminal / cmd.
#
#  Overrides:  $env:MILO_HOME (install dir), $env:MILO_NO_PATH=1 (skip PATH)
# ============================================================
$ErrorActionPreference = "Stop"

$Repo = "https://github.com/AnseedX/milo.git"
$Dir  = if ($env:MILO_HOME) { $env:MILO_HOME } else { Join-Path $env:LOCALAPPDATA "Programs\milo" }

function Have($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }
function Refresh-Path {
    $m = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $u = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = (@($m, $u) | Where-Object { $_ }) -join ";"
}

Write-Host "`n:: Installing milo..." -ForegroundColor Cyan

# --- Git ---
if (-not (Have git)) {
    Write-Host "  - Installing Git..." -ForegroundColor DarkGray
    winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements | Out-Null
    Refresh-Path
    if (-not (Have git)) { $env:Path += ";$env:ProgramFiles\Git\cmd" }
}

# --- Python ---
if (-not (Have py) -and -not (Have python)) {
    Write-Host "  - Installing Python..." -ForegroundColor DarkGray
    winget install --id Python.Python.3.12 -e --silent --accept-package-agreements --accept-source-agreements | Out-Null
    Refresh-Path
}
$Py = if (Have py) { "py" } elseif (Have python) { "python" } else { throw "Python not found after install. Please install Python 3.10+ and re-run." }

# --- Clone or update ---
if (Test-Path (Join-Path $Dir ".git")) {
    Write-Host "  - Updating existing install at $Dir" -ForegroundColor DarkGray
    git -C $Dir pull --ff-only | Out-Null
} else {
    Write-Host "  - Cloning milo to $Dir" -ForegroundColor DarkGray
    git clone --depth 1 $Repo $Dir | Out-Null
}

# --- Python dependencies ---
Write-Host "  - Installing Python dependencies..." -ForegroundColor DarkGray
& $Py -m pip install --quiet --upgrade httpx openai rich

# --- Put milo on PATH ---
if ($env:MILO_NO_PATH -ne "1") {
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if (($userPath -split ";") -notcontains $Dir) {
        $newPath = (@($userPath.TrimEnd(";"), $Dir) | Where-Object { $_ }) -join ";"
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        Write-Host "  - Added $Dir to your PATH" -ForegroundColor DarkGray
    }
    $env:Path += ";$Dir"
}

Write-Host "`n[OK] milo installed!" -ForegroundColor Green

# --- LM Studio check ---
if (-not (Test-Path "$env:USERPROFILE\.lmstudio\bin\lms.exe")) {
    Write-Host "`n[!] LM Studio not detected - milo needs it to run a local model." -ForegroundColor Yellow
    Write-Host "    Install it, then download a model (e.g. google/gemma-4-e4b):"
    Write-Host "      winget install ElementLabs.LMStudio" -ForegroundColor White
}

Write-Host "`n>> Open a NEW terminal, then run:  " -NoNewline
Write-Host "milo" -ForegroundColor Cyan
Write-Host ""
