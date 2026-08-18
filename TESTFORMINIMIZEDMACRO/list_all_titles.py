import ctypes
from ctypes import wintypes
import psutil

user32 = ctypes.windll.user32

# Look up by psutil processes first
for p in psutil.process_iter(['pid', 'name']):
    name = (p.info['name'] or '').lower()
    if 'roblox' in name:
        print(f"[PSUTIL] Found Roblox Process: PID={p.info['pid']}, Name='{p.info['name']}'")

# Look up windows using GetWindow
hwnd = user32.GetTopWindow(0)
while hwnd:
    length = user32.GetWindowTextLengthW(hwnd)
    if length > 0:
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if "roblox" in title.lower() or "account" in title.lower() or "code" in title.lower() or "cmd" in title.lower() or "powershell" in title.lower():
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            cls_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls_buf, 256)
            print(f"HWND={hwnd} | PID={pid.value} | Class='{cls_buf.value}' | Title='{title}' | Iconic={user32.IsIconic(hwnd)}")
    hwnd = user32.GetWindow(hwnd, 2)  # GW_HWNDNEXT = 2
