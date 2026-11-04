# Checks on the repository export

The clean export was independently rebuilt after private machine/evidence metadata was removed. The original full audit remains outside this repository copy.

Four worked notebooks executed in fresh kernels with allow_errors=False: 22 code cells, 27 saved output objects, two embedded figures and zero errors. Their only code change from the local teaching examples is the source-location display: it prints a package-relative path. The actual import-location assertion remains. Separate student exercises executed with four and three expected NotImplementedError outputs; machine-specific traceback paths were omitted while error names/messages and incomplete labels remain.

The portable check inspected saved notebook outputs, two deck/source/notes combinations, the current project kernel and reference implementation tests. All 18 behavioral tests passed. The two regenerated decks have 14 and 12 slides allocated to 30 and 20 minutes. Script paragraphs match their JSON presenter notes. Public source links replace private evidence paths. PDF file annotations and PPTX package XML are inspected separately for local-file targets.

Browser link/math checks are recorded in document_browser_checks.json after the final HTML build. Bundled KaTeX CSS/fonts retain their MIT license. These checks do not prove personal history, actual spoken timing, student comprehension or application submission. The project-local build reused the installed Linux CPU environment; a fresh dependency download/install on another machine was not tested.
