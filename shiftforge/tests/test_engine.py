from pathlib import Path
from shiftforge.engine import ConversionEngine


def test_project_conversion_is_dry_run(tmp_path: Path):
    root = tmp_path / "dbt"
    (root / "models").mkdir(parents=True)
    (root / "models" / "x.sql").write_text("SELECT * FROM `a.b.c`")
    report = ConversionEngine().convert_project(root, write=False)
    assert report.models_discovered == 1
    assert not Path(report.results[0].output_path).exists()
