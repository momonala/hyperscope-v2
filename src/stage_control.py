"""Host-side client for the ESP32 XY stage controller.

Speaks the newline text protocol documented in docs/hardware.md.

    uv run python src/stage_control.py jog
    uv run python src/stage_control.py status
    uv run python src/stage_control.py move X400 Y-20
    uv run python src/stage_control.py send "SPEED 2000"
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
BOOT_TIMEOUT_S = 5.0
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
        p.device
        for p in list_ports.comports()
        if "usbserial" in p.device or "usbmodem" in p.device
    ]
    if not candidates:
        raise RuntimeError("No USB serial port found. Is the ESP32 plugged in?")
    if len(candidates) > 1:
        raise RuntimeError(
            f"Several USB serial ports found, pass --port: {', '.join(candidates)}"
        )
    return candidates[0]


def open_port(port: str | None) -> serial.Serial:
    """Open the controller's serial port and wait out the boot it triggers.

    The USB adapter resets the ESP32 on every open, so the controller always
    starts fresh: motors off and position unzeroed.
    """
    connection = serial.Serial(None, BAUD, timeout=0.2)
    connection.port = port or find_port()
    # Asserted DTR holds the ESP32 in its bootloader; release both lines so it runs.
    connection.dtr = False
    connection.rts = False
    connection.open()
    deadline = time.monotonic() + BOOT_TIMEOUT_S
    while time.monotonic() < deadline:
        if connection.readline().decode("utf-8", "replace").rstrip() == "ok":
            return connection
    raise TimeoutError(f"Controller sent no boot banner within {BOOT_TIMEOUT_S:.0f}s")


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
    raise TimeoutError(
        f"No reply terminator within {REPLY_TIMEOUT_S:.0f}s; got {lines}"
    )


def send_command(connection: serial.Serial, command: str) -> list[str]:
    connection.write(f"{command}\n".encode())
    return read_reply(connection)


def is_error(reply: list[str]) -> bool:
    return reply[-1].startswith("err")


def zero(connection: serial.Serial) -> list[str]:
    """Make the current position (0, 0) once the stage has stopped."""
    reply = send_command(connection, "WAIT")
    return reply if is_error(reply) else send_command(connection, "ZERO")


def go_home(connection: serial.Serial) -> list[str]:
    """Move to (0, 0) and block until the stage arrives."""
    reply = send_command(connection, "GOTO X0 Y0")
    return reply if is_error(reply) else send_command(connection, "WAIT")


def run_once(port: str | None, *actions) -> None:
    """Open the port, run each action in turn, print every reply line, and exit 1 on an error."""
    with open_port(port) as connection:
        for action in actions:
            reply = action(connection)
            for line in reply:
                typer.echo(line)
            if is_error(reply):
                raise typer.Exit(1)


ARROW_KEYS = {b"A": "UP", b"B": "DOWN", b"C": "RIGHT", b"D": "LEFT"}
ARROW_TARGETS = {
    "RIGHT": ("X", 1),
    "LEFT": ("X", -1),
    "UP": ("Y", 1),
    "DOWN": ("Y", -1),
}
KEY_HELP = (
    ("arrows", "tap: one small step · hold: run until released"),
    ("f", f"fast hold on/off ({JOG_SPEED_FAST_HZ} µsteps/s)"),
    ("+ / -", "double / halve the tap size and normal hold speed"),
    ("z", "zero: make this spot home (0, 0)"),
    ("h", "go back to home"),
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

    def __init__(
        self, connection: serial.Serial, step: int, speed: int, release_s: float
    ) -> None:
        self.connection = connection
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

    def record(self, command: str, reply: list[str]) -> None:
        self.last_command = command
        self.last_reply = " / ".join(line for line in reply if line != "ok") or "ok"

    def send(self, command: str) -> None:
        self.record(command, send_command(self.connection, command))

    def handle(self, key: str) -> None:
        if key in ARROW_TARGETS:
            self.press_arrow(*ARROW_TARGETS[key])
        elif key == "f":
            self.toggle_fast()
        elif key in ("+", "="):
            self.scale_motion(2)
        elif key == "-":
            self.scale_motion(0.5)
        elif key == "z":
            self.release_arrow()
            self.record("zero", zero(self.connection))
        elif key == "h":
            self.release_arrow()
            self.record("go home", go_home(self.connection))

    def press_arrow(self, axis: str, direction: int) -> None:
        now = time.monotonic()
        is_repeat = (
            self.last_arrow == (axis, direction)
            and now - self.last_arrow_at < self.release_s
        )
        self.last_arrow, self.last_arrow_at = (axis, direction), now
        if not is_repeat:
            self.send(f"MOVE {axis}{direction * self.step}")
        elif self.running_axis != (axis, direction):
            self.send(f"JOG {axis}{direction * self.hold_speed}")
            self.running_axis = (axis, direction)

    @property
    def is_home_set(self) -> bool:
        return self.status["X_limits"].startswith("zeroed")

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
        self.speed = int(
            min(max(self.speed * factor, JOG_SPEED_MIN_HZ), JOG_SPEED_MAX_HZ)
        )

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
        table.add_row(
            "home",
            "[bold green]set[/]"
            if self.is_home_set
            else "[bold red]not set, press z[/]",
        )
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
    step: int = typer.Option(
        JOG_STEP_DEFAULT, help="Microsteps per tap (3200 per knob turn)"
    ),
    speed: int = typer.Option(
        JOG_SPEED_DEFAULT_HZ, help="Microsteps/s while holding a key"
    ),
    release_s: float = typer.Option(
        JOG_RELEASE_S,
        help="Seconds without key repeats before a held axis stops. Raise if the stage stutters while holding",
    ),
    port: str = PORT_OPTION,
) -> None:
    """Drive the stage from the keyboard: tap an arrow to step, hold it to run.

    Energises the motors; quitting turns them off. There are no soft
    limits, so keep clear of the stops. The panel lists every key. Going home
    (h) blocks the panel until the stage arrives.
    """
    if not sys.stdin.isatty():
        raise typer.BadParameter(
            "jog needs a real terminal; use the one-shot commands (status, move, send) from a tool or pipe"
        )
    with open_port(port) as connection:
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
        typer.echo(f"final position: X{jogger.status['X']} Y{jogger.status['Y']}")


@app.command()
def status(port: str = PORT_OPTION) -> None:
    """Print the controller's status line."""
    with open_port(port) as connection:
        for line in send_command(connection, "?"):
            typer.echo(line)


@app.command()
def move(
    targets: list[str] = typer.Argument(
        ..., help="Relative microsteps, e.g. X400 Y-20"
    ),
    port: str = PORT_OPTION,
) -> None:
    """Move relative to the current position and wait until the stage arrives."""
    run_once(
        port,
        lambda c: send_command(c, "EN 1"),
        lambda c: send_command(c, f"MOVE {' '.join(targets)}"),
        lambda c: send_command(c, "WAIT"),
    )


@app.command()
def send(
    command: str = typer.Argument(..., help="Raw command, e.g. 'SPEED 2000'"),
    port: str = PORT_OPTION,
) -> None:
    """Send one raw command and print the reply."""
    run_once(port, lambda c: send_command(c, command))


if __name__ == "__main__":
    app()
