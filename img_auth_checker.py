import os
from PIL import Image
import imghdr
import magic

class ImageAuthChecker:
    def __init__(self):
        self.fake_signatures = [
            "photoshop", "adobe", "gimp", "pixlr", 
            "edited", "paint.net", "corel", "affinity"
        ]
        self.max_reasonable_size_mb = 5  # Maximum expected size for normal images

    def is_image_fake(self, file_path):
        """Main method to check image authenticity"""
        try:
            # Check 1: Basic file validation
            if not self._is_valid_image_file(file_path):
                return True

            # Check 2: Metadata analysis
            metadata = self._extract_metadata(file_path)
            if self._has_editor_signature(metadata):
                return True

            # Check 3: File size check
            if self._is_unusually_large(file_path):
                return True

            # Check 4: Pixel analysis
            if self._has_unnatural_patterns(file_path):
                return True

            return False

        except Exception as e:
            print(f"Error during authentication: {str(e)}")
            return True  # Assume fake if we can't process

    def _is_valid_image_file(self, file_path):
        """Check if file is a valid image"""
        try:
            # Check file exists
            if not os.path.exists(file_path):
                return False

            # Check file type
            file_type = imghdr.what(file_path)
            if not file_type:
                return False

            # Verify with magic
            mime = magic.from_file(file_path, mime=True)
            return file_type in ['jpeg', 'png', 'gif'] and 'image' in mime

        except Exception:
            return False

    def _extract_metadata(self, file_path):
        """Extract basic metadata"""
        metadata = {}
        try:
            with Image.open(file_path) as img:
                if hasattr(img, '_getexif') and img._getexif():
                    for tag, value in img._getexif().items():
                        if isinstance(value, (str, int, float)):
                            metadata[tag] = str(value)
        except Exception:
            pass
        return metadata

    def _has_editor_signature(self, metadata):
        """Check for signs of editing software"""
        for value in metadata.values():
            if isinstance(value, str):
                value_lower = value.lower()
                for sig in self.fake_signatures:
                    if sig in value_lower:
                        return True
        return False

    def _is_unusually_large(self, file_path):
        """Check for suspicious file size"""
        try:
            size_mb = os.path.getsize(file_path) / (1024 * 1024)
            return size_mb > self.max_reasonable_size_mb
        except:
            return False

    def _has_unnatural_patterns(self, file_path):
        """Basic pixel pattern analysis"""
        try:
            with Image.open(file_path) as img:
                # Simple check - look for solid color areas
                pixels = list(img.getdata())
                if len(set(pixels)) < 10:  # Too few colors
                    return True
                
                # Check edges for cloning artifacts
                width, height = img.size
                edge_pixels = []
                for x in [0, width-1]:  # Left and right edges
                    for y in range(0, height, height//10):
                        edge_pixels.append(img.getpixel((x, y)))
                
                if len(set(edge_pixels)) < 5:  # Edges too similar
                    return True
        except:
            pass
        return False