"""Native WinMM Joystick Controller for Minimized Roblox.

Uses exact find_roblox logic from test23.py to target HWND 725934 / Roblox window.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import time
import win32gui
import psutil

user32 = ctypes.windll.user32

MM_JOY1MOVE = 0x3A0
JOY_BUTTON1 = 0x0001


def find_roblox():
    found = []

    def callback(hwnd, _):
        title = win32gui.GetWindowText(hwnd)
        if "Roblox" in title:
            found.append(hwnd)

    win32gui.EnumWindows(callback, None)
    return found


def run_minimized_joystick_demo(duration_sec: float = 10.0):
    print("======================================================================")
    print("   VOIE 3B: EMBEDDED WINMM JOYSTICK FEED FOR MINIMIZED ROBLOX         ")
    print("======================================================================\n")

    hwnds = find_roblox()
    if not hwnds:
        print("[!] Aucune fenêtre Roblox trouvée avec le titre 'Roblox'.")
        return

    hwnd = hwnds[0]
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    is_min = bool(user32.IsIconic(hwnd))
    print(f"[+] Roblox Détecté avec Succès ! HWND={hwnd}, Titre='{win32gui.GetWindowText(hwnd)}', PID={pid.value}")
    print(f"    Statut Minimisé: IsIconic={is_min}")

    print(f"\n[*] Maintien du Stick Analogique Virtuel HAUT (Avancer) pendant {duration_sec} secondes...")

    y_top = 0          # 0 = Top / Forward
    x_center = 32768   # 32768 = Center
    lparam_joystick = ((y_top & 0xFFFF) << 16) | (x_center & 0xFFFF)
    wparam_flags = JOY_BUTTON1

    start = time.monotonic()
    last_print = 0

    while time.monotonic() - start < duration_sec:
        elapsed = time.monotonic() - start
        
        # Post MM_JOY1MOVE directly to target Roblox HWND
        user32.PostMessageW(hwnd, MM_JOY1MOVE, wparam_flags, lparam_joystick)
        
        curr_sec = int(elapsed)
        if curr_sec > last_print:
            print(f"          --> Stick HAUT injecté... {curr_sec}/{int(duration_sec)}s (IsIconic={user32.IsIconic(hwnd)})")
            last_print = curr_sec

        time.sleep(0.05)

    # Reset joystick to neutral center
    lparam_center = ((32768 & 0xFFFF) << 16) | (32768 & 0xFFFF)
    user32.PostMessageW(hwnd, MM_JOY1MOVE, 0, lparam_center)
    print("[+] Stick réinitialisé au centre (Stop).")
    print("[SUCCESS] Test Voie 3B exécuté !")


if __name__ == "__main__":
    run_minimized_joystick_demo(10.0)
