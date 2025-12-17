import cv2 
import numpy as np 

# webcam 
cap = cv2.VideoCapture(0)


def find_faces(img):
# face detection
    face_cascade = cv2.CascadeClassifier('./haarcascade_frontalface_default.xml')
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, 1.2, 8)


    # draw rectangle around faces
    for (x, y, w, h) in faces:
        cv2.rectangle(img, (x, y), (x+w, y+h), (0, 0, 255), 3)
        center = (x + w//2, y + h//2)
        cv2.circle(img, center, 5, (255, 0, 0), -1) # draw point on center
        # write area on the image center:
        cv2.putText(img,text=f"{w*h:,.1f}",org=(center[0]+2,center[1]),fontFace=3,fontScale=1,thickness=2,color=(255,255,255))

        # visually have lines of left and right borders (to act for yaw commands if face falls outside these borders)
        # we set up this as 10% of width from each side
        image_height , image_width = img.shape[:2]
        width_margin = 0.3
        borders = (int(image_width*width_margin), int(image_width*(1-width_margin)))
        cv2.line(img,pt1=(borders[0],0),pt2=(borders[0],image_height),color=(0,0,255),thickness=5)
        cv2.line(img,pt1=(borders[1],0),pt2=(borders[1],image_height),color=(0,0,255),thickness=5)
        
    # find the face with biggest area (ie closest to drone)
    face_areas = [f[-2]*f[-1] for f in faces]
    if len(faces)>0:
        closest_face = faces[face_areas.index(max(face_areas))]
        return img , closest_face
    else:
        closest_face = faces
        return img , [0,0,0,0]

while True:
    _, img = cap.read()
    img, face = find_faces(img)
    print(face, round(face[2]*face[3],1))
    cv2.flip(img,1)
    cv2.imshow('img', img)
    
    cv2.waitKey(1)

