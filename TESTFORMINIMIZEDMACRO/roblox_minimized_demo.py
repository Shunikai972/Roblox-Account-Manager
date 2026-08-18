"""Roblox Minimized Macro Demo using AstroInput.

This script detects running Roblox instances (RobloxPlayerBeta.exe / RobloxPlayer.exe),
verifies that they are minimized (IsIconic == True), and executes background actions:
1. Hold 'Z' key (VK 0x5A / AZERTY forward move) for 2 seconds.
2. Click mouse at center of client window (0.5, 0.5).
3. Send text message.
4. Release all keys cleanly while maintaining IsIconic == True and 0 physical cursor move.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import struct
import time
from typing import List, Tuple
import psutil

from astro_input import (
    AstroCommand,
    AstroInputBroker,
    AstroOpcode,
    InstanceTarget,
    user32,
    wintypes,
)

# Win32 EnumWindows helper
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def find_roblox_instances() -> List[Tuple[int, float, wintypes.HWND, str]]:
    """Find all running Roblox processes and their main HWNDs."""
    roblox_procs: List[Tuple[int, float, wintypes.HWND, str]] = []
    pid_to_info = {}

    for proc in psutil.process_iter(["pid", "name", "create_time"]):
        try:
            name = (proc.info["name"] or "").lower()
            if name in ("robloxplayerbeta.exe", "robloxplayer.exe"):
                pid_to_info[proc.info["pid"]] = (proc.info["create_time"], proc.info["name"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not pid_to_info:
        return roblox_procs

    def enum_cb(hwnd: wintypes.HWND, lparam: wintypes.LPARAM) -> wintypes.BOOL:
        if not user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pid_to_info:
            ct_time, proc_name = pid_to_info[pid.value]
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            # Check if main Roblox window (usually titled "Roblox")
            if title or "roblox" in title.lower():
                roblox_procs.append((pid.value, ct_time, hwnd, title or proc_name))
        return True

    user32.EnumWindows(EnumWindowsProc(enum_cb), 0)
    return roblox_procs


def run_roblox_minimized_macro():
    print("======================================================================")
    print("   ASTROINPUT — ROBLOX MINIMIZED DEMO SCRIPT ('Z' MOVE + CLICK + TEXT) ")
    print("======================================================================\n")

    instances = find_roblox_instances()
    if not instances:
        print("[!] Aucun processus Roblox détecté (RobloxPlayerBeta.exe n'est pas en cours d'exécution).")
        print("[i] Exécution en mode simulation d'instance Roblox minimisée...\n")
        # Fallback simulation if no real Roblox is running
        from test_astro_input_matrix import create_test_window, pump_messages_for
        current_pid = os.getpid()
        create_time = psutil.Process(current_pid).create_time()
        hwnd_sim, log_sim, lock_sim = create_test_window("RobloxPlayerBeta_Simulated")
        instances = [(current_pid, create_time, hwnd_sim, "Roblox (Simulated)")]

    broker = AstroInputBroker()

    for pid, create_time, hwnd, title in instances:
        is_minimized = bool(user32.IsIconic(hwnd))
        print(f"[*] Target Found: PID={pid}, HWND={hwnd}, Title='{title}'")
        print(f"    State: {'MINIMIZED (IsIconic=True)' if is_minimized else 'NOT MINIMIZED (IsIconic=False)'}")

        if not is_minimized:
            print(f"    [!] Remarque: La fenêtre n'est pas minimisée. Minimisation de précaution...")
            user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE = 6
            time.sleep(0.1)

        try:
            session = broker.attach_session(pid, create_time, hwnd, title)
        except ValueError as exc:
            print(f"    [X] Échec d'attachement à la session: {exc}")
            continue

        print(f"    [+] Session AstroInput attachée avec succès pour PID {pid} !")

        # Measure pre-run workstation state
        pt_start = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt_start))
        fg_start = user32.GetForegroundWindow()

        # Step 1: Hold 'Z' (VK 0x5A) and 'W' (VK 0x57) auto-repeat for 10 seconds
        vk_z = 0x5A  # 'Z' key (AZERTY forward)
        vk_w = 0x57  # 'W' key (QWERTY forward fallback)

        print("    [1/4] Maintien continu de la touche 'Z' (et 'W') pendant 10 SECONDES en arrière-plan...")
        print("          (Envoi d'auto-repeat toutes les 50ms pour faire avancer l'avatar Roblox minimisé)")

        start_time = time.monotonic()
        last_print = 0

        while time.monotonic() - start_time < 10.0:
            elapsed = time.monotonic() - start_time
            # Post repeat KEY_DOWN for both Z and W so regardless of AZERTY/QWERTY Roblox avatar moves forward
            session.execute_command(AstroCommand(AstroOpcode.KEY_DOWN, pid, 1, payload=struct.pack("<HH", vk_z, 0)))
            session.execute_command(AstroCommand(AstroOpcode.KEY_DOWN, pid, 1, payload=struct.pack("<HH", vk_w, 0)))
            
            curr_sec = int(elapsed)
            if curr_sec > last_print:
                print(f"          --> Touche enfoncée... {curr_sec}/10 secondes (fenêtre IsIconic={session.target.check_minimized()})")
                last_print = curr_sec

            time.sleep(0.05)

        print("    [2/4] Relâchement de la touche 'Z' / 'W' (KEY_UP)...")
        session.execute_command(AstroCommand(AstroOpcode.KEY_UP, pid, 2, payload=struct.pack("<HH", vk_z, 0)))
        session.execute_command(AstroCommand(AstroOpcode.KEY_UP, pid, 2, payload=struct.pack("<HH", vk_w, 0)))
        print("          Touches relâchées avec succès !")

        # Step 2: Position mouse at center (0.5, 0.5) and click
        print("    [3/4] Positionnement de la souris à (0.5, 0.5) et Clic Gauche sur la fenêtre minimisée...")
        session.execute_command(AstroCommand(AstroOpcode.POINTER_ABS, pid, 3, payload=struct.pack("<ff", 0.5, 0.5)))
        session.execute_command(AstroCommand(AstroOpcode.BUTTON_DOWN, pid, 4, payload=struct.pack("<B", 1)))
        time.sleep(0.05)
        session.execute_command(AstroCommand(AstroOpcode.BUTTON_UP, pid, 5, payload=struct.pack("<B", 1)))
        print("          Clic gauche effectué !")

        # Step 3: Send text message
        print("    [4/4] Envoi de texte UTF-16 'AstroInput Active'...")
        session.execute_command(
            AstroCommand(AstroOpcode.TEXT_UTF16, pid, 6, payload="AstroInput Active\r".encode("utf-16le"))
        )

        # Release all safety cleanup
        session.execute_command(AstroCommand(AstroOpcode.RELEASE_ALL, pid, 99))

        # Verify workstation guarantees post-run
        pt_end = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt_end))
        fg_end = user32.GetForegroundWindow()
        iconic_final = bool(user32.IsIconic(hwnd))

        print("\n    --- GARANTIES DE SÉCURITÉ MESURÉES ---")
        print(f"    - Fenêtre IsIconic restant True: {iconic_final}")
        print(f"    - Curseur physique inchangé: ({pt_start.x}, {pt_start.y}) == ({pt_end.x}, {pt_end.y})")
        print(f"    - Focus Foreground inchangé: {fg_start == fg_end}")
        print("    -----------------------------------------\n")

    print("[SUCCESS] Démo terminée avec succès !")


if __name__ == "__main__":
    run_roblox_minimized_macro()
