#!/usr/bin/env python3
"""
Generate InvertorsDocs/SideQuests-Patent-Figures.excalidraw
from the 7 patent figures defined in SideQuests-Patent-Figures.md.
"""
import json, random
random.seed(42)

elements = []
_eid = [0]

# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------

def _next_id(prefix):
    _eid[0] += 1
    return f"{prefix}{_eid[0]:05d}"

def _idx():
    return f"a{_eid[0]:05d}"

def _base(eid):
    return {
        "id": eid,
        "angle": 0,
        "fillStyle": "solid",
        "strokeWidth": 1,
        "strokeStyle": "solid",
        "roughness": 0,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "roundness": None,
        "version": 2,
        "versionNonce": random.randint(1, 999999),
        "isDeleted": False,
        "boundElements": [],
        "updated": 1774220097921,
        "link": None,
        "locked": False,
        "seed": random.randint(1, 999999),
        "index": _idx(),
    }


def add_rect(x, y, w, h, *, fill="#f8f9fa", stroke="#343a40",
             dashed=False, rounded=True):
    eid = _next_id("r")
    el = _base(eid)
    el.update({
        "type": "rectangle",
        "x": x, "y": y, "width": w, "height": h,
        "strokeColor": stroke, "backgroundColor": fill,
        "strokeStyle": "dashed" if dashed else "solid",
        "roundness": {"type": 3} if rounded else None,
    })
    elements.append(el)
    return eid


def add_diamond(x, y, w, h, *, fill="#fff9db", stroke="#e67700"):
    eid = _next_id("d")
    el = _base(eid)
    el.update({
        "type": "diamond",
        "x": x, "y": y, "width": w, "height": h,
        "strokeColor": stroke, "backgroundColor": fill,
        "roundness": None,
    })
    elements.append(el)
    return eid


def add_text(x, y, s, *, size=12, color="#1e1e1e",
             align="left", valign="top", container=None, w=None, h=None):
    eid = _next_id("t")
    lines = s.split("\n")
    if w is None:
        w = max(len(ln) for ln in lines) * size * 0.58 + 12
    if h is None:
        h = len(lines) * size * 1.35 + 6
    el = _base(eid)
    el.update({
        "type": "text",
        "x": x, "y": y, "width": w, "height": h,
        "strokeColor": color, "backgroundColor": "transparent",
        "roundness": None,
        "text": s, "fontSize": size, "fontFamily": 1,
        "textAlign": align,
        "verticalAlign": valign,
        "containerId": container,
        "originalText": s,
        "lineHeight": 1.35,
        "autoResize": True,
    })
    elements.append(el)
    return eid


def add_arrow(x1, y1, x2, y2, *, label=None, color="#495057", dashed=False):
    eid = _next_id("a")
    el = _base(eid)
    el.update({
        "type": "arrow",
        "x": x1, "y": y1,
        "width": abs(x2 - x1), "height": abs(y2 - y1),
        "strokeColor": color, "backgroundColor": "transparent",
        "strokeStyle": "dashed" if dashed else "solid",
        "roundness": None,
        "points": [[0, 0], [x2 - x1, y2 - y1]],
        "lastCommittedPoint": None,
        "startBinding": None, "endBinding": None,
        "startArrowhead": None, "endArrowhead": "arrow",
        "elbowed": False,
    })
    elements.append(el)
    if label:
        mx = (x1 + x2) / 2
        my = (y1 + y2) / 2
        lw = len(label) * 8 + 8
        add_text(mx - lw / 2, my - 14, label, size=10, color="#868e96",
                 align="center", w=lw, h=14)
    return eid


# ---------------------------------------------------------------------------
# High-level shape helpers
# ---------------------------------------------------------------------------
NW, NH = 190, 46   # default node width / height
DW, DH = 160, 72   # diamond width / height
VS = 18            # vertical spacing between stacked nodes
STEP = NH + VS     # full vertical step


def node(cx, y, s, *, fill="#f8f9fa", stroke="#343a40", w=None):
    """Rounded rectangle centered at cx, top at y, with bound label."""
    ww = w or NW
    rid = add_rect(cx - ww // 2, y, ww, NH, fill=fill, stroke=stroke)
    tid = _next_id("t")  # pre-reserve id for bound text
    # patch boundElements on the rect we just added
    elements[-1]["boundElements"] = [{"type": "text", "id": tid}]
    # now add the text with that id
    el = _base(tid)
    lines = s.split("\n")
    th = len(lines) * 12 * 1.35 + 4
    el.update({
        "type": "text",
        "x": cx - ww // 2 + 4,
        "y": y + (NH - th) / 2,
        "width": ww - 8, "height": th,
        "strokeColor": "#1e1e1e", "backgroundColor": "transparent",
        "roundness": None,
        "text": s, "fontSize": 12, "fontFamily": 1,
        "textAlign": "center", "verticalAlign": "middle",
        "containerId": rid, "originalText": s,
        "lineHeight": 1.35, "autoResize": True,
    })
    elements.append(el)
    return rid


def diam(cx, y, s, *, fill="#fff9db", stroke="#e67700", h=None):
    """Diamond centered at cx, top at y, with bound label."""
    dh = h or DH
    did = add_diamond(cx - DW // 2, y, DW, dh, fill=fill, stroke=stroke)
    tid = _next_id("t")
    elements[-1]["boundElements"] = [{"type": "text", "id": tid}]
    lines = s.split("\n")
    th = len(lines) * 11 * 1.35 + 4
    el = _base(tid)
    el.update({
        "type": "text",
        "x": cx - DW // 2 + 14,
        "y": y + (dh - th) / 2,
        "width": DW - 28, "height": th,
        "strokeColor": "#1e1e1e", "backgroundColor": "transparent",
        "roundness": None,
        "text": s, "fontSize": 11, "fontFamily": 1,
        "textAlign": "center", "verticalAlign": "middle",
        "containerId": did, "originalText": s,
        "lineHeight": 1.35, "autoResize": True,
    })
    elements.append(el)
    return did


def heading(x, y, s):
    add_text(x, y, s, size=20, color="#1e1e1e", align="left", w=900, h=28)


def cap(x, y, s):
    add_text(x, y, s, size=11, color="#495057", align="left", w=900,
             h=len(s.split("\n")) * 11 * 1.35 + 6)


def frame(x, y, w, h, label=None, *, stroke="#868e96", dashed=True):
    add_rect(x, y, w, h, fill="transparent", stroke=stroke,
             dashed=dashed, rounded=False)
    if label:
        add_text(x + 8, y + 6, label, size=10, color=stroke,
                 w=len(label) * 7 + 6, h=14)


def varrow(cx, y_src_top, y_dst_top, *, label=None, color="#495057"):
    """Vertical arrow: bottom-center of src → top-center of dst."""
    add_arrow(cx, y_src_top + NH, cx, y_dst_top, label=label, color=color)


def varrow_d(cx, dy_top, y_dst_top, *, label=None, color="#495057"):
    """Vertical arrow: diamond bottom → node top."""
    add_arrow(cx, dy_top + DH, cx, y_dst_top, label=label, color=color)


def left_d(cx, dy_top, dst_cx, dst_y, *, label=None, color="#495057"):
    """Arrow: diamond left point → dest node (connects to right edge of dest)."""
    ex = dst_cx + (NW // 2) if dst_cx < cx else dst_cx - (NW // 2)
    add_arrow(cx - DW // 2, dy_top + DH // 2, ex, dst_y + NH // 2,
              label=label, color=color)


def right_d(cx, dy_top, dst_cx, dst_y, *, label=None, color="#495057"):
    """Arrow: diamond right point → dest node."""
    ex = dst_cx - (NW // 2) if dst_cx > cx else dst_cx + (NW // 2)
    add_arrow(cx + DW // 2, dy_top + DH // 2, ex, dst_y + NH // 2,
              label=label, color=color)


# ---------------------------------------------------------------------------
# FIGURE 1  —  System Architecture
# ---------------------------------------------------------------------------
F1X, F1Y = 60, 60
heading(F1X, F1Y, "FIG. 1  —  System Architecture (Decoupled Brain Model)")
cap(F1X, F1Y + 32,
    "FIG. 1 illustrates the modular, decoupled system topology comprising per-client adapters,\n"
    "two separate message capture paths, a local Brain Daemon, graph/vector persistence,\n"
    "and a user-facing memory control panel bound to 127.0.0.1.")

DY1 = F1Y + 110

# Capture group
frame(F1X, DY1, 210, 110, "Capture", stroke="#0c8599")
node(F1X + 105, DY1 + 14, "Hook: UserPromptSubmit", fill="#e3fafc", stroke="#0c8599")
node(F1X + 105, DY1 + 64, "notify_turn MCP call",   fill="#e3fafc", stroke="#0c8599")

# Client adapter group
CLI_X = F1X + 255
frame(CLI_X, DY1, 210, 110, "Client Adapter", stroke="#7048e8")
node(CLI_X + 105, DY1 + 38, "AI Client Adapter", fill="#f3f0ff", stroke="#7048e8")

# MCP Tool Surface
MCP_X = F1X + 510
node(MCP_X + 95, DY1 + 38, "MCP Tool Surface", fill="#e7f5ff", stroke="#1c7ed6", w=190)

# Brain Daemon
BD_X = F1X + 755
node(BD_X + 95, DY1 + 38, "Brain Daemon", fill="#ebfbee", stroke="#2f9e44", w=190)

# Storage cluster
ST_X = F1X + 1010
node(ST_X + 95, DY1,      "Graph + Vector Store",          fill="#fff9db", stroke="#e67700", w=200)
node(ST_X + 95, DY1 + 54, "Background Sweep",              fill="#fff4e6", stroke="#f76707", w=200)
node(ST_X + 95, DY1 + 108,"Memory Control Panel\n127.0.0.1", fill="#ffe8cc", stroke="#d9480f", w=200)

# Arrows
add_arrow(F1X + 210, DY1 + 37,  CLI_X,     DY1 + 61, label="user turns",  color="#0c8599")
add_arrow(F1X + 210, DY1 + 87,  CLI_X,     DY1 + 61, label="asst turns",  color="#0c8599")
add_arrow(CLI_X + 210, DY1 + 61, MCP_X,    DY1 + 61)
add_arrow(MCP_X + 190, DY1 + 61, BD_X,     DY1 + 61)
add_arrow(BD_X + 190,  DY1 + 61, ST_X,     DY1 + 23)
add_arrow(BD_X + 190,  DY1 + 61, ST_X,     DY1 + 77)
add_arrow(BD_X + 190,  DY1 + 61, ST_X,     DY1 + 131)

F1_BOTTOM = DY1 + 160


# ---------------------------------------------------------------------------
# FIGURE 2  —  9-Step Gated Consolidation Loop
# ---------------------------------------------------------------------------
F2X, F2Y = 60, F1_BOTTOM + 80
heading(F2X, F2Y, "FIG. 2  —  9-Step Gated Consolidation Loop")
cap(F2X, F2Y + 32,
    "FIG. 2 illustrates the ordered 9-step consolidation method: NER / zoning, relation fast-path,\n"
    "dual-process gist classification, schema.org sub-graph routing, semantic relation extraction,\n"
    "confidence gating, dual-scope retrieval, contradiction arbitration, and pathway update.")

DY2 = F2Y + 110
CX2 = F2X + 320

STEPS2 = [
    ("Input Turn / Document",            "#e7f5ff", "#1c7ed6"),
    ("Step 1: NER / Zoning",             "#f8f9fa", "#495057"),
    ("Step 1b: Relation Fast Path",      "#f8f9fa", "#495057"),
    ("Step 2: gist Classification",      "#f8f9fa", "#495057"),
    ("Step 3: schema.org Sub-graph Routing", "#f8f9fa", "#495057"),
    ("Step 3b: Semantic Relation Extraction","#f8f9fa", "#495057"),
]
for i, (lbl, fill, stroke) in enumerate(STEPS2):
    node(CX2, DY2 + i * STEP, lbl, fill=fill, stroke=stroke, w=260)
    if i > 0:
        varrow(CX2, DY2 + (i - 1) * STEP, DY2 + i * STEP)

# Confidence gate diamond
GATE2_Y = DY2 + len(STEPS2) * STEP
diam(CX2, GATE2_Y, "Step 4:\nConfidence Gate")
varrow(CX2, DY2 + (len(STEPS2) - 1) * STEP, GATE2_Y)

# Three branches
BR2_Y = GATE2_Y + DH + 20
N2_CX = CX2 - 320
T2_CX = CX2
C2_CX = CX2 + 320
node(N2_CX, BR2_Y, "Noise Log\n(vector only)",     fill="#ffe3e3", stroke="#c92a2a", w=180)
node(T2_CX, BR2_Y, "Tentative\n(confidence_low)",  fill="#fff9db", stroke="#e67700", w=180)
node(C2_CX, BR2_Y, "Confirmed Artifact",           fill="#ebfbee", stroke="#2f9e44", w=180)
left_d( CX2, GATE2_Y, N2_CX, BR2_Y, label="<60%",  color="#c92a2a")
varrow_d(CX2, GATE2_Y, BR2_Y,        label="60-90%",color="#e67700")
right_d(CX2, GATE2_Y, C2_CX, BR2_Y, label=">90%",  color="#2f9e44")

# S5 / S6 / S7
S5_CX, S5_W = T2_CX + 140, 240
S5_Y = BR2_Y + STEP + 10
S6_Y = S5_Y + STEP
S7_Y = S6_Y + STEP
node(S5_CX, S5_Y, "Step 5: Dual-Scope Retrieval",     fill="#f8f9fa", stroke="#495057", w=S5_W)
node(S5_CX, S6_Y, "Step 6: Contradiction Arbitration", fill="#f8f9fa", stroke="#495057", w=S5_W)
node(S5_CX, S7_Y, "Step 7: Pathway Update + Lineage",  fill="#f8f9fa", stroke="#495057", w=S5_W)

add_arrow(T2_CX + 90, BR2_Y + NH, S5_CX - S5_W // 2, S5_Y + NH // 2)
add_arrow(C2_CX - 90, BR2_Y + NH, S5_CX + S5_W // 2, S5_Y + NH // 2)
varrow(S5_CX, S5_Y, S6_Y)
varrow(S5_CX, S6_Y, S7_Y)

F2_BOTTOM = S7_Y + NH


# ---------------------------------------------------------------------------
# FIGURE 3  —  Cocktail Party Effect
# ---------------------------------------------------------------------------
F3X, F3Y = 60, F2_BOTTOM + 80
heading(F3X, F3Y, "FIG. 3  —  Cocktail Party Effect: Selective Attention and Confidence Gating")
cap(F3X, F3Y + 32,
    "FIG. 3 illustrates the passive selective attention mechanism: six cognitive senses evaluate inbound content,\n"
    "a confidence score gates the result into noise, tentative, or confirmed paths, and a dedicated anomaly\n"
    "branch flags GlobalConstraint violations as potential prompt injection or goal hijacking.")

DY3 = F3Y + 110
CX3 = F3X + 540

node(CX3, DY3,        "Inbound Turn  (Always Listening)", fill="#e7f5ff", stroke="#1c7ed6", w=280)
node(CX3, DY3 + STEP, "Sense Evaluation",                 fill="#f1f3f5", stroke="#868e96", w=220)
varrow(CX3, DY3, DY3 + STEP)

# Six senses
SENSE_Y = DY3 + STEP * 2 + 10
SENSES3 = [
    (CX3 - 525, "Decision\nSense",     "#e7f5ff", "#1c7ed6"),
    (CX3 - 315, "Constraint\nSense",   "#fff4e6", "#e67700"),
    (CX3 - 105, "Plan\nSense",         "#ebfbee", "#2f9e44"),
    (CX3 + 105, "Entity\nSense",       "#f3f0ff", "#7048e8"),
    (CX3 + 315, "Contradiction\nSense","#ffe3e3", "#c92a2a"),
    (CX3 + 525, "Anomaly\nSense",      "#f3d9fa", "#ae3ec9"),
]
SW = 160
for sx, lbl, fill, stk in SENSES3:
    node(sx, SENSE_Y, lbl, fill=fill, stroke=stk, w=SW)
    add_arrow(CX3, DY3 + STEP + NH, sx, SENSE_Y)

# Confidence score diamond
GATE3_Y = SENSE_Y + STEP + 10
diam(CX3, GATE3_Y, "Confidence\nScore")
for sx, _, _, _ in SENSES3:
    add_arrow(sx, SENSE_Y + NH, CX3 - DW // 2 + 10, GATE3_Y + DH // 2)

# Three result paths
RES3_Y = GATE3_Y + DH + 20
node(CX3 - 320, RES3_Y, "Noise:\nVector Log Only",       fill="#ffe3e3", stroke="#c92a2a", w=200)
node(CX3,       RES3_Y, "Tentative:\nconfidence_low",    fill="#fff9db", stroke="#e67700", w=200)
node(CX3 + 320, RES3_Y, "Confirmed:\nStructural Write",  fill="#ebfbee", stroke="#2f9e44", w=200)
left_d( CX3, GATE3_Y, CX3 - 320, RES3_Y, label="<60%",  color="#c92a2a")
varrow_d(CX3, GATE3_Y, RES3_Y,           label="60-90%", color="#e67700")
right_d(CX3, GATE3_Y, CX3 + 320, RES3_Y,label=">90%",   color="#2f9e44")

# Anomaly alert branch (far right)
ANOM_CX = CX3 + 620
node(ANOM_CX, SENSE_Y + 20, "Anomaly Alert\n(GlobalConstraint violated)", fill="#f3d9fa", stroke="#ae3ec9", w=230)
add_arrow(CX3 + 525 + SW // 2, SENSE_Y + NH // 2, ANOM_CX - 115, SENSE_Y + 43, color="#ae3ec9")

# Re-scoring downstream
RESCORE3_Y = RES3_Y + STEP
node(CX3 - 320, RESCORE3_Y, "Eligible for\nBackground Re-Scoring", fill="#f8f9fa", stroke="#868e96", w=220)
varrow(CX3 - 320, RES3_Y, RESCORE3_Y)

F3_BOTTOM = RESCORE3_Y + NH


# ---------------------------------------------------------------------------
# FIGURE 4  —  Temporal Truth and Reversible Merge Lineage
# ---------------------------------------------------------------------------
F4X, F4Y = 60, F3_BOTTOM + 80
heading(F4X, F4Y, "FIG. 4  —  Temporal Truth and Reversible Merge Lineage")
cap(F4X, F4Y + 32,
    "FIG. 4 illustrates temporal truth handling: additive evidence increments pathway_strength;\n"
    "contradictory evidence creates a new artifact node linked by a DEPRECATED_BY edge with a\n"
    "MergeEvent audit record enabling deterministic rollback; uncertain evidence produces a soft-lock.")

DY4 = F4Y + 110
CX4 = F4X + 360

node(CX4, DY4, "Existing Artifact Node", fill="#e7f5ff", stroke="#1c7ed6", w=220)

GATE4_Y = DY4 + STEP
diam(CX4, GATE4_Y, "New Evidence\nType?")
varrow(CX4, DY4, GATE4_Y)

BR4_Y = GATE4_Y + DH + 20
ADD_CX  = CX4 - 340
CONT_CX = CX4
UNC_CX  = CX4 + 340

node(ADD_CX,  BR4_Y, "Increment\npathway_strength", fill="#ebfbee", stroke="#2f9e44", w=190)
node(CONT_CX, BR4_Y, "Create New\nArtifact Node",   fill="#ffe3e3", stroke="#c92a2a", w=190)
node(UNC_CX,  BR4_Y, "Soft-Lock:\nconfidence_low",  fill="#fff9db", stroke="#e67700", w=190)

left_d( CX4, GATE4_Y, ADD_CX,  BR4_Y, label="Additive",     color="#2f9e44")
varrow_d(CX4, GATE4_Y, BR4_Y,         label="Contradiction", color="#c92a2a")
right_d(CX4, GATE4_Y, UNC_CX,  BR4_Y, label="Uncertain",    color="#e67700")

# Contradiction path
DEP4_Y     = BR4_Y + STEP
MERGE4_Y   = DEP4_Y + STEP
ROLLBACK_Y = MERGE4_Y + STEP
node(CONT_CX, DEP4_Y,     "DEPRECATED_BY → old node",        fill="#ffe3e3", stroke="#c92a2a", w=220)
node(CONT_CX, MERGE4_Y,   "MergeEvent Audit Record",          fill="#f8f9fa", stroke="#495057", w=220)
node(CONT_CX, ROLLBACK_Y, "Rollback: Delete MergeEvent",      fill="#f3f0ff", stroke="#7048e8", w=220)
varrow(CONT_CX, BR4_Y,   DEP4_Y)
varrow(CONT_CX, DEP4_Y,  MERGE4_Y)
varrow(CONT_CX, MERGE4_Y, ROLLBACK_Y)

# Uncertain path
AWAIT4_Y = BR4_Y + STEP
node(UNC_CX, AWAIT4_Y, "Await Arbitration\nor User Review", fill="#fff9db", stroke="#e67700", w=200)
varrow(UNC_CX, BR4_Y, AWAIT4_Y)

F4_BOTTOM = max(ROLLBACK_Y, AWAIT4_Y) + NH


# ---------------------------------------------------------------------------
# FIGURE 5  —  Working Memory Awareness, Deduplication, Session Handoff
# ---------------------------------------------------------------------------
F5X, F5Y = 60, F4_BOTTOM + 80
heading(F5X, F5Y, "FIG. 5  —  Working Memory Awareness, Deduplication, and Session Handoff")
cap(F5X, F5Y + 32,
    "FIG. 5 illustrates working-memory state tracking via Session→[LOADED]→Artifact edges, token burden\n"
    "estimation, smart deduplication with relevance demotion, refresher reinjection gating, and Session\n"
    "Handoff Intelligence that seeds a new session with the prior session's top loaded artifacts.")

DY5 = F5Y + 110
CX5 = F5X + 310

STEPS5 = [
    ("current_truth Retrieval",              "#e7f5ff", "#1c7ed6"),
    ("Inject Artifact into Active Session",  "#f8f9fa", "#495057"),
    ("Session —[LOADED]→ Artifact Edge",     "#f8f9fa", "#495057"),
    ("Record: token_estimate + injected_at", "#f8f9fa", "#495057"),
    ("Subsequent Retrieval",                 "#f8f9fa", "#495057"),
]
for i, (lbl, fill, stk) in enumerate(STEPS5):
    node(CX5, DY5 + i * STEP, lbl, fill=fill, stroke=stk, w=260)
    if i > 0:
        varrow(CX5, DY5 + (i - 1) * STEP, DY5 + i * STEP)

LOAD_D5_Y = DY5 + len(STEPS5) * STEP
diam(CX5, LOAD_D5_Y, "Already\nLOADED?")
varrow(CX5, DY5 + (len(STEPS5) - 1) * STEP, LOAD_D5_Y)

DEM_Y  = LOAD_D5_Y + DH + 20
RANK_Y = LOAD_D5_Y + DH + 20
DEM_CX  = CX5 - 240
RANK_CX = CX5 + 240
node(DEM_CX,  DEM_Y,  "Demote:\nrelevance × 0.3", fill="#ffe3e3", stroke="#c92a2a", w=190)
node(RANK_CX, RANK_Y, "Rank Normally",             fill="#ebfbee", stroke="#2f9e44", w=190)
left_d( CX5, LOAD_D5_Y, DEM_CX,  DEM_Y,  label="Yes", color="#c92a2a")
right_d(CX5, LOAD_D5_Y, RANK_CX, RANK_Y, label="No",  color="#2f9e44")

# Refresher gate
REF_D5_Y = DEM_Y + STEP
diam(DEM_CX, REF_D5_Y, "High-Salience\nRefresher?")
varrow(DEM_CX, DEM_Y, REF_D5_Y)

ALLOW_Y   = REF_D5_Y + DH + 20
SUPPRESS_Y = REF_D5_Y + DH + 20
ALLOW_CX   = DEM_CX - 150
SUPP_CX    = DEM_CX + 190
node(ALLOW_CX, ALLOW_Y,   "Allow\nReinjection",      fill="#ebfbee", stroke="#2f9e44", w=160)
node(SUPP_CX,  SUPPRESS_Y,"Suppress Redundant\nInjection", fill="#ffe3e3", stroke="#c92a2a", w=190)
add_arrow(DEM_CX - DW // 2, REF_D5_Y + DH // 2, ALLOW_CX + 80, ALLOW_Y + NH // 2,   label="Yes", color="#2f9e44")
add_arrow(DEM_CX + DW // 2, REF_D5_Y + DH // 2, SUPP_CX - 95,  SUPPRESS_Y + NH // 2, label="No",  color="#c92a2a")

# Session Handoff path (from Record node, level i=3)
SH_X = CX5 + 520
SH_Y0 = DY5 + 3 * STEP
node(SH_X + 100, SH_Y0,          "New Session\non Same Quest?", fill="#e7f5ff", stroke="#1c7ed6", w=210)
add_arrow(CX5 + 130, SH_Y0 + NH // 2, SH_X, SH_Y0 + NH // 2, label="Yes →", color="#1c7ed6")

SH_Y1 = SH_Y0 + STEP
SH_Y2 = SH_Y1 + STEP
SH_Y3 = SH_Y2 + STEP
node(SH_X + 100, SH_Y1, "Session Handoff\nIntelligence",       fill="#f3f0ff", stroke="#7048e8", w=210)
node(SH_X + 100, SH_Y2, "Load Top 5 LOADED\nfrom Prior Session",fill="#f3f0ff", stroke="#7048e8", w=210)
node(SH_X + 100, SH_Y3, "Inject into New\nSession Context",    fill="#ebfbee", stroke="#2f9e44", w=210)
varrow(SH_X + 100, SH_Y0, SH_Y1)
varrow(SH_X + 100, SH_Y1, SH_Y2)
varrow(SH_X + 100, SH_Y2, SH_Y3)

F5_BOTTOM = max(ALLOW_Y, SUPPRESS_Y, SH_Y3) + NH


# ---------------------------------------------------------------------------
# FIGURE 6  —  Semantic Quest Routing (Hippocampus)
# ---------------------------------------------------------------------------
F6X, F6Y = 60, F5_BOTTOM + 80
heading(F6X, F6Y, "FIG. 6  —  Semantic Quest Routing (Hippocampus Mechanism)")
cap(F6X, F6Y + 32,
    "FIG. 6 illustrates multi-signal routing fusion computing a confidence score from semantic intent,\n"
    "entity overlap, and workspace context; threshold-based quest attachment; LLM escalation for\n"
    "ambiguous cases; and prediction-error reconsolidation via Long-Term Depression (LTD).")

DY6 = F6Y + 110
CX6 = F6X + 430

node(CX6, DY6,        "New Session Thread",     fill="#e7f5ff", stroke="#1c7ed6", w=220)
node(CX6, DY6 + STEP, "Extract Initial Signals",fill="#f8f9fa", stroke="#495057", w=220)
varrow(CX6, DY6, DY6 + STEP)

SIG6_Y = DY6 + STEP * 2 + 10
SIG_W = 190
SEM_CX  = CX6 - 300
ENT_CX  = CX6
WRK_CX  = CX6 + 300
node(SEM_CX, SIG6_Y, "Semantic Intent\nEmbedding",   fill="#f8f9fa", stroke="#495057", w=SIG_W)
node(ENT_CX, SIG6_Y, "Entity Overlap\n(1-hop graph)",fill="#f8f9fa", stroke="#495057", w=SIG_W)
node(WRK_CX, SIG6_Y, "Workspace / OS\nContext",      fill="#f8f9fa", stroke="#495057", w=SIG_W)
add_arrow(CX6, DY6 + STEP + NH, SEM_CX, SIG6_Y)
varrow(CX6, DY6 + STEP, SIG6_Y)
add_arrow(CX6, DY6 + STEP + NH, WRK_CX, SIG6_Y)

FUSE6_Y = SIG6_Y + STEP
node(CX6, FUSE6_Y, "Compute Fused Routing Confidence", fill="#f3f0ff", stroke="#7048e8", w=280)
add_arrow(SEM_CX, SIG6_Y + NH, CX6 - 140, FUSE6_Y + NH // 2)
varrow(ENT_CX, SIG6_Y, FUSE6_Y)
add_arrow(WRK_CX, SIG6_Y + NH, CX6 + 140, FUSE6_Y + NH // 2)

GATE6_Y = FUSE6_Y + STEP
diam(CX6, GATE6_Y, "Routing\nConfidence?")
varrow(CX6, FUSE6_Y, GATE6_Y)

ATT_Y = GATE6_Y + DH + 20
ATT_CX  = CX6 - 330
LLM_CX  = CX6
NEW_CX  = CX6 + 330
node(ATT_CX, ATT_Y, "Attach to Existing\nMainQuest", fill="#ebfbee", stroke="#2f9e44", w=210)
node(LLM_CX, ATT_Y, "Escalate to LLM\nDisambiguation",fill="#fff9db", stroke="#e67700", w=210)
node(NEW_CX, ATT_Y, "Create New\nMainQuest",          fill="#e3fafc", stroke="#0c8599", w=210)
left_d( CX6, GATE6_Y, ATT_CX, ATT_Y, label=">0.85",  color="#2f9e44")
varrow_d(CX6, GATE6_Y, ATT_Y,        label="0.60–0.85",color="#e67700")
right_d(CX6, GATE6_Y, NEW_CX, ATT_Y, label="<0.60",  color="#0c8599")

PRED6_Y = ATT_Y + STEP + 10
node(CX6, PRED6_Y, "Monitor Prediction Error", fill="#f8f9fa", stroke="#495057", w=240)
add_arrow(ATT_CX + 105, ATT_Y + NH, CX6 - 120, PRED6_Y + NH // 2)
varrow(LLM_CX, ATT_Y, PRED6_Y)
add_arrow(NEW_CX - 105, ATT_Y + NH, CX6 + 120, PRED6_Y + NH // 2)

PRED_D6_Y = PRED6_Y + STEP
diam(CX6, PRED_D6_Y, "Error\nDetected?")
varrow(CX6, PRED6_Y, PRED_D6_Y)

# Reroute path
REROUTE_CX = CX6 + 420
DETACH6_Y  = PRED_D6_Y + 10
LTD6_Y     = DETACH6_Y + STEP
AUDIT6_Y   = LTD6_Y + STEP
REANCHOR_Y = AUDIT6_Y + STEP
node(REROUTE_CX, DETACH6_Y, "Detach Thread",                  fill="#ffe3e3", stroke="#c92a2a", w=200)
node(REROUTE_CX, LTD6_Y,    "Weaken False Link (LTD)",        fill="#ffe3e3", stroke="#c92a2a", w=200)
node(REROUTE_CX, AUDIT6_Y,  "Draw REROUTED_FROM\nAudit Edge", fill="#f8f9fa", stroke="#495057", w=200)
node(REROUTE_CX, REANCHOR_Y,"Re-anchor to\nCorrect Quest",    fill="#ebfbee", stroke="#2f9e44", w=200)
right_d(CX6, PRED_D6_Y, REROUTE_CX, DETACH6_Y, label="Yes", color="#c92a2a")
varrow(REROUTE_CX, DETACH6_Y, LTD6_Y)
varrow(REROUTE_CX, LTD6_Y,    AUDIT6_Y)
varrow(REROUTE_CX, AUDIT6_Y,  REANCHOR_Y)

F6_BOTTOM = max(PRED_D6_Y + DH, REANCHOR_Y + NH)


# ---------------------------------------------------------------------------
# FIGURE 7  —  Synaptic Pruning, Hebbian Learning, and Long-Term Potentiation
# ---------------------------------------------------------------------------
F7X, F7Y = 60, F6_BOTTOM + 80
heading(F7X, F7Y, "FIG. 7  —  Synaptic Pruning, Hebbian Learning, and Long-Term Potentiation")
cap(F7X, F7Y + 32,
    "FIG. 7 illustrates use-based pathway strengthening, exponential time-decay pruning, archive mechanics,\n"
    "embedding-similarity resurrection, and promotion of implicit CO_OCCURS_WITH edges to named semantic\n"
    "relationship edges via Hebbian Long-Term Potentiation.")

DY7 = F7Y + 110

# Left branch: Artifact lifecycle
L7_CX = F7X + 270
frame(F7X, DY7 - 12, 500, 720, "Artifact Lifecycle (Synaptic Pruning)", stroke="#495057")

node(L7_CX, DY7, "Artifact Node", fill="#e7f5ff", stroke="#1c7ed6", w=180)

ACC_D7_Y = DY7 + STEP
diam(L7_CX, ACC_D7_Y, "Accessed\nRecently?")
varrow(L7_CX, DY7, ACC_D7_Y)

STR7_Y  = ACC_D7_Y + DH + 20
STR7_CX = L7_CX - 160
DEC7_CX = L7_CX + 160
node(STR7_CX, STR7_Y, "Strengthen:\nstrength += log δ", fill="#ebfbee", stroke="#2f9e44", w=190)
node(DEC7_CX, STR7_Y, "Decay:\nstrength ×= rate^days", fill="#ffe3e3", stroke="#c92a2a", w=190)
left_d( L7_CX, ACC_D7_Y, STR7_CX, STR7_Y, label="Yes", color="#2f9e44")
right_d(L7_CX, ACC_D7_Y, DEC7_CX, STR7_Y, label="No",  color="#c92a2a")

ARCH_D7_Y = STR7_Y + STEP
diam(DEC7_CX, ARCH_D7_Y, "Below archive\nthreshold?")
varrow(DEC7_CX, STR7_Y, ARCH_D7_Y)

ARCH7_Y  = ARCH_D7_Y + DH + 20
STAY7_CX = DEC7_CX - 160
node(STAY7_CX, ARCH7_Y, "Stay Active",  fill="#ebfbee", stroke="#2f9e44", w=150)
node(DEC7_CX,  ARCH7_Y, "Archive:\narchived = true", fill="#ffe3e3", stroke="#c92a2a", w=190)
add_arrow(DEC7_CX - DW // 2, ARCH_D7_Y + DH // 2, STAY7_CX + 75,  ARCH7_Y + NH // 2, label="No",  color="#2f9e44")
varrow_d(DEC7_CX, ARCH_D7_Y, ARCH7_Y,                               label="Yes", color="#c92a2a")

RESUR_D7_Y = ARCH7_Y + STEP
diam(DEC7_CX, RESUR_D7_Y, "Similarity >\nresurrection\nthreshold?", h=80)
varrow(DEC7_CX, ARCH7_Y, RESUR_D7_Y)

RES7_Y    = RESUR_D7_Y + 80 + 20
REMAIN_CX = DEC7_CX - 160
node(DEC7_CX, RES7_Y,  "Resurrect:\narchived = false", fill="#ebfbee", stroke="#2f9e44", w=190)
node(REMAIN_CX, RES7_Y,"Remain Archived",               fill="#f8f9fa", stroke="#868e96", w=160)
varrow_d(DEC7_CX, RESUR_D7_Y, RES7_Y,                              label="Yes", color="#2f9e44")
add_arrow(DEC7_CX - DW // 2, RESUR_D7_Y + 40, REMAIN_CX + 80, RES7_Y + NH // 2, label="No", color="#868e96")

# Right branch: Hebbian / LTP
R7_CX = F7X + 870
frame(F7X + 560, DY7 - 12, 500, 720, "Hebbian Co-occurrence → LTP", stroke="#7048e8")

node(R7_CX, DY7,        "Concept A  co-occurs with\nConcept B",  fill="#f3f0ff", stroke="#7048e8", w=230)
node(R7_CX, DY7 + STEP, "CO_OCCURS_WITH Edge:\ncount++",         fill="#f3f0ff", stroke="#7048e8", w=230)
varrow(R7_CX, DY7, DY7 + STEP)

COUNT_D7_Y = DY7 + STEP * 2
diam(R7_CX, COUNT_D7_Y, "count >\nco_occurrence\nthreshold?", h=80)
varrow(R7_CX, DY7 + STEP, COUNT_D7_Y)

PROM7_Y   = COUNT_D7_Y + 80 + 20
PROM7_CX  = R7_CX - 160
IMPL7_CX  = R7_CX + 160
node(PROM7_CX, PROM7_Y, "Promote to Named\nSemantic Edge",  fill="#ebfbee", stroke="#2f9e44", w=200)
node(IMPL7_CX, PROM7_Y, "Remain Implicit\nHebbian Evidence",fill="#f3f0ff", stroke="#7048e8", w=200)
add_arrow(R7_CX - DW // 2, COUNT_D7_Y + 40, PROM7_CX + 100, PROM7_Y + NH // 2, label="Yes", color="#2f9e44")
add_arrow(R7_CX + DW // 2, COUNT_D7_Y + 40, IMPL7_CX - 100, PROM7_Y + NH // 2, label="No",  color="#7048e8")

NAMED7_Y = PROM7_Y + STEP
SRC7_Y   = NAMED7_Y + STEP
node(PROM7_CX, NAMED7_Y, "ENABLES / REQUIRES /\nCHOSEN_OVER / etc.", fill="#ebfbee", stroke="#2f9e44", w=220)
node(PROM7_CX, SRC7_Y,   "inferred_by:\nsystem | LLM | user",        fill="#f8f9fa", stroke="#495057", w=220)
varrow(PROM7_CX, PROM7_Y,  NAMED7_Y)
varrow(PROM7_CX, NAMED7_Y, SRC7_Y)

F7_BOTTOM = max(RES7_Y, SRC7_Y) + NH


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
out = {
    "type": "excalidraw",
    "version": 2,
    "source": "https://marketplace.visualstudio.com/items?itemName=pomdtr.excalidraw-editor",
    "elements": elements,
    "appState": {
        "gridSize": None,
        "viewBackgroundColor": "#ffffff",
    },
    "files": {},
}

import pathlib
out_path = pathlib.Path(__file__).parent.parent / "InvertorsDocs" / "SideQuests-Patent-Figures.excalidraw"
out_path.write_text(json.dumps(out, indent=2))

print(f"✓  {len(elements)} elements written to {out_path}")
print(f"   Canvas height: ~{int(F7_BOTTOM + 120)} px")
