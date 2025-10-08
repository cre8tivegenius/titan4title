from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import os, glob

def register_directory(dir_path: str = "app/assets/fonts"):
    if not os.path.isdir(dir_path):
        return []
    registered = []
    for path in glob.glob(os.path.join(dir_path, "*.ttf")) + glob.glob(os.path.join(dir_path, "*.otf")):
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            pdfmetrics.registerFont(TTFont(name, path))
            registered.append({"name": name, "path": path})
        except Exception:
            # Skip non-loadable fonts
            pass
    return registered
