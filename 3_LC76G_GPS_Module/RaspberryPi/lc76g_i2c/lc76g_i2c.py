# -*- coding:utf-8 -*-
from micropyGPS import MicropyGPS
import RPi.GPIO as GPIO
from smbus import SMBus
import time
import os
import L76X

I2C_ADDRESS_CR_OR_CW=0x50
I2C_ADDRESS_R=0x54
I2C_ADDRESS_W=0x58

RESET_PIN=4

step1=[0x08,0x00,0x51,0xaa,0x04,0x00,0x00,0x00]
step2_cmd=[0x00,0x20,0x51,0xaa]
data_read_len=[]
step2=step2_cmd+data_read_len
data_len=0
os_cmd=''

def lc76g_i2c():
    data_s=''
    time.sleep(0.1)

    while 1:
        data_len=0
        i2c.write_i2c_block_data(I2C_ADDRESS_CR_OR_CW,step1[0],step1[1:])
        time.sleep(0.1)
        data_read_len=i2c.read_i2c_block_data(I2C_ADDRESS_R,0,4)
        step2=step2_cmd+data_read_len
        for i,l in enumerate(data_read_len):
            data_len |= l<<(i*8)
        #print(data_len)
        if data_len>0:
            break
        time.sleep(0.2)
    time.sleep(0.1)
    i2c.write_i2c_block_data(I2C_ADDRESS_CR_OR_CW,step2[0],step2[1:])
    time.sleep(0.01+data_len/100000)

    os_cmd='i2ctransfer -y 1 r{}@0x54'.format(data_len)
    data_b=os.popen(os_cmd)
    time.sleep(data_len/10000)
    data_l=(data_b.read()).split(' ',data_len)
    for i in data_l:
        if(i!=''):
            data_s+=chr(int(i,16))
        else:
            data_s+=' '
    data_b=os.system('i2cdetect -y 1')
    print(data_s)
    if data_s!='':
        for i in data_s:
            gps.update(i)
        Lat=gps.latitude[0]+gps.latitude[1]/100
        Lon=gps.longitude[0]+gps.longitude[1]/100
        if gps.latitude[2]!='N':
            Lat=Lat*(-1)
        if gps.longitude[2]!='E':
            Lon=Lon*(-1)
        x.L76X_Baidu_Coordinates(Lat,Lon)
        Time_H = gps.timestamp[0]
        Time_M = gps.timestamp[1]
        Time_S = gps.timestamp[2]
        print('BD09:',x.Lat_Baidu,',',x.Lon_Baidu)
        print('GCJ-02:',x.Lat_Goodle,',',x.Lon_Goodle)
        print('{:02.0f}:{:02.0f}:{:02.0f}'.format(Time_H,Time_M,Time_S))
    #time.sleep(0.1)

x=L76X.L76X()
gps=MicropyGPS(+8)
i2c=SMBus(1)
GPIO.setmode(GPIO.BCM)
GPIO.setup(RESET_PIN,GPIO.OUT)
GPIO.output(4,GPIO.LOW)
time.sleep(0.1)
GPIO.output(4,GPIO.HIGH)
time.sleep(1)
print('init success')

i=0
try:
    while 1:
        lc76g_i2c()
    print('\nEnding')
    GPIO.output(4,GPIO.LOW)
    time.sleep(0.1)
    GPIO.output(4,GPIO.HIGH)
    time.sleep(0.1)
    i2c.close()
    GPIO.cleanup()
    print('\n测试正常')
except(KeyboardInterrupt):
    print('\nEnding')
    GPIO.output(4,GPIO.LOW)
    time.sleep(0.1)
    GPIO.output(4,GPIO.HIGH)
    time.sleep(0.1)
    i2c.close()
    GPIO.cleanup()
    print('\nEnded')

    
