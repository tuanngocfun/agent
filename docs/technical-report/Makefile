PYTHON ?= python3
TECTONIC ?= tectonic
PDFLATEX ?= pdflatex

.PHONY: all tables check clean

all: report.pdf

tables:
	$(PYTHON) generate_tables.py
	$(PYTHON) generate_visual_tables.py

check:
	$(PYTHON) generate_tables.py --check
	$(PYTHON) generate_visual_tables.py --check

report.pdf: report.tex visual-results.tex generate_tables.py generate_visual_tables.py ../../evidence/run-summary.json ../../evidence/visual-evaluation-summary.json $(wildcard figures/*.pdf figures/*.png)
	$(PYTHON) generate_tables.py
	$(PYTHON) generate_visual_tables.py
	@if command -v "$(TECTONIC)" >/dev/null 2>&1; then \
		"$(TECTONIC)" --keep-logs report.tex; \
	elif command -v "$(PDFLATEX)" >/dev/null 2>&1; then \
		"$(PDFLATEX)" -interaction=nonstopmode -halt-on-error report.tex && \
		"$(PDFLATEX)" -interaction=nonstopmode -halt-on-error report.tex; \
	else \
		printf '%s\n' 'Install Tectonic or pdfLaTeX, or set TECTONIC=/absolute/path/to/tectonic'; \
		exit 1; \
	fi

clean:
	rm -f report.aux report.log report.out report.toc report.synctex.gz
