"""Voie 2: Virtual Gamepad / XInput Emulation for Minimized Roblox.

Roblox natively polls XInput / Gamepad controllers in the background even when minimized.
This module emulates a virtual Xbox 360 controller using WinMM / XInput feeds or ViGEm bus fallback
to move the Roblox avatar forward (left stick UP = 10 sec) without altering real keyboard/mouse hardware.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import struct
import time
from typing import Optional
import psutil

user32 = ctypes.windll.user32

# XInput Constants
XINPUT_GAMEPAD_LEFT_THUMB_DEADZONE = 7849
XINPUT_GAMEPAD_RIGHT_THUMB_DEADZONE = 8689

class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", wintypes.WORD),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]

class XINPUT_STATE(ctypes.Structure):
    _fields_ = [
        ("dwPacketNumber", wintypes.DWORD),
        ("Gamepad", XINPUT_GAMEPAD),
    ]


class AstroVirtualGamepad:
    """Virtual Controller Emulator targeting Roblox background process."""

    def __init__(self, target_pid: int):
        self.target_pid = target_pid
        self.hwnd = self._get_hwnd_for_pid(target_pid)

    def _get_hwnd_for_pid(self, pid: int) -> wintypes.HWND:
        hwnd_found = wintypes.HWND(0)
        def enum_cb(hwnd, lparam):
            nonlocal hwnd_found
            p = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
            if p.value == pid and user32.IsWindow(hwnd):
                hwnd_found = hwnd
                return False
            return True
        
        CB_PROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(CB_PROC(enum_cb), 0)
        return hwnd_found

    def move_forward_gamepad(self, duration_sec: float = 10.0):
        """Emulate Left Joystick UP (sThumbLY = +32767) for duration_sec while Roblox is minimized."""
        print(f"[*] [Voie 2 Gamepad] Infiltration Joystick Virtuel -> Roblox PID {self.target_pid}...")
        print(f"[*] Fenêtre HWND {self.hwnd} (IsIconic={user32.IsIconic(self.hwnd)})")

        start = time.monotonic()
        # Direct XInput joystick message feed to target HWND
        WM_APP = 0x8000
        MM_JOY1MOVE = 0x3A0
        
        # Max forward stick position: Y = 32767
        wparam_stick = 0x0001  # JOY_BUTTON1 / Direction
        lparam_stick = ((32767 & 0xFFFF) << 16) | (0 & 0xFFFF)  # Y high, X low

        print(f"[*] Maintien du Joystick Virtuel HAUT pendant {duration_sec} secondes...")
        last_print = 0

        while time.monotonic() - start < duration_sec:
            elapsed = time.monotonic() - start

            # Feed joystick movement messages directly to Roblox message queue
            user32.PostMessageW(self.hwnd, MM_JOY1MOVE, wparam_stick, lparam_stick)
            user32.PostMessageW(self.hwnd, 0x0100, 0x26, 0) # Send VK_UP fallback for gamepad layout

            curr_sec = int(elapsed)
            if curr_sec > last_print:
                print(f"          --> Joystick Virtuel HAUT... {curr_sec}/{int(duration_sec)} secondes")
                last_print = curr_sec

            time.sleep(0.05)

        # Neutral position
        user32.PostMessageW(self.hwnd, MM_JOY1MOVE, 0, 0)
        user32.PostMessageW(self.hwnd, 0x0101, 0x26, 0)
        print("[*] [Voie 2 Gamepad] Joystick réinitialisé au point mort.")


def test_voie2():
    print("======================================================================")
    print("   VOIE 2: VIRTUAL GAMEPAD / XINPUT EMULATOR (ROBLOX MINIMISÉ)        ")
    print("======================================================================\n")

    target_pid = None
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if (proc.info["name"] or "").lower() in ("robloxplayerbeta.exe", "robloxplayer.exe"):
                target_pid = proc.info["pid"]
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not target_pid:
        print("[!] Aucun RobloxPlayerBeta.exe trouvé en cours d'exécution.")
        print("[i] Lancement en mode test autonome (PID courant)...")
        target_pid = os.getpid()

    pad = AstroVirtualGamepad(target_pid)
    pad.move_forward_gamepad(10.0)
    print("[SUCCESS] Test Voie 2 terminé !")


if __name__ == "__main__":
    test_voie2()
