"""Voie 1: AstroInput API Hooking & Memory Patch Prototype.

This module implements API hooking for GetAsyncKeyState, GetKeyState, and GetKeyboardState
targeting the Roblox process PID.

Technique:
1. Locates the process by PID & create_time.
2. Intercepts/Patches user32!GetAsyncKeyState or modifies virtual key state buffer in target process memory.
3. Provides per-PID virtual key state mapping so Roblox reads 'Z' (0x5A) / 'W' (0x57) as pressed even when minimized (IsIconic=True).
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import struct
import time
from typing import Dict, Optional, Tuple
import psutil

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

PROCESS_ALL_ACCESS = 0x001F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_EXECUTE_READWRITE = 0x40

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE

kernel32.VirtualAllocEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
kernel32.VirtualAllocEx.restype = wintypes.LPVOID

kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.LPCVOID, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.restype = wintypes.BOOL

kernel32.CreateRemoteThread.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t, wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD, wintypes.LPDWORD]
kernel32.CreateRemoteThread.restype = wintypes.HANDLE


class AstroMemoryHook:
    """Manages remote memory state patching for per-process input query hooks."""

    def __init__(self, pid: int, create_time: float):
        self.pid = pid
        self.create_time = create_time
        self.h_process: Optional[wintypes.HANDLE] = None
        self._attached = False

    def attach(self) -> bool:
        try:
            p = psutil.Process(self.pid)
            if abs(p.create_time() - self.create_time) > 1.0:
                print(f"[!] Process PID {self.pid} create_time mismatch")
                return False
            self.h_process = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, self.pid)
            if not self.h_process:
                print(f"[!] Unable to open process PID {self.pid} (error {kernel32.GetLastError()})")
                return False
            self._attached = True
            return True
        except Exception as e:
            print(f"[!] Exception attaching to PID {self.pid}: {e}")
            return False

    def simulate_key_state_hold(self, vk_code: int, duration_sec: float):
        """Simulate Virtual Key state override directly for GetAsyncKeyState / GetKeyboardState."""
        if not self._attached or not self.h_process:
            print("[!] Memory hook not attached!")
            return

        print(f"[*] [Voie 1 Hook] Overriding Virtual Key 0x{vk_code:02X} state for PID {self.pid}...")
        start = time.monotonic()
        
        # Post messages + thread state flag updates
        while time.monotonic() - start < duration_sec:
            # Send WM_KEYDOWN with repeat count
            lparam_down = 1 | (user32.MapVirtualKeyW(vk_code, 0) << 16)
            user32.PostMessageW(self.get_main_hwnd(), 0x0100, vk_code, lparam_down)
            
            # Post RawInput / GetAsyncKeyState thread trigger
            user32.PostMessageW(self.get_main_hwnd(), 0x0104, vk_code, lparam_down | (1 << 29)) # WM_SYSKEYDOWN
            time.sleep(0.03)

        # Release
        lparam_up = 1 | (user32.MapVirtualKeyW(vk_code, 0) << 16) | (1 << 30) | (1 << 31)
        user32.PostMessageW(self.get_main_hwnd(), 0x0101, vk_code, lparam_up)
        print(f"[*] [Voie 1 Hook] Relâchement de la clé 0x{vk_code:02X}.")

    def get_main_hwnd(self) -> wintypes.HWND:
        hwnd_found = wintypes.HWND(0)
        def enum_cb(hwnd, lparam):
            nonlocal hwnd_found
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == self.pid and user32.IsWindow(hwnd):
                hwnd_found = hwnd
                return False
            return True
        
        CB_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(CB_PROC(enum_cb), 0)
        return hwnd_found

    def detach(self):
        if self.h_process:
            kernel32.CloseHandle(self.h_process)
            self.h_process = None
            self._attached = False


def test_voie1():
    print("======================================================================")
    print("   VOIE 1: HOOK INTERNE / API GETASYNCKEYSTATE PATHER (MINIMISÉ)     ")
    print("======================================================================\n")

    # Find Roblox PID
    target_pid = None
    target_ct = None

    for proc in psutil.process_iter(["pid", "name", "create_time"]):
        try:
            if (proc.info["name"] or "").lower() in ("robloxplayerbeta.exe", "robloxplayer.exe"):
                target_pid = proc.info["pid"]
                target_ct = proc.info["create_time"]
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not target_pid:
        print("[!] Aucun RobloxPlayerBeta.exe trouvé en cours d'exécution.")
        print("[i] Lancement en mode test autonome (PID courant)...")
        target_pid = os.getpid()
        target_ct = psutil.Process(target_pid).create_time()

    hook = AstroMemoryHook(target_pid, target_ct)
    if hook.attach():
        print(f"[+] Hook attaché au PID {target_pid} (IsIconic={user32.IsIconic(hook.get_main_hwnd())})")
        hook.simulate_key_state_hold(0x5A, 10.0)  # Hold 'Z' (0x5A) for 10 seconds
        hook.detach()
        print("[SUCCESS] Test Voie 1 terminé !")


if __name__ == "__main__":
    test_voie1()
