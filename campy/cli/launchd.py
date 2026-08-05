import os
import subprocess
import sys
import shutil
from pathlib import Path

from campy.branding import LEGACY_LAUNCHD_LABEL, LEGACY_LAUNCHD_LABELS, PRIMARY_LAUNCHD_LABEL
from campy.paths import get_daemon_log_path, get_launchd_plist_path, get_legacy_launchd_plist_path

LABEL = PRIMARY_LAUNCHD_LABEL
LEGACY_LABEL = LEGACY_LAUNCHD_LABEL
PLIST_PATH = get_launchd_plist_path(LABEL)
LEGACY_PLIST_PATH = get_legacy_launchd_plist_path()
LOG_PATH = get_daemon_log_path()


def _canonical_repo_root() -> Path:
    """Resolve the main-checkout repo root, never an ephemeral git worktree.

    ``Path(__file__).parent.parent.parent`` is wrong when this module is
    imported from inside a git worktree (e.g. an isolated agent worktree
    under ``.claude/worktrees/``) — it resolves to the worktree itself, not
    the primary checkout. Since the launchd job this module configures is a
    single shared, machine-wide daemon, generating its plist from a worktree
    silently repoints that shared daemon at a directory that will eventually
    be deleted, and that (being an ephemeral worktree) typically lacks
    untracked runtime assets the main checkout has — the daemon then
    crash-loops under launchd's keep-alive supervision. See B-series
    incident write-up for the concrete case (all worktrees under
    .claude/worktrees/, launchd stuck respawning a worktree copy that was
    missing InvertorsDocs/GistSeedExamples.md, an untracked file).

    ``git rev-parse --git-common-dir`` resolves correctly from any worktree
    back to the main checkout's shared ``.git`` directory, so we use that
    instead of a plain ``__file__``-relative path whenever git is available
    and the result actually looks like the repo (has ``brain_daemon.py``).
    Falls back to the ``__file__``-relative path for non-git installs
    (e.g. pipx/pip, where ``_daemon_script`` also has its own fallback).
    """
    fallback = Path(__file__).parent.parent.parent
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=str(fallback),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            common_dir = Path(result.stdout.strip())
            root = common_dir.parent if common_dir.name == ".git" else common_dir
            if (root / "brain_daemon.py").is_file():
                return root
    except Exception:
        pass
    return fallback


def resolve_system_python(repo_root: Path | None = None) -> str:
    """Find the Python interpreter launchd should use.

    repo_root defaults to the canonical repo checkout (never an ephemeral
    worktree, see ``_canonical_repo_root``); tests pass an explicit root so
    the venv-preference branch is exercised regardless of whether the
    runner's checkout has a .venv.
    """
    if repo_root is None:
        repo_root = _canonical_repo_root()
    venv_python = Path(repo_root) / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)

    candidates = ["python3.12", "python3", "/usr/bin/python3"]
    for cmd in candidates:
        full_path = shutil.which(cmd)
        if full_path and "/.pyenv/shims/" not in full_path:
            return os.path.realpath(full_path)
    return os.path.realpath(sys.executable)


def _daemon_script() -> str:
    """Return absolute path to brain_daemon.py, or the console-script path.

    Always resolves against the canonical repo root (see
    ``_canonical_repo_root``), never an ephemeral git worktree — this is the
    shared, machine-wide daemon, so its script path must be stable
    regardless of which worktree happened to generate the plist.

    When installed via pipx the repo-root brain_daemon.py does not exist
    inside the venv.  Fall back to the ``campy-daemon`` console script
    which pipx *does* install, or finally ``python -m campy.daemon``.
    """
    repo_candidate = _canonical_repo_root() / "brain_daemon.py"
    if repo_candidate.is_file():
        return str(repo_candidate)

    # pipx / pip console-script
    console = shutil.which("campy-daemon")
    if console:
        return console

    return str(repo_candidate)  # best-effort; plist generation will surface the error


def _launchctl_list(label: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", "list", label], capture_output=True, text=True)


def is_loaded(label: str = LABEL) -> bool:
    """Return True if the service is loaded in launchctl."""
    return _launchctl_list(label).returncode == 0


def unload_plist(label: str = LABEL, plist_path: Path | None = None) -> bool:
    """Unload the plist from launchctl."""
    path = plist_path or (LEGACY_PLIST_PATH if label == LEGACY_LABEL else PLIST_PATH)
    if not path.exists():
        if not is_loaded(label):
            return True
        subprocess.run(["launchctl", "remove", label], capture_output=True, text=True)
        return not is_loaded(label)
    result = subprocess.run(["launchctl", "unload", str(path)], capture_output=True, text=True)
    if result.returncode != 0 and is_loaded(label):
        subprocess.run(["launchctl", "remove", label], capture_output=True, text=True)
    return result.returncode == 0 or not is_loaded(label)


def load_plist(label: str = LABEL, plist_path: Path | None = None) -> bool:
    """Load the plist into launchctl."""
    path = plist_path or (LEGACY_PLIST_PATH if label == LEGACY_LABEL else PLIST_PATH)
    if not path.exists():
        return False
    result = subprocess.run(["launchctl", "load", str(path)], capture_output=True, text=True)
    return result.returncode == 0 or is_loaded(label)


def generate_plist(brain_daemon_path: str, plist_path: str, label: str = LABEL) -> bool:
    """Generate the launchd plist file for auto-start on macOS."""
    try:
        python_exe = resolve_system_python()
        log_path = get_daemon_log_path()

        # Console scripts (e.g. campy-daemon from pipx) are self-contained;
        # .py files need the Python interpreter as arg[0].
        daemon_path = Path(brain_daemon_path)
        if daemon_path.suffix == ".py":
            prog_args = (
                f"        <string>{python_exe}</string>\n"
                f"        <string>{brain_daemon_path}</string>"
            )
            work_dir = str(daemon_path.parent)
        else:
            prog_args = f"        <string>{brain_daemon_path}</string>"
            work_dir = str(Path.home())

        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
{prog_args}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
    <key>WorkingDirectory</key>
    <string>{work_dir}</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{Path(python_exe).parent}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
"""
        p = Path(plist_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(plist_content)
        return True
    except Exception:
        return False


def write_plist() -> Path:
    """Write the launchd plist file using canonical Campy locations."""
    generate_plist(_daemon_script(), str(PLIST_PATH), LABEL)
    return PLIST_PATH


def setup_daemon(brain_daemon_path: str = None) -> bool:
    """Install/reload the Campy daemon launchd plist."""
    write_plist()
    for legacy_label in LEGACY_LAUNCHD_LABELS:
        if is_loaded(legacy_label):
            unload_plist(legacy_label, get_launchd_plist_path(legacy_label))
    if is_loaded(LABEL):
        unload_plist(LABEL, PLIST_PATH)
    return load_plist(LABEL, PLIST_PATH)
