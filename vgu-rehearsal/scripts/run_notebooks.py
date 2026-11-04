"""Strictly execute canonical WORKED notebooks and save actual outputs in place."""
from __future__ import annotations
import hashlib,json,os,sys,time
from datetime import datetime,timezone
from pathlib import Path
import nbformat
from nbclient import NotebookClient

ROOT=Path(__file__).resolve().parents[1]
NOTEBOOKS=ROOT/'notebooks'
VERIFY=ROOT/'verification'


def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def code_text(nb):return [c.source for c in nb.cells if c.cell_type=='code']


def main():
    VERIFY.mkdir(exist_ok=True)
    runtime=ROOT/'.runtime'
    runtime.mkdir(parents=True,exist_ok=True)
    (runtime/'ipython').mkdir(parents=True,exist_ok=True)
    kernel=ROOT/'.jupyter/kernels/vgu-rehearsal'
    kernel.mkdir(parents=True,exist_ok=True)
    (kernel/'kernel.json').write_text(json.dumps({'argv':[sys.executable,'-m','ipykernel_launcher','-f','{connection_file}'],
        'display_name':'VGU rehearsal (CPU)','language':'python'},indent=2)+'\n')
    os.environ.update({'JUPYTER_PATH':str(ROOT/'.jupyter'),'JUPYTER_RUNTIME_DIR':str(runtime),
       'IPYTHONDIR':str(ROOT/'.runtime/ipython'),'MPLCONFIGDIR':str(ROOT/'.cache/matplotlib'),'TORCH_HOME':str(ROOT/'.cache/torch'),
       'PYTHONDONTWRITEBYTECODE':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'})
    paths=sorted(NOTEBOOKS.glob('*_Worked.ipynb'))
    if len(paths)!=4:raise RuntimeError(f'Expected four worked notebooks, got {len(paths)}')
    rows=[]
    for p in paths:
        start=time.perf_counter();nb=nbformat.read(p,as_version=4);sources=code_text(nb)
        before=digest(p)
        for c in nb.cells:
            if c.cell_type=='code':c.outputs=[];c.execution_count=None
        error=None
        try:
            NotebookClient(nb,timeout=180,kernel_name='vgu-rehearsal',allow_errors=False,
                           resources={'metadata':{'path':str(NOTEBOOKS)}}).execute()
        except Exception as exc:error={'type':type(exc).__name__,'message':str(exc)}
        if code_text(nb)!=sources:raise RuntimeError(f'Code changed: {p}')
        cells=[]
        for i,c in enumerate(nb.cells):
            if c.cell_type!='code':continue
            outputs=c.get('outputs',[])
            cells.append({'cell_index':i,'execution_count':c.execution_count,
                          'output_count':len(outputs),'output_types':[o.output_type for o in outputs],
                          'errors':[{'ename':o.ename,'evalue':o.evalue} for o in outputs if o.output_type=='error'],
                          'text_outputs':[o.text for o in outputs if o.output_type=='stream'],
                          'image_output_count':sum('image/png' in o.get('data',{}) for o in outputs)})
        complete=error is None and all(c['execution_count'] is not None and not c['errors'] for c in cells)
        status='PASS: fresh instructor execution' if complete else 'FAIL: incomplete execution; inspect errors'
        first=nb.cells[0].source
        marker='<!-- canonical-execution-status:end -->'
        if marker in first:first=first.split(marker,1)[1].lstrip('\n')
        nb.cells[0].source=(f'**{status}.** All saved outputs below came from this notebook\'s actual code. '
          f'Run UTC: `{datetime.now(timezone.utc).isoformat()}`; '
          f'executed {sum(c["execution_count"] is not None for c in cells)}/{len(cells)} code cells; '
          f'{sum(c["output_count"] for c in cells)} output objects. '
          f'This validates the displayed computations; the described synthetic scope still applies.\n{marker}\n\n'+first)
        nbformat.validate(nb);nbformat.write(nb,p)
        saved=nbformat.read(p,as_version=4)
        if code_text(saved)!=sources:raise RuntimeError(f'Saved code changed: {p}')
        assert [[dict(o) for o in c.get('outputs',[])] for c in saved.cells if c.cell_type=='code']==[[dict(o) for o in c.get('outputs',[])] for c in nb.cells if c.cell_type=='code']
        rows.append({'path':str(p),'status':'pass' if complete else 'fail','allow_errors':False,
          'sha256_before':before,'sha256_after':digest(p),'code_unchanged':True,'saved_outputs_verified':True,
          'code_cells':len(cells),'executed_code_cells':sum(c['execution_count'] is not None for c in cells),
          'output_count':sum(c['output_count'] for c in cells),'image_output_count':sum(c['image_output_count'] for c in cells),
          'errors':error,'elapsed_s':round(time.perf_counter()-start,3),'per_cell':cells})
        manifest={'python_executable':sys.executable,'python_version':sys.version,
          'policy':'Fresh independent kernel per instructor notebook; allow_errors=False; original code preserved; outputs saved at linked original canonical paths; student exercises excluded and incomplete.',
          'notebooks':rows}
        (VERIFY/'notebook_execution.json').write_text(json.dumps(manifest,indent=2)+'\n')
        print(status,p.name,'cells',rows[-1]['executed_code_cells'],'outputs',rows[-1]['output_count'],flush=True)
    return int(any(r['status']!='pass' for r in rows))

if __name__=='__main__':raise SystemExit(main())
