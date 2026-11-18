import ctypes, sys, time
u = ctypes.WinDLL("user32")
vk = int(sys.argv[1], 16)
u.keybd_event(vk, 0, 0, 0); time.sleep(0.05); u.keybd_event(vk, 0, 2, 0)
