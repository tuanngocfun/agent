# Read the materials in a browser

Open [Present this lecture](PRESENT_THIS.md) for delivery, or its rendered page at `site/PRESENT_THIS.html`.
The wider [reading library](site/index.html) provides lecture/research scripts, technical prompts
and saved notebook outputs. Tables, code, equations and fonts are bundled for offline reading.

From the package directory, you can also start a loopback-only server:

```bash
python3 scripts/serve_docs.py
```

Open `http://127.0.0.1:8766/site/PRESENT_THIS.html`. Keep the full package together so links to PDFs,
PowerPoint files, notebooks and local assets continue to work. Use HTML links for reading;
Markdown-source downloads are provided separately.

All eight current notebooks are completed references. The two historical `Student` filenames
also contain complete examples. Independent learner tasks are in
[Student practice](teaching/STUDENT_PRACTICE.md); they are not deliberate error cells in a
presentation notebook. The main delivery route links the completed instructor demonstrations.

## Clone and run code

```bash
git clone --branch codex/vgu-rehearsal-2026-11-04 --single-branch https://github.com/tuanngocfun/agent.git
cd agent/vgu-rehearsal
```

For the Linux/WSL CPU environment, have `uv` or Python 3.12 with `venv` support, then run:

```bash
bash scripts/setup_environment.sh
.venv/bin/python scripts/check_portable.py
bash scripts/open_jupyter.sh
```

Setup installs the pinned dependencies and dynamically registers **VGU rehearsal (CPU)** for the
current folder. Open `VGU_Rehearsal.code-workspace` for the relative interpreter setting.
Environments, project-local kernels and caches are deliberately excluded from Git.

The portable check reads saved outputs and runs packaged reference tests. It does not rerun
notebooks, update their execution manifests or certify human understanding. Read
[PUBLICATION_SCOPE.md](PUBLICATION_SCOPE.md) for the export boundary.

## Rebuild the reading pages

After environment setup, rebuild with:

```bash
.venv/bin/python scripts/render_docs.py --bootstrap
```

The first build obtains pinned KaTeX for build-time typesetting. Generated pages use bundled
assets and need no CDN requests; their KaTeX license is included with the assets. Rebuilding
HTML does not execute notebooks. A browser automation check may require its own installed
browser runtime; that is separate from reading the already generated pages.

No private application records, contact instructions, private evidence filenames or original
machine audit are part of this export. Administrative arrangements and any submission remain
the presenter's own actions.

## Read Markdown as formatted documents

Use `python3 scripts/serve_docs.py` for HackMD-style reading. Open
`http://127.0.0.1:8766/site/PRESENT_THIS.html` for the lecture, or `site/index.html` for the library. Requests ending in `.md` redirect to the
matching rendered HTML, so equations, tables, code and relative assets display correctly.
Add `?raw=1` when you want the original Markdown text; source-download buttons use that query.

The server uses only Python’s standard library and binds to `127.0.0.1`. It serves this package
by default. For an older exported URL beneath a wider folder, pass `--root <reading-root>` and
keep the URL path relative to that root. A Markdown file in an existing HTML export opens its
sibling HTML page. Requests outside the chosen root and symlink escapes are refused.

If a Markdown page has no rendered counterpart, the server explains how to open the reading
index or request raw source. Rebuild the pages after editing documents. Press Ctrl+C to stop.
