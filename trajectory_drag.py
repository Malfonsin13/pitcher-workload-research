import math

# set our constants

dt = 0.1 # change in time

g = 32.2 # gravity

cda = 0.24

cdb = 0.26

dv = 10.3

const = 0.000167

vel = 83.9

x = 0 # distance, in feet

t = 0 # starting time, in seconds

def hitball_func(v,a,y):

        # initialize our variables

        x = 0 # distance, in feet

        t = 0 # starting time, in seconds

        ax = 0
        ay = 0

        # v = 80 # velocity, in mph

        # a = 35 # angle, in degrees

        # y = 2 # height, in feet

        # calculate vx and vy

        vx = v*1.467*math.cos(math.radians(a))

        vy = v*1.467*math.sin(math.radians(a))

        while y > 0:
                vx = vx + ax * dt
                vy = vy + ay * dt
                v = math.sqrt(pow(vx,2)+pow(vy,2))
                vmph = v/1.467
                cd = cda+cdb/(1+math.exp((vmph-vel)/dv))
                ax = -const * cd * v * vx * g
                ay = -const * cd * v * vy * g - g
                x = x + vx*dt
                y = y + vy*dt
                t = t + dt

        return x , t

# ab, bb = hitball_func(80,35,3)

# print(ab)
# print(bb)
