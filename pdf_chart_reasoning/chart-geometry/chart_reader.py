"""Measure a rasterised statistical chart instead of looking at it.

The figures in this document are pictures: no text layer, no vector paths. But
a bar is a solid block of one colour standing on a baseline, and a dot is a
small blob at a fixed height -- both are measurable to the pixel. What the code
cannot do is read the question, so it measures EVERYTHING and hands the table
to a model.

Nothing here is specific to a page number or a coordinate. Panels are found by
their baselines, bins by the labels underneath them, rate levels by the numbers
printed up the axis. Point it at a different SEP and it still works.
"""
from __future__ import annotations

import re
from collections import defaultdict

import numpy as np
import pymupdf

DPI = 200
BAR_RGB = (186, 216, 242)     # the June bars: light fill, dark outline
DOT_RGB = (35, 96, 147)       # the dot plot's markers
TOL = 30


def _page_image(page: pymupdf.Page) -> np.ndarray:
    pix = page.get_pixmap(dpi=DPI)
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
    return a[:, :, :3].astype(int)


def _mask(img: np.ndarray, rgb: tuple[int, int, int], tol: int = TOL) -> np.ndarray:
    return ((abs(img[:, :, 0] - rgb[0]) < tol)
            & (abs(img[:, :, 1] - rgb[1]) < tol)
            & (abs(img[:, :, 2] - rgb[2]) < tol))


def _runs(flags: np.ndarray, min_len: int = 1) -> list[tuple[int, int]]:
    """Contiguous True stretches as (start, end_exclusive)."""
    out, start = [], None
    for i, f in enumerate(flags):
        if f and start is None:
            start = i
        elif not f and start is not None:
            if i - start >= min_len:
                out.append((start, i))
            start = None
    if start is not None and len(flags) - start >= min_len:
        out.append((start, len(flags)))
    return out


def bars(img: np.ndarray) -> list[dict]:
    """Every filled bar on the page: its x span, its baseline, its height."""
    m = _mask(img, BAR_RGB)
    found = []
    for x0, x1 in _runs(m.any(axis=0), min_len=8):
        col = m[:, x0:x1].any(axis=1)
        for y0, y1 in _runs(col, min_len=2):
            found.append({"x0": x0, "x1": x1, "top": y0, "base": y1,
                          "height": y1 - y0, "xc": (x0 + x1) / 2})
    return found


def dots(img: np.ndarray, text_boxes: list[dict] | None = None) -> list[dict]:
    """Every marker in a dot plot, as centres -- whatever colour it is drawn in.

    The June release prints the dots blue and the March one grey, so matching a
    fixed colour reads one and misses the other. What is stable is the shape: a
    small, filled, roughly round patch of ink, all of them the same size. Text
    is ink too, so anything sitting inside an OCR box is dropped.
    """
    from scipy import ndimage

    ink = img.mean(axis=2) < 205
    lab, n = ndimage.label(ink)
    if not n:
        return []

    boxes = text_boxes or []
    out = []
    for i, (sy, sx) in enumerate(ndimage.find_objects(lab), start=1):
        h, w = sy.stop - sy.start, sx.stop - sx.start
        if not (4 <= w <= 22 and 4 <= h <= 22 and 0.6 <= w / h <= 1.7):
            continue
        area = int((lab[sy, sx] == i).sum())
        if area < 0.55 * w * h:          # a ring or a glyph, not a filled disc
            continue
        xc, yc = (sx.start + sx.stop) / 2, (sy.start + sy.stop) / 2
        if any(b["x0"] - 2 <= xc <= b["x1"] + 2 and b["y0"] - 2 <= yc <= b["y1"] + 2
               for b in boxes):
            continue                      # inside a line of text
        out.append({"xc": xc, "yc": yc, "w": w, "h": h, "area": area})

    if len(out) < 20:
        return []
    # One size fits all: the markers of a dot plot are identical, so anything
    # far from the modal area is furniture that survived the shape test.
    # One size fits all -- except where two markers touch and label as one
    # component. Those stand for as many dots as they have area for; dropping
    # them lost one dot per dense row.
    med = float(np.median([c["area"] for c in out]))
    kept = []
    for c in out:
        if c["area"] < 0.6 * med:
            continue
        n = max(1, round(c["area"] / med))
        for k in range(n):
            kept.append({**c, "xc": c["xc"] + (k - (n - 1) / 2) * (c["w"] / n)})
    return kept


# --- reading the page's own labels -------------------------------------------
# The scale, the bin names and the panel names are all printed on the page. OCR
# them rather than hardcoding: that is what makes this work on the next release
# as well as this one.

_OCR = None


def ocr_boxes(img: np.ndarray) -> list[dict]:
    """Every text box on the page, with its centre."""
    global _OCR
    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR = RapidOCR()
    res, _ = _OCR(np.ascontiguousarray(img.astype(np.uint8)))
    out = []
    for box, text, conf in (res or []):
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        out.append({"text": text.strip(), "xc": sum(xs) / 4, "yc": sum(ys) / 4,
                    "x0": min(xs), "x1": max(xs), "y0": min(ys), "y1": max(ys),
                    "conf": conf})
    return out


def _numeric(t: str) -> float | None:
    t = t.strip().replace("−", "-").replace("–", "-")
    try:
        return float(t)
    except ValueError:
        return None


def value_scale(boxes: list[dict], x_min: float, y_lo: float, y_hi: float
                ) -> tuple[float, float] | None:
    """Map pixel y to axis value, from the tick labels down the right-hand side.

    Returns (value_at_y0, value_per_pixel) or None when too few ticks are legible.
    """
    ticks = [(b["yc"], _numeric(b["text"])) for b in boxes
             if b["xc"] > x_min and y_lo <= b["yc"] <= y_hi and _numeric(b["text"]) is not None]
    if len(ticks) < 4:
        return None
    ys = np.array([t[0] for t in ticks], float)
    vs = np.array([t[1] for t in ticks], float)

    # An axis label from the panel above can drift into the window -- a bin label
    # like "4.2" sitting where a count tick would be. Fit, drop whatever the fit
    # cannot explain, refit. Two passes is enough for one or two strays.
    for _ in range(2):
        slope, intercept = np.polyfit(ys, vs, 1)
        resid = np.abs(vs - (slope * ys + intercept))
        keep = resid <= max(1.0, 2 * np.median(resid))
        if keep.all() or keep.sum() < 4:
            break
        ys, vs = ys[keep], vs[keep]
    slope, intercept = np.polyfit(ys, vs, 1)
    return float(intercept), float(slope)


# --- assembling a page into a table -------------------------------------------

def _label_below(boxes: list[dict], baseline: float, x0: float, x1: float) -> str:
    """The bin label under a bar.

    Printed as two stacked lines ("1.5-" over "1.6"), so the two are joined by
    the numbers they carry rather than by string concatenation -- OCR splits
    them inconsistently and drops the dash about a third of the time. Anything
    with letters in it is the axis caption ("Percent range"), not a bin.
    """
    band = [b for b in boxes
            if baseline + 2 < b["yc"] < baseline + 58
            and x0 - 6 < b["xc"] < x1 + 6
            and not re.search(r"[A-Za-z]", b["text"])]
    nums = []
    for b in sorted(band, key=lambda b: b["yc"]):
        nums += re.findall(r"\d+\.?\d*", b["text"].replace("−", "-").replace("–", "-"))
    if len(nums) >= 2:
        return f"{nums[0]}-{nums[-1]}"
    return nums[0] if nums else ""


def _panel_name(boxes: list[dict], baseline: float, top: float, x1: float) -> str:
    """The panel's caption -- a year, or "Longer run" -- printed above it, left.

    Searched between the panel's own top and its baseline rather than at a fixed
    offset: figures with a three-line title push their panels down the page.
    """
    near = [b for b in boxes if top < b["yc"] < baseline and b["x1"] < x1]
    for b in sorted(near, key=lambda b: b["yc"]):
        t = b["text"].strip()
        if re.fullmatch(r"(19|20)\d{2}", t[:4]) and t[:4].isdigit():
            return t[:4]
        if "onger" in t:
            return "longer run"
    return "?"


def read_histograms(img: np.ndarray, boxes: list[dict]) -> list[dict]:
    """Every panel of a distribution figure: panel name -> {bin label: count}."""
    W = img.shape[1]
    all_bars = [b for b in bars(img) if b["height"] >= 5]

    # Bars of one panel do not all end on the same pixel row -- JPEG softening
    # moves the last row of fill by a pixel or two -- so baselines are clustered,
    # not matched exactly. Keyed on equality, one panel became sixteen.
    by_base: dict[int, list[dict]] = defaultdict(list)
    for b in sorted(all_bars, key=lambda b: b["base"]):
        near = [k for k in by_base if abs(k - b["base"]) <= 8]
        by_base[near[0] if near else b["base"]].append(b)

    # Panels sit on evenly spaced baselines. A baseline carrying a single bar is
    # still a panel -- the longer-run panel of one figure puts everyone in one
    # bin -- so panels are kept when the axis beside them can be calibrated.
    # Two passes. Which baselines are panels has to be settled before any name
    # is looked up, because a panel's caption sits between it and the panel
    # above -- and a stray cluster (the legend swatch) in that gap moves the
    # search window past the caption. That cost four figures their panel names.
    measured = []
    for base in sorted(by_base):
        scale = value_scale(boxes, W * 0.75, base - 400, base)
        if scale is None:
            continue
        icept, slope = scale
        counts = {}
        for b in sorted(by_base[base], key=lambda b: b["x0"]):
            n = round((slope * b["top"] + icept) - (slope * b["base"] + icept))
            label = _label_below(boxes, base, b["x0"], b["x1"])
            if n > 0 and label:
                counts[label] = n
        if len(counts) < 2 and sum(counts.values()) < 5:
            continue
        measured.append((base, counts))

    panels = []
    bases = [b for b, _ in measured]
    pitch = min((bases[i] - bases[i - 1] for i in range(1, len(bases))), default=400)
    for i, (base, counts) in enumerate(measured):
        top = bases[i - 1] + 20 if i else max(0, base - pitch)
        panels.append({"panel": _panel_name(boxes, base, top, W * 0.35),
                       "counts": counts, "total": sum(counts.values())})
    return panels


def read_dotplot(img: np.ndarray, boxes: list[dict]) -> list[dict]:
    """The dot plot: column name -> {rate level: how many dots}."""
    W = img.shape[1]
    ds = dots(img, boxes)
    if len(ds) < 20:
        return []
    ys = [d["yc"] for d in ds]
    scale = value_scale(boxes, W * 0.75, min(ys) - 250, max(ys) + 250)
    if scale is None:
        return []
    icept, slope = scale

    xs = sorted(d["xc"] for d in ds)
    groups, cur = [], [xs[0]]
    for x in xs[1:]:
        (cur.append(x) if x - cur[-1] < 60 else (groups.append(cur), cur := [x]))
    groups.append(cur)

    out = []
    for g in groups:
        lo, hi = min(g) - 5, max(g) + 5
        counts: dict[str, int] = defaultdict(int)
        for d in ds:
            if lo <= d["xc"] <= hi:
                counts[f"{round((slope * d['yc'] + icept) * 8) / 8:.3f}"] += 1
        raw = min((b for b in boxes if b["yc"] > max(ys)),
                  key=lambda b: abs(b["xc"] - (lo + hi) / 2), default={"text": "?"})["text"]
        name = "longer run" if "onger" in raw.lower() else raw.strip()
        out.append({"column": name, "counts": dict(sorted(counts.items(),
                                                          key=lambda kv: -float(kv[0]))),
                    "total": sum(counts.values())})
    return out


def read_document(pdf_path) -> dict:
    """Measure every figure page. The only input is the PDF."""
    doc = pymupdf.open(pdf_path)
    figures = {}
    for i, page in enumerate(doc, start=1):
        if page.get_text().strip():
            continue                       # a page with text is not a figure page
        img = _page_image(page)
        boxes = ocr_boxes(img)
        title = next((b["text"] for b in sorted(boxes, key=lambda b: b["yc"])[:6]
                      if "igure" in b["text"] or "Fig" in b["text"]), f"page {i}")
        hists = read_histograms(img, boxes)
        dotp = read_dotplot(img, boxes)
        if hists or dotp:
            figures[title] = {"page": i, "panels": hists, "columns": dotp}
    return figures
