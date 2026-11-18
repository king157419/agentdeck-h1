import ctypes, sys
from ctypes import wintypes
from PIL import ImageGrab
u=ctypes.WinDLL("user32"); u.SetProcessDPIAware()
h=u.FindWindowW(None, "AgentDeck Virtual Device")
r=wintypes.RECT(); u.GetWindowRect(h, ctypes.byref(r))
print(h, r.left, r.top, r.right, r.bottom)
ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom)).save(sys.argv[1])
