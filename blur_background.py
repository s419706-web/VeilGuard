import cv2
import numpy as np
from rembg import remove
from PIL import Image
import io

def blur_background_super_simple(image_path, blur_strength=51):
    # Read image
    with open(image_path, 'rb') as f:
        input_image = f.read()
    
    # Remove background
    output_image = remove(input_image)
    
    # Open the result image
    result_image = Image.open(io.BytesIO(output_image))
    
    # Convert to numpy array
    result_array = np.array(result_image)
    
    # If the image has alpha channel, use it as mask
    if result_array.shape[2] == 4:
        # Separate RGB and Alpha
        rgb = result_array[:, :, :3]
        alpha = result_array[:, :, 3]
        
        # Read original image
        original = cv2.imread(image_path)
        original_rgb = cv2.cvtColor(original, cv2.COLOR_BGR2RGB)
        
        # Blur original image for background
        blurred = cv2.GaussianBlur(original_rgb, (blur_strength, blur_strength), 0)
        
        # Create mask
        mask = alpha.astype(float) / 255.0
        mask_3d = np.stack([mask] * 3, axis=-1)
        
        # Blend
        final_result = (rgb * mask_3d + blurred * (1 - mask_3d)).astype(np.uint8)
        
        # Convert back to BGR
        final_result_bgr = cv2.cvtColor(final_result, cv2.COLOR_RGB2BGR)
        return final_result_bgr
    else:
        # If no alpha channel, just return the result
        return cv2.cvtColor(result_array, cv2.COLOR_RGB2BGR)

# Simple usage
try:
    result = blur_background_super_simple(r"C:\Users\shapi\Downloads\test12.jpeg")
    cv2.imwrite("output_simple.jpg", result)
    print("Done! Check output_simple.jpg")
    cv2.imshow("Result", result)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
except Exception as e:
    print(f"Error: {e}")