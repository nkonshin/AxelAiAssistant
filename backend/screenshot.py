"""
Screen capture for code task analysis via Vision model.

Captures the main display, resizes Retina screenshots to max 1920px,
and returns base64-encoded JPEG.

Uses macOS `screencapture` CLI, with Pillow ImageGrab as fallback.
Both require Screen Recording permission in System Settings.
"""

import base64
import io
import logging
import os
import subprocess
import tempfile

logger = logging.getLogger(__name__)

PERMISSION_ERROR_MSG = (
    "Нет разрешения на запись экрана. "
    "Откройте Системные настройки → Конфиденциальность → Запись экрана, "
    "добавьте приложение и перезапустите его."
)


class ScreenshotCapture:
    @staticmethod
    def capture_full_screen() -> str:
        """Capture the main display and return base64 JPEG."""
        # Try macOS screencapture CLI first
        try:
            return ScreenshotCapture._capture_via_cli()
        except PermissionError:
            raise  # Don't fallback on permission issues
        except Exception as e:
            logger.warning(f"screencapture CLI failed: {e}, trying Pillow...")

        # Fallback to Pillow ImageGrab
        try:
            return ScreenshotCapture._capture_via_pillow()
        except Exception as e:
            err_str = str(e)
            if "cannot identify image file" in err_str or "CGWindowListCreateImage" in err_str:
                raise PermissionError(PERMISSION_ERROR_MSG) from e
            raise

    @staticmethod
    def _capture_via_cli() -> str:
        """Capture using macOS screencapture command."""
        tmp_path = os.path.join(tempfile.gettempdir(), "axel_screenshot.jpg")
        # Remove old file to detect empty captures
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

        result = subprocess.run(
            ["screencapture", "-x", "-t", "jpg", tmp_path],
            capture_output=True, timeout=10,
        )
        if result.returncode != 0:
            raise RuntimeError(f"screencapture exit code {result.returncode}")

        if not os.path.exists(tmp_path):
            raise PermissionError(PERMISSION_ERROR_MSG)

        file_size = os.path.getsize(tmp_path)
        if file_size == 0:
            os.unlink(tmp_path)
            raise PermissionError(PERMISSION_ERROR_MSG)

        # Very small file (<1KB) usually means a blank/permission-denied capture
        if file_size < 1000:
            os.unlink(tmp_path)
            raise PermissionError(PERMISSION_ERROR_MSG)

        with open(tmp_path, "rb") as f:
            data = f.read()
        os.unlink(tmp_path)

        # Validate that it's a real image
        from PIL import Image
        try:
            img = Image.open(io.BytesIO(data))
        except Exception:
            raise PermissionError(PERMISSION_ERROR_MSG)

        # Resize if too large (Retina)
        max_side = max(img.width, img.height)
        if max_side > 1920:
            ratio = 1920 / max_side
            img = img.resize((int(img.width * ratio), int(img.height * ratio)))
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            return base64.b64encode(buffer.getvalue()).decode()

        return base64.b64encode(data).decode()

    @staticmethod
    def _capture_via_pillow() -> str:
        """Capture using Pillow ImageGrab (requires Screen Recording permission)."""
        from PIL import ImageGrab
        img = ImageGrab.grab(all_screens=False)

        if img.mode == "RGBA":
            img = img.convert("RGB")

        max_side = max(img.width, img.height)
        if max_side > 1920:
            ratio = 1920 / max_side
            img = img.resize((int(img.width * ratio), int(img.height * ratio)))

        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        return base64.b64encode(buffer.getvalue()).decode()
