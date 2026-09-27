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


def _fake_pyodide(tmp_path):
    import json

    d = tmp_path / "pyodide"
    d.mkdir()
    lock = {"packages": {
        "pandas": {"file_name": "pandas.whl", "depends": ["numpy", "six"]},
        "scipy": {"file_name": "scipy.whl", "depends": ["numpy"]},
        "numpy": {"file_name": "numpy.whl", "depends": []},
        "six": {"file_name": "six.whl", "depends": []},
        "astropy": {"file_name": "astropy.whl", "depends": []},
    }}
    (d / "pyodide-lock.json").write_text(json.dumps(lock), encoding="utf-8")
    for name in build_site.PYODIDE_CORE[:-1] + ["pandas.whl", "scipy.whl", "numpy.whl", "six.whl", "astropy.whl"]:
        (d / name).write_bytes(b"x")
    return d


def test_build_site_with_chat(tmp_path):
    import zipfile

    out = tmp_path / "site"
    index = build_site.build(out, _fake_pyodide(tmp_path))
    html = index.read_text(encoding="utf-8")
    assert 'id="chat-app"' in html and '<script src="chat.js" defer></script>' in html
    assert "connect-src 'self' https://api.anthropic.com https://api.cohere.com" in html
    wheels = sorted(p.name for p in (out / "pyodide").glob("*.whl"))
    assert wheels == ["numpy.whl", "pandas.whl", "scipy.whl", "six.whl"]  # só o necessário
    names = zipfile.ZipFile(out / "py" / "hcb.zip").namelist()
    assert "hcb/ai/tools.py" in names and "hcb/ai/grounding.py" in names
    assert (out / "py" / "bridge.py").exists() and (out / "data" / "fato_internacoes.csv").exists()
    assert (out / "chat.js").stat().st_size > 1000


def test_build_site_without_chat_has_fallback_note(tmp_path):
    html = build_site.build(tmp_path / "site").read_text(encoding="utf-8")
    assert 'id="chat-app"' not in html and "chat não foi incluído" in html
