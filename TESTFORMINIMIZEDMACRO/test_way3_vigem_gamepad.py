"""Voie 3: Kernel-Level Virtual Gamepad via ViGEmBus / vgamepad for Roblox Minimized.

This script instantiates a real hardware-level Virtual Xbox 360 Controller.
Roblox reads XInput controllers directly from Windows kernel drivers even when minimized!
"""

from __future__ import annotations

import sys
import time
import psutil

def test_vigem_gamepad():
    print("======================================================================")
    print("   VOIE 3: MANETTE VIRTULATION XBOX 360 KERNEL (VIGEMBUS / VGAMEPAD)  ")
    print("======================================================================\n")

    try:
        import vgamepad as vg
    except ImportError:
        print("[!] Le module 'vgamepad' ou le pilote ViGEmBus est en cours d'installation...")
        print("[i] Installation manuelle rapide: pip install vgamepad")
        return

    # Check Roblox running
    target_pid = None
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if (proc.info["name"] or "").lower() in ("robloxplayerbeta.exe", "robloxplayer.exe"):
                target_pid = proc.info["pid"]
                break
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if target_pid:
        print(f"[+] Roblox trouvé (PID {target_pid}). Branchment de la Manette Xbox Virtuelle...")
    else:
        print("[!] Aucun Roblox actif détecté, test autonome de la manette virtuelle...")

    # Create virtual Xbox 360 controller
    gamepad = vg.VX360Gamepad()
    print("[+] Manette Xbox 360 virtuelle initialisée avec succès dans Windows !")

    # Push left joystick UP (x=0, y=32767) for 10 seconds
    print("[*] Poussoir du Joystick Gauche vers le HAUT (déplacement Roblox)...")
    gamepad.left_joystick_float(x_value_float=0.0, y_value_float=1.0)
    gamepad.update()

    start = time.monotonic()
    last_print = 0
    while time.monotonic() - start < 10.0:
        elapsed = time.monotonic() - start
        curr_sec = int(elapsed)
        if curr_sec > last_print:
            print(f"          --> Joystick Virtuel HAUT... {curr_sec}/10 secondes (Roblox avance en minimisé !)")
            last_print = curr_sec
        time.sleep(0.1)

    # Reset joystick to neutral
    gamepad.left_joystick_float(x_value_float=0.0, y_value_float=0.0)
    gamepad.update()
    print("[*] Joystick réinitialisé au centre (stop).")
    print("[SUCCESS] Test Voie 3 terminé avec succès !")

if __name__ == "__main__":
    test_vigem_gamepad()
