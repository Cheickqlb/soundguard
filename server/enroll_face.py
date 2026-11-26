"""
Enrol a consenting person with the webcam.
Run:  python enroll_face.py Cheick
- Press SPACE to take a photo (take 10-15, change angle/expression a little)
- Press Q to finish
Photos are saved in known_faces/<Name>/
"""
import os
import sys

import cv2
import face_recognition

import config as C

if len(sys.argv) < 2:
    print("Usage: python enroll_face.py <Name>")
    sys.exit(1)

name = sys.argv[1]
folder = os.path.join(C.KNOWN_FACES_DIR, name)
os.makedirs(folder, exist_ok=True)
cam = cv2.VideoCapture(0, cv2.CAP_DSHOW)
count = len(os.listdir(folder))
print("SPACE = take photo, Q = quit")

while True:
    ok, frame = cam.read()
    if not ok:
        print("Webcam not available")
        break
    view = frame.copy()
    cv2.putText(view, f"{name}: {count} photos  (SPACE=save, Q=quit)", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    cv2.imshow("Enrolment", view)
    key = cv2.waitKey(1) & 0xFF
    if key == ord("q"):
        break
    if key == ord(" "):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        faces = face_recognition.face_locations(rgb)
        if len(faces) != 1:
            print(f"  skipped: {len(faces)} faces found (need exactly 1)")
            continue
        count += 1
        cv2.imwrite(os.path.join(folder, f"{name}_{count:02d}.jpg"), frame)
        print(f"  saved photo {count}")

cam.release()
cv2.destroyAllWindows()
print(f"Done: {count} photos in {folder}")
