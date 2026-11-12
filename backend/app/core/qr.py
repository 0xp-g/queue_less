import base64
import io

import qrcode


def qr_png_base64(data: str) -> str:
    """Render a QR code as a base64 PNG (the frontend shows it with a data: URL)."""
    img = qrcode.make(data, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()
