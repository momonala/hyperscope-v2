# Stage controller carrier PCB

A 2-layer, 84 x 68 mm carrier that the ESP32 HW-394 DevKit and two BIGTREETECH TMC2209
modules plug into. Everything else is through-hole and hand-soldered: motor and 12 V
screw terminals, a joystick header, input protection, bulk capacitors, and six solder
jumpers on the back. Electrical design and pin map: [`docs/hardware.md`](../../docs/hardware.md).

Not yet ordered. Before ordering, print `review/top.svg` at 1:1 and stand a DevKit and a
TMC2209 module on it.

## Generating

`generate.py` holds the netlist and placement in one place and writes the schematic and the
PCB from it, so the two cannot disagree. Never hand-edit the KiCad files; change the script
and rerun:

```bash
/Applications/KiCad/KiCad.app/Contents/Frameworks/Python.framework/Versions/Current/bin/python3 \
    hardware/pcb/generate.py --route        # place, autoroute, ERC, DRC, Gerbers, previews
```

Needs KiCad 10 (Homebrew cask), Java 21 (`brew install openjdk@21`) and
`freerouting-1.9.0.jar` beside the script (gitignored; Freerouting 2.x writes an empty
session from the CLI). `--no-fab` skips the checks and exports; omitting `--route` leaves the
board unrouted.

| Path | What |
|---|---|
| `generate.py` | Source of truth: netlist, placement, net classes, silkscreen |
| `kicad/` | Generated KiCad project, open in the GUI to inspect |
| `gerbers.zip` | Bare boards: upload as is to JLCPCB or PCBWay |
| `review/` | `schematic.pdf`, `top.svg` (print 1:1 for the fit test), `bottom.svg`, `erc.rpt`, `drc.rpt` |

## Layout

Top view, USB-C out of the left edge, motor wires out of the top edge:

- **DevKit** along the bottom edge in two 1x15 female headers 25.4 mm apart. Component side
  up with USB left, the HW-394's VIN column is the upper row and the 3V3 column the lower
  row, so EN, UART, STEP, DIR and DIAG route under the DevKit up to the modules. The pin
  pattern is symmetric, so a swapped row passes every check and the fit test; verify any
  DevKit-row change against `docs/photos/esp32-hw394-devkit-top.png` rotated USB-left.
  A copper keep-out sits under the antenna.
- **Driver modules** X and Y side by side above the DevKit, each in two 1x8 female headers
  15.24 mm apart plus a 1x2 for DIAG/INDEX. Logic row faces the DevKit, power row faces
  its motor terminal. 100 µF across VS/GND beside each socket.
- **Back, under each module:** MS1 and MS2 address jumpers (GND left pad, 3V3 right pad in
  top view) and the DIAG-select jumper. All ship open; bridge the address jumpers before
  first power-up. Intended addresses: X = 00, Y = MS1 high.
- **12 V** enters top right: screw terminal, 3 A polyfuse, series Schottky (SR340) for
  reverse polarity, 470 µF bulk. VIN on the DevKit is unconnected; logic runs from USB.
- **Joystick** 1x5 pin header bottom right (GND, 3V3, VRX, VRY, SW) with 100 nF on each axis.
- **Spare pad row** along the bottom edge, no header fitted: GPIO 15 2 13 14 27 26 25 32 39 36,
  then 3x 3V3 and 3x GND. GPIO 15 and 2 are boot-strapping pins.
- Four M3 mounting holes.

Copper: VM 1.5 mm, motor phases 1.0 mm, logic 0.25 mm, ground pours on both faces.

## Fab settings

84 x 68 mm, 3 mm corner radius, 2 layers, 1.6 mm FR-4, 1 oz, lead-free HASL, min track
0.25 mm, min clearance 0.2 mm, min drill 0.3 mm, vias 0.8/0.4 mm. Under 100 x 100 mm keeps
the cheapest fab tier.

## Parts

Plug-in, not soldered: the ESP32 HW-394 DevKit and two BTT TMC2209 V1.3 modules with
heatsinks and the DIAG pin intact.

| Ref | Qty | Part | Notes |
|---|---|---|---|
| J1, J2 | 2 | Female header 1x15, 2.54 mm | DevKit socket |
| J3 to J6 | 4 | Female header 1x8, 2.54 mm | Module sockets |
| J7, J8 | 2 | Female header 1x2, 2.54 mm | DIAG/INDEX |
| J9, J10 | 2 | Screw terminal 4P, 5.0 mm pitch (KF128/MX126) | Motor A2 A1 B1 B2 |
| J11 | 1 | Screw terminal 2P, 5.0 mm pitch | 12 V in, pin 1 (left) is + |
| J13 | 1 | Pin header 1x5, 2.54 mm | Joystick via dupont leads |
| F1 | 1 | Polyfuse, 3 A hold, radial (RXEF300 class) | |
| D1 | 1 | Schottky 40 V 3 A, DO-201AD (SR340) | Band toward VM |
| C1, C2 | 2 | Electrolytic 100 µF 35 V, 6.3 x 11 mm, 2.5 mm pitch | One per module |
| C3 | 1 | Electrolytic 470 µF 25 V, 10 x 12.5 mm, 5 mm pitch | Input bulk |
| C6, C7 | 2 | Ceramic 100 nF disc, 5 mm pitch | Joystick ADC filters |
| R1 to R3 | 3 | 1 kΩ 1/4 W axial | UART TX and DIAG series |
| R4 | 1 | 2.2 kΩ 1/4 W axial | EN pull-up |
| JP1 to JP6 | | Solder jumpers, bare pads on the back | See layout |
| H1 to H4 | | M3 mounting holes | |

## Assembly and bring-up

1. Passives and headers first, no modules. Power 12 V at a 0.5 A limit; check for shorts
   and 12 V at each socket's VS pin.
2. Bridge the address jumpers. Plug the DevKit only; check 3V3 at each socket's VIO.
3. Plug the X module, PSU limit 2 A, run `?`, `DIRTEST X`, `MOVE X3200`. Repeat for Y.
4. DIAG jumpers: move a motor, probe which of the two pads pulses (that one is INDEX),
   then bridge the centre pad to the other one. Modules with the DIAG pin snipped still
   work but cannot report stalls.
5. After ten minutes of jogging, `?` should still show 16 microsteps on both drivers and
   no `driver lost its settings` lines.
