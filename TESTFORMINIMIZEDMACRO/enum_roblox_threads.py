import ctypes
from ctypes import wintypes
import psutil

user32 = ctypes.windll.user32

target_pid = 37660  # RobloxPlayerBeta.exe PID

print(f"Searching all thread windows for PID {target_pid}...")

def thread_cb(hwnd, lparam):
    length = user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    cls_buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls_buf, 256)
    print(f"  [THREAD WINDOW] HWND={hwnd} | Class='{cls_buf.value}' | Title='{buf.value}' | Iconic={user32.IsIconic(hwnd)}")
    return True

CB = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
cb_func = CB(thread_cb)

try:
    proc = psutil.Process(target_pid)
    for thread in proc.threads():
        user32.EnumThreadWindows(thread.id, cb_func, 0)
except Exception as e:
    print(f"Error enumerating thread windows: {e}")
