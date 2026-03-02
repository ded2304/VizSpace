# -*- coding: utf-8 -*-
"""
VizSpaceIsovist - 2D Raycasting + Polygon + Report
Revit 2024+
"""

from pyrevit import revit, DB, UI, script
from Autodesk.Revit.UI.Selection import ObjectType
from System.Collections.Generic import List
import math

doc = revit.doc
uidoc = revit.uidoc
view = doc.ActiveView

# ---------------------------------------------------------
# Ensure Floor Plan
# ---------------------------------------------------------
if not isinstance(view, DB.ViewPlan):
    UI.TaskDialog.Show("VizSpaceIsovist",
                       "Run inside a Floor Plan view.")
    script.exit()

# ---------------------------------------------------------
# Pick point
# ---------------------------------------------------------
try:
    origin = uidoc.Selection.PickPoint("Click a point for Isovist analysis")
except:
    script.exit()

ray_count = 360
max_range = 100

# ---------------------------------------------------------
# Duplicate View
# ---------------------------------------------------------
t_dup = DB.Transaction(doc, "Duplicate View")
t_dup.Start()

new_view_id = view.Duplicate(DB.ViewDuplicateOption.Duplicate)
analysis_view = doc.GetElement(new_view_id)
analysis_view.Name = view.Name + "_Isovist"

t_dup.Commit()

# ---------------------------------------------------------
# Collect Walls
# ---------------------------------------------------------
walls = DB.FilteredElementCollector(doc, view.Id)\
    .OfClass(DB.Wall)\
    .WhereElementIsNotElementType()\
    .ToElements()

# ---------------------------------------------------------
# Collect Doors
# ---------------------------------------------------------
doors = DB.FilteredElementCollector(doc, view.Id)\
    .OfCategory(DB.BuiltInCategory.OST_Doors)\
    .WhereElementIsNotElementType()\
    .ToElements()

door_openings = {}

for door in doors:
    host = door.Host
    if not host:
        continue

    if not isinstance(host.Location, DB.LocationCurve):
        continue

    wall_curve = host.Location.Curve

    width_param = door.Symbol.LookupParameter("Width")
    if not width_param:
        continue

    half_width = width_param.AsDouble() / 2.0
    door_point = door.Location.Point

    proj = wall_curve.Project(door_point)
    if not proj:
        continue

    param_center = proj.Parameter
    min_param = param_center - half_width
    max_param = param_center + half_width

    if host.Id not in door_openings:
        door_openings[host.Id] = []

    door_openings[host.Id].append((min_param, max_param))

# ---------------------------------------------------------
# Raycasting
# ---------------------------------------------------------
t = DB.Transaction(doc, "Isovist Raycasting")
t.Start()

boundary_points = []
visible_rays = 0
blocked_rays = 0

for i in range(ray_count):

    angle = (2 * math.pi / ray_count) * i

    direction = DB.XYZ(math.cos(angle),
                       math.sin(angle),
                       0)

    ray_end = origin + direction.Multiply(max_range)

    closest_dist = max_range
    hit_found = False

    for wall in walls:

        if not isinstance(wall.Location, DB.LocationCurve):
            continue

        wall_curve = wall.Location.Curve

        ws = wall_curve.GetEndPoint(0)
        we = wall_curve.GetEndPoint(1)

        x1, y1 = origin.X, origin.Y
        x2, y2 = ray_end.X, ray_end.Y
        x3, y3 = ws.X, ws.Y
        x4, y4 = we.X, we.Y

        denom = (x1-x2)*(y3-y4) - (y1-y2)*(x3-x4)
        if abs(denom) < 1e-9:
            continue

        t_param = ((x1-x3)*(y3-y4) - (y1-y3)*(x3-x4)) / denom
        u_param = ((x1-x3)*(y1-y2) - (y1-y3)*(x1-x2)) / denom

        if t_param <= 0:
            continue

        if not (0 <= u_param <= 1):
            continue

        ix = x1 + t_param*(x2-x1)
        iy = y1 + t_param*(y2-y1)
        intersection = DB.XYZ(ix, iy, origin.Z)

        # Door check
        allow_pass = False

        if wall.Id in door_openings:
            proj = wall_curve.Project(intersection)
            if proj:
                param_hit = proj.Parameter
                for (min_p, max_p) in door_openings[wall.Id]:
                    if min_p <= param_hit <= max_p:
                        allow_pass = True
                        break

        if allow_pass:
            continue

        dist = origin.DistanceTo(intersection)

        if dist < closest_dist:
            closest_dist = dist
            hit_found = True

    if hit_found:
        end_point = origin + direction.Multiply(closest_dist)
        blocked_rays += 1
    else:
        end_point = ray_end
        visible_rays += 1

    boundary_points.append(end_point)

    detail_line = doc.Create.NewDetailCurve(
        analysis_view,
        DB.Line.CreateBound(origin, end_point)
    )

    ogs = DB.OverrideGraphicSettings()
    ogs.SetProjectionLineWeight(1)

    if hit_found:
        ogs.SetProjectionLineColor(DB.Color(220, 0, 0))
    else:
        ogs.SetProjectionLineColor(DB.Color(0, 180, 0))

    analysis_view.SetElementOverrides(detail_line.Id, ogs)

# ---------------------------------------------------------
# Build Isovist Polygon
# ---------------------------------------------------------
curve_loop = DB.CurveLoop()

for i in range(len(boundary_points)):
    p1 = boundary_points[i]
    p2 = boundary_points[(i + 1) % len(boundary_points)]
    curve_loop.Append(DB.Line.CreateBound(p1, p2))

loops = List[DB.CurveLoop]()
loops.Add(curve_loop)

fr_type = DB.FilteredElementCollector(doc)\
    .OfClass(DB.FilledRegionType)\
    .FirstElement()

filled_region = DB.FilledRegion.Create(
    doc,
    fr_type.Id,
    analysis_view.Id,
    loops
)

# ---------------------------------------------------------
# Green Transparent Override
# ---------------------------------------------------------

ogs_poly = DB.OverrideGraphicSettings()

green_color = DB.Color(0, 180, 0)

# Set green fill color
ogs_poly.SetSurfaceForegroundPatternColor(green_color)

# Find solid fill pattern
solid_fill = None
fill_patterns = DB.FilteredElementCollector(doc)\
    .OfClass(DB.FillPatternElement)

for pat in fill_patterns:
    if pat.GetFillPattern().IsSolidFill:
        solid_fill = pat
        break

if solid_fill:
    ogs_poly.SetSurfaceForegroundPatternId(solid_fill.Id)

# Set transparency (0-100)
ogs_poly.SetSurfaceTransparency(70)

# Darker green boundary
ogs_poly.SetProjectionLineColor(DB.Color(0, 120, 0))
ogs_poly.SetProjectionLineWeight(6)

analysis_view.SetElementOverrides(filled_region.Id, ogs_poly)

t.Commit()

# ---------------------------------------------------------
# Metrics
# ---------------------------------------------------------
def compute_perimeter(points):
    perimeter = 0.0
    for i in range(len(points)):
        perimeter += points[i].DistanceTo(points[(i+1)%len(points)])
    return perimeter

def compute_centroid(points):
    A = 0.0
    cx = 0.0
    cy = 0.0

    for i in range(len(points)):
        x0, y0 = points[i].X, points[i].Y
        x1, y1 = points[(i+1)%len(points)].X, points[(i+1)%len(points)].Y
        cross = x0 * y1 - x1 * y0
        A += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross

    A *= 0.5
    if abs(A) < 1e-9:
        return None

    return DB.XYZ(cx/(6*A), cy/(6*A), origin.Z)

area = 0.0
for i in range(len(boundary_points)):
    x1 = boundary_points[i].X
    y1 = boundary_points[i].Y
    x2 = boundary_points[(i+1)%len(boundary_points)].X
    y2 = boundary_points[(i+1)%len(boundary_points)].Y
    area += (x1*y2 - x2*y1)

area = abs(area) / 2.0

perimeter = compute_perimeter(boundary_points)
compactness = (4 * math.pi * area) / (perimeter * perimeter)
centroid = compute_centroid(boundary_points)
drift_mag = origin.DistanceTo(centroid)
drift_dir = math.degrees(math.atan2(
    centroid.Y-origin.Y,
    centroid.X-origin.X))

coverage = (float(visible_rays) / ray_count) * 100
occlusivity = float(blocked_rays) / ray_count

# ---------------------------------------------------------
# Generate Report
# ---------------------------------------------------------

report_text = """
IISOVIST ANALYTICAL REPORT
---------------------------------------------

View: {0}

1. ISOVIST AREA

Computed Area: {1:.2f} sq.ft

A large isovist area indicates open, expansive spaces that afford easy orientation.
Franz and Wiener (2005) demonstrated correlation between isovist area and perceived spaciousness.
The 2022 Hong Kong study found sudden excessive openness may increase stress.

------------------------------------------------

2. ISOVIST PERIMETER

Computed Perimeter: {2:.2f} ft

Koutsolampros et al. (2019) found perimeter strongly predicts movement patterns in office plans (R^2 = 0.98).

------------------------------------------------

3. COMPACTNESS

Computed Compactness: {3:.3f}

C = 4 * pi * A / P^2

Values range from 0 (elongated shape) to 1 (perfect circle).
Snopkova et al. (2023) found higher compactness increases corridor choice probability.

------------------------------------------------

4. OCCLUSIVITY

Computed Occlusivity: {4:.3f}

High occlusivity indicates hidden areas just beyond corners.
Relates to Gibson's affordance theory (1983).

------------------------------------------------

5. DRIFT

Computed Drift Magnitude: {5:.2f} ft
Computed Drift Direction: {6:.1f} degrees

Drift captures the directional pull of visible space.
Hong Kong (2022) study found drift magnitude influenced emotional response (p < 0.05).

------------------------------------------------

6. VISIBILITY COVERAGE

Coverage: {7:.1f} %

Indicates percentage of rays not blocked within max range.

------------------------------------------------

End of Report
""".format(
    view.Name,
    area,
    perimeter,
    compactness,
    occlusivity,
    drift_mag,
    drift_dir,
    coverage
)


t_report = DB.Transaction(doc, "Create Isovist Report")
t_report.Start()

view_type = None
for vft in DB.FilteredElementCollector(doc).OfClass(DB.ViewFamilyType):
    if vft.ViewFamily == DB.ViewFamily.Drafting:
        view_type = vft
        break

report_view = DB.ViewDrafting.Create(doc, view_type.Id)
report_view.Name = "Isovist_Report_" + view.Name

text_type = DB.FilteredElementCollector(doc)\
    .OfClass(DB.TextNoteType)\
    .FirstElement()

DB.TextNote.Create(
    doc,
    report_view.Id,
    DB.XYZ(0, 0, 0),
    report_text,
    text_type.Id
)

t_report.Commit()

UI.TaskDialog.Show("Report Created",
                   "Isovist report saved in Drafting Views.")