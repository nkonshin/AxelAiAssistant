"""
Screen capture for code task analysis via GPT-4o Vision.

Captures the main display, resizes Retina screenshots to max 1920px,
and returns base64-encoded JPEG.
"""

from PIL import ImageGrab
import base64
import io


class ScreenshotCapture:
    @staticmethod
    def capture_full_screen() -> str:
        """Capture the main display and return base64 JPEG."""
        img = ImageGrab.grab(all_screens=False)

        # macOS returns RGBA — convert to RGB for JPEG
        if img.mode == "RGBA":
            img = img.convert("RGB")

        # Resize Retina screenshots (e.g. 3456x2234 on M1)
        max_side = max(img.width, img.height)
        if max_side > 1920:
            ratio = 1920 / max_side
            img = img.resize(
                (int(img.width * ratio), int(img.height * ratio))
            )

        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        return base64.b64encode(buffer.getvalue()).decode()
