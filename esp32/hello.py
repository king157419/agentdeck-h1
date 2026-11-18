import sys, machine, network, time, gc
print("MicroPython", sys.version, "| CPU", machine.freq() // 1000000, "MHz")
led = machine.Pin(2, machine.Pin.OUT)
for i in range(10):
    led.value(i % 2)
    time.sleep(0.15)
led.value(1)
w = network.WLAN(network.STA_IF)
w.active(True)
nets = sorted(w.scan(), key=lambda n: -n[3])
print("WiFi found:", len(nets))
for n in nets[:6]:
    print("  %-24s ch%-2d %ddBm" % (n[0].decode('utf-8', 'replace') or '(hidden)', n[2], n[3]))
gc.collect()
print("free RAM:", gc.mem_free(), "bytes")
