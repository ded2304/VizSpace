# -*- coding: utf-8 -*-
__title__ = "Clustering Coefficient"
__author__ = "VizSpace"

from pyrevit import revit, forms, script
from Autodesk.Revit.DB import *
import math, time

doc   = revit.doc
uidoc = revit.uidoc
view  = doc.ActiveView
op    = script.get_output()

start_time = time.time()

GRID_SIZE    = 2
TRANSPARENCY = 70

# ── PLAN CHECK ────────────────────────────────────────────────────────────────
if not isinstance(view, ViewPlan) or view.ViewType != ViewType.FloorPlan:
    forms.alert("Run from a Floor Plan.", exitscript=True)

level      = view.GenLevel
level_elev = level.Elevation if level else 0.0

# ── SOLID FILL ────────────────────────────────────────────────────────────────
solid_id = None
for p in FilteredElementCollector(doc).OfClass(FillPatternElement):
    if p.GetFillPattern().IsSolidFill:
        solid_id = p.Id
        break

if not solid_id:
    forms.alert("No solid fill pattern found.", exitscript=True)

# ── WALLS + DOORS ─────────────────────────────────────────────────────────────
wall_segs = []
door_pts  = []

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

for d in FilteredElementCollector(doc)\
        .OfCategory(BuiltInCategory.OST_Doors)\
        .WhereElementIsNotElementType():
    loc = d.Location
    if isinstance(loc, LocationPoint):
        pt = loc.Point
        if abs(pt.Z - level_elev) < 2.0:
            door_pts.append((pt.X, pt.Y))

op.print_md("🧱 Walls: **{}** | 🚪 Doors: **{}**".format(len(wall_segs), len(door_pts)))

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
    return (a1[0] + t*dx_a, a1[1] + t*dy_a)

def near_door(x, y, r=1.8):
    return any(math.hypot(dx-x, dy-y) < r for dx, dy in door_pts)

def can_see(ax, ay, bx, by):
    for (wx1,wy1),(wx2,wy2) in wall_segs:
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
    # blue (low CC) → green → yellow → red (high CC)
    n = max(0.0, min(1.0, float(n)))
    if   n < 0.25: t=n/0.25;        return Color(0,          int(255*t),     255)
    elif n < 0.5:  t=(n-0.25)/0.25; return Color(0,          255,            int(255*(1-t)))
    elif n < 0.75: t=(n-0.5)/0.25;  return Color(int(255*t), 255,            0)
    else:          t=(n-0.75)/0.25; return Color(255,         int(255*(1-t)), 0)

# ── BUILD GRID ────────────────────────────────────────────────────────────────
op.print_md("## 📍 Building Grid...")

floors = FilteredElementCollector(doc)\
    .OfCategory(BuiltInCategory.OST_Floors)\
    .WhereElementIsNotElementType().ToElements()

all_nodes = []
node_z    = level_elev  # fixed once, not overwritten per face

for floor in floors:
    geo = floor.get_Geometry(Options())
    for obj in geo:
        if isinstance(obj, Solid):
            for face in obj.Faces:
                if isinstance(face, PlanarFace) and abs(face.FaceNormal.Z) > 0.99:
                    loops = face.GetEdgesAsCurveLoops()
                    if not loops: continue
                    poly = [(c.GetEndPoint(0).X, c.GetEndPoint(0).Y) for c in loops[0]]
                    bbox = floor.get_BoundingBox(view)
                    x = bbox.Min.X
                    while x < bbox.Max.X:
                        y = bbox.Min.Y
                        while y < bbox.Max.Y:
                            cx = x + GRID_SIZE/2.0
                            cy = y + GRID_SIZE/2.0
                            if point_in_polygon(cx, cy, poly):
                                all_nodes.append((cx, cy))
                            y += GRID_SIZE
                        x += GRID_SIZE

K = len(all_nodes)
op.print_md("📊 Nodes: **{}**".format(K))
if K < 3:
    forms.alert("Too few grid nodes.", exitscript=True)

# ── VISIBILITY GRAPH ──────────────────────────────────────────────────────────
op.print_md("## 🔍 Building Visibility Graph...")

adj     = [[] for _ in range(K)]
adj_set = [set() for _ in range(K)]   # set for O(1) pair lookup in CC

for i in range(K):
    ax, ay = all_nodes[i]
    for j in range(i+1, K):
        bx, by = all_nodes[j]
        if can_see(ax, ay, bx, by):
            adj[i].append(j);     adj[j].append(i)
            adj_set[i].add(j);    adj_set[j].add(i)

total_edges = sum(len(a) for a in adj) // 2
op.print_md("Edges: **{}**".format(total_edges))

# ── CLUSTERING COEFFICIENT ────────────────────────────────────────────────────
#
#   For each node i with k neighbors:
#     a = possible pairs among neighbors = k*(k-1)/2
#     b = pairs that actually see each other (triangles)
#     CC_i = b / a  →  "% of neighbor-pairs that are mutually visible"
#
#   Red   = high CC → tight visual cluster (courtyard, atrium)
#   Blue  = low CC  → linear/tree visibility (corridor, spoke)
# ─────────────────────────────────────────────────────────────────────────────
op.print_md("## 🔗 Computing **Clustering Coefficient**...")

metric = []

for i in range(K):
    neighbors = adj[i]
    k = len(neighbors)

    if k < 2:
        metric.append(0.0)
        continue

    # b: count neighbor pairs that see each other
    b = 0
    for x in range(k):
        for y in range(x+1, k):
            if neighbors[y] in adj_set[neighbors[x]]:   # O(1) set lookup
                b += 1

    # a: total possible pairs
    a = k * (k - 1) / 2.0

    metric.append(b / a)   # percentage → 0.0 to 1.0

m_min = min(metric)
m_max = max(metric)
m_range = m_max - m_min if m_max != m_min else 1.0

op.print_md("CC range: **{:.3f} – {:.3f}**".format(m_min, m_max))
op.print_md("Avg CC:   **{:.3f}**".format(sum(metric) / K))
op.print_md("Max CC:   **{:.3f}** (Node {})".format(m_max, metric.index(m_max)))

# ── DRAW HEATMAP ──────────────────────────────────────────────────────────────
op.print_md("## 🎨 Drawing Clustering Coefficient Heatmap...")

region_type = FilteredElementCollector(doc)\
    .OfClass(FilledRegionType).FirstElement()

t = Transaction(doc, "VGA Clustering Heatmap")
t.Start()

new_view_id = view.Duplicate(ViewDuplicateOption.Duplicate)
new_view    = doc.GetElement(new_view_id)
new_view.Name = view.Name + " - Clustering CC"

for idx, (cx, cy) in enumerate(all_nodes):
    n     = (metric[idx] - m_min) / m_range   # normalize 0→1
    color = get_color(n)

    x0 = cx - GRID_SIZE/2; y0 = cy - GRID_SIZE/2
    x1 = cx + GRID_SIZE/2; y1 = cy + GRID_SIZE/2

    p1 = XYZ(x0, y0, node_z); p2 = XYZ(x1, y0, node_z)
    p3 = XYZ(x1, y1, node_z); p4 = XYZ(x0, y1, node_z)

    loop = CurveLoop()
    loop.Append(Line.CreateBound(p1, p2))
    loop.Append(Line.CreateBound(p2, p3))
    loop.Append(Line.CreateBound(p3, p4))
    loop.Append(Line.CreateBound(p4, p1))

    region = FilledRegion.Create(doc, region_type.Id, new_view.Id, [loop])

    ogs = OverrideGraphicSettings()
    ogs.SetSurfaceForegroundPatternId(solid_id)
    ogs.SetSurfaceForegroundPatternColor(color)
    ogs.SetSurfaceTransparency(TRANSPARENCY)
    ogs.SetProjectionLineColor(color)        # line color = same as fill
    ogs.SetProjectionLineWeight(-1)          # -1 = invisible/no override
    new_view.SetElementOverrides(region.Id, ogs)

t.Commit()

elapsed = time.time() - start_time
op.print_md("## ✅ Done in **{:.2f} seconds**".format(elapsed))
op.print_md("### View: **{}**".format(new_view.Name))
