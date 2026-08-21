import tomllib
from pathlib import Path

import typer

_config_file = Path(__file__).parent.parent / "pyproject.toml"
with _config_file.open("rb") as f:
    _config = tomllib.load(f)

_project_config = _config["project"]

PROJECT_NAME = _project_config["name"]
PROJECT_VERSION = _project_config["version"]


def config_cli(
    all: bool = typer.Option(False, "--all", help="Show all configuration values"),
    project_name: bool = typer.Option(False, "--project-name", help=PROJECT_NAME),
    project_version: bool = typer.Option(False, "--project-version", help=PROJECT_VERSION),
) -> None:
    """Expose non-secret configuration defined in pyproject.toml.

    See docs/CONFIGURATION.md for details on adding new options.
    """
    if all:
        typer.echo(f"project_name={PROJECT_NAME}")
        typer.echo(f"project_version={PROJECT_VERSION}")
        return

    param_map = {
        project_name: PROJECT_NAME,
        project_version: PROJECT_VERSION,
    }

    for is_set, value in param_map.items():
        if is_set:
            typer.echo(value)
            return

    typer.secho(
        "Error: No config key specified. Use --help to see available options.",
        fg=typer.colors.RED,
        err=True,
    )
    raise typer.Exit(1)


def main():
    typer.run(config_cli)


if __name__ == "__main__":
    main()
