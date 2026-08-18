"""AstroInput: Standalone Per-Instance Minimized Input Engine for Astro Account Manager.

Strict Requirements & Constraints:
1. 100% Invisible & Non-Intrusive:
   - Window MUST remain IsIconic == True (minimized) throughout the action.
   - NEVER call ShowWindow, SetForegroundWindow, BringWindowToTop, or AttachThreadInput.
   - NEVER modify window opacity (WS_EX_LAYERED alpha 1/255 is strictly prohibited).
   - NEVER move window off-screen or un-minimize.
2. Zero Real Hardware / Global State Mutators:
   - NO global SendInput calls.
   - Physical mouse position (GetCursorPos) MUST NOT change.
   - Foreground window (GetForegroundWindow) MUST NOT change.
   - Keyboard physical state MUST NOT be altered.
3. Strict Isolation & Parallelism:
   - Targeted exclusively by (PID, create_time).
   - Per-session worker threads and queues; zero global lock across instances.
   - Independent atomic key & pointer state per session.
4. Binary Protocol ("AINP"):
   - Closed opcode set: KEY_DOWN, KEY_UP, TEXT, POINTER_ABS, POINTER_REL, BUTTON_DOWN, BUTTON_UP, WHEEL, RELEASE_ALL, PING.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass, field
import enum
import struct
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import psutil

# Win32 Constants
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020E
WM_MOUSEHWHEEL = 0x020E

MK_LBUTTON = 0x0001
MK_RBUTTON = 0x0002
MK_SHIFT = 0x0004
MK_CONTROL = 0x0008
MK_MBUTTON = 0x0010

# Win32 Functions
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL

user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = wintypes.HWND

user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL

user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostMessageW.restype = wintypes.BOOL

user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = wintypes.LPARAM

user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetClientRect.restype = wintypes.BOOL

user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT


def make_lparam(low: int, high: int) -> int:
    return ((high & 0xFFFF) << 16) | (low & 0xFFFF)


def get_scan_code(vk: int) -> int:
    return user32.MapVirtualKeyW(vk, 0)


def build_key_lparam(vk: int, down: bool, repeat: int = 1, prev_state: bool = False) -> int:
    scan_code = get_scan_code(vk)
    lparam = repeat & 0xFFFF
    lparam |= (scan_code & 0xFF) << 16
    if vk in (0x25, 0x26, 0x27, 0x28, 0x24, 0x23, 0x21, 0x22, 0x2D, 0x2E):  # Arrow keys, etc.
        lparam |= 1 << 24
    if not down:
        lparam |= (1 << 30)  # Previous key state (1 for key up)
        lparam |= (1 << 31)  # Transition state (1 for key up)
    elif prev_state:
        lparam |= (1 << 30)
    return lparam


class AstroOpcode(enum.IntEnum):
    PING = 0x0001
    KEY_DOWN = 0x0002
    KEY_UP = 0x0003
    TEXT_UTF16 = 0x0004
    POINTER_ABS = 0x0005
    POINTER_REL = 0x0006
    BUTTON_DOWN = 0x0007
    BUTTON_UP = 0x0008
    WHEEL = 0x0009
    RELEASE_ALL = 0x000A


@dataclass
class AstroCommand:
    opcode: AstroOpcode
    session_id: int
    sequence: int
    payload: bytes = b""


class AstroProtocol:
    """AINP Protocol Serializer & Deserializer."""
    MAGIC = b"AINP"
    VERSION = 1
    HEADER_FMT = "<4sHHIIQQQI"  # magic[4], ver, opcode, payload_len, session_id, seq, monotonic_ns, flags
    HEADER_SIZE = struct.calcsize(HEADER_FMT)

    @classmethod
    def pack(cls, opcode: AstroOpcode, session_id: int, sequence: int, payload: bytes = b"", flags: int = 0) -> bytes:
        now_ns = time.monotonic_ns()
        payload_len = len(payload)
        header = struct.pack(
            cls.HEADER_FMT,
            cls.MAGIC,
            cls.VERSION,
            int(opcode),
            payload_len,
            session_id,
            sequence,
            now_ns,
            flags,
        )
        return header + payload

    @classmethod
    def unpack_header(cls, data: bytes) -> Tuple[AstroOpcode, int, int, int, int, int]:
        if len(data) < cls.HEADER_SIZE:
            raise ValueError("Data too short for AINP header")
        magic, ver, opcode, payload_len, session_id, sequence, now_ns, flags = struct.unpack(
            cls.HEADER_FMT, data[: cls.HEADER_SIZE]
        )
        if magic != cls.MAGIC:
            raise ValueError(f"Invalid magic: {magic}")
        if ver != cls.VERSION:
            raise ValueError(f"Unsupported protocol version: {ver}")
        return AstroOpcode(opcode), payload_len, session_id, sequence, now_ns, flags


@dataclass
class InstanceTarget:
    pid: int
    create_time: float
    hwnd: wintypes.HWND
    hwnd_title: str

    def is_valid(self) -> bool:
        try:
            p = psutil.Process(self.pid)
            if abs(p.create_time() - self.create_time) > 1.0:
                return False
            return user32.IsWindow(self.hwnd) != 0
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def check_minimized(self) -> bool:
        """Verify window is strictly minimized (IsIconic == True)."""
        return bool(user32.IsIconic(self.hwnd))


class InputSession:
    """Independent, isolated input session targeting a specific PID + create_time."""

    def __init__(self, target: InstanceTarget):
        self.target = target
        self.session_id = target.pid
        self.lock = threading.Lock()
        self.keys_down: set[int] = set()
        self.cursor_x: float = 0.5  # Normalized [0.0, 1.0]
        self.cursor_y: float = 0.5
        self.buttons_down: set[str] = set()
        self.sequence: int = 0
        self.last_active: float = time.monotonic()
        self._command_queue: List[AstroCommand] = []
        self._worker_thread: Optional[threading.Thread] = None
        self._running = False

    def verify_safety_constraints(self) -> Tuple[bool, str]:
        """Strict check before sending any input: window MUST be minimized and process MUST match."""
        if not self.target.is_valid():
            return False, f"Target process {self.target.pid} invalid or create_time mismatch"
        if not self.target.check_minimized():
            return False, f"Window HWND {self.target.hwnd} for PID {self.target.pid} is NOT minimized (IsIconic=False)"
        return True, "OK"

    def execute_command(self, cmd: AstroCommand) -> Tuple[bool, str]:
        """Dispatch AINP command safely to the target HWND without altering real system hardware state."""
        ok, err = self.verify_safety_constraints()
        if not ok:
            return False, f"Constraint failed: {err}"

        hwnd = self.target.hwnd
        rect = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width <= 0 or height <= 0:
            width = 1920
            height = 1080

        if cmd.opcode == AstroOpcode.KEY_DOWN:
            vk, scan = struct.unpack("<HH", cmd.payload)
            lparam = build_key_lparam(vk, down=True)
            with self.lock:
                self.keys_down.add(vk)
            user32.PostMessageW(hwnd, WM_KEYDOWN, vk, lparam)
            return True, "KEY_DOWN posted"

        elif cmd.opcode == AstroOpcode.KEY_UP:
            vk, scan = struct.unpack("<HH", cmd.payload)
            lparam = build_key_lparam(vk, down=False)
            with self.lock:
                self.keys_down.discard(vk)
            user32.PostMessageW(hwnd, WM_KEYUP, vk, lparam)
            return True, "KEY_UP posted"

        elif cmd.opcode == AstroOpcode.TEXT_UTF16:
            text = cmd.payload.decode("utf-16le")
            for char in text:
                user32.PostMessageW(hwnd, WM_CHAR, ord(char), 0)
            return True, f"TEXT posted ({len(text)} chars)"

        elif cmd.opcode == AstroOpcode.POINTER_ABS:
            x_norm, y_norm = struct.unpack("<ff", cmd.payload)
            with self.lock:
                self.cursor_x = max(0.0, min(1.0, x_norm))
                self.cursor_y = max(0.0, min(1.0, y_norm))
                px = int(self.cursor_x * width)
                py = int(self.cursor_y * height)
            lparam = make_lparam(px, py)
            user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
            return True, f"POINTER_ABS posted ({px},{py})"

        elif cmd.opcode == AstroOpcode.POINTER_REL:
            dx, dy = struct.unpack("<ff", cmd.payload)
            with self.lock:
                self.cursor_x = max(0.0, min(1.0, self.cursor_x + dx))
                self.cursor_y = max(0.0, min(1.0, self.cursor_y + dy))
                px = int(self.cursor_x * width)
                py = int(self.cursor_y * height)
            lparam = make_lparam(px, py)
            user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lparam)
            return True, f"POINTER_REL posted ({px},{py})"

        elif cmd.opcode == AstroOpcode.BUTTON_DOWN:
            btn_id, = struct.unpack("<B", cmd.payload)
            px = int(self.cursor_x * width)
            py = int(self.cursor_y * height)
            lparam = make_lparam(px, py)

            if btn_id == 1:  # Left
                msg = WM_LBUTTONDOWN
                wparam = MK_LBUTTON
                name = "left"
            elif btn_id == 2:  # Right
                msg = WM_RBUTTONDOWN
                wparam = MK_RBUTTON
                name = "right"
            else:  # Middle
                msg = WM_MBUTTONDOWN
                wparam = MK_MBUTTON
                name = "middle"

            with self.lock:
                self.buttons_down.add(name)
            user32.PostMessageW(hwnd, msg, wparam, lparam)
            return True, f"BUTTON_DOWN ({name}) posted"

        elif cmd.opcode == AstroOpcode.BUTTON_UP:
            btn_id, = struct.unpack("<B", cmd.payload)
            px = int(self.cursor_x * width)
            py = int(self.cursor_y * height)
            lparam = make_lparam(px, py)

            if btn_id == 1:
                msg = WM_LBUTTONUP
                name = "left"
            elif btn_id == 2:
                msg = WM_RBUTTONUP
                name = "right"
            else:
                msg = WM_MBUTTONUP
                name = "middle"

            with self.lock:
                self.buttons_down.discard(name)
            user32.PostMessageW(hwnd, msg, 0, lparam)
            return True, f"BUTTON_UP ({name}) posted"

        elif cmd.opcode == AstroOpcode.WHEEL:
            delta_x, delta_y = struct.unpack("<hh", cmd.payload)
            px = int(self.cursor_x * width)
            py = int(self.cursor_y * height)
            lparam = make_lparam(px, py)
            if delta_y != 0:
                wparam = (delta_y & 0xFFFF) << 16
                user32.PostMessageW(hwnd, WM_MOUSEWHEEL, wparam, lparam)
            return True, "WHEEL posted"

        elif cmd.opcode == AstroOpcode.RELEASE_ALL:
            with self.lock:
                keys = list(self.keys_down)
                buttons = list(self.buttons_down)

            for vk in keys:
                lparam = build_key_lparam(vk, down=False)
                user32.PostMessageW(hwnd, WM_KEYUP, vk, lparam)
            
            px = int(self.cursor_x * width)
            py = int(self.cursor_y * height)
            lparam = make_lparam(px, py)

            for btn in buttons:
                msg = WM_LBUTTONUP if btn == "left" else (WM_RBUTTONUP if btn == "right" else WM_MBUTTONUP)
                user32.PostMessageW(hwnd, msg, 0, lparam)

            with self.lock:
                self.keys_down.clear()
                self.buttons_down.clear()

            return True, "RELEASE_ALL executed"

        elif cmd.opcode == AstroOpcode.PING:
            return True, "PONG"

        return False, f"Unknown opcode {cmd.opcode}"


class AstroInputBroker:
    """Broker managing multi-instance InputSessions independently."""

    def __init__(self):
        self._sessions: Dict[Tuple[int, float, int], InputSession] = {}
        self._lock = threading.RLock()

    def attach_session(self, pid: int, create_time: float, hwnd: wintypes.HWND, title: str = "") -> InputSession:
        target = InstanceTarget(pid=pid, create_time=create_time, hwnd=hwnd, hwnd_title=title)
        if not target.is_valid():
            raise ValueError(f"Cannot attach: Process PID {pid} is invalid or HWND is closed.")
        
        key = (pid, create_time, int(hwnd))
        with self._lock:
            if key in self._sessions:
                return self._sessions[key]
            session = InputSession(target)
            self._sessions[key] = session
            return session

    def detach_session(self, pid: int, create_time: float, hwnd: int):
        key = (pid, create_time, int(hwnd))
        with self._lock:
            session = self._sessions.pop(key, None)
            if session:
                # Guarantee key up/release all on detach
                cmd = AstroCommand(AstroOpcode.RELEASE_ALL, session.session_id, 0)
                session.execute_command(cmd)

    def dispatch(self, pid: int, create_time: float, hwnd: int, opcode: AstroOpcode, payload: bytes = b"") -> Tuple[bool, str]:
        key = (pid, create_time, int(hwnd))
        with self._lock:
            session = self._sessions.get(key)
        if not session:
            return False, f"No active session for PID {pid} HWND {hwnd}"
        
        session.sequence += 1
        cmd = AstroCommand(opcode=opcode, session_id=pid, sequence=session.sequence, payload=payload)
        return session.execute_command(cmd)
