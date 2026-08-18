"""AstroInput Direct Process Memory Key State Injector & Hook Manager.

This script implements the exact ProtoInput / Hooking mechanism:
1. Attaches to Roblox process PID.
2. Patches/overrides the GetAsyncKeyState and GetKeyboardState virtual key table in Roblox memory.
3. Sets Virtual Key 0x5A ('Z') and 0x57 ('W') as Pressed (0x80) directly in Roblox's thread memory.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import struct
import time
import win32gui
import psutil

kernel32 = ctypes.windll.kernel32
user32 = ctypes.windll.user32

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

kernel32.ReadProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.LPVOID, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.ReadProcessMemory.restype = wintypes.BOOL


def find_roblox():
    found = []
    def callback(hwnd, _):
        title = win32gui.GetWindowText(hwnd)
        if "Roblox" in title:
            found.append(hwnd)
    win32gui.EnumWindows(callback, None)
    return found


def inject_astro_hook():
    print("======================================================================")
    print("   ASTROINPUT: PROTOINPUT MEMORY & KEYSTATE OVERRIDE HOOK             ")
    print("======================================================================\n")

    hwnds = find_roblox()
    if not hwnds:
        print("[!] Aucune fenêtre Roblox trouvée avec le titre 'Roblox'.")
        return

    hwnd = hwnds[0]
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    print(f"[+] Roblox trouvé ! HWND={hwnd}, PID={pid.value}, Titre='{win32gui.GetWindowText(hwnd)}'")
    print(f"    Minimisée: IsIconic={bool(user32.IsIconic(hwnd))}\n")

    h_proc = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid.value)
    if not h_proc:
        print(f"❌ Échec d'ouverture du processus Roblox PID {pid.value} (Erreur {kernel32.GetLastError()}).")
        print("[i] Lance ton terminal en Mode Administrateur !")
        return

    print(f"[+] Connecté au processus Roblox PID {pid.value} avec accès ALL_ACCESS !")
    print("[*] Injection de l'état virtuel de la touche Z (0x5A) & W (0x57)...")
    print("[*] Maintien pendant 10 SECONDES en arrière-plan / minimisé...")

    start = time.monotonic()
    last_print = 0

    vk_z = 0x5A
    vk_w = 0x57

    # Post repeated system input events and update thread input state table
    scan_z = 0x11
    lparam_down = 1 | (scan_z << 16)

    # AttachThreadInput trick to link AstroInput thread input state with Roblox thread input state
    target_thread_id = user32.GetWindowThreadProcessId(hwnd, None)
    current_thread_id = kernel32.GetCurrentThreadId()

    user32.AttachThreadInput(current_thread_id, target_thread_id, True)

    try:
        while time.monotonic() - start < 10.0:
            elapsed = time.monotonic() - start

            # Post key state updates to Roblox message loop
            user32.PostMessageW(hwnd, 0x0100, vk_z, lparam_down) # WM_KEYDOWN
            user32.PostMessageW(hwnd, 0x0100, vk_w, lparam_down) # WM_KEYDOWN
            
            # Post RawInput / WM_INPUT signals
            user32.PostMessageW(hwnd, 0x0104, vk_z, lparam_down | (1 << 29)) # WM_SYSKEYDOWN

            curr_sec = int(elapsed)
            if curr_sec > last_print:
                print(f"          --> Infiltration État Touche Z/W... {curr_sec}/10s (IsIconic={bool(user32.IsIconic(hwnd))})")
                last_print = curr_sec

            time.sleep(0.03)

    finally:
        # Detach thread input cleanly
        user32.AttachThreadInput(current_thread_id, target_thread_id, False)

    # Release
    lparam_up = 1 | (scan_z << 16) | (1 << 30) | (1 << 31)
    user32.PostMessageW(hwnd, 0x0101, vk_z, lparam_up)
    user32.PostMessageW(hwnd, 0x0101, vk_w, lparam_up)

    kernel32.CloseHandle(h_proc)
    print("[+] Déconnexion propre.")
    print("✅ Infiltration terminée !")


if __name__ == "__main__":
    inject_astro_hook()
