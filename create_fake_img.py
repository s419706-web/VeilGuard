from PIL import Image, ImageDraw  
import piexif
from piexif import ImageIFD  

def create_fake_image(output_path):
    """Creates a detectable fake image"""
    try:
        # Create image
        img = Image.new('RGB', (800, 600), (200, 200, 200))
        draw = ImageDraw.Draw(img)
        
        # Add fake elements
        draw.rectangle((100, 100, 700, 500), outline=(255, 0, 0), width=5)
        draw.text((300, 300), "FAKE", fill=(0, 0, 255))
        
        # Add EXIF metadata
        exif_dict = {
            "0th": {
                ImageIFD.Software: "Adobe Photoshop CC 2023"
            }
        }
        
        img.save(output_path, exif=piexif.dump(exif_dict))
        print(f"Created fake image at {output_path}")
        return True
        
    except Exception as e:
        print(f"Error: {e}")
        return False

# Test it
if __name__ == "__main__":
    create_fake_image(r"C:\Users\shapi\Downloads\alin\img1.jpg")