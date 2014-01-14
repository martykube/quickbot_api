#!/usr/bin/python
"""
@brief QuickBot class for Beaglebone Black

@author Rowland O'Flaherty 
@date 08/27/2013
"""
import os
import sys
import time
import math
import re
import socket
import threading

import Adafruit_BBIO.GPIO as GPIO
import Adafruit_BBIO.PWM as PWM
import Adafruit_BBIO.ADC as ADC


# Constants
LEFT = 0
RIGHT = 1
MIN = 0
MAX = 1

ENC_VAL = [0, 0]
ENC_VAL_LOCK = threading.Lock()
ENC_VEL = [0, 0]
ENC_VEL_LOCK = threading.Lock()
ENC_DIR = [0, 0]
ENC_DIR_LOCK = threading.Lock()
RUN_FLAG = True
RUN_FLAG_LOCK = threading.Lock()

def convertHEXtoDEC(hexString, N):
    # Return 2's compliment of hexString
    for hexChar in hexString:
        asciiNum = ord(hexChar)
        if not ((asciiNum >= 48 and asciiNum <= 57) or \
             (asciiNum >= 65 and asciiNum <= 70) or \
             (asciiNum >= 97 and asciiNum <= 102)):
             val = float('nan')
             return val

    if len(hexString) == N:
        val = int(hexString, 16)
        bits = 4*len(hexString)
        if  (val & (1<<(bits-1))) != 0:
            val = val - (1<<bits)
        return val

class QuickBot():
    """The QuickBot Class"""

    # === Class Properties ===
    # Parameters
    sampleTime = 50.0 / 1000.0

    # Pins
    ledPin = 'USR1'

    # Motor Pins -- (LEFT, RIGHT)
    dir1Pin = ('P8_12', 'P8_14')
    dir2Pin = ('P8_10', 'P8_16')
    pwmPin = ('P9_14', 'P9_16')

    # ADC Pins
    irPin = ('P9_35', 'P9_33', 'P9_40', 'P9_36', 'P9_38')
    encoderPin = ('P9_39','P9_37')

    # State -- (LEFT, RIGHT)
    pwm = [0, 0]
    irVal = [0, 0, 0, 0, 0]
    encoderVal = [0, 0]
    encoderVel = [0.0, 0.0]

    # Constraints
    pwmLimits = [-100, 100] # [min, max]

    # Variables
    ledFlag = True
    cmdBuffer = ''

    # UDP
    baseIP = '192.168.7.1'
    robotIP = '192.168.7.2'

    port = 5005
    robotSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    robotSocket.setblocking(False)

    # === Class Methods ===
    # Constructor
    def __init__(self, baseIP, robotIP):
        
        # Initialize GPIO pins
        GPIO.setup(self.dir1Pin[LEFT], GPIO.OUT)
        GPIO.setup(self.dir2Pin[LEFT], GPIO.OUT)
        GPIO.setup(self.dir1Pin[RIGHT], GPIO.OUT)
        GPIO.setup(self.dir2Pin[RIGHT], GPIO.OUT)

        GPIO.setup(self.ledPin, GPIO.OUT)

        # Initialize PWM pins: PWM.start(channel, duty, freq=2000, polarity=0)
        PWM.start(self.pwmPin[LEFT], 0)
        PWM.start(self.pwmPin[RIGHT], 0)

        # Set motor speed to 0
        self.setPWM([0, 0])

        # Initialize ADC
        ADC.setup()

        # Set IP addresses
        self.baseIP = baseIP
        self.robotIP = robotIP
        self.robotSocket.bind((self.robotIP, self.port))
        
        # Initialize encoders
        self.encoders = Encoders(self.encoderPin)

    # Getters and Setters
    def setPWM(self, pwm):
        global ENC_DIR
        # [leftSpeed, rightSpeed]: 0 is off, caps at min and max values

        self.pwm[LEFT] = min(max(pwm[LEFT], self.pwmLimits[MIN]), self.pwmLimits[MAX])
        self.pwm[RIGHT] = min(max(pwm[RIGHT], self.pwmLimits[MIN]), self.pwmLimits[MAX])
        print 'Setting motor PWMs to: left = ' + str(self.pwm[LEFT]) + ' and right = ' + str(self.pwm[RIGHT])

        # Left motor
        if self.pwm[LEFT] > 0:
            ENC_DIR_LOCK.acquire()
            ENC_DIR[LEFT] = 1
            ENC_DIR_LOCK.release()
            GPIO.output(self.dir1Pin[LEFT], GPIO.LOW)
            GPIO.output(self.dir2Pin[LEFT], GPIO.HIGH)
            PWM.set_duty_cycle(self.pwmPin[LEFT], abs(self.pwm[LEFT]))
        elif self.pwm[LEFT] < 0:
            ENC_DIR_LOCK.acquire()
            ENC_DIR[LEFT] = -1
            ENC_DIR_LOCK.release()
            GPIO.output(self.dir1Pin[LEFT], GPIO.HIGH)
            GPIO.output(self.dir2Pin[LEFT], GPIO.LOW)
            PWM.set_duty_cycle(self.pwmPin[LEFT], abs(self.pwm[LEFT]))
        else:
            GPIO.output(self.dir1Pin[LEFT], GPIO.LOW)
            GPIO.output(self.dir2Pin[LEFT], GPIO.LOW)
            PWM.set_duty_cycle(self.pwmPin[LEFT], 0)

        # Right motor
        if self.pwm[RIGHT] > 0:
            ENC_DIR_LOCK.acquire()
            ENC_DIR[RIGHT] = 1
            ENC_DIR_LOCK.release()
            GPIO.output(self.dir1Pin[RIGHT], GPIO.LOW)
            GPIO.output(self.dir2Pin[RIGHT], GPIO.HIGH)
            PWM.set_duty_cycle(self.pwmPin[RIGHT], abs(self.pwm[RIGHT]))
        elif self.pwm[RIGHT] < 0:
            ENC_DIR_LOCK.acquire()
            ENC_DIR[RIGHT] = -1
            ENC_DIR_LOCK.release()
            GPIO.output(self.dir1Pin[RIGHT], GPIO.HIGH)
            GPIO.output(self.dir2Pin[RIGHT], GPIO.LOW)
            PWM.set_duty_cycle(self.pwmPin[RIGHT], abs(self.pwm[RIGHT]))
        else:
            GPIO.output(self.dir1Pin[RIGHT], GPIO.LOW)
            GPIO.output(self.dir2Pin[RIGHT], GPIO.LOW)
            PWM.set_duty_cycle(self.pwmPin[RIGHT], 0)

    # Methods
    def run(self):
        global RUN_FLAG
        self.encoders.start()
        
        while RUN_FLAG == True:
            self.update()
            # Flash BBB LED
            if self.ledFlag == True:
                self.ledFlag = False
                GPIO.output(self.ledPin, GPIO.HIGH)
            else:
                self.ledFlag = True
                GPIO.output(self.ledPin, GPIO.LOW)
        self.cleanup()        
        return

    def cleanup(self):
        print "Clean up"
        self.setPWM([0, 0])
        self.robotSocket.close()
        GPIO.cleanup()
        PWM.cleanup()

    def update(self):
#         self.readIRValues()
        self.readEncoderValues()
        self.parseCmdBuffer()

    def parseCmdBuffer(self):
        global RUN_FLAG
        try:
            line = self.robotSocket.recv(1024)
        except socket.error as msg:
            #print msg
            return
        
        self.cmdBuffer += line

        bufferPattern = r'\$[^\$\*]*?\*' # String contained within $ and * symbols with no $ or * symbols in it
        bufferRegex = re.compile(bufferPattern)
        bufferResult = bufferRegex.search(self.cmdBuffer)

        if bufferResult:
            msg = bufferResult.group()
            print msg
            self.cmdBuffer = ''

            msgPattern = r'\$(?P<CMD>[A-Z]{3,})(?P<SET>=?)(?P<QUERY>\??)(?(2)(?P<ARGS>.*)).*\*'
            msgRegex = re.compile(msgPattern)
            msgResult = msgRegex.search(msg)

            if msgResult.group('CMD') == 'CHECK':
                self.robotSocket.sendto('Hello from QuickBot\n',(self.baseIP, self.port))

            elif msgResult.group('CMD') == 'PWM':
                if msgResult.group('QUERY'):
                    self.robotSocket.sendto(str(self.pwm) + '\n',(self.baseIP, self.port))

                elif msgResult.group('SET') and msgResult.group('ARGS'):
                    args = msgResult.group('ARGS')
                    pwmArgPattern = r'(?P<LEFT>[-]?\d+),(?P<RIGHT>[-]?\d+)'
                    pwmRegex = re.compile(pwmArgPattern)
                    pwmResult = pwmRegex.match(args)
                    if pwmResult:
                        pwm = [int(pwmRegex.match(args).group('LEFT')), \
                        int(pwmRegex.match(args).group('RIGHT'))]
                        self.setPWM(pwm)

            elif msgResult.group('CMD') == 'IRVAL':
                if msgResult.group('QUERY'):
                    reply = '[' + ', '.join(map(str, self.irVal)) + ']'
                    print 'Sending: ' + reply
                    self.robotSocket.sendto(reply + '\n', (self.baseIP, self.port))

            elif msgResult.group('CMD') == 'ENVAL':
                if msgResult.group('QUERY'):
                    reply = '[' + ', '.join(map(str, self.encoderVal)) + ']'
                    print 'Sending: ' + reply
                    self.robotSocket.sendto(reply + '\n', (self.baseIP, self.port))

            elif msgResult.group('CMD') == 'ENVEL':
                if msgResult.group('QUERY'):
                    reply = '[' + ', '.join(map(str, self.encoderVel)) + ']'
                    print 'Sending: ' + reply
                    self.robotSocket.sendto(reply + '\n', (self.baseIP, self.port))

            elif msgResult.group('CMD') == 'UPDATE':
                if msgResult.group('SET') and msgResult.group('ARGS'):
                    args = msgResult.group('ARGS')
                    pwmArgPattern = r'(?P<LEFT>[-]?\d+),(?P<RIGHT>[-]?\d+)'
                    pwmRegex = re.compile(pwmArgPattern)
                    pwmResult = pwmRegex.match(args)
                    if pwmResult:
                        pwm = [int(pwmRegex.match(args).group('LEFT')), \
                        int(pwmRegex.match(args).group('RIGHT'))]
                        self.setPWM(pwm)

                    reply = '[' + ', '.join(map(str, self.encoderVal)) + ', ' \
                      + ', '.join(map(str, self.encoderVel)) + ']'
                    print 'Sending: ' + reply
                    self.robotSocket.sendto(reply + '\n', (self.baseIP, self.port))

            elif msgResult.group('CMD') == 'END':
                print 'Quitting QuickBot run loop'
                RUN_FLAG_LOCK.acquire()
                RUN_FLAG = False
                RUN_FLAG_LOCK.release()

    def readIRValues(self):
        for i in range(0,len(self.irPin)):
            readFlag =True
            while readFlag:
                try:
                    self.irVal[i] = ADC.read_raw(self.irPin[i])
                    readFlag = False
                except:
                    continue
            
            # print "IR " + str(i) + ": " + str(self.irVal[i])
            
    def readEncoderValues(self):
        self.encoderVal[LEFT] = ENC_VAL[LEFT]
        self.encoderVel[LEFT] = ENC_VEL[LEFT]
        self.encoderVal[RIGHT] = ENC_VAL[RIGHT]
        self.encoderVel[RIGHT] = ENC_VEL[RIGHT]
#         print "ENC_LEFT_VAL: " + str(ENC_VAL[LEFT]) + "  ENC_LEFT_VEL: " + str(ENC_VEL[LEFT]) + \
#               " ENC_RIGHT_VAL: " + str(ENC_VAL[RIGHT]) + "  ENC_RIGHT_VEL: " + str(ENC_VEL[RIGHT])
            

class Encoders(threading.Thread):
    """The Encoders Class"""
    
    # === Class Properties ===
    # Parameters
    writeFlag = False
    sampleTime = 0.001
    threshold = [1325, 1325]
    tickPerRev = 16
    
    # State
    t0 = -1
    t = 0
    tickTime = [-1, -1]
    tickPrevTime = [-1, -1]
    val = [-1, -1]
    cog = [-1, -1]
    pos = [0, 0]
    vel = [0, 0]
    
    if writeFlag:
        size = 1000
          
        timeLeftList = [0] * size
        valLeftList = [0] * size
        cogLeftList = [0] * size
          
        timeRightList = [0] * size
        valRightList = [0] * size
        cogRightList = [0] * size
    
    
    # === Class Methods ===
    # Constructor
    def __init__(self,pin=('P9_39', 'P9_37')):
        
        # Initialize thread
        threading.Thread.__init__(self)
        
        # Set properties
        self.pin = pin

    # Methods
    def run(self):
        global RUN_FLAG
        global ENC_VAL
        cnt = 0
        self.t0 = time.time()
        
        while RUN_FLAG:
            self.sample(LEFT)
            
            if self.writeFlag:
                self.timeLeftList[cnt] = self.t
                self.valLeftList[cnt] = self.val[LEFT]
                self.cogLeftList[cnt] = self.cog[LEFT]
            
            time.sleep(self.sampleTime)
            
            self.sample(RIGHT)
            
            if self.writeFlag:
                self.timeRightList[cnt] = self.t
                self.valRightList[cnt] = self.val[RIGHT]
                self.cogRightList[cnt] = self.cog[RIGHT]
                
            time.sleep(self.sampleTime)
                
            if self.writeFlag:
                cnt = cnt + 1
                if cnt == self.size:
                    print 'Quitting b/c ' + str(self.size) + ' updates occured'
                    RUN_FLAG_LOCK.acquire()
                    RUN_FLAG = False
                    RUN_FLAG_LOCK.release()
            
            
            
        if self.writeFlag:
            self.writeToFile()
        
        return
    
    def sample(self,side):
        self.t = time.time() - self.t0
        self.val[side] = ADC.read_raw(self.pin[side])
        
#         readFlag =True
#         while readFlag:
#             try:
#                 self.t = time.time() - self.t0
#                 self.val[side] = ADC.read_raw(self.pin[side])
#                 readFlag = False
#             except:
#                 continue
        
        cogPrev = self.cog[side]
        if self.val[side] >= self.threshold[side]:
            self.cog[side] = 1
        else:
            self.cog[side] = 0
         
        if cogPrev == 0 and self.cog[side] == 1:
            # Tick
            dir = ENC_DIR[side]
            self.tickPrevTime[side] = self.tickTime[side]
            self.tickTime[side] = self.t
            self.pos[side] = self.pos[side] + dir
            if self.tickPrevTime[side] != -1:
                self.vel[side] = dir * (self.tickTime[side] - self.tickPrevTime[side])**(-1.0) / (self.tickPerRev)
                
            ENC_VAL_LOCK.acquire()
            ENC_VAL[side] = self.pos[side]
            ENC_VAL_LOCK.release()
            ENC_VEL_LOCK.acquire()
            ENC_VEL[side] = self.vel[side]
            ENC_VEL_LOCK.release()
            
            
    def writeToFile(self):
        matrix = map(list, zip(*[self.timeLeftList, self.valLeftList, self.cogLeftList, 
                                 self.timeRightList, self.valRightList, self.cogRightList]))
        s = [[str(e) for e in row] for row in matrix]
        lens = [len(max(col, key=len)) for col in zip(*s)]
        fmt = '\t'.join('{{:{}}}'.format(x) for x in lens)
        table = [fmt.format(*row) for row in s]
        f = open('output.txt','w')
        f.write('\n'.join(table))
        f.close()
            