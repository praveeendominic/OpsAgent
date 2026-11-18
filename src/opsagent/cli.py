"""OpsAgent command line. `python -m opsagent --help`."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console

# CrewAI prints emoji in its event banners; Windows consoles default to a code page that cannot encode them.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

app = typer.Typer(no_args_is_help=True, add_completion=False, help="OpsAgent: agentic L1/L2 incident response (PoC)")
kb_app = typer.Typer(no_args_is_help=True, help="Knowledge base commands")
app.add_typer(kb_app, name="kb")
console = Console()


@app.command()
def run(
    event: Path = typer.Option(Path("events/log_event.json"), "--event", "-e", help="raw-1.0 event file"),
    force: bool = typer.Option(False, "--force", help="ignore the de-duplication window"),
) -> None:
    """Run the IncidentFlow on one raw-1.0 event."""
    from opsagent.flow.incident_flow import run_event

    result = run_event(event, force=force)
    console.print_json(json.dumps(result, default=str))


@app.command()
def smoke() -> None:
    """One cheap call to the Azure OpenAI deployment."""
    from opsagent.llm import smoke_test

    console.print(f"model replied: {smoke_test()!r}")


@app.command()
def plot(out: Path = typer.Option(Path("docs/flow-plot/incident_flow.html"), "--out")) -> None:
    """Render the real IncidentFlow with CrewAI's Flow.plot()."""
    from opsagent.flow.incident_flow import IncidentFlow

    import shutil

    out.parent.mkdir(parents=True, exist_ok=True)
    # crewai 1.x renders into a temp folder (html + css + js); copy the set next to the requested name
    produced = Path(IncidentFlow().plot(out.name, show=False))
    for f in produced.parent.iterdir():
        shutil.copy(f, out.parent / f.name)
    console.print(f"plot written: {out.parent / produced.name}")


@app.command()
def ui(port: int = typer.Option(8501, "--port")) -> None:
    """Start the Streamlit run recorder UI."""
    import subprocess
    import sys

    from opsagent.config import PACKAGE_ROOT

    subprocess.run([sys.executable, "-m", "streamlit", "run", str(PACKAGE_ROOT / "ui" / "app.py"),
                    "--server.port", str(port), "--server.headless", "true"], check=False)


@app.command()
def traces(port: int = typer.Option(5000, "--port")) -> None:
    """Start the MLflow UI on the incident traces (needs OPSAGENT_MLFLOW=1 for runs to be traced)."""
    import subprocess

    from opsagent.config import get_settings

    s = get_settings()
    if s.mlflow_uri.startswith(("http://", "https://")):
        console.print(f"traces are on the MLflow server: {s.mlflow_uri} (experiment {s.mlflow_experiment})")
        return
    if not s.mlflow_tracing:
        console.print("OPSAGENT_MLFLOW is off: runs are not traced until it is set to 1 in .env")
    # one worker: a local viewer needs no more, and uvicorn's worker processes fail to spawn on some Windows setups
    subprocess.run([sys.executable, "-m", "mlflow", "ui", "--backend-store-uri", s.mlflow_uri, "--port", str(port),
                    "--workers", "1"], check=False)


@app.command()
def runs() -> None:
    """List recorded runs."""
    from opsagent.tracing import list_runs

    for r in list_runs():
        t = r.get("totals", {})
        console.print(f"{r['incident_id']}  {r.get('status')}  stage1={r.get('timings', {}).get('stage1')}s "
                      f"stage2={r.get('timings', {}).get('stage2')}s  tokens={t.get('total_tokens')}  cost=${t.get('cost_usd')}")


@kb_app.command("build")
def kb_build() -> None:
    """Ingest the bundled docs into the FAISS knowledge base."""
    from opsagent.kb.ingest import build_docs_index

    n = build_docs_index()
    console.print(f"knowledge base built: {n} chunks")


@kb_app.command("search")
def kb_search(query: str, k: int = 5, namespace: str = "docs") -> None:
    from opsagent.kb.store import get_store

    for hit in get_store().search(query, k=k, namespace=namespace):
        console.print(f"[bold]{hit.score:.3f}[/bold] {hit.title}  ({hit.source})\n  {hit.text[:200]}...")


@kb_app.command("label")
def kb_label(incident_id: str, label: str = typer.Argument(..., help="accepted | partially_correct | wrong"),
             by: str = typer.Option("l2-oncall", "--by")) -> None:
    """Attach the human label to a closed incident's knowledge record."""
    from opsagent.kb.incidents import label_incident

    rec = label_incident(incident_id, label, by)
    console.print(f"{rec.incident_id} labelled {rec.label} by {rec.labelled_by}")


if __name__ == "__main__":
    app()
