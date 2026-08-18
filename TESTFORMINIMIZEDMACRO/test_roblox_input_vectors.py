"""Roblox Multi-Vector Input Diagnostic Suite.

Tests 5 distinct Win32 input delivery mechanisms against a live target Roblox window
to determine exactly which message structures trigger Roblox UserInputService.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import struct
import time
import win32gui
import psutil

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_INPUT = 0x00FF
WM_ACTIVATE = 0x0006
WM_SETFOCUS = 0x0007

RID_INPUT = 0x10000003

class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]

class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [
        ("MakeCode", wintypes.WORD),
        ("Flags", wintypes.WORD),
        ("Reserved", wintypes.WORD),
        ("VKey", wintypes.WORD),
        ("Message", wintypes.UINT),
        ("ExtraInformation", wintypes.ULONG),
    ]

class RAWINPUT_KEYBOARD(ctypes.Structure):
    _fields_ = [
        ("header", RAWINPUTHEADER),
        ("keyboard", RAWKEYBOARD),
    ]


def find_roblox_windows():
    found = []
    def callback(hwnd, _):
        title = win32gui.GetWindowText(hwnd)
        if "Roblox" in title:
            found.append(hwnd)
    win32gui.EnumWindows(callback, None)
    return found


def test_input_vectors():
    print("======================================================================")
    print("   ASTROINPUT — ROBLOX INPUT VECTOR DIAGNOSTIC SUITE                 ")
    print("======================================================================\n")

    hwnds = find_roblox_windows()
    if not hwnds:
        print("[!] Aucune fenêtre Roblox trouvée avec le titre 'Roblox'.")
        return

    hwnd = hwnds[0]
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    print(f"[+] Roblox trouvé ! HWND={hwnd}, PID={pid.value}, Titre='{win32gui.GetWindowText(hwnd)}'")
    print(f"    Statut Minimisé: IsIconic={bool(user32.IsIconic(hwnd))}\n")

    vk_z = 0x5A  # 'Z'
    scan_z = 0x11

    # VECTOR 1: Standard WM_KEYDOWN with exact scan code & repeat bits
    print("[VECTOR 1] Testing WM_KEYDOWN + Scan Code 0x11...")
    lparam_down = 1 | (scan_z << 16)
    lparam_up = 1 | (scan_z << 16) | (1 << 30) | (1 << 31)

    user32.PostMessageW(hwnd, WM_KEYDOWN, vk_z, lparam_down)
    time.sleep(1.0)
    user32.PostMessageW(hwnd, WM_KEYUP, vk_z, lparam_up)
    print("          --> Envoyé.")

    # VECTOR 2: Synthetic WM_INPUT (RawInput Keyboard Packet)
    print("[VECTOR 2] Testing Synthetic WM_INPUT (RawInput Packet)...")
    raw_inp = RAWINPUT_KEYBOARD()
    raw_inp.header.dwType = 1  # RIM_TYPEKEYBOARD = 1
    raw_inp.header.dwSize = ctypes.sizeof(RAWINPUT_KEYBOARD)
    raw_inp.header.hDevice = wintypes.HANDLE(0x1234)
    raw_inp.header.wParam = 0  # RIM_INPUT

    raw_inp.keyboard.MakeCode = scan_z
    raw_inp.keyboard.Flags = 0  # RI_KEY_MAKE = 0
    raw_inp.keyboard.VKey = vk_z
    raw_inp.keyboard.Message = WM_KEYDOWN
    raw_inp.keyboard.ExtraInformation = 0

    # Send WM_INPUT via SendMessageCallback or PostMessage
    user32.PostMessageW(hwnd, WM_INPUT, 0, ctypes.addressof(raw_inp))
    time.sleep(1.0)
    raw_inp.keyboard.Flags = 1  # RI_KEY_BREAK = 1
    raw_inp.keyboard.Message = WM_KEYUP
    user32.PostMessageW(hwnd, WM_INPUT, 0, ctypes.addressof(raw_inp))
    print("          --> Envoyé.")

    # VECTOR 3: WM_SYSKEYDOWN (System key simulation)
    print("[VECTOR 3] Testing WM_SYSKEYDOWN (System Alt key state)...")
    lparam_sys_down = 1 | (scan_z << 16) | (1 << 29) # Alt down flag
    lparam_sys_up = 1 | (scan_z << 16) | (1 << 29) | (1 << 30) | (1 << 31)
    user32.PostMessageW(hwnd, WM_SYSKEYDOWN, vk_z, lparam_sys_down)
    time.sleep(1.0)
    user32.PostMessageW(hwnd, WM_SYSKEYUP, vk_z, lparam_sys_up)
    print("          --> Envoyé.")

    # VECTOR 4: Virtual Focus Signal + Key Loop
    print("[VECTOR 4] Testing Virtual WA_ACTIVE (0x0006) + KEYDOWN loop...")
    user32.PostMessageW(hwnd, WM_ACTIVATE, 1, 0) # WA_ACTIVE = 1
    user32.PostMessageW(hwnd, WM_SETFOCUS, 0, 0)

    start = time.monotonic()
    while time.monotonic() - start < 2.0:
        user32.PostMessageW(hwnd, WM_KEYDOWN, vk_z, lparam_down)
        time.sleep(0.02)
    user32.PostMessageW(hwnd, WM_KEYUP, vk_z, lparam_up)
    print("          --> Envoyé.")

    print("\n[DIAGNOSTIC FINISHED] Tous les vecteurs ont été émis vers la fenêtre Roblox.")


if __name__ == "__main__":
    test_input_vectors()
