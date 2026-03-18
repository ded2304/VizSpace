# -*- coding: utf-8 -*-
__title__ = "Isovist Perimeter"
__author__ = "VizSpace"

from pyrevit import revit, forms, script
from Autodesk.Revit.DB import *
import math, time, re

doc        = revit.doc
uidoc      = revit.uidoc
view       = doc.ActiveView
op         = script.get_output()
start_time = time.time()

GRID_SIZE    = 2
TRANSPARENCY = 60
EPS          = 0.02

# ── PLAN CHECK ───────────────────────────────────────────────────────────────
if not isinstance(view, ViewPlan) or view.ViewType != ViewType.FloorPlan:
    forms.alert("Run from a Floor Plan.", exitscript=True)

level      = view.GenLevel
level_elev = level.Elevation if level else 0.0

op.print_md("# 🏢 Isovist Perimeter Heatmap — VizSpace")
op.print_md("Level: **{}** | Elevation: **{:.2f}**".format(
    level.Name if level else "None", level_elev))

# ── SOLID FILL ───────────────────────────────────────────────────────────────
solid_id = None
for p in FilteredElementCollector(doc).OfClass(FillPatternElement):
    if p.GetFillPattern().IsSolidFill:
        solid_id = p.Id
        break

if not solid_id:
    forms.alert("No solid fill pattern found.", exitscript=True)

# ── FILLED REGION TYPE ───────────────────────────────────────────────────────
region_type = None
for rt in FilteredElementCollector(doc).OfClass(FilledRegionType):
    region_type = rt
    break

if not region_type:
    forms.alert("No FilledRegionType found. Load a filled region style first.",
                exitscript=True)

# ── WALLS + DOORS ─────────────────────────────────────────────────────────────
wall_segs   = []
wall_bboxes = []
door_pts    = []

for w in FilteredElementCollector(doc)\
        .OfCategory(BuiltInCategory.OST_Walls)\
        .WhereElementIsNotElementType():
    loc = w.Location
    if isinstance(loc, LocationCurve):
        c = loc.Curve
        if isinstance(c, Line):
            p0 = c.GetEndPoint(0)
            p1 = c.GetEndPoint(1)
            if abs(p0.Z - level_elev) < 2.0:
                wall_segs.append(((p0.X, p0.Y), (p1.X, p1.Y)))
                wall_bboxes.append((
                    min(p0.X, p1.X), min(p0.Y, p1.Y),
                    max(p0.X, p1.X), max(p0.Y, p1.Y)
                ))

for d in FilteredElementCollector(doc)\
        .OfCategory(BuiltInCategory.OST_Doors)\
        .WhereElementIsNotElementType():
    loc = d.Location
    if isinstance(loc, LocationPoint):
        pt = loc.Point
        if abs(pt.Z - level_elev) < 2.0:
            door_pts.append((pt.X, pt.Y))

op.print_md("🧱 Walls: **{}** | 🚪 Doors: **{}**".format(
    len(wall_segs), len(door_pts)))

# ── HELPERS ───────────────────────────────────────────────────────────────────

def seg_intersect(a1, a2, b1, b2):
    def cross(o, a, b):
        return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])
    d1 = cross(b1,b2,a1); d2 = cross(b1,b2,a2)
    d3 = cross(a1,a2,b1); d4 = cross(a1,a2,b2)
    return ((d1>0 and d2<0) or (d1<0 and d2>0)) and \
           ((d3>0 and d4<0) or (d3<0 and d4>0))

def get_intersection_pt(a1, a2, b1, b2):
    dx_a = a2[0]-a1[0]; dy_a = a2[1]-a1[1]
    dx_b = b2[0]-b1[0]; dy_b = b2[1]-b1[1]
    denom = dx_a*dy_b - dy_a*dx_b
    if abs(denom) < 1e-10:
        return None
    t = ((b1[0]-a1[0])*dy_b - (b1[1]-a1[1])*dx_b) / denom
    u = ((b1[0]-a1[0])*dy_a - (b1[1]-a1[1])*dx_a) / denom
    if 1e-10 < t < 1-1e-10 and 0.0 <= u <= 1.0:
        return (a1[0] + t*dx_a, a1[1] + t*dy_a)
    return None

def near_door(x, y, r=1.8):
    return any(math.hypot(dx-x, dy-y) < r for dx, dy in door_pts)

def bbox_overlap(ax, ay, bx, by, bbox):
    return (max(ax,bx) >= bbox[0] and min(ax,bx) <= bbox[2] and
            max(ay,by) >= bbox[1] and min(ay,by) <= bbox[3])

def can_see(ax, ay, bx, by):
    for idx, ((wx1,wy1),(wx2,wy2)) in enumerate(wall_segs):
        if not bbox_overlap(ax, ay, bx, by, wall_bboxes[idx]):
            continue
        if seg_intersect((ax,ay),(bx,by),(wx1,wy1),(wx2,wy2)):
            pt = get_intersection_pt((ax,ay),(bx,by),(wx1,wy1),(wx2,wy2))
            if pt and near_door(pt[0], pt[1]):
                continue
            return False
    return True

def point_in_polygon(px, py, poly):
    inside = False
    n = len(poly)
    x1, y1 = poly[0]
    for i in range(1, n+1):
        x2, y2 = poly[i % n]
        if min(y1,y2) < py <= max(y1,y2) and px <= max(x1,x2):
            xi = x1 if y1==y2 else (py-y1)*(x2-x1)/(y2-y1) + x1
            if px <= xi:
                inside = not inside
        x1, y1 = x2, y2
    return inside

def get_color(n):
    n = max(0.0, min(1.0, float(n)))
    if   n < 0.25: t = n/0.25;         return Color(0,          int(255*t),     255)
    elif n < 0.5:  t = (n-0.25)/0.25;  return Color(0,          255,            int(255*(1-t)))
    elif n < 0.75: t = (n-0.5)/0.25;   return Color(int(255*t), 255,            0)
    else:          t = (n-0.75)/0.25;  return Color(255,        int(255*(1-t)), 0)

def sanitize_name(name):
    cleaned = re.sub(r'[\\/:*?"<>|{};,]', '', name).strip()
    return cleaned if cleaned else "Isovist View"

def unique_view_name(doc, base_name):
    base_name = sanitize_name(base_name)
    existing  = {v.Name for v in FilteredElementCollector(doc)
                                  .OfClass(View).ToElements()}
    if base_name not in existing:
        return base_name
    counter = 1
    while "{} ({})".format(base_name, counter) in existing:
        counter += 1
    return "{} ({})".format(base_name, counter)

# ── BUILD GRID ────────────────────────────────────────────────────────────────
op.print_md("## 📍 Building Grid  (GRID_SIZE = {} ft)...".format(GRID_SIZE))

floors = FilteredElementCollector(doc)\
    .OfCategory(BuiltInCategory.OST_Floors)\
    .WhereElementIsNotElementType().ToElements()

all_nodes = []   # (cx, cy, nz) — per-node elevation

for floor in floors:
    geo = floor.get_Geometry(Options())
    for obj in geo:
        if isinstance(obj, Solid):
            for face in obj.Faces:
                if isinstance(face, PlanarFace) and abs(face.FaceNormal.Z) > 0.99:
                    loops = face.GetEdgesAsCurveLoops()
                    if not loops:
                        continue
                    poly = [(c.GetEndPoint(0).X, c.GetEndPoint(0).Y)
                            for c in loops[0]]
                    bbox = floor.get_BoundingBox(view)
                    nz   = bbox.Min.Z

                    x = bbox.Min.X
                    while x < bbox.Max.X:
                        y = bbox.Min.Y
                        while y < bbox.Max.Y:
                            cx = x + GRID_SIZE/2.0
                            cy = y + GRID_SIZE/2.0
                            if point_in_polygon(cx, cy, poly):
                                all_nodes.append((cx, cy, nz))
                            y += GRID_SIZE
                        x += GRID_SIZE

K = len(all_nodes)
op.print_md("📊 Nodes: **{}** | Pairs: **{}** | Walls: **{}**".format(
    K, K*(K-1)//2, len(wall_segs)))

if K < 3:
    forms.alert("Too few grid nodes. Check floors exist on this level.",
                exitscript=True)

est_sec = (K**2 * len(wall_segs)) / 1e6
op.print_md("⏱ Estimated time: **~{:.0f} sec**".format(est_sec))
if K > 600:
    op.print_md("⚠️ K > 600 — consider increasing GRID_SIZE to 4.0 or 5.0")

# ── VISIBILITY GRAPH ──────────────────────────────────────────────────────────
op.print_md("## 🔍 Building Visibility Graph...")

adj = [[] for _ in range(K)]

for i in range(K):
    ax, ay, _ = all_nodes[i]
    for j in range(i+1, K):
        bx, by, _ = all_nodes[j]
        if can_see(ax, ay, bx, by):
            adj[i].append(j)
            adj[j].append(i)

total_edges = sum(len(a) for a in adj) // 2
op.print_md("✅ Edges: **{}**".format(total_edges))

# ── ISOVIST PERIMETER METRIC ──────────────────────────────────────────────────
# Approximates perimeter as the sum of distances to all visible neighbours.
# Nodes visible only at short range (tight corners) get low values → blue.
# Nodes with long unobstructed sightlines get high values → red.
op.print_md("## 📐 Computing Isovist Perimeters...")

metric = []

for i in range(K):
    ax, ay, _ = all_nodes[i]
    perimeter  = 0.0
    for j in adj[i]:
        bx, by, _ = all_nodes[j]
        perimeter += math.hypot(bx - ax, by - ay)
    metric.append(perimeter)

valid_vals = [v for v in metric if v > 0.0]
if not valid_vals:
    forms.alert("All nodes isolated — no visible connections found.", exitscript=True)

m_min   = min(valid_vals)
m_max   = max(valid_vals)
m_range = m_max - m_min if m_max != m_min else 1.0

best_idx = metric.index(m_max)
op.print_md("Max perimeter: **{:.1f} ft** (Node {}) | Min: **{:.1f} ft**".format(
    m_max, best_idx, m_min))
op.print_md("Isolated nodes: **{}**".format(metric.count(0.0)))

# ── COLOR LEGEND ──────────────────────────────────────────────────────────────
op.print_md("## 🗺️ Color Legend")
op.print_html("""
<table style="border-collapse:collapse;font-family:sans-serif;font-size:13px;margin:8px 0;">
  <thead>
    <tr>
      <th style="padding:5px 10px;border:1px solid #ccc;">Color</th>
      <th style="padding:5px 10px;border:1px solid #ccc;">Perimeter</th>
      <th style="padding:5px 10px;border:1px solid #ccc;">Typical Space</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td style="background:#0000FF;width:50px;border:1px solid #ccc;"></td>
      <td style="padding:4px 10px;border:1px solid #ccc;">Very Short</td>
      <td style="padding:4px 10px;border:1px solid #ccc;">Enclosed corners, tight rooms</td>
    </tr>
    <tr>
      <td style="background:#00FFFF;border:1px solid #ccc;"></td>
      <td style="padding:4px 10px;border:1px solid #ccc;">Short</td>
      <td style="padding:4px 10px;border:1px solid #ccc;">Small offices, alcoves</td>
    </tr>
    <tr>
      <td style="background:#00FF00;border:1px solid #ccc;"></td>
      <td style="padding:4px 10px;border:1px solid #ccc;">Medium</td>
      <td style="padding:4px 10px;border:1px solid #ccc;">Regular rooms, secondary corridors</td>
    </tr>
    <tr>
      <td style="background:#FFFF00;border:1px solid #ccc;"></td>
      <td style="padding:4px 10px;border:1px solid #ccc;">Long</td>
      <td style="padding:4px 10px;border:1px solid #ccc;">Open plan areas, wide corridors</td>
    </tr>
    <tr>
      <td style="background:#FF0000;border:1px solid #ccc;"></td>
      <td style="padding:4px 10px;border:1px solid #ccc;">Very Long</td>
      <td style="padding:4px 10px;border:1px solid #ccc;">Main halls, lobbies, atria</td>
    </tr>
  </tbody>
</table>
<p style="font-size:11px;color:#666;margin:4px 0;">
  ⚪ Cells with zero visible neighbours are skipped entirely.
</p>
""")

# ── DRAW HEATMAP ──────────────────────────────────────────────────────────────
op.print_md("## 🎨 Drawing Heatmap...")

t = Transaction(doc, "Isovist Perimeter Heatmap")
t.Start()

new_view_id  = view.Duplicate(ViewDuplicateOption.Duplicate)
new_view     = doc.GetElement(new_view_id)
new_view.Name = unique_view_name(doc, view.Name + " - Isovist Perimeter")

drawn   = 0
skipped = 0

for idx, (cx, cy, nz) in enumerate(all_nodes):

    val = metric[idx]
    if val == 0.0:
        skipped += 1
        continue

    n     = (val - m_min) / m_range
    color = get_color(n)

    x0 = cx - GRID_SIZE/2.0 - EPS
    y0 = cy - GRID_SIZE/2.0 - EPS
    x1 = cx + GRID_SIZE/2.0 + EPS
    y1 = cy + GRID_SIZE/2.0 + EPS

    pt1 = XYZ(x0, y0, nz)
    pt2 = XYZ(x1, y0, nz)
    pt3 = XYZ(x1, y1, nz)
    pt4 = XYZ(x0, y1, nz)

    loop = CurveLoop()
    loop.Append(Line.CreateBound(pt1, pt2))
    loop.Append(Line.CreateBound(pt2, pt3))
    loop.Append(Line.CreateBound(pt3, pt4))
    loop.Append(Line.CreateBound(pt4, pt1))

    region = FilledRegion.Create(doc, region_type.Id, new_view.Id, [loop])

    ogs = OverrideGraphicSettings()
    ogs.SetSurfaceForegroundPatternId(solid_id)
    ogs.SetSurfaceForegroundPatternColor(color)
    ogs.SetSurfaceBackgroundPatternId(solid_id)       # ← purple fix
    ogs.SetSurfaceBackgroundPatternColor(color)        # ← purple fix
    ogs.SetProjectionLineColor(color)
    ogs.SetProjectionLineWeight(1)
    ogs.SetSurfaceTransparency(TRANSPARENCY)
    ogs.SetHalftone(False)

    new_view.SetElementOverrides(region.Id, ogs)
    drawn += 1

t.Commit()

elapsed = time.time() - start_time
op.print_md("## ✅ Done in **{:.1f} sec**".format(elapsed))
op.print_md("- Cells drawn: **{}** | Skipped (isolated): **{}**".format(drawn, skipped))
op.print_md("- View created: **{}**".format(new_view.Name))
