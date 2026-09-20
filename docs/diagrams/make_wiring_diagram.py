"""Generate the XY stage wiring diagram as SVG.

Run:  uv run python docs/diagrams/make_wiring_diagram.py
Pin assignments mirror firmware/hyperscope_stage/config.h.

Layout rule that keeps the wires untangled: driver signals come off the ESP32's
right-hand column and joystick signals off its left-hand column, each in the
same top-to-bottom order as the pins it lands on. X DIR is the one exception:
the right column ran out, so it leaves D25 on the left and crosses over the top.
"""

from pathlib import Path

OUT = Path(__file__).parent / "wiring.svg"

W, H = 1500, 1320
PITCH = 24  # px per 0.1" pin pitch
FONT = "Helvetica, Arial, sans-serif"

COLOR = {
    "12v": "#d62828",
    "3v3": "#f77f00",
    "gnd": "#222222",
    "step": "#1d6fd8",
    "dir": "#2a9d3a",
    "en": "#8e44ad",
    "uart": "#c9a400",
    "tx": "#8b5a2b",
    "joy_x": "#1d6fd8",
    "joy_y": "#9aa0a6",
    "sw": "#e05a9c",
    "coil_a": "#d62828",
    "coil_b": "#1d6fd8",
}

Point = tuple[float, float]
svg: list[str] = []


# ----------------------------------------------------------------------------- primitives


def add(element: str) -> None:
    svg.append(element)


def text(x, y, s, size=13, anchor="start", weight="normal", fill="#111", rotate=None) -> None:
    s = str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    transform = f' transform="rotate({rotate} {x} {y})"' if rotate is not None else ""
    add(
        f'<text x="{x}" y="{y}" font-size="{size}" text-anchor="{anchor}" font-weight="{weight}"'
        f' fill="{fill}" font-family="{FONT}"{transform}>{s}</text>'
    )


def pin(x, y, used=True) -> None:
    add(f'<circle cx="{x}" cy="{y}" r="6" fill="{"#f4d35e" if used else "#777"}" stroke="#333" stroke-width="1.5"/>')
    add(f'<circle cx="{x}" cy="{y}" r="2.2" fill="#222"/>')


def wire(points: list[Point], color: str, width=4) -> None:
    """Polyline with a pale halo so crossings read as over/under."""
    d = " ".join(f"{x},{y}" for x, y in points)
    for stroke, w in (("#fafafa", width + 3.5), (color, width)):
        add(f'<polyline points="{d}" fill="none" stroke="{stroke}" stroke-width="{w}" stroke-linejoin="round" stroke-linecap="round"/>')


def board(x, y, w, h, title) -> None:
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="#1e1e1e" stroke="#000" stroke-width="2"/>')
    text(x + w / 2, y + 24, title, 15, "middle", "bold", "#fff")


def pin_column(x, y0, names, used, label_side: str, labels: dict[str, str] | None = None) -> dict[str, Point]:
    """Header pins spaced PITCH apart, keyed by name. label_side is 'left' or 'right' of the pins."""
    points = {}
    for i, name in enumerate(names):
        y = y0 + i * PITCH
        is_used = name in used
        pin(x, y, is_used)
        label = (labels or {}).get(name, name)
        if label_side == "right":
            text(x + 14, y + 4, label, 11, "start", "bold" if is_used else "normal", "#fff" if is_used else "#aaa")
        else:
            text(x - 14, y + 4, label, 11, "end", "bold" if is_used else "normal", "#fff" if is_used else "#aaa")
        points[name] = (x, y)
    return points


def resistor(x, y, length=50, label="1 kOhm") -> None:
    add(f'<rect x="{x}" y="{y - 8}" width="{length}" height="16" rx="3" fill="#e8d5a8" stroke="#6b4f1d" stroke-width="2"/>')
    for k, band in enumerate(["#6b4f1d", "#000", "#d62828"]):
        add(f'<rect x="{x + 10 + k * 11}" y="{y - 8}" width="5" height="16" fill="{band}"/>')
    text(x + length / 2, y - 14, label, 11, "middle", "bold")


def capacitor(x, red_y, black_y) -> None:
    """Electrolytic between a 12 V rail (above) and a 0 V rail (below)."""
    wire([(x, red_y), (x, red_y + 9)], COLOR["12v"], 3)
    add(f'<line x1="{x - 12}" y1="{red_y + 10}" x2="{x + 12}" y2="{red_y + 10}" stroke="#111" stroke-width="3"/>')
    add(f'<path d="M {x - 12} {black_y - 8} Q {x} {black_y - 16} {x + 12} {black_y - 8}" fill="none" stroke="#111" stroke-width="3"/>')
    wire([(x, black_y - 9), (x, black_y)], COLOR["gnd"], 3)
    text(x + 20, red_y - 6, "100 uF, 25 V or more", 10, "start", "bold")
    text(x + 20, black_y + 18, "plus leg to 12 V, mount at the driver", 9, "start", fill="#444")
    text(x - 110, red_y - 10, "12 V", 9, "middle", "bold", COLOR["12v"])
    text(x - 95, black_y + 16, "0 V", 9, "middle", "bold", COLOR["gnd"])


# ----------------------------------------------------------------------------- components


def draw_esp32(x, y) -> dict[str, Point]:
    """HW-394 DevKit, USB-C down. Returns pins keyed 'L:<name>' and 'R:<name>'."""
    w, h = 250, 420
    left = ["EN", "VP", "VN", "D34", "D35", "D32", "D33", "D25", "D26", "D27", "D14", "D12", "D13", "GND", "VIN"]
    right = ["D23", "D22", "TX0", "RX0", "D21", "D19", "D18", "D5", "D17", "D16", "D4", "D2", "D15", "GND", "3V3"]
    used = {"3V3", "GND", "D34", "D35", "D33", "D25", "D22", "D21", "D19", "D23", "D17", "D5"}

    board(x, y, w, h, "ESP32 DevKit  (HW-394)")
    add(f'<rect x="{x + w/2 - 22}" y="{y + h - 12}" width="44" height="26" rx="8" fill="#9a9a9a" stroke="#444" stroke-width="2"/>')
    text(x + w / 2, y + h + 6, "USB-C", 9, "middle", fill="#111")
    add(f'<rect x="{x + 55}" y="{y + 42}" width="140" height="168" rx="4" fill="#b8b8b8" stroke="#666" stroke-width="2"/>')
    text(x + w / 2, y + 132, "ESP32-WROOM-32", 11, "middle", fill="#333")
    text(x + 48, y + 412, "EN (reset)", 8, "middle", fill="#aaa")
    text(x + w - 48, y + 412, "BOOT", 8, "middle", fill="#aaa")

    pins = {}
    pins.update({f"L:{k}": v for k, v in pin_column(x + 14, y + 50, left, used, "right").items()})
    pins.update({f"R:{k}": v for k, v in pin_column(x + w - 14, y + 50, right, used, "left").items()})
    return pins


def draw_driver(x, y, axis: str, address: int) -> dict[str, Point]:
    """BTT TMC2209 V1.3 seen from the top. Right-hand pins are keyed by name; the two GND pins as 'GND_VS' and 'GND_IO'."""
    w, h = 170, 250
    left = ["EN", "MS1", "MS2", "UART", "PDN", "CLK", "STEP", "DIR"]
    right = ["VS", "GND_VS", "A2", "A1", "B1", "B2", "VIO", "GND_IO"]
    used = {"EN", "UART", "STEP", "DIR"} | ({"MS1"} if address else set())

    board(x, y, w, h, f"TMC2209 V1.3  ({axis})")
    text(x + w / 2, y + h + 16, f"UART address {address}", 10, "middle", "bold", "#444")
    add(f'<rect x="{x + 45}" y="{y + 95}" width="80" height="110" rx="3" fill="#2f5fd6" stroke="#1a3a8a" stroke-width="2" opacity="0.85"/>')
    for k in range(4):
        add(f'<line x1="{x + 45}" y1="{y + 105 + k*26}" x2="{x + 125}" y2="{y + 105 + k*26}" stroke="#1a3a8a" stroke-width="2"/>')
    add(f'<circle cx="{x + 118}" cy="{y + 50}" r="11" fill="#ddd" stroke="#555" stroke-width="2"/>')
    add(f'<line x1="{x + 110}" y1="{y + 42}" x2="{x + 126}" y2="{y + 58}" stroke="#555" stroke-width="2"/>')

    y0 = y + 60
    for j, name in enumerate(["DIAG", "INDEX"]):  # snipped, drawn as red crosses
        cx = x + 14 + (j + 1) * PITCH
        add(f'<line x1="{cx-6}" y1="{y0-6}" x2="{cx+6}" y2="{y0+6}" stroke="#c0392b" stroke-width="3"/>')
        add(f'<line x1="{cx-6}" y1="{y0+6}" x2="{cx+6}" y2="{y0-6}" stroke="#c0392b" stroke-width="3"/>')
        text(cx, y0 - 14, name, 8, "middle", fill="#c0392b", rotate=-60)

    pins = pin_column(x + 14, y0, left, used, "right")
    pins.update(pin_column(x + w - 14, y0, right, set(right), "left", {"GND_VS": "GND", "GND_IO": "GND"}))
    return pins


def draw_motor(x, y, title) -> dict[str, Point]:
    add(f'<rect x="{x}" y="{y}" width="150" height="150" rx="16" fill="#3a3a3a" stroke="#000" stroke-width="2"/>')
    add(f'<circle cx="{x + 75}" cy="{y + 75}" r="42" fill="#777" stroke="#222" stroke-width="2"/>')
    add(f'<circle cx="{x + 75}" cy="{y + 75}" r="8" fill="#ccc" stroke="#222" stroke-width="2"/>')
    text(x + 75, y + 174, title, 14, "middle", "bold")
    text(x + 75, y + 192, "1.5 A/phase, 1.8 deg", 10, "middle", fill="#444")
    pins = {name: (x, y + 30 + i * 30) for i, name in enumerate(["A2", "A1", "B1", "B2"])}
    for px, py in pins.values():
        pin(px, py)
    return pins


def draw_psu(x, y) -> tuple[Point, Point]:
    """Returns (plus, minus) terminal positions."""
    w, h = 230, 105
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="#e9e9e9" stroke="#666" stroke-width="2"/>')
    text(x + w / 2, y + 46, "Bench PSU", 15, "middle", "bold", "#111")
    text(x + w / 2, y + 68, "12.0 V  ·  current limit 2 A", 11, "middle", fill="#333")
    text(x + w / 2, y + 88, "motor supply only, ESP32 stays on USB", 9, "middle", fill="#666")
    plus, minus = (x + 150, y), (x + 70, y)
    for (px, py), fill, sign in ((plus, "#d62828", "+"), (minus, "#222", "-")):
        add(f'<circle cx="{px}" cy="{py}" r="12" fill="{fill}" stroke="#333" stroke-width="2"/>')
        text(px, py + 5, sign, 16, "middle", "bold", "#fff")
    return plus, minus


def draw_joystick(x, y) -> dict[str, Point]:
    w, h = 270, 190
    board(x, y, w, h, "XY joystick module")
    add(f'<circle cx="{x + 90}" cy="{y + 115}" r="46" fill="#444" stroke="#000" stroke-width="2"/>')
    add(f'<circle cx="{x + 90}" cy="{y + 115}" r="21" fill="#111" stroke="#666" stroke-width="2"/>')
    names = ["SW", "VRY", "VRX", "+5V", "GND"]
    pins = pin_column(x + w - 22, y + 50, names, set(names), "left")
    text(x + w / 2, y + h - 12, "header turned to face the board", 9, "middle", fill="#bbb")
    return pins


def wire_coils(driver: dict[str, Point], motor: dict[str, Point]) -> None:
    """Four coil wires on their own vertical lanes between driver and motor."""
    lanes = {"A2": 1180, "A1": 1195, "B1": 1210, "B2": 1225}
    for name, color in (("A2", "coil_a"), ("A1", "coil_a"), ("B1", "coil_b"), ("B2", "coil_b")):
        src, dst = driver[name], motor[name]
        wire([src, (lanes[name], src[1]), (lanes[name], dst[1]), dst], COLOR[color], 3.5)
    text(1150, motor["A2"][1] - 22, "coil A", 10, "middle", "bold", COLOR["coil_a"])
    text(1150, motor["B2"][1] + 24, "coil B", 10, "middle", "bold", COLOR["coil_b"])


# ----------------------------------------------------------------------------- layout

esp = draw_esp32(470, 120)
drv_x = draw_driver(950, 130, "X", 0)
drv_y = draw_driver(950, 480, "Y", 1)
motor_x = draw_motor(1255, 180, "NEMA 17  (X axis)")
motor_y = draw_motor(1255, 530, "NEMA 17  (Y axis)")
psu_plus, psu_minus = draw_psu(1180, 1050)
joy = draw_joystick(60, 250)

# Vertical lanes between the ESP32 and the drivers, one per signal.
LANE = {"gnd": 745, "en": 760, "uart": 790, "step_x": 850, "dir_x": 880, "step_y": 900, "dir_y": 925}
RAIL_12V, RAIL_0V = 1455, 1430  # PSU rails running down the right edge
BUS_Y = 1000  # common ground trunk

# ----------------------------------------------------------------------------- wires

# Shared driver signals fan out to both boards.
wire([esp["R:D22"], (LANE["en"], esp["R:D22"][1]), (LANE["en"], drv_x["EN"][1]), drv_x["EN"]], COLOR["en"])
wire([(LANE["en"], esp["R:D22"][1]), (LANE["en"], drv_y["EN"][1]), drv_y["EN"]], COLOR["en"])
wire([esp["R:D21"], (LANE["uart"], esp["R:D21"][1]), (LANE["uart"], drv_x["UART"][1]), drv_x["UART"]], COLOR["uart"])
wire([(LANE["uart"], esp["R:D21"][1]), (LANE["uart"], drv_y["UART"][1]), drv_y["UART"]], COLOR["uart"])
wire([esp["R:D19"], (735, esp["R:D19"][1])], COLOR["tx"])
resistor(735, esp["R:D19"][1])
wire([(785, esp["R:D19"][1]), (LANE["uart"], esp["R:D19"][1])], COLOR["tx"])

# Per-axis step and direction.
for esp_pin, lane, driver_pin, color in (
    ("R:D17", "step_x", drv_x["STEP"], "step"),
    ("R:D23", "step_y", drv_y["STEP"], "step"),
    ("R:D5", "dir_y", drv_y["DIR"], "dir"),
):
    src = esp[esp_pin]
    wire([src, (LANE[lane], src[1]), (LANE[lane], driver_pin[1]), driver_pin], COLOR[color])

# X DIR leaves the left column and crosses over the top of the ESP32 to its lane.
wire([esp["L:D25"], (455, esp["L:D25"][1]), (455, 100), (LANE["dir_x"], 100), (LANE["dir_x"], drv_x["DIR"][1]), drv_x["DIR"]], COLOR["dir"])

# 3.3 V logic: between the two driver boards, then up to X VIO, down to Y VIO, and to Y MS1 for address 1.
V33_Y, V33_LANE = 440, 1240
wire([esp["R:3V3"], (730, esp["R:3V3"][1]), (730, V33_Y), (V33_LANE, V33_Y), (V33_LANE, drv_x["VIO"][1]), drv_x["VIO"]], COLOR["3v3"])
wire([(V33_LANE, V33_Y), (V33_LANE, drv_y["VIO"][1]), drv_y["VIO"]], COLOR["3v3"])
wire([(945, V33_Y), (945, drv_y["MS1"][1]), drv_y["MS1"]], COLOR["3v3"])
text(1000, V33_Y - 8, "3.3 V", 10, "middle", "bold", COLOR["3v3"])

# Ground: one trunk from the ESP32 to the PSU; driver logic grounds join it or the 0 V rail.
wire([esp["R:GND"], (LANE["gnd"], esp["R:GND"][1]), (LANE["gnd"], BUS_Y), (psu_minus[0], BUS_Y), psu_minus], COLOR["gnd"])
wire([drv_x["GND_IO"], (1130, drv_x["GND_IO"][1]), (1130, 410), (RAIL_0V, 410)], COLOR["gnd"])
wire([drv_y["GND_IO"], (1150, drv_y["GND_IO"][1]), (1150, BUS_Y)], COLOR["gnd"])
text(940, BUS_Y + 18, "common ground: both ESP32 GND pins, driver logic GND, driver power GND, PSU minus", 10, "middle", fill="#222")

# 12 V: two rails down the right edge, each driver starred off them with its own capacitor.
wire([(RAIL_12V, 92), (RAIL_12V, BUS_Y + 30), (psu_plus[0], BUS_Y + 30), psu_plus], COLOR["12v"], 5)
wire([(RAIL_0V, 120), (RAIL_0V, BUS_Y + 15), (psu_minus[0], BUS_Y + 15), psu_minus], COLOR["gnd"], 5)
for driver, red_y, black_y in ((drv_x, 92, 120), (drv_y, 480, 510)):
    wire([driver["VS"], (1135, driver["VS"][1]), (1135, red_y), (RAIL_12V, red_y)], COLOR["12v"], 5)
    wire([driver["GND_VS"], (1160, driver["GND_VS"][1]), (1160, black_y), (RAIL_0V, black_y)], COLOR["gnd"], 5)
    capacitor(1290, red_y, black_y)

wire_coils(drv_x, motor_x)
wire_coils(drv_y, motor_y)

# Joystick: signals on the left column, power wrapped under the board.
wire([joy["VRX"], (400, joy["VRX"][1]), (400, esp["L:D34"][1]), esp["L:D34"]], COLOR["joy_x"])
wire([joy["SW"], (420, joy["SW"][1]), (420, esp["L:D33"][1]), esp["L:D33"]], COLOR["sw"])
wire([joy["VRY"], (440, joy["VRY"][1]), (440, esp["L:D35"][1]), esp["L:D35"]], COLOR["joy_y"])
wire([(730, esp["R:3V3"][1]), (730, 660), (470, 660), (470, joy["+5V"][1]), joy["+5V"]], COLOR["3v3"])
wire([(LANE["gnd"], 690), (460, 690), (460, joy["GND"][1]), joy["GND"]], COLOR["gnd"])
text(452, 678, "3.3 V and ground run under the board", 10, "end", fill="#555")

# ----------------------------------------------------------------------------- legend and notes

text(40, 44, "hyperscope XY stage wiring", 22, "start", "bold")
text(40, 66, "ESP32 HW-394 + 2x BIGTREETECH TMC2209 V1.3 (UART mode) + 2x NEMA 17 + joystick", 12, "start", fill="#444")

legend = [
    ("12v", "12 V motor supply (VS)"),
    ("3v3", "3.3 V logic (VIO, Y MS1, joystick)"),
    ("gnd", "Ground, all joined"),
    ("en", "EN  <- D22, shared   (LOW = drivers on)"),
    ("uart", "UART bus  <- D21 (RX), shared"),
    ("tx", "UART TX  <- D19, through 1 kOhm onto the bus"),
    ("step", "STEP  <- D17 (X), D23 (Y)"),
    ("dir", "DIR  <- D25 (X), D5 (Y)"),
    ("joy_x", "Joystick VRX -> D34   (blue)"),
    ("joy_y", "Joystick VRY -> D35   (grey)"),
    ("sw", "Joystick SW -> D33"),
    ("coil_a", "Motor coil A -> A1 / A2"),
    ("coil_b", "Motor coil B -> B1 / B2"),
]
for i, (key, label) in enumerate(legend):
    y = 520 + i * 23
    add(f'<line x1="40" y1="{y}" x2="80" y2="{y}" stroke="{COLOR[key]}" stroke-width="5" stroke-linecap="round"/>')
    text(90, y + 4, label, 12)

notes = [
    "Snip DIAG and INDEX off each driver first: on a breadboard they land in EN's tie strip.",
    "MS1 open on X = UART address 0. MS1 to 3.3 V on Y = address 1. Leave MS2, PDN and CLK open on both.",
    "The Vref potentiometers do nothing here. Current (0.6 A RMS) is set over UART.",
    "Wire the logic side and flash first. Only connect the motors, then 12 V, once both 'driver ok' lines appear.",
    "Never plug or unplug a motor while the 12 V supply is on.",
    "Motor coil pairs read a few ohms between them. Either pair can be A.",
]
for i, note in enumerate(notes):
    text(40, 1190 + i * 20, "- " + note, 12, fill="#222")

header = (
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
    f'<rect width="{W}" height="{H}" fill="#fafafa"/>'
)
OUT.write_text(header + "\n".join(svg) + "</svg>\n")
print(f"wrote {OUT}")
