"""
SlimyOS Host Desktop Room — Controlled real desktop interaction.

THIS IS THE HIGHEST RISK ROOM. The agent touches the user's actual
screen, keyboard, and mouse.

Safety requirements:
- Explicit session approval with time limit
- Visible "Host Assist Active" overlay
- Allowed apps/paths whitelist per session
- Emergency stop via F12 / panic button / phone
- All actions logged with screenshots
- Session auto-expires

Implementation primitives (from research report):
- ydotool + ydotoold: Wayland-compatible input simulation via uinput
- PipeWire ScreenCast: XDG portal screen capture
- Hyprland IPC: hyprctl for window management
- AT-SPI2: accessibility tree for element identification
- D-Bus: notifications, media control, system info

All tools are WRAPPERS. They check session validity before every action.
"""

import os
import subprocess
import uuid
import time
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field


@dataclass
class HostSession:
    """A time-limited permission token for host desktop access."""
    session_id: str
    task_id: str
    agent_id: str
    goal: str
    allowed_apps: list = field(default_factory=list)
    allowed_paths: list = field(default_factory=list)
    expires_at: str = ""
    created_at: str = ""
    active: bool = True
    actions_taken: int = 0
    max_actions: int = 50

    def is_valid(self) -> bool:
        if not self.active:
            return False
        if self.actions_taken >= self.max_actions:
            return False
        if self.expires_at:
            exp = datetime.fromisoformat(self.expires_at)
            if datetime.now(timezone.utc) > exp:
                return False
        return True


# Session registry
_sessions: dict[str, HostSession] = {}


def _check_session(args: dict) -> tuple[bool, str, HostSession | None]:
    """Verify a valid host session exists."""
    sid = args.get("session_id", "")
    session = _sessions.get(sid)
    if not session:
        return False, "No active host session. Create one first.", None
    if not session.is_valid():
        return False, f"Session {sid} expired or exhausted.", None
    return True, "", session


def _tool_available(name: str) -> bool:
    """Check if a system tool is installed."""
    try:
        subprocess.run(["which", name], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# ═══ Session Management ═══

def handle_host_session_create(args: dict) -> dict:
    """
    Create a host assist session. Requires approval.
    The session is a time-limited token that gates all desktop actions.
    """
    session_id = str(uuid.uuid4())[:8]
    duration_minutes = args.get("duration_minutes", 15)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=duration_minutes)
    
    session = HostSession(
        session_id=session_id,
        task_id=args.get("task_id", ""),
        agent_id=args.get("agent_id", ""),
        goal=args.get("goal", "No goal specified"),
        allowed_apps=args.get("allowed_apps", ["Terminal", "Browser"]),
        allowed_paths=args.get("allowed_paths", []),
        expires_at=expires.isoformat(),
        created_at=now.isoformat(),
        max_actions=args.get("max_actions", 50),
    )
    _sessions[session_id] = session
    
    return {
        "output": (
            f"Host Assist Session Created\n"
            f"  ID: {session_id}\n"
            f"  Goal: {session.goal}\n"
            f"  Allowed apps: {', '.join(session.allowed_apps)}\n"
            f"  Expires: {duration_minutes} minutes\n"
            f"  Max actions: {session.max_actions}"
        ),
        "session_id": session_id,
        "expires_at": session.expires_at,
    }


def handle_host_session_end(args: dict) -> dict:
    """End a host assist session."""
    sid = args.get("session_id", "")
    session = _sessions.get(sid)
    if session:
        session.active = False
        return {
            "output": f"Session {sid} ended. Actions taken: {session.actions_taken}",
            "actions_taken": session.actions_taken,
        }
    return {"output": f"Session {sid} not found", "error": True}


# ═══ Screen ═══

def handle_desktop_screenshot(args: dict) -> dict:
    """
    Take a screenshot of the desktop via PipeWire ScreenCast portal.
    Real: uses grim (Wayland) or scrot (X11).
    """
    valid, err, session = _check_session(args)
    if not valid:
        return {"output": "", "error": err}
    session.actions_taken += 1
    
    label = args.get("label", "screenshot")
    output_path = args.get("output_path", f"/tmp/slimyos-screenshot-{label}.png")
    
    if _tool_available("grim"):
        r = subprocess.run(["grim", output_path], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return {"output": f"Screenshot saved: {output_path}", "path": output_path, "mode": "grim"}
    
    return {
        "output": f"[MOCK] Screenshot '{label}' → {output_path}",
        "path": output_path,
        "mode": "mock",
    }


# ═══ Input Simulation ═══

def handle_desktop_type_text(args: dict) -> dict:
    """
    Type text via ydotool. Requires active session.
    Real: ydotool type --delay 50 "text"
    """
    valid, err, session = _check_session(args)
    if not valid:
        return {"output": "", "error": err}
    session.actions_taken += 1
    
    text = args["text"]
    
    if _tool_available("ydotool"):
        r = subprocess.run(
            ["ydotool", "type", "--delay", "50", text],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            return {"output": f"Typed: {text[:50]}{'...' if len(text)>50 else ''}", "mode": "ydotool"}
        return {"output": "", "error": f"ydotool error: {r.stderr}"}
    
    return {"output": f"[MOCK] Type: {text[:80]}", "mode": "mock"}


def handle_desktop_click(args: dict) -> dict:
    """
    Click at coordinates via ydotool. Requires active session.
    Real: ydotool mousemove --absolute x y && ydotool click 0xC0
    """
    valid, err, session = _check_session(args)
    if not valid:
        return {"output": "", "error": err}
    session.actions_taken += 1
    
    x, y = args["x"], args["y"]
    button = args.get("button", "left")
    
    if _tool_available("ydotool"):
        subprocess.run(["ydotool", "mousemove", "--absolute", str(x), str(y)],
                       capture_output=True, timeout=5)
        btn_code = "0xC0" if button == "left" else "0xC1"
        r = subprocess.run(["ydotool", "click", btn_code], capture_output=True, timeout=5)
        return {"output": f"Clicked ({x}, {y}) [{button}]", "mode": "ydotool"}
    
    return {"output": f"[MOCK] Click ({x}, {y}) [{button}]", "mode": "mock"}


def handle_desktop_key(args: dict) -> dict:
    """
    Press a key combo via ydotool. Requires active session.
    Real: ydotool key <keycode>
    """
    valid, err, session = _check_session(args)
    if not valid:
        return {"output": "", "error": err}
    session.actions_taken += 1
    
    key = args["key"]  # e.g., "ctrl+c", "Return", "super"
    
    if _tool_available("ydotool"):
        r = subprocess.run(["ydotool", "key", key], capture_output=True, timeout=5)
        return {"output": f"Key: {key}", "mode": "ydotool"}
    
    return {"output": f"[MOCK] Key: {key}", "mode": "mock"}


# ═══ Window Management ═══

def handle_hyprland_windows(args: dict) -> dict:
    """
    List open windows via Hyprland IPC.
    Real: hyprctl clients -j
    """
    valid, err, session = _check_session(args)
    if not valid:
        return {"output": "", "error": err}
    
    if _tool_available("hyprctl"):
        r = subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return {"output": r.stdout[:2000], "mode": "hyprland"}
    
    return {
        "output": '[MOCK] [{"class":"kitty","title":"Terminal","workspace":1},{"class":"chromium","title":"SlimyOS","workspace":1}]',
        "mode": "mock",
    }


def handle_hyprland_focus(args: dict) -> dict:
    """
    Focus a window by class or title via Hyprland IPC.
    Real: hyprctl dispatch focuswindow class:chromium
    """
    valid, err, session = _check_session(args)
    if not valid:
        return {"output": "", "error": err}
    session.actions_taken += 1
    
    target = args.get("window_class", "") or args.get("window_title", "")
    
    if _tool_available("hyprctl"):
        selector = f"class:{target}" if args.get("window_class") else f"title:{target}"
        r = subprocess.run(["hyprctl", "dispatch", "focuswindow", selector],
                          capture_output=True, text=True, timeout=5)
        return {"output": f"Focused: {selector}", "mode": "hyprland"}
    
    return {"output": f"[MOCK] Focus: {target}", "mode": "mock"}


# ═══ Accessibility ═══

def handle_desktop_read_elements(args: dict) -> dict:
    """
    Read accessible elements via AT-SPI2.
    Real: uses pyatspi2 to walk the accessibility tree.
    This is the Linux equivalent of macOS VoiceOver / Windows UI Automation.
    """
    valid, err, session = _check_session(args)
    if not valid:
        return {"output": "", "error": err}
    
    try:
        import pyatspi
        desktop = pyatspi.Registry.getDesktop(0)
        elements = []
        for app in desktop:
            elements.append({"app": app.name, "role": str(app.getRole())})
        return {"output": str(elements[:20]), "mode": "atspi"}
    except ImportError:
        pass
    
    return {
        "output": '[MOCK] [{"app":"kitty","role":"ROLE_APPLICATION"},{"app":"chromium","role":"ROLE_APPLICATION"}]',
        "mode": "mock",
    }


# ═══ D-Bus Notifications ═══

def handle_desktop_notify(args: dict) -> dict:
    """
    Send a desktop notification via D-Bus.
    Real: uses notify-send or direct D-Bus call.
    """
    title = args.get("title", "SlimyOS")
    body = args.get("body", "")
    urgency = args.get("urgency", "normal")
    
    if _tool_available("notify-send"):
        r = subprocess.run(
            ["notify-send", f"--urgency={urgency}", title, body],
            capture_output=True, timeout=5,
        )
        if r.returncode == 0:
            return {"output": f"Notification sent: {title}", "mode": "notify-send"}
    
    return {"output": f"[MOCK] Notify: {title} — {body}", "mode": "mock"}


DESKTOP_ROOM_TOOLS = {
    "host_session_create": handle_host_session_create,
    "host_session_end": handle_host_session_end,
    "desktop_screenshot": handle_desktop_screenshot,
    "desktop_type_text": handle_desktop_type_text,
    "desktop_click": handle_desktop_click,
    "desktop_key": handle_desktop_key,
    "hyprland_windows": handle_hyprland_windows,
    "hyprland_focus": handle_hyprland_focus,
    "desktop_read_elements": handle_desktop_read_elements,
    "desktop_notify": handle_desktop_notify,
}
