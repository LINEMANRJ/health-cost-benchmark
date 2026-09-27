import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_site  # noqa: E402


def test_build_site_generates_self_contained_page(tmp_path):
    index = build_site.build(tmp_path / "site")
    html = index.read_text(encoding="utf-8")
    assert html.count('class="plotly-graph-div"') == 6
    assert '<script src="plotly.min.js"></script>' in html
    assert (tmp_path / "site" / "plotly.min.js").stat().st_size > 1_000_000
    assert (tmp_path / "site" / ".nojekyll").exists()
    assert "BASE SINTÉTICA" in html
    for question in ["evoluem ao longo do tempo", "maior variação", "valores atípicos",
                     "diferenças relevantes entre regiões", "maior volume financeiro"]:
        assert question in html
