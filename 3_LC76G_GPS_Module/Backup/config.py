# config.py
import serial
from gpiozero import DigitalInputDevice, DigitalOutputDevice

class config(object):
    FORCE_PIN   = 17
    STANDBY_PIN = 4

    def __init__(ser, Baudrate = 115200): # Updated default to 115200
        ser.serial = serial.Serial("/dev/ttyAMA0", Baudrate, timeout=1)
        
        # Fixed: Added active_state=True to resolve the PinInvalidState error
        ser.force_gpio = DigitalInputDevice(ser.FORCE_PIN, pull_up=None, active_state=True)
        ser.standby_gpio = DigitalOutputDevice(ser.STANDBY_PIN, initial_value=True)

    def Uart_SendByte(ser, value): 
        ser.serial.write(value) 
        
    def Uart_SendString(ser, value): 
        ser.serial.write(value)

    def Uart_ReceiveByte(ser): 
        return ser.serial.read(1)

    def Uart_Set_Baudrate(ser, Baudrate):
         ser.serial.baudrate = Baudrate