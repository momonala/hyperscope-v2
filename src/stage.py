"""Host-side client for the ESP32 XY stage controller.

Speaks the newline text protocol documented in docs/hardware.md.

    uv run python src/stage.py status
    uv run python src/stage.py send "MOVE X3200"
    uv run python src/stage.py jog
"""

import os
import select
import sys
import termios
import time
import tty
from collections.abc import Iterator
from contextlib import contextmanager

import serial
import typer
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from serial.tools import list_ports

BAUD = 115200
REPLY_TIMEOUT_S = 120.0  # WAIT blocks for the whole move
JOG_STEP_DEFAULT = 50  # microsteps per tap, about 1/64 of a knob turn
JOG_STEP_MIN, JOG_STEP_MAX = 5, 3200
JOG_SPEED_DEFAULT_HZ = 800  # a quarter knob turn per second while holding
JOG_SPEED_MIN_HZ, JOG_SPEED_MAX_HZ = 50, 6400
JOG_SPEED_FAST_HZ = 2500
JOG_RELEASE_S = 0.5
HOME_SPEED_HZ = 1000
HOME_RUNS = (("Y", 1), ("X", -1))  # up into the top stop, then left into the left stop
BOOT_SETTLE_S = 1.0
KEY_POLL_S = 0.02
ESCAPE_FOLLOWUP_S = 0.05
STATUS_POLL_S = 0.1

app = typer.Typer(help="Talk to the hyperscope XY stage controller.")
PORT_OPTION = typer.Option(None, "--port", help="Serial port; auto-detected if omitted")


def find_port() -> str:
    """Return the single USB serial port the controller is on.

    Raises:
        RuntimeError: If no USB serial port is present, or several are.
    """
    candidates = [
        p.device for p in list_ports.comports() if "usbserial" in p.device or "usbmodem" in p.device
    ]
    if not candidates:
        raise RuntimeError("No USB serial port found. Is the ESP32 plugged in?")
    if len(candidates) > 1:
        raise RuntimeError(f"Several USB serial ports found, pass --port: {', '.join(candidates)}")
    return candidates[0]


def open_port(port: str | None, reset: bool) -> serial.Serial:
    """Open the controller's serial port, optionally resetting the board first."""
    connection = serial.Serial(port or find_port(), BAUD, timeout=0.2)
    if reset:
        connection.setDTR(False)
        connection.setRTS(True)
        time.sleep(0.15)
        connection.setRTS(False)
        time.sleep(0.05)
        connection.setDTR(True)
    connection.reset_input_buffer()
    return connection


def read_reply(connection: serial.Serial) -> list[str]:
    """Collect lines up to and including the terminating "ok" or "err ..." line.

    Raises:
        TimeoutError: If no terminator arrives within REPLY_TIMEOUT_S.
    """
    lines: list[str] = []
    deadline = time.monotonic() + REPLY_TIMEOUT_S
    while time.monotonic() < deadline:
        line = connection.readline().decode("utf-8", "replace").rstrip()
        if not line:
            continue
        lines.append(line)
        if line == "ok" or line.startswith("err"):
            return lines
    raise TimeoutError(f"No reply terminator within {REPLY_TIMEOUT_S:.0f}s; got {lines}")


def send_command(connection: serial.Serial, command: str) -> list[str]:
    connection.write(f"{command}\n".encode())
    return read_reply(connection)


@app.command()
def status(port: str = PORT_OPTION) -> None:
    """Reset the controller, print its boot banner, then print a status line."""
    with open_port(port, reset=True) as connection:
        for line in read_reply(connection) + send_command(connection, "?"):
            typer.echo(line)


ARROW_KEYS = {b"A": "UP", b"B": "DOWN", b"C": "RIGHT", b"D": "LEFT"}
KEY_HELP = (
    ("arrows", "tap: one small step · hold: run until released"),
    (
        "h",
        "home: run up into the top stop, then left into the left stop; zero is set there",
    ),
    (
        "f",
        f"fast hold on/off ({JOG_SPEED_FAST_HZ} µsteps/s); press before holding an arrow",
    ),
    ("+ / -", "double / halve the tap size and normal hold speed"),
    ("z", "zero here without moving"),
    ("l", "soft limits on/off"),
    ("s · x · y", "swap arrow axes · flip left/right · flip up/down"),
    ("q", "quit; turns the motors off"),
)


def read_key(timeout_s: float) -> str | None:
    """Return one key from a cbreak terminal: a character, an arrow name, or None on timeout.

    Reads the file descriptor directly: buffered stdin would swallow a whole
    escape sequence on the first read and make the arrow look like a bare Escape.
    Escape sequences other than arrows return None.
    """
    fd = sys.stdin.fileno()
    if not select.select([fd], [], [], timeout_s)[0]:
        return None
    data = os.read(fd, 8)
    if not data.startswith(b"\x1b"):
        return data[:1].decode("utf-8", "replace")
    if len(data) == 1 and select.select([fd], [], [], ESCAPE_FOLLOWUP_S)[0]:
        data += os.read(fd, 8)
    # Arrows arrive as ESC [ A..D, or ESC O A..D in application cursor mode.
    if len(data) >= 3 and data[1:2] in (b"[", b"O"):
        return ARROW_KEYS.get(data[2:3])
    return None


@contextmanager
def cbreak_terminal() -> Iterator[None]:
    """Deliver key presses unbuffered and without echo, restoring the terminal on exit."""
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    try:
        yield
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def parse_status(lines: list[str]) -> dict[str, str]:
    """Parse a status line into fields.

    "pos X400 Y-20 moving:1 X:zeroed[-3200..3200] ..." becomes
    {"X": "400", "Y": "-20", "moving": "1", "X_limits": "zeroed[-3200..3200]", ...}.
    """
    _, x_position, y_position, *named = lines[0].split()
    fields = {"X": x_position[1:], "Y": y_position[1:]}
    for token in named:
        key, value = token.split(":", 1)
        if key in fields:
            key = f"{key}_limits"
        fields[key] = value
    return fields


class Jogger:
    """Keyboard-driven stage control with a live status panel.

    A tap sends one small relative step. A held key auto-repeats; on the
    first repeat the axis switches to continuous motion and stops once the
    repeats go quiet, since a terminal never reports key release.
    """

    def __init__(self, connection: serial.Serial, step: int, speed: int, release_s: float) -> None:
        self.connection = connection
        self.horizontal_axis = "X"
        self.horizontal_sign = 1
        self.vertical_sign = 1
        self.step = step
        self.speed = speed
        self.fast = False
        self.release_s = release_s
        self.last_arrow: tuple[str, int] | None = None
        self.last_arrow_at = 0.0
        self.running_axis: tuple[str, int] | None = None
        self.last_status_at = 0.0
        self.status = parse_status(send_command(connection, "?"))
        self.last_command = ""
        self.last_reply = ""

    @property
    def vertical_axis(self) -> str:
        return "Y" if self.horizontal_axis == "X" else "X"

    def arrow_target(self, key: str) -> tuple[str, int]:
        if key in ("LEFT", "RIGHT"):
            sign = self.horizontal_sign * (1 if key == "RIGHT" else -1)
            return self.horizontal_axis, sign
        sign = self.vertical_sign * (1 if key == "UP" else -1)
        return self.vertical_axis, sign

    def mapping(self) -> str:
        horizontal = "right" if self.horizontal_sign > 0 else "left"
        vertical = "up" if self.vertical_sign > 0 else "down"
        return f"+{self.horizontal_axis} = {horizontal}, +{self.vertical_axis} = {vertical}"

    def send(self, command: str) -> bool:
        """Send a command, record it for the panel, and return whether it succeeded."""
        self.last_command = command
        reply = send_command(self.connection, command)
        self.last_reply = " / ".join(line for line in reply if line != "ok") or "ok"
        return not reply[-1].startswith("err")

    def handle(self, key: str) -> None:
        if key in ("UP", "DOWN", "LEFT", "RIGHT"):
            self.press_arrow(*self.arrow_target(key))
        elif key == "s":
            self.release_arrow()
            self.horizontal_axis = self.vertical_axis
        elif key == "x":
            self.release_arrow()
            self.horizontal_sign *= -1
        elif key == "y":
            self.release_arrow()
            self.vertical_sign *= -1
        elif key == "h":
            self.home()
        elif key == "f":
            self.toggle_fast()
        elif key == "l":
            self.send(f"LIMITS {0 if self.limits_on else 1}")
        elif key in ("+", "="):
            self.scale_motion(2)
        elif key == "-":
            self.scale_motion(0.5)
        elif key == "z":
            self.send("ZERO")

    def press_arrow(self, axis: str, direction: int) -> None:
        now = time.monotonic()
        is_repeat = self.last_arrow == (axis, direction) and now - self.last_arrow_at < self.release_s
        self.last_arrow, self.last_arrow_at = (axis, direction), now
        if not is_repeat:
            self.send(f"MOVE {axis}{direction * self.step}")
        elif self.running_axis != (axis, direction):
            self.send(f"JOG {axis}{direction * self.hold_speed}")
            self.running_axis = (axis, direction)

    def home(self) -> None:
        """Run each axis into its top-left stop; the controller zeroes it there.

        Blocks until both axes finish, so the panel freezes meanwhile.
        """
        self.release_arrow()
        for axis, direction in HOME_RUNS:
            if not self.send(f"HOME {axis}{direction * HOME_SPEED_HZ}"):
                return

    @property
    def limits_on(self) -> bool:
        return self.status["limits"] == "1"

    @property
    def hold_speed(self) -> int:
        return JOG_SPEED_FAST_HZ if self.fast else self.speed

    def toggle_fast(self) -> None:
        self.fast = not self.fast
        if self.running_axis:
            axis, direction = self.running_axis
            self.send(f"JOG {axis}{direction * self.hold_speed}")

    def release_arrow(self) -> None:
        if self.running_axis:
            self.send(f"JOG {self.running_axis[0]}0")
        self.running_axis = None
        self.last_arrow = None

    def scale_motion(self, factor: float) -> None:
        self.step = int(min(max(self.step * factor, JOG_STEP_MIN), JOG_STEP_MAX))
        self.speed = int(min(max(self.speed * factor, JOG_SPEED_MIN_HZ), JOG_SPEED_MAX_HZ))

    def tick(self) -> None:
        """Stop a held axis once repeats stop, and refresh the position readout."""
        now = time.monotonic()
        if self.last_arrow and now - self.last_arrow_at > self.release_s:
            self.release_arrow()
        if now - self.last_status_at > STATUS_POLL_S:
            self.last_status_at = now
            self.status = parse_status(send_command(self.connection, "?"))

    def render(self) -> Panel:
        is_moving = self.status["moving"] == "1"
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bold cyan")
        table.add_column()
        table.add_row("X", f"[bold]{self.status['X']:>8}[/]")
        table.add_row("Y", f"[bold]{self.status['Y']:>8}[/]")
        table.add_row("state", "[bold green]moving[/]" if is_moving else "[dim]idle[/]")
        table.add_row("limits", "[bold green]on[/]" if self.limits_on else "[bold red]OFF[/]")
        table.add_row("arrows", self.mapping())
        table.add_row("tap", f"{self.step} µsteps")
        hold = f"{self.hold_speed} µsteps/s"
        table.add_row("hold", f"[bold yellow]{hold} fast[/]" if self.fast else hold)
        table.add_row("last", f"[dim]{self.last_command}[/]")
        table.add_row("reply", f"[dim]{self.last_reply}[/]")
        table.add_row("", "")
        for key, meaning in KEY_HELP:
            table.add_row(f"[dim]{key}[/]", f"[dim]{meaning}[/]")
        return Panel(
            table,
            title="[bold]hyperscope stage[/]",
            border_style="green" if is_moving else "blue",
        )


@app.command()
def jog(
    step: int = typer.Option(JOG_STEP_DEFAULT, help="Microsteps per tap (3200 per knob turn)"),
    speed: int = typer.Option(JOG_SPEED_DEFAULT_HZ, help="Microsteps/s while holding a key"),
    release_s: float = typer.Option(
        JOG_RELEASE_S,
        help="Seconds without key repeats before a held axis stops. Raise if the stage stutters while holding",
    ),
    port: str = PORT_OPTION,
) -> None:
    """Drive the stage from the keyboard: tap an arrow to step, hold it to run.

    Zeroes wherever the stage is and energises the motors; quitting turns them
    off. The panel lists every key. Homing (h) blocks the panel until both axes
    finish; cut the 12 V supply to stop it.
    """
    if not sys.stdin.isatty():
        raise typer.BadParameter(
            "jog needs a real terminal; run it in a shell window, not through a tool or pipe"
        )
    with open_port(port, reset=False) as connection:
        time.sleep(BOOT_SETTLE_S)  # opening the port resets the board; let the boot banner finish
        connection.reset_input_buffer()
        send_command(connection, "ZERO")
        send_command(connection, "EN 1")
        jogger = Jogger(connection, step, speed, release_s)
        try:
            with (
                cbreak_terminal(),
                Live(jogger.render(), refresh_per_second=20, transient=True) as live,
            ):
                while True:
                    key = read_key(KEY_POLL_S)
                    if key in ("q", "\x03"):
                        jogger.release_arrow()
                        break
                    if key is not None:
                        jogger.handle(key)
                    jogger.tick()
                    live.update(jogger.render())
        finally:
            send_command(connection, "EN 0")
        typer.echo(f"arrow mapping: {jogger.mapping()}")
        typer.echo(f"final position: X{jogger.status['X']} Y{jogger.status['Y']}")


@app.command()
def send(
    command: str = typer.Argument(..., help="Command to send, e.g. 'MOVE X3200'"),
    port: str = PORT_OPTION,
) -> None:
    """Send one command to an already-running controller and print the reply."""
    with open_port(port, reset=False) as connection:
        for line in send_command(connection, command):
            typer.echo(line)


if __name__ == "__main__":
    app()
