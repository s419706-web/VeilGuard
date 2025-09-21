import cv2

# נתיב לתמונה
image_path = r"C:\Users\shapi\Downloads\test5.jpg"
output_path = r"C:\Users\shapi\Downloads\alin\output.jpg"

# עוצמת הטשטוש: ערך קטן יותר = טשטוש חזק יותר
blur_strength = 0.05  # אפשר לשנות בין 0.02 ל-0.2

# טוענים את התמונה
img = cv2.imread(image_path)
gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

# טוענים את הקסקייד לזיהוי פנים
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

# מזהים פנים
faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)

for (x, y, w, h) in faces:
    face = img[y:y+h, x:x+w]
    
    # טשטוש חזק יותר על ידי הקטנה והגדלה
    small = cv2.resize(face, (0,0), fx=blur_strength, fy=blur_strength)
    blurred_face = cv2.resize(small, (w,h), interpolation=cv2.INTER_LINEAR)
    
    # מחליפים את הפנים המקוריים בפנים המטושטשות
    img[y:y+h, x:x+w] = blurred_face

# שמירה של התמונה החדשה
cv2.imwrite(output_path, img)
print(f"Faces blurred and saved to {output_path}")

# אפשר גם להציג את התמונה
cv2.imshow("Blurred Faces", img)
cv2.waitKey(0)
cv2.destroyAllWindows()
