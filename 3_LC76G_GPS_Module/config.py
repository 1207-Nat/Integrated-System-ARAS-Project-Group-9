# config.py
import serial

class config(object):
    def __init__(self, Baudrate=115200): 
        # Only initialize the serial port. 
        # Completely removed the gpiozero Pin 17/4 initialization to protect the NeoPixels!
        self.serial = serial.Serial("/dev/ttyAMA0", Baudrate, timeout=1)

    def Uart_SendByte(self, value): 
        self.serial.write(value) 
        
    def Uart_SendString(self, value): 
        self.serial.write(value)

    def Uart_ReceiveByte(self): 
        return self.serial.read(1)

    def Uart_Set_Baudrate(self, Baudrate):
         self.serial.baudrate = Baudrate