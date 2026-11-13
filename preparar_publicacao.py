"""Create an isolated copy of the site and its public data."""
import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def prepare(destination):
    manifest = json.loads((ROOT / "outputs/manifest.json").read_text(encoding="utf-8"))
    years = [entry["year"] for entry in manifest["years"]]
    if not years:
        raise ValueError("O manifesto precisa conter pelo menos um ano.")

    files = [
        "app.py", "main.py", "config.json", "requirements.txt", "vercel.json",
        "preparar_publicacao.py", ".github/workflows/atualizar-mapas.yml",
        "data/processed/bairros.geojson", "data/processed/grid.json",
        "outputs/manifest.json", "outputs/metrics.json",
    ]
    files.extend(str(path.relative_to(ROOT)) for folder in ("web", "src")
                 for path in (ROOT / folder).rglob("*")
                 if path.is_file() and path.suffix in {".html", ".js", ".css", ".svg", ".png", ".txt", ".py"})
    for year in years:
        files.extend([f"data/processed/{year}.npz", f"outputs/bairros_{year}.csv"])
        files.extend(f"outputs/maps/{year}_{layer}.{extension}"
                     for layer in ("temperature", "ndvi", "anomaly", "predicted")
                     for extension in ("png", "tif"))
    for name in files:
        if not (ROOT / name).is_file():
            raise FileNotFoundError(name)
    destination.mkdir(parents=True)
    for name in files:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    shutil.copy2(ROOT / ("requirements-processing.txt" if (ROOT / "requirements-processing.txt").exists()
                         else "requirements.txt"), destination / "requirements-processing.txt")
    (destination / "requirements.txt").write_text(
        "Flask>=3.1,<4\nrequests>=2.32,<3\nnumpy>=2.2,<3\npyproj>=3.7,<4\naffine>=2.4,<4\n",
        encoding="utf-8",
    )
    shutil.copytree(destination / "web", destination / "public/static",
                    ignore=shutil.ignore_patterns("index.html"))
    (destination / ".gitignore").write_text(
        ".vercel/\n.env*\n.venv/\n__pycache__/\ndata/raw/\noutputs/models/\n",
        encoding="utf-8",
    )
    (destination / ".vercelignore").write_text(
        ".github/\n.venv/\n__pycache__/\nmain.py\nsrc/pipeline.py\npreparar_publicacao.py\nrequirements-processing.txt\n"
        "data/raw/\noutputs/models/\noutputs/validation_predictions.csv\n",
        encoding="utf-8",
    )
    print(f"Cópia pronta: {destination} ({len(years)} anos)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    prepare(parser.parse_args().destination.resolve())
