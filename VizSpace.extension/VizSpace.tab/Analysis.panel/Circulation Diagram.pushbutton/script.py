import serial, time

ser = serial.Serial("COM9", 9600, timeout=1)
time.sleep(2)
print("Connected to COM9")

while True:
    line = ser.readline().decode(errors="ignore").strip()
    if line:
        print("RX:", line)