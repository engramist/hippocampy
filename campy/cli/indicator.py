"""Cross-platform system tray indicator for Campy daemon phase status."""
import json
import logging
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

HEARTBEAT_URL = "http://127.0.0.1:7799/api/v1/heartbeat"
STREAM_URL = "http://127.0.0.1:7799/api/v1/activity/stream"
CONTROL_PANEL_URL = "http://127.0.0.1:7799"

PHASE_COLORS = {
    "idle":      (72, 187, 120),    # green
    "encoding":  (236, 201, 75),    # amber
    "recalling": (66, 153, 225),    # blue
    "sweeping":  (159, 122, 234),   # purple
    "offline":   (113, 128, 150),   # grey
}

ICON_SIZE = 22


def _make_icon_image(color: tuple):
    """Generate a colored circle icon image using Pillow."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = 2
    draw.ellipse(
        [margin, margin, ICON_SIZE - margin, ICON_SIZE - margin],
        fill=(*color, 255),
    )
    return img


def _sse_listener(icon, stop_event: threading.Event):
    """Background thread: subscribe to SSE stream and update tray icon."""
    import httpx

    while not stop_event.is_set():
        try:
            with httpx.stream("GET", STREAM_URL, timeout=None) as response:
                event_type = ""
                for line in response.iter_lines():
                    if stop_event.is_set():
                        return
                    if line.startswith("event:"):
                        event_type = line[6:].strip()
                    elif line.startswith("data:") and event_type in ("phase", "heartbeat"):
                        data = json.loads(line[5:].strip())
                        phase = data.get("phase", "idle")
                        uptime = data.get("uptime_s", 0)
                        color = PHASE_COLORS.get(phase, PHASE_COLORS["idle"])
                        icon.icon = _make_icon_image(color)
                        icon.title = f"Campy: {phase} ({uptime:.0f}s)"
        except Exception:
            # Connection lost — show offline and retry
            icon.icon = _make_icon_image(PHASE_COLORS["offline"])
            icon.title = "Campy: offline"
            if not stop_event.is_set():
                stop_event.wait(timeout=5.0)


def _open_control_panel():
    """Open the Campy control panel in the default browser."""
    import webbrowser
    webbrowser.open(CONTROL_PANEL_URL)


def run_indicator():
    """Launch the system tray indicator (blocking — runs the event loop)."""
    try:
        import pystray
    except ImportError:
        print("pystray not installed. Run: pip install campy[indicator]")
        sys.exit(1)

    stop_event = threading.Event()

    menu = pystray.Menu(
        pystray.MenuItem("Open Control Panel", lambda: _open_control_panel()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", lambda icon, _: (stop_event.set(), icon.stop())),
    )

    icon = pystray.Icon(
        name="campy",
        icon=_make_icon_image(PHASE_COLORS["offline"]),
        title="Campy: connecting...",
        menu=menu,
    )

    # Start SSE listener in background thread
    listener = threading.Thread(target=_sse_listener, args=(icon, stop_event), daemon=True)
    listener.start()

    # Run the icon (blocking)
    icon.run()
    stop_event.set()


# --- Auto-start install/uninstall ---

_LAUNCHD_PLIST = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>dev.hippocampy.indicator</string>
  <key>ProgramArguments</key>
  <array>
    <string>{exe}</string>
    <string>indicator</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><false/>
</dict>
</plist>
"""

_LINUX_DESKTOP = """\
[Desktop Entry]
Type=Application
Name=Campy Indicator
Exec={exe} indicator
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
"""


def install_autostart():
    """Install platform-appropriate auto-start entry."""
    exe = sys.executable.replace("python", "campy")
    campy_bin = Path(sys.executable).parent / "campy"
    if campy_bin.exists():
        exe = str(campy_bin)

    system = platform.system()
    if system == "Darwin":
        plist_path = Path.home() / "Library" / "LaunchAgents" / "dev.hippocampy.indicator.plist"
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist_path.write_text(_LAUNCHD_PLIST.format(exe=exe))
        subprocess.run(["launchctl", "load", str(plist_path)], check=False)
        print(f"Installed: {plist_path}")
    elif system == "Windows":
        startup = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        bat = startup / "campy-indicator.bat"
        bat.write_text(f'@echo off\nstart /b "" "{exe}" indicator\n')
        print(f"Installed: {bat}")
    elif system == "Linux":
        desktop_path = Path.home() / ".config" / "autostart" / "campy-indicator.desktop"
        desktop_path.parent.mkdir(parents=True, exist_ok=True)
        desktop_path.write_text(_LINUX_DESKTOP.format(exe=exe))
        print(f"Installed: {desktop_path}")
    else:
        print(f"Unsupported platform: {system}")
        return
    print("Campy indicator will start automatically on login.")


def uninstall_autostart():
    """Remove platform-appropriate auto-start entry."""
    system = platform.system()
    if system == "Darwin":
        plist_path = Path.home() / "Library" / "LaunchAgents" / "dev.hippocampy.indicator.plist"
        subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
        plist_path.unlink(missing_ok=True)
        print(f"Removed: {plist_path}")
    elif system == "Windows":
        bat = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "campy-indicator.bat"
        bat.unlink(missing_ok=True)
        print(f"Removed: {bat}")
    elif system == "Linux":
        desktop_path = Path.home() / ".config" / "autostart" / "campy-indicator.desktop"
        desktop_path.unlink(missing_ok=True)
        print(f"Removed: {desktop_path}")
    else:
        print(f"Unsupported platform: {system}")
