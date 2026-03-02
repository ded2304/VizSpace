# -*- coding: utf-8 -*-
__title__ = "VGA Connectivity Heatmap"
__author__ = "VizSpace"

from pyrevit import revit, forms, script
from Autodesk.Revit.DB import *
import math
import time

doc  = revit.doc
uidoc = revit.uidoc
view  = doc.ActiveView
op    = script.get_output()

start_time = time.time()

GRID_SIZE = 2.0     # Reduce to 0.5 for smoother result (slower)
TRANSPARENCY = 60

# --------------------------------------------------
# PLAN CHECK
# --------------------------------------------------
if not isinstance(view, ViewPlan) or view.ViewType != ViewType.FloorPlan:
    forms.alert("Run from a Floor Plan.", exitscript=True)

level = view.GenLevel
level_elev = level.Elevation if level else 0.0

# --------------------------------------------------
# SOLID FILL
# --------------------------------------------------
solid_id = None
for p in FilteredElementCollector(doc).OfClass(FillPatternElement):
    if p.GetFillPattern().IsSolidFill:
        solid_id = p.Id
        break

if not solid_id:
    forms.alert("No solid fill pattern found.", exitscript=True)

# --------------------------------------------------
# WALLS + DOORS
# --------------------------------------------------
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
                wall_segs.append(((p0.X,p0.Y),(p1.X,p1.Y)))

for d in FilteredElementCollector(doc)\
        .OfCategory(BuiltInCategory.OST_Doors)\
        .WhereElementIsNotElementType():

    loc = d.Location
    if isinstance(loc, LocationPoint):
        pt = loc.Point
        if abs(pt.Z - level_elev) < 2.0:
            door_pts.append((pt.X,pt.Y))

op.print_md("🧱 Walls: **{}** | 🚪 Doors: **{}**".format(len(wall_segs), len(door_pts)))

# --------------------------------------------------
# HELPERS
# --------------------------------------------------
def seg_intersect(a1,a2,b1,b2):
    def cross(o,a,b):
        return (a[0]-o[0])*(b[1]-o[1]) - (a[1]-o[1])*(b[0]-o[0])
    d1 = cross(b1,b2,a1)
    d2 = cross(b1,b2,a2)
    d3 = cross(a1,a2,b1)
    d4 = cross(a1,a2,b2)
    return ((d1>0 and d2<0) or (d1<0 and d2>0)) and \
           ((d3>0 and d4<0) or (d3<0 and d4>0))

def near_door(x,y,r=1.8):
    return any(math.hypot(dx-x,dy-y)<r for dx,dy in door_pts)

def can_see(ax,ay,bx,by):
    midx = (ax+bx)*0.5
    midy = (ay+by)*0.5
    for (wx1,wy1),(wx2,wy2) in wall_segs:
        if seg_intersect((ax,ay),(bx,by),(wx1,wy1),(wx2,wy2)):
            if near_door(midx,midy):
                continue
            return False
    return True

def point_in_polygon(px,py,poly):
    inside=False
    n=len(poly)
    x1,y1=poly[0]
    for i in range(1,n+1):
        x2,y2=poly[i%n]
        if min(y1,y2)<py<=max(y1,y2) and px<=max(x1,x2):
            xi=x1 if y1==y2 else (py-y1)*(x2-x1)/(y2-y1)+x1
            if px<=xi: inside=not inside
        x1,y1=x2,y2
    return inside

# --------------------------------------------------
# TRUE CONTINUOUS GRADIENT (Blue → Cyan → Yellow → Red)
# --------------------------------------------------
def get_color(n):
    n = max(0.0, min(1.0, n))

    if n < 0.33:
        # Blue (0,0,255) → Cyan (0,255,255)
        t = n / 0.33
        return Color(0, int(255*t), 255)

    elif n < 0.66:
        # Cyan → Yellow (255,255,0)
        t = (n-0.33)/0.33
        return Color(int(255*t), 255, int(255*(1-t)))

    else:
        # Yellow → Red (255,0,0)
        t = (n-0.66)/0.34
        return Color(255, int(255*(1-t)), 0)

# --------------------------------------------------
# BUILD GRID
# --------------------------------------------------
op.print_md("## 📍 Building Grid...")

floors = FilteredElementCollector(doc)\
    .OfCategory(BuiltInCategory.OST_Floors)\
    .WhereElementIsNotElementType()\
    .ToElements()

all_nodes=[]
node_z=level_elev

for floor in floors:
    geo=floor.get_Geometry(Options())
    for obj in geo:
        if isinstance(obj,Solid):
            for face in obj.Faces:
                if isinstance(face,PlanarFace) and abs(face.FaceNormal.Z)>0.99:
                    loops=face.GetEdgesAsCurveLoops()
                    if not loops: continue
                    poly=[(c.GetEndPoint(0).X,c.GetEndPoint(0).Y) for c in loops[0]]
                    bbox=floor.get_BoundingBox(view)
                    node_z=bbox.Min.Z

                    x=bbox.Min.X
                    while x<bbox.Max.X:
                        y=bbox.Min.Y
                        while y<bbox.Max.Y:
                            cx=x+GRID_SIZE/2.0
                            cy=y+GRID_SIZE/2.0
                            if point_in_polygon(cx,cy,poly):
                                all_nodes.append((cx,cy))
                            y+=GRID_SIZE
                        x+=GRID_SIZE

K=len(all_nodes)
op.print_md("📊 Nodes: **{}**".format(K))

if K<3:
    forms.alert("Too few grid nodes.",exitscript=True)

# --------------------------------------------------
# VISIBILITY GRAPH
# --------------------------------------------------
op.print_md("## 🔍 Building Visibility Graph...")

adj=[[] for _ in range(K)]

for i in range(K):
    ax,ay=all_nodes[i]
    for j in range(i+1,K):
        bx,by=all_nodes[j]
        if can_see(ax,ay,bx,by):
            adj[i].append(j)
            adj[j].append(i)

# --------------------------------------------------
# CONNECTIVITY
# --------------------------------------------------
op.print_md("## 📐 Computing Connectivity...")

connectivity = [float(len(adj[i])) for i in range(K)]

c_min=min(connectivity)
c_max=max(connectivity)
c_range=c_max-c_min if c_max!=c_min else 1.0

# --------------------------------------------------
# DRAW HEATMAP
# --------------------------------------------------
op.print_md("## 🎨 Drawing Heatmap...")

region_type = FilteredElementCollector(doc)\
    .OfClass(FilledRegionType)\
    .FirstElement()

t=Transaction(doc,"VGA Connectivity Heatmap")
t.Start()

new_view_id=view.Duplicate(ViewDuplicateOption.Duplicate)
new_view=doc.GetElement(new_view_id)
new_view.Name=view.Name+" - Connectivity"

for idx,(cx,cy) in enumerate(all_nodes):

    n=(connectivity[idx]-c_min)/c_range
    color=get_color(n)

    x0=cx-GRID_SIZE/2
    y0=cy-GRID_SIZE/2
    x1=cx+GRID_SIZE/2
    y1=cy+GRID_SIZE/2

    p1=XYZ(x0,y0,node_z)
    p2=XYZ(x1,y0,node_z)
    p3=XYZ(x1,y1,node_z)
    p4=XYZ(x0,y1,node_z)

    loop=CurveLoop()
    loop.Append(Line.CreateBound(p1,p2))
    loop.Append(Line.CreateBound(p2,p3))
    loop.Append(Line.CreateBound(p3,p4))
    loop.Append(Line.CreateBound(p4,p1))

    region=FilledRegion.Create(doc,region_type.Id,new_view.Id,[loop])

    ogs=OverrideGraphicSettings()
    ogs.SetSurfaceForegroundPatternId(solid_id)
    ogs.SetSurfaceForegroundPatternColor(color)
    ogs.SetSurfaceTransparency(TRANSPARENCY)

    new_view.SetElementOverrides(region.Id,ogs)

t.Commit()

elapsed=time.time()-start_time
op.print_md("## ✅ Complete in {:.2f} seconds".format(elapsed))
op.print_md("### View Created: **{}**".format(new_view.Name))