import typer

app = typer.Typer(name="cleanroom", help="Agentic Cleanroom CLI")


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
