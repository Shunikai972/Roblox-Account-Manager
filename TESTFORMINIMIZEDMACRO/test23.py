import ctypes
import json
import time
import win32gui

user32 = ctypes.windll.user32

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101

with open("z_macro.json", "r", encoding="utf-8") as f:
    events = json.load(f)

def find_roblox():
    found = []

    def callback(hwnd, _):
        title = win32gui.GetWindowText(hwnd)
        if "Roblox" in title:
            found.append(hwnd)

    win32gui.EnumWindows(callback, None)
    return found

roblox = find_roblox()

if not roblox:
    print("Aucune fenêtre Roblox trouvée.")
    raise SystemExit

hwnd = roblox[0]

print("HWND :", hwnd)
print("Titre :", win32gui.GetWindowText(hwnd))
print("Minimisée :", win32gui.IsIconic(hwnd))
print("Replay dans 3 secondes...")
time.sleep(3)

previous = 0

for event in events:
    time.sleep(max(0, event["time"] - previous))

    msg = WM_KEYDOWN if event["event"] == "down" else WM_KEYUP

    user32.PostMessageW(
        hwnd,
        msg,
        0x5A,  # VK_Z
        0
    )

    previous = event["time"]

print("Terminé.")