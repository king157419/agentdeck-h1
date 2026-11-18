import ctypes, sys
from ctypes import wintypes
from PIL import Image
u=ctypes.WinDLL("user32"); g=ctypes.WinDLL("gdi32"); u.SetProcessDPIAware()
h=u.FindWindowW(None, sys.argv[1])
r=wintypes.RECT(); u.GetWindowRect(h, ctypes.byref(r)); w,hh=r.right-r.left, r.bottom-r.top
hdc=u.GetWindowDC(h); mdc=g.CreateCompatibleDC(hdc); bmp=g.CreateCompatibleBitmap(hdc,w,hh); g.SelectObject(mdc,bmp)
ok=u.PrintWindow(h, mdc, 2)
class BMI(ctypes.Structure): _fields_=[("biSize",ctypes.c_uint32),("biWidth",ctypes.c_int32),("biHeight",ctypes.c_int32),("biPlanes",ctypes.c_uint16),("biBitCount",ctypes.c_uint16),("biCompression",ctypes.c_uint32),("a",ctypes.c_uint32*5)]
bi=BMI(); bi.biSize=40; bi.biWidth=w; bi.biHeight=-hh; bi.biPlanes=1; bi.biBitCount=32
buf=ctypes.create_string_buffer(w*hh*4); g.GetDIBits(mdc,bmp,0,hh,buf,ctypes.byref(bi),0)
Image.frombuffer("RGB",(w,hh),buf,"raw","BGRX",0,1).save(sys.argv[2]); print("PrintWindow",ok,w,hh)
