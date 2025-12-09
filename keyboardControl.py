from djitellopy import tello
from time import sleep
import key_press_module as kp
import cv2 
from datetime import datetime as dt
global img 

kp.init()
drone = tello.Tello()
# drone.connect()
drone.stream_on()

def getKeyboardInput():
    lr, fb, ud, yv = 0, 0, 0, 0
    speed = 50
    if kp.get_key_events("LEFT"): lr = -speed
    elif kp.get_key_events("RIGHT"):lr = speed

    if kp.get_key_events("UP"): fb = speed
    elif kp.get_key_events("DOWN"):fb = -speed

    if kp.get_key_events("w"): ud = speed
    elif kp.get_key_events("s"): ud = -speed

    if kp.get_key_events("a"): yv = -speed
    elif kp.get_key_events("d"): yv = speed

    if kp.get_key_events("q"):
        drone.land()
        sleep(3)
    if kp.get_key_events("e"):
        drone.takeoff()
        sleep(2)

    # save an image if 'z' key is pressed 
    if kp.get_key_events("z"):
        cv2.imwrite(f"camera_feed/images/drone_image_{str(dt.now())}.jpg", img)
        sleep(0.3)

    return [lr, fb, ud, yv]

while True:
    vals = getKeyboardInput()
    print(vals)
    drone.send_rc_control(vals[0],vals[1],vals[2],vals[3])
    # Display the drone camera feed
    frame = drone.get_frame_read().frame
    frame = cv2.resize(frame, (360, 240))
    cv2.imshow("Drone Camera", frame)
    if cv2.waitKey(1) & 0xFF == ord('x'):
        drone.stream_off()
        break


    