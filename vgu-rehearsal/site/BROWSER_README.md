# Read the materials in a browser

Open [site/index.html](site/index.html) with Live Server or directly in a browser. It provides
rendered lecture/research scripts, technical prompts and saved notebook outputs. Tables, code,
equations and fonts are bundled for offline reading.

From the package directory, you can also start a loopback-only server:

```bash
python3 -m http.server 8766 --bind 127.0.0.1
```

Open `http://127.0.0.1:8766/site/index.html`. Keep the full package together so links to PDFs,
PowerPoint files, notebooks and local assets continue to work. Use HTML links for reading;
Markdown-source downloads are provided separately.

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
