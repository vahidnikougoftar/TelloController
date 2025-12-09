from djitellopy import tello 
from time import sleep 
import cv2 


drone = tello.Tello()
drone.connect()

print(drone.get_battery())

drone.takeoff()
drone.send_rc_control(0, 50, 0, 0)  # Move forward at speed 50
sleep(0.5) 
drone.send_rc_control(0, 0, 0, 0)  # Stop movement
drone.land()

# streaming example 
drone.streamon()
frame_read = drone.get_frame_read()
while True:
    frame = frame_read.frame
    # Process the frame (e.g., resize small and display it using OpenCV)   
    frame = cv2.resize(frame, (360, 240))
    cv2.imshow("Drone Camera", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break
drone.streamoff()



