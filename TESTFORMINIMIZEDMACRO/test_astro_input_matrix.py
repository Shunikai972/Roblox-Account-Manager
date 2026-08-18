"""Validation Matrix Test Suite for AstroInput.

This script runs the mandatory validation matrix on standard Win32 minimized test windows
to empirically measure and prove non-intrusiveness, isolation, and parallelism.
"""

import ctypes
from ctypes import wintypes
import json
import os
import sys
import threading
import time
from typing import Dict, List, Tuple
import psutil

import struct
from astro_input import (
    AstroCommand,
    AstroInputBroker,
    AstroOpcode,
    InstanceTarget,
    user32,
    kernel32,
    wintypes,
    make_lparam,
    build_key_lparam,
    get_scan_code,
)

# Custom Window Class for Matrix Verification
LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t

WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)

user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT

user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.DispatchMessageW.restype = LRESULT

HCURSOR = wintypes.HANDLE
HICON = wintypes.HANDLE

class WNDCLASSEX(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", HICON),
        ("hCursor", HCURSOR),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", HICON),
    ]

_created_windows: List[Tuple[wintypes.HWND, List[Tuple[int, int, int]], threading.Lock]] = []
_wndproc_refs = []

def create_test_window(title: str) -> Tuple[wintypes.HWND, List[Tuple[int, int, int]], threading.Lock]:
    """Create a native Win32 window, minimize it immediately, and collect all received messages."""
    msg_log: List[Tuple[int, int, int]] = []
    lock = threading.Lock()

    def py_wnd_proc(hwnd: wintypes.HWND, msg: int, wparam: int, lparam: int) -> int:
        if msg in (0x0100, 0x0101, 0x0102, 0x0200, 0x0201, 0x0202, 0x0204, 0x0205, 0x0207, 0x0208, 0x020E):
            with lock:
                msg_log.append((msg, wparam, lparam))
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    wndproc_ptr = WNDPROC(py_wnd_proc)
    _wndproc_refs.append(wndproc_ptr)
    
    hinstance = kernel32.GetModuleHandleW(None)
    cls_name = f"AstroTestWndClass_{title}_{time.time_ns()}"

    wndclass = WNDCLASSEX()
    wndclass.cbSize = ctypes.sizeof(WNDCLASSEX)
    wndclass.style = 0
    wndclass.lpfnWndProc = wndproc_ptr
    wndclass.hInstance = hinstance
    wndclass.lpszClassName = cls_name

    atom = user32.RegisterClassExW(ctypes.byref(wndclass))
    if not atom:
        raise RuntimeError(f"Failed to register window class (error {kernel32.GetLastError()})")

    hwnd = user32.CreateWindowExW(
        0,
        cls_name,
        f"AstroTestWindow_{title}",
        0x00CF0000,  # WS_OVERLAPPEDWINDOW
        100, 100, 400, 300,
        0, 0, hinstance, 0
    )

    if not hwnd:
        raise RuntimeError("Failed to create test window")

    # Minimize window immediately
    user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE = 6
    user32.UpdateWindow(hwnd)

    _created_windows.append((hwnd, msg_log, lock))
    return hwnd, msg_log, lock


def pump_messages_for(seconds: float):
    """Pump Windows message loop for background window message processing safely."""
    end_time = time.monotonic() + seconds
    msg = wintypes.MSG()
    while time.monotonic() < end_time:
        while user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):  # PM_REMOVE = 1
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.005)


def run_matrix_tests():
    print("======================================================================")
    print("   ASTROINPUT MATRIX VALIDATION TEST SUITE (MINIMIZED NON-INTRUSIVE)   ")
    print("======================================================================\n")

    results = []

    def record_test(name: str, expected: str, observed: str, passed: bool, details: dict = None):
        status = "PASS" if passed else "FAIL"
        results.append({
            "name": name,
            "expected": expected,
            "observed": observed,
            "status": status,
            "details": details or {}
        })
        print(f"[{status}] {name}")
        print(f"   Expected: {expected}")
        print(f"   Observed: {observed}\n")

    current_pid = os.getpid()
    create_time = psutil.Process(current_pid).create_time()

    # 1. Window & User Workstation Isolation
    print("--- CATEGORY 1: WINDOW & WORKSTATION ISOLATION ---")
    hwnd1, log1, lock1 = create_test_window("InstanceA")
    hwnd2, log2, lock2 = create_test_window("InstanceB")
    hwnd3, log3, lock3 = create_test_window("InstanceC")

    # Measure initial state
    pt_start = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt_start))
    fg_start = user32.GetForegroundWindow()

    broker = AstroInputBroker()
    s1 = broker.attach_session(current_pid, create_time, hwnd1, "InstanceA")
    s2 = broker.attach_session(current_pid, create_time, hwnd2, "InstanceB")
    s3 = broker.attach_session(current_pid, create_time, hwnd3, "InstanceC")

    # Perform input actions across A/B/C while checking window state
    iconic_all_true = True
    cursor_unchanged = True
    fg_unchanged = True

    for i in range(5):
        s1.execute_command(AstroCommand(AstroOpcode.KEY_DOWN, current_pid, i, payload=struct.pack("<HH", 0x57, 0))) # 'W'
        s2.execute_command(AstroCommand(AstroOpcode.POINTER_ABS, current_pid, i, payload=struct.pack("<ff", 0.3, 0.4)))
        s3.execute_command(AstroCommand(AstroOpcode.BUTTON_DOWN, current_pid, i, payload=struct.pack("<B", 1)))
        
        pump_messages_for(0.01)

        if not (s1.target.check_minimized() and s2.target.check_minimized() and s3.target.check_minimized()):
            iconic_all_true = False
        
        pt_now = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt_now))
        if pt_now.x != pt_start.x or pt_now.y != pt_start.y:
            cursor_unchanged = False
        
        if user32.GetForegroundWindow() != fg_start:
            fg_unchanged = False

    s1.execute_command(AstroCommand(AstroOpcode.RELEASE_ALL, current_pid, 99))
    s2.execute_command(AstroCommand(AstroOpcode.RELEASE_ALL, current_pid, 99))
    s3.execute_command(AstroCommand(AstroOpcode.RELEASE_ALL, current_pid, 99))
    pump_messages_for(0.02)

    record_test(
        "IsIconic 100% Maintained",
        "All 3 target HWNDs remain IsIconic == True throughout all actions",
        f"IsIconic remained True: {iconic_all_true}",
        iconic_all_true
    )

    record_test(
        "Physical GetCursorPos Unchanged",
        "System cursor position does not move at all during macro inputs",
        f"Cursor started at ({pt_start.x}, {pt_start.y}), remained unchanged: {cursor_unchanged}",
        cursor_unchanged
    )

    record_test(
        "GetForegroundWindow Unchanged",
        "Foreground window focus is untouched",
        f"Foreground HWND remained unchanged: {fg_unchanged}",
        fg_unchanged
    )

    # 2. Per-instance Keyboard Isolation & Parallelism
    print("--- CATEGORY 2: KEYBOARD ISOLATION & PARALLELISM ---")
    pump_messages_for(0.02)
    with lock1: log1.clear()
    with lock2: log2.clear()
    with lock3: log3.clear()

    # Instance A holds W (0x57), Instance B holds A (0x41), Instance C presses SPACE (0x20)
    s1.execute_command(AstroCommand(AstroOpcode.KEY_DOWN, current_pid, 100, payload=struct.pack("<HH", 0x57, 0)))
    s2.execute_command(AstroCommand(AstroOpcode.KEY_DOWN, current_pid, 101, payload=struct.pack("<HH", 0x41, 0)))
    for k in range(5):
        s3.execute_command(AstroCommand(AstroOpcode.KEY_DOWN, current_pid, 200 + k, payload=struct.pack("<HH", 0x20, 0)))
        s3.execute_command(AstroCommand(AstroOpcode.KEY_UP, current_pid, 300 + k, payload=struct.pack("<HH", 0x20, 0)))

    pump_messages_for(0.05)

    with lock1: log1_copy = list(log1)
    with lock2: log2_copy = list(log2)
    with lock3: log3_copy = list(log3)

    log1_vks = [wp for msg, wp, lp in log1_copy if msg in (0x0100, 0x0101)]
    log2_vks = [wp for msg, wp, lp in log2_copy if msg in (0x0100, 0x0101)]
    log3_vks = [wp for msg, wp, lp in log3_copy if msg in (0x0100, 0x0101)]

    no_leak = (0x41 not in log1_vks and 0x20 not in log1_vks and
               0x57 not in log2_vks and 0x20 not in log2_vks and
               0x57 not in log3_vks and 0x41 not in log3_vks and
               len(log1_vks) > 0 and len(log2_vks) > 0 and len(log3_vks) > 0)

    record_test(
        "Keyboard Message Isolation per Instance",
        "Key events sent to A do not leak to B or C",
        f"A VKs: {log1_vks}, B VKs: {log2_vks}, C VKs: {log3_vks}. Exact isolated routing: {no_leak}",
        no_leak
    )

    # Clean release test
    s1.execute_command(AstroCommand(AstroOpcode.RELEASE_ALL, current_pid, 999))
    s2.execute_command(AstroCommand(AstroOpcode.RELEASE_ALL, current_pid, 999))
    s3.execute_command(AstroCommand(AstroOpcode.RELEASE_ALL, current_pid, 999))
    pump_messages_for(0.02)

    record_test(
        "Key-up Release All Guaranteed",
        "All held keys released upon RELEASE_ALL call",
        f"S1 keys down: {len(s1.keys_down)}, S2 keys down: {len(s2.keys_down)}, S3 keys down: {len(s3.keys_down)}",
        len(s1.keys_down) == 0 and len(s2.keys_down) == 0 and len(s3.keys_down) == 0
    )

    # 3. Per-instance Mouse Isolation & Coords
    print("--- CATEGORY 3: MOUSE ISOLATION & COORDINATES ---")
    pump_messages_for(0.02)
    with lock1: log1.clear()
    with lock2: log2.clear()
    
    s1.execute_command(AstroCommand(AstroOpcode.POINTER_ABS, current_pid, 1000, payload=struct.pack("<ff", 0.1, 0.2)))
    s2.execute_command(AstroCommand(AstroOpcode.POINTER_ABS, current_pid, 1001, payload=struct.pack("<ff", 0.8, 0.9)))
    pump_messages_for(0.05)

    with lock1: mouse1 = [lp for msg, wp, lp in log1 if msg == 0x0200]
    with lock2: mouse2 = [lp for msg, wp, lp in log2 if msg == 0x0200]

    mouse_isolated = (len(mouse1) > 0 and len(mouse2) > 0 and mouse1[0] != mouse2[0])
    record_test(
        "Mouse Coordinates Distinct per Instance",
        "Independent client mouse coordinates posted to distinct minimized windows",
        f"Instance A mouse lparam: {mouse1}, Instance B mouse lparam: {mouse2}",
        mouse_isolated
    )

    # 4. Robustness & Safety Gates
    print("--- CATEGORY 4: ROBUSTNESS & SAFETY GATES ---")
    
    # Try attaching with invalid create_time
    invalid_attached = False
    try:
        broker.attach_session(current_pid, create_time + 100.0, hwnd1, "InvalidTest")
        invalid_attached = True
    except ValueError as e:
        invalid_err = str(e)

    record_test(
        "PID Mismatch / Stale create_time Rejection",
        "Attach fails if target create_time does not match running process",
        f"Attach rejected with: {invalid_err}",
        not invalid_attached
    )

    # Un-minimize window 1 and attempt execution -> MUST be rejected
    user32.ShowWindow(hwnd1, 1)  # SW_SHOWNORMAL = 1
    user32.UpdateWindow(hwnd1)

    unminimized_ok, unminimized_reason = s1.execute_command(
        AstroCommand(AstroOpcode.KEY_DOWN, current_pid, 5000, payload=struct.pack("<HH", 0x41, 0))
    )

    record_test(
        "Strict Non-Minimized Rejection Gate",
        "Execution is refused if target window becomes un-minimized (IsIconic=False)",
        f"Execution allowed: {unminimized_ok}, Reason: {unminimized_reason}",
        not unminimized_ok and "NOT minimized" in unminimized_reason
    )

    # Restore minimization for cleanup
    user32.ShowWindow(hwnd1, 6)

    # Write summary JSON report
    report_path = os.path.join(os.path.dirname(__file__), "astro_input_matrix_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\nMatrix test complete! Report saved to {report_path}")
    total_passed = sum(1 for r in results if r["status"] == "PASS")
    total_tests = len(results)
    print(f"RESULT: {total_passed}/{total_tests} matrix checks PASSED.")

if __name__ == "__main__":
    run_matrix_tests()
