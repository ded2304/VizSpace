# -*- coding: utf-8 -*-
__title__ = "VGA Integration [HH] Heatmap"


from pyrevit import revit, forms, script
from Autodesk.Revit.DB import *
from collections import deque
import math, time

doc   = revit.doc
uidoc = revit.uidoc
view  = doc.ActiveView
op    = script.get_output()

start_time = time.time()

GRID_SIZE    = 2
TRANSPARENCY = 60

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

# ── DIAGNOSTIC: print first 3 wall segments to verify ─────────────────────────
op.print_md("**Sample walls (first 3):**")
for i, seg in enumerate(wall_segs[:3]):
    op.print_md("  Wall {}: ({:.1f},{:.1f}) → ({:.1f},{:.1f})".format(
        i, seg[0][0], seg[0][1], seg[1][0], seg[1][1]))

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

# Blue → Cyan → Yellow → Red
def get_color(n):
    n = max(0.0, min(1.0, float(n)))
    if n < 0.33:
        t = n / 0.33
        return Color(0, int(255*t), 255)
    elif n < 0.66:
        t = (n-0.33) / 0.33
        return Color(int(255*t), 255, int(255*(1-t)))
    else:
        t = (n-0.66) / 0.34
        return Color(255, int(255*(1-t)), 0)

# ── BUILD GRID ────────────────────────────────────────────────────────────────
op.print_md("## 📍 Building Grid...")

floors = FilteredElementCollector(doc)\
    .OfCategory(BuiltInCategory.OST_Floors)\
    .WhereElementIsNotElementType().ToElements()

op.print_md("Floors found: **{}**".format(len(floors)))

all_nodes = []
node_z    = level_elev   # fixed — never overwritten

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

adj = [[] for _ in range(K)]

for i in range(K):
    ax, ay = all_nodes[i]
    for j in range(i+1, K):
        bx, by = all_nodes[j]
        if can_see(ax, ay, bx, by):
            adj[i].append(j)
            adj[j].append(i)

total_edges  = sum(len(a) for a in adj) // 2
max_possible = K*(K-1) // 2
degrees      = [len(a) for a in adj]

op.print_md("Edges: **{} / {}** ({:.1f}%)".format(
    total_edges, max_possible, 100.0*total_edges/max(1,max_possible)))
op.print_md("Degree min/avg/max: **{} / {:.1f} / {}**".format(
    min(degrees), sum(degrees)/float(K), max(degrees)))

# ── DIAGNOSTIC: if edges > 80% of max → walls not blocking ───────────────────
if total_edges > 0.8 * max_possible:
    op.print_md("⚠️ **WARNING**: >80% edges present — walls may not be blocking sightlines!")
    op.print_md("Check wall Z elevation matches level elevation: **{:.2f}**".format(level_elev))

# ── VISUAL INTEGRATION [HH] ───────────────────────────────────────────────────
#
#   Turner (2001) / Hillier & Hanson formula:
#
#   Step 1: Mean Depth
#     MD_i = Σ d(i,j) / (K-1)         [BFS topological depth to all nodes]
#
#   Step 2: Relative Asymmetry
#     RA = 2*(MD - 1) / (K - 2)
#
#   Step 3: D-value (Krüger 1989) — size normalization
#     D = 2*(K*(log2(K+2)/3) - 1) / ((K-1)*(K-2))
#
#   Step 4: RRA + Integration [HH]
#     RRA  = RA / D
#     Int  = 1 / RRA
#
#   This makes integration comparable across buildings of different sizes.
# ─────────────────────────────────────────────────────────────────────────────
op.print_md("## 📐 Computing **Visual Integration [HH]**...")

# D-value: computed once using global K
if K > 2:
    D = 2.0 * (K * (math.log(K + 2, 2) / 3.0) - 1.0) / ((K - 1) * (K - 2))
else:
    D = 1.0

op.print_md("D-value (Krüger): **{:.6f}**".format(D))

integration = []

for i in range(K):
    visited    = [False]*K
    visited[i] = True
    q          = deque([(i, 0)])
    total_depth = 0
    count       = 0

    while q:
        curr, depth = q.popleft()
        for nb in adj[curr]:
            if not visited[nb]:
                visited[nb] = True
                nd = depth + 1
                total_depth += nd
                count += 1
                q.append((nb, nd))

    if count < 2:
        integration.append(0.0)
        continue

    # Step 1: Mean Depth (use global K — paper definition)
    MD = total_depth / float(K - 1)

    # Step 2: RA
    RA = 2.0 * (MD - 1.0) / float(K - 2)

    # Step 3+4: RRA → Integration [HH]
    RRA = RA / D if D > 1e-10 else 0.0
    integration.append(1.0 / RRA if RRA > 1e-10 else 0.0)

i_min = min(integration)
i_max = max(integration)
i_rng = i_max - i_min if i_max != i_min else 1.0

op.print_md("Integration [HH] range: **{:.4f} – {:.4f}**".format(i_min, i_max))
op.print_md("Highest node: **{:.4f}** (Node {})".format(i_max, integration.index(i_max)))

# EQUAL COUNT (QUANTILE) NORMALIZATION for full color spectrum
order      = sorted(range(K), key=lambda i: integration[i])
quantile_n = [0.0] * K
for rank, node_idx in enumerate(order):
    quantile_n[node_idx] = float(rank) / float(K - 1)

# ── DRAW HEATMAP ──────────────────────────────────────────────────────────────
op.print_md("## 🎨 Drawing Integration [HH] Heatmap...")

region_type = None
for rt in FilteredElementCollector(doc).OfClass(FilledRegionType):
    region_type = rt
    break

if not region_type:
    forms.alert("No FilledRegionType found in document.\nLoad a filled region style first.", exitscript=True)

t = Transaction(doc, "VGA Integration HH")
t.Start()


new_view_id = view.Duplicate(ViewDuplicateOption.Duplicate)
new_view    = doc.GetElement(new_view_id)
new_view.Name = view.Name + " - Integration HH"

for idx, (cx, cy) in enumerate(all_nodes):
    n     = quantile_n[idx]
    color = get_color(n)

    x0 = cx - GRID_SIZE/2;  y0 = cy - GRID_SIZE/2
    x1 = cx + GRID_SIZE/2;  y1 = cy + GRID_SIZE/2

    p1 = XYZ(x0, y0, node_z);  p2 = XYZ(x1, y0, node_z)
    p3 = XYZ(x1, y1, node_z);  p4 = XYZ(x0, y1, node_z)

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
