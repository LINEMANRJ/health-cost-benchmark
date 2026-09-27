.PHONY: install install-dev data pipeline dashboard test lint figures notebooks site all clean

PY ?= python

install:          ## Instala dependências de execução e o pacote
	$(PY) -m pip install -r requirements.txt && $(PY) -m pip install -e . --no-deps

install-dev:      ## Instala dependências de desenvolvimento
	$(PY) -m pip install -r requirements-dev.txt && $(PY) -m pip install -e . --no-deps

data:             ## Regera a base sintética
	$(PY) scripts/generate_synthetic_data.py

pipeline:         ## Executa o pipeline completo
	$(PY) -m hcb.pipeline

dashboard:        ## Abre o dashboard em http://localhost:8501
	streamlit run dashboard/app.py

test:             ## Testes unitários
	$(PY) -m pytest

lint:             ## Lint (ruff)
	ruff check .

figures:          ## Figuras estáticas do README
	$(PY) scripts/make_figures.py

notebooks:        ## Regera e executa os notebooks
	$(PY) scripts/build_notebooks.py

site:             ## Gera o site estático (GitHub Pages) em site/
	$(PY) scripts/build_site.py

all: pipeline test figures notebooks site

clean:
	rm -rf data/processed/* data/raw/*.csv .pytest_cache .ruff_cache
	touch data/processed/.gitkeep
