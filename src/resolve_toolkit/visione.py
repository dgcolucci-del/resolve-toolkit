"""Riconoscimento di visi e scritte sui fotogrammi.

Sul Mac usa Apple Vision (pyobjc), che trova anche il testo. Altrove (o se Vision manca) usa OpenCV
solo per i visi: in quel caso le scritte/loghi vanno confermati a occhio e il risultato lo dice.
"""
from __future__ import annotations

import sys

Box = dict  # {"x": px, "y": px (dall'alto), "w": px, "h": px, "tipo": "viso"|"testo", "testo": str}


def _vision(path: str) -> list[Box] | None:
    if sys.platform != "darwin":
        return None
    try:
        import Quartz  # type: ignore
        import Vision  # type: ignore
        from Foundation import NSURL  # type: ignore
    except ImportError:
        return None
    url = NSURL.fileURLWithPath_(path)
    src = Quartz.CGImageSourceCreateWithURL(url, None)
    if src is None:
        return None
    img = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    W, H = Quartz.CGImageGetWidth(img), Quartz.CGImageGetHeight(img)
    visi = Vision.VNDetectFaceRectanglesRequest.alloc().init()
    testo = Vision.VNRecognizeTextRequest.alloc().init()
    testo.setRecognitionLevel_(1)  # accurato
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(img, None)
    ok, _ = handler.performRequests_error_([visi, testo], None)
    if not ok:
        return None
    out = []

    def box(o, tipo, t=""):
        bb = o.boundingBox()  # normalizzato, origine in basso a sinistra
        x, y, w, h = bb.origin.x, bb.origin.y, bb.size.width, bb.size.height
        out.append({"x": x * W, "y": (1 - y - h) * H, "w": w * W, "h": h * H, "tipo": tipo, "testo": t})

    for o in visi.results() or []:
        box(o, "viso")
    for o in testo.results() or []:
        cand = o.topCandidates_(1)
        box(o, "testo", str(cand[0].string()) if cand else "")
    return out


def _opencv(path: str) -> list[Box] | None:
    try:
        import cv2  # type: ignore
    except ImportError:
        return None
    img = cv2.imread(path)
    if img is None:
        return None
    grigio = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    out = []
    for nome in ("haarcascade_frontalface_default.xml", "haarcascade_profileface.xml"):
        c = cv2.CascadeClassifier(cv2.data.haarcascades + nome)
        for (x, y, w, h) in c.detectMultiScale(grigio, 1.1, 5, minSize=(40, 40)):
            out.append({"x": float(x), "y": float(y), "w": float(w), "h": float(h), "tipo": "viso", "testo": ""})
    return out


def rileva(path: str) -> dict:
    boxes = _vision(path)
    if boxes is not None:
        return {"motore": "Apple Vision", "box": boxes, "testo_rilevato": True}
    boxes = _opencv(path)
    if boxes is not None:
        return {"motore": "OpenCV (solo visi)", "box": boxes, "testo_rilevato": False}
    return {"motore": "nessuno", "box": [], "testo_rilevato": False}
