"""Generate the hyperscope stage carrier PCB: KiCad schematic, board, and fab outputs.

One netlist, defined below, produces both the schematic and the PCB, so the two
cannot disagree. Run with KiCad's bundled Python so `pcbnew` is importable:

    /Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 \
        hardware/pcb/generate.py [--route] [--no-fab]

--route runs Freerouting 1.9.0 (needs Java 21 and freerouting-1.9.0.jar beside this file)
and imports the result; without it the board is placed but unrouted.

Coordinates are millimetres, board origin top-left, y down (KiCad convention).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME = "hyperscope-stage"
KICAD_DIR, REVIEW = HERE / "kicad", HERE / "review"
KICAD = Path("/Applications/KiCad/KiCad.app/Contents")
KICAD_CLI = KICAD / "MacOS/kicad-cli"
SYMBOLS = KICAD / "SharedSupport/symbols"
FOOTPRINTS = KICAD / "SharedSupport/footprints"
# Freerouting 1.9.0 on Java 21. The 2.x releases write an empty session file from the CLI.
FREEROUTING = Path(os.environ.get("FREEROUTING_JAR", HERE / "freerouting-1.9.0.jar"))
JAVA = os.environ.get("JAVA", "/opt/homebrew/opt/openjdk@21/bin/java")

BOARD_W, BOARD_H, CORNER_R = 84.0, 72.0, 3.0
NC = None  # a pin with no net

# ---------------------------------------------------------------- footprints

FP = {
    "sock15": "Connector_PinSocket_2.54mm:PinSocket_1x15_P2.54mm_Vertical",
    "sock8": "Connector_PinSocket_2.54mm:PinSocket_1x08_P2.54mm_Vertical",
    "sock2": "Connector_PinSocket_2.54mm:PinSocket_1x02_P2.54mm_Vertical",
    "hdr14": "Connector_PinHeader_2.54mm:PinHeader_1x14_P2.54mm_Vertical",
    "hdr5": "Connector_PinHeader_2.54mm:PinHeader_1x05_P2.54mm_Vertical",
    # 5.0 mm pitch screw terminals (KF128 / MX126 style), side wire entry
    "term2": "TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm",
    "term4": "TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-04P_1x04_P5.00mm",
    "fuse": "Fuse:Fuse_Bourns_MF-RHT300",
    "do201": "Diode_THT:D_DO-201AD_P15.24mm_Horizontal",
    "cp63": "Capacitor_THT:CP_Radial_D6.3mm_P2.50mm",
    "cp10": "Capacitor_THT:CP_Radial_D10.0mm_P5.00mm",
    "cdisc": "Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P5.00mm",
    "r": "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P2.54mm_Vertical",  # standing, pin 1 under the body
    "led5": "LED_THT:LED_D5.0mm",  # 3 mm LEDs fit the same holes
    "sj3": "Jumper:SolderJumper-3_P1.3mm_Open_RoundedPad1.0x1.5mm",
    "m3": "MountingHole:MountingHole_3.2mm_M3",
}

SYM = {
    "conn": lambda n: f"Connector_Generic:Conn_01x{n:02d}",
    "r": "Device:R",
    "cp": "Device:C_Polarized",
    "c": "Device:C",
    "d": "Device:D_Schottky",
    "led": "Device:LED",
    "fuse": "Device:Fuse",
    "sj3": "Jumper:SolderJumper_3_Open",
    "hole": "Mechanical:MountingHole",
}


@dataclass
class Part:
    ref: str
    symbol: str
    footprint: str
    value: str
    pins: dict  # pin number (str) -> net name or NC
    x: float
    y: float
    rot: float = 0.0
    side: str = "F"
    note: str = ""


PARTS: list[Part] = []


def part(ref, symbol, footprint, value, pins, x, y, rot=0.0, note=""):
    p = Part(ref, symbol, FP[footprint], value, {str(k): v for k, v in pins.items()}, x, y, rot, "F", note)
    PARTS.append(p)
    return p


def seq(nets):
    return {i + 1: n for i, n in enumerate(nets)}


# ---------------------------------------------------------------- the design
#
# Landscape 84 x 68 mm (top view). The DevKit lies along the bottom edge,
# component side up, with its USB-C out of the left edge. In that orientation the
# HW-394's VIN column is the upper row and the 3V3 column (EN, UART, STEP, DIR,
# DIAG) is the lower row, nearest the board edge; see docs/photos/esp32-hw394-
# devkit-top.png rotated USB-left. The driver signals therefore route under the
# DevKit up to the modules, which sit side by side with their logic rows facing
# down and their power rows facing the motor connectors on the top edge. 12 V
# enters top-right; the joystick header sits bottom right.

# DevKit HW-394, 30 pins, rows 25.4 mm apart, USB end at x=0.
DEV_X1, DEV_YT, DEV_YB = 10.0, 38.8, 64.2  # pin 1 (VIN / 3V3) nearest the USB end
# USB end -> antenna end. Upper row (DEV_YT) is the VIN column, lower row (DEV_YB)
# the 3V3 column. The pin pattern is symmetric, so a swapped row passes ERC, DRC and
# the paper fit test yet puts VIN on the 3V3 net: check against the photo, not the fit.
DEV_3V3 = [
    "+3V3",
    "GND",
    "GPIO15",
    "GPIO2",
    "DRV_EN",
    "TMC_TX",
    "TMC_UART",
    "X_STEP",
    "X_DIR",
    "Y_STEP",
    "Y_DIR",
    NC,
    NC,
    "DIAG_Y",
    "LED_Y",
]
DEV_VIN = [
    NC,
    "GND",
    "DIAG_X",
    NC,
    "GPIO14",
    "GPIO27",
    "GPIO26",
    "GPIO25",
    "JOY_SW",
    "LED_X",
    "JOY_VRY",
    "JOY_VRX",
    "GPIO39",
    "GPIO36",
    NC,
]
DEV_3V3_NAMES = [
    "3V3",
    "GND",
    "D15",
    "D2",
    "D4",
    "D16",
    "D17",
    "D5",
    "D18",
    "D19",
    "D21",
    "RX0",
    "TX0",
    "D22",
    "D23",
]
DEV_VIN_NAMES = [
    "VIN",
    "GND",
    "D13",
    "D12",
    "D14",
    "D27",
    "D26",
    "D25",
    "D33",
    "D32",
    "D35",
    "D34",
    "VN",
    "VP",
    "EN",
]

part(
    "J1",
    SYM["conn"](15),
    "sock15",
    "HW-394 3V3 row (lower, board edge side)",
    seq(DEV_3V3),
    DEV_X1,
    DEV_YB,
    90,
    "ESP32 DevKit socket, 3V3 column",
)
part(
    "J2",
    SYM["conn"](15),
    "sock15",
    "HW-394 VIN row (upper, module side)",
    seq(DEV_VIN),
    DEV_X1,
    DEV_YT,
    90,
    "ESP32 DevKit socket, VIN column",
)

# Driver modules X and Y. Logic row (EN..DIR left to right) facing the DevKit, power
# row (VS..GND) 12.7 mm above it: the StepStick pin-row pitch. 15.24 mm is the module's
# board width, not its pin spacing (rev B used it and the modules did not fit). DIAG
# and INDEX sit on the EN end, one and two pitches inboard, so here they stand above
# EN on the module's left edge. The channel between the logic rows and the DevKit
# holds the series and pull-up resistors, in line with the signals they sit on.
DRV_YL, DRV_YP = 31.0, 31.0 - 12.7
CHAN_Y = 35.0
DRV_X = {"X": 17.0, "Y": 46.0}  # EN / VS pin x; leaves room for the 5 mm terminals and caps above
DIAG_GPIO = {"X": "DIAG_X", "Y": "DIAG_Y"}
BOTTOM = set()  # refs mounted on the back
for i, ax in enumerate("XY"):
    x = DRV_X[ax]
    n = 3 + i  # J3/J4 logic rows, J5/J6 power rows, J7/J8 diag pairs
    part(
        f"J{n}",
        SYM["conn"](8),
        "sock8",
        f"TMC2209 {ax} logic",
        seq(["DRV_EN", f"{ax}_MS1", f"{ax}_MS2", "TMC_UART", NC, NC, f"{ax}_STEP", f"{ax}_DIR"]),
        x,
        DRV_YL,
        90,
    )
    part(
        f"J{n + 2}",
        SYM["conn"](8),
        "sock8",
        f"TMC2209 {ax} power",
        seq(["VM", "GND", f"{ax}_A2", f"{ax}_A1", f"{ax}_B1", f"{ax}_B2", "+3V3", "GND"]),
        x,
        DRV_YP,
        90,
    )
    part(
        f"J{n + 4}",
        SYM["conn"](2),
        "sock2",
        f"TMC2209 {ax} DIAG/INDEX",
        seq([f"{ax}_DIAGP1", f"{ax}_DIAGP2"]),
        x,
        DRV_YL - 2.54,
        180,
    )
    # Address and DIAG-select jumpers on the back, under the module. Each MS jumper
    # lies along x with its centre pad directly above its socket pin, so the stub
    # runs straight down; staggered in y so the two do not touch. GND is the left
    # pad and 3V3 the right pad in top view.
    part(
        f"JP{2 * i + 1}",
        SYM["sj3"],
        "sj3",
        f"{ax} MS1",
        {1: "GND", 2: f"{ax}_MS1", 3: "+3V3"},
        x + 2.54,
        23.0,
        0,
    )
    part(
        f"JP{2 * i + 2}",
        SYM["sj3"],
        "sj3",
        f"{ax} MS2",
        {1: "GND", 2: f"{ax}_MS2", 3: "+3V3"},
        x + 5.08,
        26.5,
        0,
    )
    part(
        f"JP{5 + i}",
        SYM["sj3"],
        "sj3",
        f"{ax} DIAG sel",
        {1: f"{ax}_DIAGP1", 2: f"{ax}_DIAGSEL", 3: f"{ax}_DIAGP2"},
        x - 4.54,
        21.5,
        90,
    )
    # DIAG series resistor just below its select jumper, left of the module.
    part(
        f"R{2 + i}",
        SYM["r"],
        "r",
        "1k",
        {1: f"{ax}_DIAGSEL", 2: f"DIAG_{ax}"},
        x - 4.54,
        25.0,
        270,
        "DIAG series",
    )
    BOTTOM.update({f"JP{2 * i + 1}", f"JP{2 * i + 2}", f"JP{5 + i}"})
    # Bulk cap on VS/GND, left of the motor terminal.
    part(f"C{1 + i}", SYM["cp"], "cp63", "100u 35V", {1: "VM", 2: "GND"}, x - 7.2, 7.0, 0)
    # Motor screw terminal A2 A1 B1 B2, centred over power-row pins 3..6, wires out the top edge.
    part(
        f"J{9 + i}",
        SYM["conn"](4),
        "term4",
        f"MOTOR {ax}",
        seq([f"{ax}_A2", f"{ax}_A1", f"{ax}_B1", f"{ax}_B2"]),
        x + 1.39,
        5.0,
        0,
    )
    # Blue "motor active" LED under the terminal's B2 end, cathode left; firmware
    # lights it while the axis moves.
    part(
        f"D{2 + i}",
        SYM["led"],
        "led5",
        "blue",
        {1: "GND", 2: f"{ax}_LED_A"},
        x + 15.53,
        13.05,
        0,
        f"{ax} motor active",
    )
# LED series resistors beside their LEDs. LED_X (GPIO32) climbs the gap between the
# modules; LED_Y (GPIO23, the DevKit's corner pin) leaves right under the antenna
# keep-out and climbs the open right side.
part("R5", SYM["r"], "r", "100", {1: "X_LED_A", 2: "LED_X"}, 39.0, 14.2, 0, "LED series")
part("R6", SYM["r"], "r", "100", {1: "LED_Y", 2: "Y_LED_A"}, 67.4, 23.5, 90, "LED series")
# TX (GPIO16) feeds the shared PDN_UART line through 1k; RX (GPIO17) sits on it
# directly. Pads on the gaps right of DevKit pins 6 and 7, where those two rise.
part("R1", SYM["r"], "r", "1k", {1: "TMC_TX", 2: "TMC_UART"}, DEV_X1 + 5 * 2.54 + 1.27, CHAN_Y, 0, "UART TX")
# The BTT module pulls EN to GND with 20k, so a floating DRV_EN enables both drivers
# (ESP32 boot, or the DevKit unplugged). GPIO4 also has a ~45k internal pull-down at
# reset, and the TMC2209 needs ~0.7*VIO (2.3 V) to read high: 2.2k against 20k||45k
# gives ~2.85 V, and the ESP32 sinks only 1.5 mA when it drives EN low.
part("R4", SYM["r"], "r", "2.2k", {1: "+3V3", 2: "DRV_EN"}, 15.0, CHAN_Y, 0, "EN pull-up")

# 12 V entry down the right edge: terminal -> polyfuse -> Schottky -> VM. Joystick bottom right.
part("J11", SYM["conn"](2), "term2", "12V IN", {1: "VM_IN", 2: "GND"}, 72.0, 14.0, 0)
part("F1", SYM["fuse"], "fuse", "3A polyfuse", {1: "VM_IN", 2: "VM_F"}, 72.0, 22.0, 0)
part("D1", SYM["d"], "do201", "SR340", {1: "VM", 2: "VM_F"}, 79.5, 27.0, 270, "cathode pin 1 to VM")
part("C3", SYM["cp"], "cp10", "470u 25V", {1: "VM", 2: "GND"}, 71.0, 36.0, 270, "input bulk")


part(
    "J13",
    SYM["conn"](5),
    "hdr5",
    "JOYSTICK",
    seq(["GND", "+3V3", "JOY_VRX", "JOY_VRY", "JOY_SW"]),
    66.0,
    54.0,
    90,
    "pin header, dupont leads to the joystick module",
)
part("C6", SYM["c"], "cdisc", "100n", {1: "JOY_VRX", 2: "GND"}, 66.0, 60.0, 0)
part("C7", SYM["c"], "cdisc", "100n", {1: "JOY_VRY", 2: "GND"}, 74.0, 60.0, 0)

# Spare GPIOs and power as bare pads along the bottom edge, no header fitted.
SPARE = [
    "GPIO15",
    "GPIO2",
    "GPIO14",
    "GPIO27",
    "GPIO26",
    "GPIO25",
    "GPIO39",
    "GPIO36",
    "+3V3",
    "+3V3",
    "+3V3",
    "GND",
    "GND",
    "GND",
]
SPARE_NAMES = ["15b", "2b", "14", "27", "26", "25", "39", "36", "3V3", "3V3", "3V3", "GND", "GND", "GND"]
SPARE_X, SPARE_Y = 10.0, 68.0
part(
    "J14",
    SYM["conn"](len(SPARE)),
    "hdr14",
    "spare GPIO + power pads",
    seq(SPARE),
    SPARE_X,
    SPARE_Y,
    90,
    "bare pads, solder wires or a header as needed",
)

HOLES = [(4, 4), (80, 4), (80, 68), (62, 68)]

for i, (x, y) in enumerate(HOLES):
    part(f"H{i + 1}", SYM["hole"], "m3", "M3", {}, x, y, 0)

# ---------------------------------------------------------------- schematic


def _u():
    return str(uuid.uuid4())


def extract_symbol(lib_id: str) -> str:
    lib, name = lib_id.split(":")
    text = (SYMBOLS / f"{lib}.kicad_sym").read_text()
    start = text.index(f'(symbol "{name}"')
    depth, i = 0, start
    while True:
        c = text[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    block = text[start : i + 1]
    return block.replace(f'(symbol "{name}"', f'(symbol "{lib_id}"', 1)


def symbol_pins(block: str) -> dict:
    """pin number -> (x, y, angle) in symbol coordinates (y up)."""
    pins = {}
    for m in re.finditer(
        r'\(pin\s+\w+\s+\w+\s*\(at\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\).*?\(number\s+"([^"]+)"', block, re.S
    ):
        pins[m.group(4)] = (float(m.group(1)), float(m.group(2)), float(m.group(3)))
    return pins


def write_schematic(path: Path):
    root = _u()
    libs = {}
    for p in PARTS:
        if p.symbol not in libs:
            libs[p.symbol] = extract_symbol(p.symbol)
    out = [
        '(kicad_sch (version 20250114) (generator "hyperscope-generate") (generator_version "10.0")',
        f'  (uuid "{root}") (paper "A2")',
        '  (title_block (title "hyperscope stage carrier") (rev "C") (company "hyperscope")',
        '    (comment 1 "ESP32 HW-394 DevKit + 2x BTT TMC2209, generated by hardware/pcb/generate.py"))',
        "  (lib_symbols",
    ]
    out += ["    " + libs[k].replace("\n", "\n    ") for k in libs]
    out.append("  )")

    # Grid placement: 7 columns, generous cells, in PARTS order.
    col_w, row_h, cols = 45.72, 45.72, 7
    for idx, p in enumerate(PARTS):
        sx = 25.4 + col_w * (idx % cols)
        sy = 25.4 + row_h * (idx // cols)
        pins = symbol_pins(libs[p.symbol])
        out.append(
            f'  (symbol (lib_id "{p.symbol}") (at {sx} {sy} 0) (unit 1) (exclude_from_sim no) (in_bom yes) (on_board yes) (dnp no)'
        )
        out.append(f'    (uuid "{_u()}")')
        out.append(
            f'    (property "Reference" "{p.ref}" (at {sx} {sy - 12.7} 0) (effects (font (size 1.27 1.27))))'
        )
        out.append(
            f'    (property "Value" "{p.value}" (at {sx} {sy + 12.7} 0) (effects (font (size 1.27 1.27))))'
        )
        out.append(
            f'    (property "Footprint" "{p.footprint}" (at {sx} {sy} 0) (effects (font (size 1.27 1.27)) (hide yes)))'
        )
        out.append(
            f'    (property "Datasheet" "" (at {sx} {sy} 0) (effects (font (size 1.27 1.27)) (hide yes)))'
        )
        if p.note:
            out.append(
                f'    (property "Note" "{p.note}" (at {sx} {sy + 15.24} 0) (effects (font (size 1.0 1.0))))'
            )
        for num in pins:
            out.append(f'    (pin "{num}" (uuid "{_u()}"))')
        out.append(f'    (instances (project "{NAME}" (path "/{root}" (reference "{p.ref}") (unit 1))))')
        out.append("  )")
        for num, (px, py, ang) in pins.items():
            x, y = round(sx + px, 3), round(sy - py, 3)
            net = p.pins.get(num, NC)
            if net is NC:
                out.append(f'  (no_connect (at {x} {y}) (uuid "{_u()}"))')
                continue
            # Label reads away from the pin: pin angle 0 points right into the body, so text goes left.
            rot = {0: 180, 180: 0, 90: 270, 270: 90}[int(ang) % 360]
            just = "right" if rot == 180 else "left"
            out.append(
                f'  (label "{net}" (at {x} {y} {rot}) (effects (font (size 1.27 1.27)) (justify {just} bottom)) (uuid "{_u()}"))'
            )
    out.append('  (sheet_instances (path "/" (page "1")))')
    out.append(")")
    path.write_text("\n".join(out) + "\n")


def write_project(path: Path):
    path.write_text(
        json.dumps(
            {
                "board": {
                    "design_settings": {"defaults": {}, "rules": {}},
                    "layer_presets": [],
                    "viewports": [],
                },
                "meta": {"filename": path.name, "version": 1},
                "net_settings": {"classes": [], "meta": {"version": 3}},
                "pcbnew": {"page_layout_descr_file": ""},
                "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
                "sheets": [],
                "text_variables": {},
            },
            indent=2,
        )
    )


# ---------------------------------------------------------------- pcb

POWER_NETS = {"VM", "VM_IN", "VM_F"}
MOTOR_RE = re.compile(r"^[XYZ]_[AB][12]$")


def build_pcb(path: Path, route: bool):
    import pcbnew  # only importable under KiCad's Python

    board = pcbnew.BOARD()
    ds = board.GetDesignSettings()
    ds.SetCopperLayerCount(2)
    ds.m_MinClearance = pcbnew.FromMM(0.2)
    ds.m_TrackMinWidth = pcbnew.FromMM(0.2)
    ds.m_ViasMinSize = pcbnew.FromMM(0.6)
    ds.m_MinThroughDrill = pcbnew.FromMM(0.3)
    ds.m_CopperEdgeClearance = pcbnew.FromMM(0.3)

    def mm(v):
        return pcbnew.FromMM(v)

    def V(x, y):
        return pcbnew.VECTOR2I(mm(x), mm(y))

    # Outline: rectangle with rounded corners.
    def edge(item):
        item.SetLayer(pcbnew.Edge_Cuts)
        item.SetWidth(mm(0.1))
        board.Add(item)

    W, H, r = BOARD_W, BOARD_H, CORNER_R
    for x1, y1, x2, y2 in [(r, 0, W - r, 0), (W, r, W, H - r), (W - r, H, r, H), (0, H - r, 0, r)]:
        sgm = pcbnew.PCB_SHAPE(board)
        sgm.SetShape(pcbnew.SHAPE_T_SEGMENT)
        sgm.SetStart(V(x1, y1))
        sgm.SetEnd(V(x2, y2))
        edge(sgm)
    k = r * (1 - 0.7071)
    for sx, sy, mx, my, ex, ey in [
        (W - r, 0, W - k, k, W, r),
        (W, H - r, W - k, H - k, W - r, H),
        (r, H, k, H - k, 0, H - r),
        (0, r, k, k, r, 0),
    ]:
        arc = pcbnew.PCB_SHAPE(board)
        arc.SetShape(pcbnew.SHAPE_T_ARC)
        arc.SetArcGeometry(V(sx, sy), V(mx, my), V(ex, ey))
        edge(arc)

    nets = {}

    def net(name):
        if name not in nets:
            n = pcbnew.NETINFO_ITEM(board, name)
            board.Add(n)
            nets[name] = n
        return nets[name]

    for p in PARTS:
        lib, fpname = p.footprint.split(":")
        fp = pcbnew.FootprintLoad(str(FOOTPRINTS / f"{lib}.pretty"), fpname)
        assert fp is not None, p.footprint
        fp.SetReference(p.ref)
        fp.SetValue(p.value)
        fp.SetPosition(V(p.x, p.y))
        fp.SetOrientationDegrees(p.rot)
        board.Add(fp)
        if p.ref in BOTTOM:
            fp.Flip(V(p.x, p.y), False)  # needs a parent board first
        for pad in fp.Pads():
            n = p.pins.get(pad.GetNumber(), NC)
            if n is not NC:
                pad.SetNet(net(n))
        if p.footprint == FP["sock2"]:
            # The DIAG pair abuts the logic-row socket exactly as on the module, so the
            # stock courtyard margin would overlap it. Replace it with a tight one.
            for g in list(fp.GraphicalItems()):
                if g.GetLayer() == pcbnew.F_CrtYd:
                    fp.Remove(g)
            cy = pcbnew.PCB_SHAPE(fp)
            cy.SetShape(pcbnew.SHAPE_T_RECT)
            cy.SetLayer(pcbnew.F_CrtYd)
            cy.SetWidth(mm(0.05))
            cy.SetStart(V(p.x - 1.27, p.y + 0.65))
            cy.SetEnd(V(p.x + 1.27, p.y - 2.54 - 1.27))
            fp.Add(cy)
        fp.Reference().SetTextSize(pcbnew.VECTOR2I(mm(0.8), mm(0.8)))
        if p.ref.startswith(("J", "H")):
            fp.Reference().SetVisible(False)
        fp.Reference().SetTextThickness(mm(0.12))
        fp.Value().SetVisible(False)

    # Net classes: fat power and motor tracks, default logic.
    ns = ds.m_NetSettings
    default = ns.GetDefaultNetclass()
    default.SetTrackWidth(mm(0.25))
    # router works to this; relaxed to 0.2 before saving so rounding never trips DRC
    default.SetClearance(mm(0.22))
    default.SetViaDiameter(mm(0.8))
    default.SetViaDrill(mm(0.4))
    for cname, width, _pattern in [("Power", 1.5, None), ("Motor", 1.0, None), ("Ground", 0.5, None)]:
        nc = pcbnew.NETCLASS(cname)
        nc.SetTrackWidth(mm(width))
        nc.SetClearance(mm(0.25))
        nc.SetViaDiameter(mm(1.2))
        nc.SetViaDrill(mm(0.6))
        ns.SetNetclass(cname, nc)
    for name in nets:
        if name in POWER_NETS:
            ns.SetNetclassPatternAssignment(name, "Power")
        elif MOTOR_RE.match(name):
            ns.SetNetclassPatternAssignment(name, "Motor")
        elif name == "GND":
            # the pours carry ground; tracks just guarantee it
            ns.SetNetclassPatternAssignment(name, "Ground")

    # Silkscreen: module outlines and legends.
    def text(s, x, y, size=1.0, layer=pcbnew.F_SilkS, rot=0, left=False, width=None):
        size = max(size, 0.8)
        t = pcbnew.PCB_TEXT(board)
        t.SetText(s)
        t.SetPosition(V(x, y))
        t.SetLayer(layer)
        t.SetTextSize(pcbnew.VECTOR2I(mm(width or size), mm(size)))
        if left:
            t.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_LEFT)
        t.SetTextThickness(mm(0.15))
        t.SetTextAngleDegrees(rot)
        if layer == pcbnew.B_SilkS:
            t.SetMirrored(True)
        board.Add(t)

    def rect(x1, y1, x2, y2, layer=pcbnew.F_SilkS):
        for ax, ay, bx, by in [(x1, y1, x2, y1), (x2, y1, x2, y2), (x2, y2, x1, y2), (x1, y2, x1, y1)]:
            s = pcbnew.PCB_SHAPE(board)
            s.SetShape(pcbnew.SHAPE_T_SEGMENT)
            s.SetStart(V(ax, ay))
            s.SetEnd(V(bx, by))
            s.SetLayer(layer)
            s.SetWidth(mm(0.12))
            board.Add(s)

    for ax in "XY":
        x = DRV_X[ax]
        rect(x - 1.6, DRV_YP - 1.6, x + 17.78 + 1.6, DRV_YL + 1.6)
        text(f"TMC2209 {ax}", x + 8.9, (DRV_YP + DRV_YL) / 2, 1.2)
        text("VS", x, DRV_YP - 2.6, 0.8)
        text("GND", x + 17.78 + 2.4, DRV_YP, 0.8, rot=90)
        text(f"MOTOR {ax}  A2 A1 B1 B2", x + 6.5, 10.9, 0.8)
        text(f"{ax}: DIAG  MS1 MS2", x + 2.0, 20.2, 0.8, pcbnew.B_SilkS)
        text("3V3< >GND", x + 3.81, 21.3, 0.8, pcbnew.B_SilkS)  # mirrored: reads correctly from the back
    rect(0.6, DEV_YT - 1.3, 51.5, DEV_YB + 1.3)
    text("ESP32 HW-394   USB-C at left edge", 26.0, (DEV_YT + DEV_YB) / 2, 0.9)
    text("antenna", 48.5, (DEV_YT + DEV_YB) / 2, 0.8, rot=90)
    text("VIN", DEV_X1 - 0.3, DEV_YT - 2.6, 0.8)  # pin 1 markers; the DevKit carries its own pin labels
    text("3V3", DEV_X1 - 3.2, DEV_YB, 0.8)
    for i, nm in enumerate(SPARE_NAMES):
        text(nm, SPARE_X + 2.54 * i, SPARE_Y + 2.6, 0.8, rot=90)
    text("b=boot", SPARE_X + 2.54 * len(SPARE) + 1.0, SPARE_Y + 0.4, 0.8)
    text("12V IN  + -", 74.5, 7.6, 0.9)
    text("hyperscope v1", 66.0, 2.6, 0.9, left=True, width=0.8)
    text("designed by momonala", 66.0, 4.9, 0.8, left=True, width=0.55)
    text("JOY: GND 3V3 VRX VRY SW", 72.0, 50.3, 0.8)
    text("hyperscope v1  stage carrier rev C", 26.0, 44.0, 0.9, pcbnew.B_SilkS)
    text("DIAG jumper: bridge the pad that does NOT pulse (other = INDEX)", 26.0, 51.0, 0.8, pcbnew.B_SilkS)
    text("Address: X = 00,  Y = MS1 high", 26.0, 48.0, 0.8, pcbnew.B_SilkS)

    board.SetFileName(str(path))
    pcbnew.SaveBoard(str(path), board)

    add_keepout(board, pcbnew)
    if route:
        autoroute(board, path, pcbnew)
        ns.GetDefaultNetclass().SetClearance(mm(0.2))
    add_zones(board, pcbnew, net)

    filler = pcbnew.ZONE_FILLER(board)
    filler.Fill(board.Zones())
    pcbnew.SaveBoard(str(path), board)
    return board


def add_zones(board, pcbnew, net):
    """GND pours on both faces plus the antenna keep-out. Added after routing so the
    autorouter connects every GND pad with copper of its own; the pour only adds."""

    def mm(v):
        return pcbnew.FromMM(v)

    def V(x, y):
        return pcbnew.VECTOR2I(mm(x), mm(y))

    # Ground pours on both sides, antenna keep-out under the DevKit's far end.
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        z = pcbnew.ZONE(board)
        z.SetLayer(layer)
        z.SetNet(net("GND"))
        z.SetIsFilled(False)
        z.SetLocalClearance(mm(0.3))
        z.SetMinThickness(mm(0.25))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        outline = z.Outline()
        outline.NewOutline()
        for x, y in [(0.5, 0.5), (BOARD_W - 0.5, 0.5), (BOARD_W - 0.5, BOARD_H - 0.5), (0.5, BOARD_H - 0.5)]:
            outline.Append(mm(x), mm(y))
        z.SetAssignedPriority(0)
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
        board.Add(z)


def add_keepout(board, pcbnew):
    """No copper under the DevKit's PCB antenna. Added before routing so the router respects it."""

    def mm(v):
        return pcbnew.FromMM(v)

    ko = pcbnew.ZONE(board)
    ko.SetIsRuleArea(True)
    ko.SetDoNotAllowZoneFills(True)
    ko.SetDoNotAllowTracks(True)
    ko.SetDoNotAllowVias(True)
    ko.SetLayerSet(pcbnew.LSET.AllCuMask(2))
    o = ko.Outline()
    o.NewOutline()
    x0 = DEV_X1 + 14 * 2.54 - 1.0  # just past the last pin
    for x, y in [(x0, DEV_YT + 4.0), (52.0, DEV_YT + 4.0), (52.0, DEV_YB - 4.0), (x0, DEV_YB - 4.0)]:
        o.Append(mm(x), mm(y))
    board.Add(ko)


def autoroute(board, path, pcbnew):
    dsn = path.with_suffix(".dsn")
    ses = path.with_suffix(".ses")
    assert pcbnew.ExportSpecctraDSN(board, str(dsn)), "DSN export failed"
    cmd = [JAVA, "-jar", str(FREEROUTING), "-de", str(dsn), "-do", str(ses), "-mp", "120", "-mt", "1"]
    print(" ".join(cmd))
    # Freerouting drops logs/ and freerouting.json into the working directory; keep them here (gitignored).
    subprocess.run(cmd, check=True, timeout=1800, cwd=HERE)
    assert pcbnew.ImportSpecctraSES(board, str(ses)), "SES import failed"
    # The session import leaves near-zero-length stubs where paths meet; they can
    # register as shorts against neighbouring copper. Drop them.
    for t in list(board.GetTracks()):
        if t.GetClass() == "PCB_TRACK" and t.GetLength() < pcbnew.FromMM(0.02):
            board.Remove(t)
    for f in (dsn, ses):
        f.unlink(missing_ok=True)


def fab(pcb: Path, sch: Path):
    import shutil
    import tempfile

    out = Path(tempfile.mkdtemp())
    for d in (KICAD_DIR, REVIEW):
        d.mkdir(exist_ok=True)
    run(KICAD_CLI, "sch", "erc", "--severity-error", "-o", str(REVIEW / "erc.rpt"), str(sch))
    print((REVIEW / "erc.rpt").read_text()[-600:])
    run(
        KICAD_CLI,
        "pcb",
        "drc",
        "--severity-error",
        "--schematic-parity",
        "-o",
        str(REVIEW / "drc.rpt"),
        str(pcb),
    )
    print((REVIEW / "drc.rpt").read_text()[-800:])
    run(
        KICAD_CLI,
        "pcb",
        "export",
        "gerbers",
        "--layers",
        "F.Cu,B.Cu,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts",
        "--subtract-soldermask",
        "-o",
        str(out),
        str(pcb),
    )
    run(
        KICAD_CLI,
        "pcb",
        "export",
        "drill",
        "--format",
        "excellon",
        "--excellon-separate-th",
        "-o",
        str(out),
        str(pcb),
    )
    zip_path = HERE / "gerbers.zip"
    zip_path.unlink(missing_ok=True)
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", out)
    shutil.rmtree(out)
    run(
        KICAD_CLI,
        "pcb",
        "export",
        "svg",
        "--layers",
        "F.Cu,F.SilkS,Edge.Cuts,F.Fab",
        "--page-size-mode",
        "2",
        "--exclude-drawing-sheet",
        "-o",
        str(REVIEW / "top.svg"),
        str(pcb),
    )
    run(
        KICAD_CLI,
        "pcb",
        "export",
        "svg",
        "--layers",
        "B.Cu,B.SilkS,Edge.Cuts",
        "--page-size-mode",
        "2",
        "--exclude-drawing-sheet",
        "--mirror",
        "-o",
        str(REVIEW / "bottom.svg"),
        str(pcb),
    )
    run(KICAD_CLI, "sch", "export", "pdf", "-o", str(REVIEW / "schematic.pdf"), str(sch))


def run(*cmd):
    print("$", " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], check=False, capture_output=True, text=True)
    if r.stdout.strip():
        print(r.stdout.strip()[-1500:])
    if r.returncode != 0:
        print(r.stderr.strip()[-1500:])
    return r.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--route", action="store_true")
    ap.add_argument("--no-fab", action="store_true")
    a = ap.parse_args()
    KICAD_DIR.mkdir(exist_ok=True)
    sch, pcb, pro = (
        KICAD_DIR / f"{NAME}.kicad_sch",
        KICAD_DIR / f"{NAME}.kicad_pcb",
        KICAD_DIR / f"{NAME}.kicad_pro",
    )
    write_project(pro)
    write_schematic(sch)
    print(f"schematic: {len(PARTS)} parts")
    build_pcb(pcb, a.route)
    if not a.no_fab:
        fab(pcb, sch)


if __name__ == "__main__":
    main()
