from pathlib import Path

import typer

from src.cleanroom.agents.spec_agent.agent import SpecAgent

app = typer.Typer(help="Extract structured spec from an SRS document.")


@app.command()
def extract(
    srs_file: Path = typer.Argument(..., help="Path to the SRS XML file"),
    output: Path = typer.Option(Path("outputs"), help="Directory to write the extracted spec JSON"),
) -> None:
    agent = SpecAgent()
    ir = agent.run(srs_path=srs_file, output_dir=output)
    typer.echo(f"Project: {ir.project_name}")
    typer.echo(f"Features: {len(ir.features)}")
    typer.echo(f"Spec written to {output}/{srs_file.stem}_ir.json")
