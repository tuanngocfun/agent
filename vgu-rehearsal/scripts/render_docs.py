#!/usr/bin/env python3
"""Build the standalone offline documentation browser.

No notebook is executed or rewritten. Private evidence and HR files are never copied.
Uses pinned KaTeX only at build time; generated pages need no CDN or JavaScript.
"""
from __future__ import annotations
import argparse, base64, hashlib, html, io, json, os, re, shutil, subprocess, sys, tarfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from urllib.request import urlopen
import mistune
import playwright
from bs4 import BeautifulSoup
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name, TextLexer

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT/'site'
KATEX_VERSION='0.19.1'
TOOLS=ROOT/'.tooling/katex'
PORTABLE_REFERENCE=ROOT/'reference/legacy_teaching_pack'
OLD_PACK=PORTABLE_REFERENCE
LEGACY_NAMES=['INSTRUCTOR_FULLY_WORKED_SOLUTIONS.md','STUDENT_ASSIGNMENT_HANDOUT.md','LECTURE_AND_SOURCE_LINKS.md']
NODE=Path(playwright.__file__).resolve().parent/'driver/node'
CSS='''
:root{color-scheme:light;--ink:#193044;--muted:#526574;--line:#dce4ea;--accent:#006a71}
*{box-sizing:border-box}body{margin:0;background:#f1f5f8;color:var(--ink);font:17px/1.65 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{background:#142d43;color:white;padding:18px 4vw}header a{color:#d4f6f2;text-decoration:none;margin-right:22px}
main{max-width:1120px;margin:24px auto 60px;background:white;padding:36px 44px;border:1px solid var(--line);border-radius:12px;min-width:0;overflow-wrap:anywhere}
h1{font-size:2rem;line-height:1.25}h2{margin-top:2em;border-top:1px solid var(--line);padding-top:1em}h3{margin-top:1.65em}a{color:var(--accent);overflow-wrap:anywhere}p,li{max-width:95ch}
pre{background:#f2f6f9;padding:16px;overflow:auto;border:1px solid var(--line);border-radius:6px;font:14px/1.6 ui-monospace,SFMono-Regular,Consolas,monospace}code{font:0.88em ui-monospace,SFMono-Regular,Consolas,monospace;background:#f2f6f9;padding:.1em .25em;border-radius:3px}pre code{padding:0}
table{border-collapse:collapse;width:100%;font-size:15px;margin:22px 0;display:block;overflow:auto}th,td{border:1px solid #d2dee7;padding:10px 13px;text-align:left;vertical-align:top;min-width:95px}th{background:#e7f0f5;font-weight:650}tr:nth-child(even){background:#f8fafb}img{max-width:100%;height:auto}blockquote{margin:20px 0;padding:10px 18px;background:#eef5fa;border-left:4px solid #63a1b8}.notice{padding:14px 18px;border-left:4px solid #bd8500;background:#fff8e3;margin:18px 0}.meta{font-size:14px;color:var(--muted)}.unbundled{color:#6b5d43;border-bottom:1px dotted #b8aa8e;cursor:help}.math-block{overflow-x:auto;padding:16px 0;max-width:100%}.katex-display{margin:.5em 0!important}.katex{display:inline-block;max-width:100%;overflow-x:auto;overflow-y:hidden;vertical-align:middle}code{overflow-wrap:anywhere;word-break:break-word}.cell{margin:22px 0}.cell-label{font:13px ui-monospace,monospace;color:#547080}.output pre{background:#f7fbf7;border-color:#c9dfcc}.error pre{background:#fff2ef;border-color:#efb5a8}.output figure{margin:18px 0}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px}.card{border:1px solid var(--line);padding:18px;border-radius:8px}.card h3{margin-top:0}.task-list-item{list-style:none}.codehilite{overflow:auto}footer{color:var(--muted);font-size:13px;padding-top:25px;border-top:1px solid var(--line)}
@media(max-width:700px){body{font-size:16px}main{margin:10px;padding:20px 16px}h1{font-size:1.6rem}header{padding:14px 16px}table{font-size:13px}pre{font-size:12px}}@media print{header,.download{display:none}body{background:white}main{border:0;margin:0;padding:0;max-width:none}pre,table,.math-block{overflow:visible}}
'''
REPORT={'generated_utc':datetime.now(timezone.utc).isoformat(),'katex_version':KATEX_VERSION,
        'markdown_pages':[],'notebook_pages':[],'legacy_pages':[],'math_errors':[],
        'unbundled_private_references':[],'copied_assets':[]}

def rel(path):
    return Path(path).resolve().relative_to(ROOT).as_posix()

def excluded(path):
    parts=Path(path).relative_to(ROOT).parts
    return any(x.endswith('_pages') or x in {'figures','document_browser','notebook_screenshots','notebook_images'} for x in parts) or Path(path).name.endswith('_contact.png')


def is_within(path, parent):
    try:path.resolve().relative_to(parent.resolve());return True
    except ValueError:return False


def href_to(target:Path, page:Path):
    return quote(os.path.relpath(target,page.parent).replace(os.sep,'/'),safe='/._-~')


def setup_katex(bootstrap=False):
    js=TOOLS/'dist/katex.js'
    if not js.exists():
        if not bootstrap:raise SystemExit('Missing offline math build tool. Run once with --bootstrap (downloads pinned KaTeX only).')
        TOOLS.mkdir(parents=True,exist_ok=True)
        url=f'https://registry.npmjs.org/katex/-/katex-{KATEX_VERSION}.tgz'
        payload=urlopen(url,timeout=60).read()
        (TOOLS/'download.json').write_text(json.dumps({'url':url,'sha256':hashlib.sha256(payload).hexdigest(),'bytes':len(payload)},indent=2)+'\n')
        with tarfile.open(fileobj=io.BytesIO(payload),mode='r:gz') as archive:
            for item in archive.getmembers():
                if not item.isfile():continue
                name=item.name.removeprefix('package/')
                if not (name.startswith('dist/') or name in {'LICENSE','README.md','package.json'}):continue
                dest=(TOOLS/name).resolve()
                if not is_within(dest,TOOLS):raise ValueError('Unsafe package path')
                dest.parent.mkdir(parents=True,exist_ok=True)
                with archive.extractfile(item) as f:dest.write_bytes(f.read())
    if not NODE.exists():raise SystemExit('Bundled Node runtime unavailable. Run with the installed project environment.')
    return js


def install_assets(output_root):
    a=output_root/'assets';a.mkdir(parents=True,exist_ok=True)
    (a/'docs.css').write_text(CSS+HtmlFormatter().get_style_defs('.codehilite'))
    dest=a/'katex';dest.mkdir(exist_ok=True)
    shutil.copy2(TOOLS/'dist/katex.min.css',dest/'katex.min.css')
    shutil.copytree(TOOLS/'dist/fonts',dest/'fonts',dirs_exist_ok=True)
    shutil.copy2(TOOLS/'LICENSE',dest/'LICENSE')


NODE_RENDER=r'''const fs=require('fs');const katex=require(process.argv[1]);
const input=JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(input.map(x=>{try{return {html:katex.renderToString(x.tex,{displayMode:x.display,throwOnError:true,strict:'ignore',trust:false,output:'htmlAndMathml'})};}catch(e){return {error:e.message,tex:x.tex};}})));'''


def render_math(items,source):
    if not items:return []
    proc=subprocess.run([str(NODE),'-e',NODE_RENDER,str(TOOLS/'dist/katex.js')],input=json.dumps(items),text=True,capture_output=True,check=True)
    answers=json.loads(proc.stdout)
    for answer in answers:
        if 'error' in answer:REPORT['math_errors'].append({'source':rel(source),'tex':answer['tex'],'error':answer['error']})
    return answers


class Renderer(mistune.HTMLRenderer):
    def block_code(self,code,info=None):
        try:lexer=get_lexer_by_name((info or 'text').split()[0])
        except Exception:lexer=TextLexer()
        return highlight(code,lexer,HtmlFormatter(cssclass='codehilite'))


MD=mistune.create_markdown(renderer=Renderer(escape=False),plugins=['table','task_lists','strikethrough','url'])


def math_markdown(text,source):
    # Protect code before replacing TeX. This also protects | inside table math.
    codes=[]
    def save_code(m):codes.append(m.group(0));return f'CODEPROTECTEDTOKEN{len(codes)-1}END'
    text=re.sub(r'(?ms)^(`{3,}|~{3,})[^\n]*\n.*?^\1[ \t]*$',save_code,text)
    text=re.sub(r'(`+)[^`]*?\1',save_code,text)
    items=[]
    def save_math(m,display):
        items.append({'tex':m.group(1).strip(),'display':display})
        token=f'MATHTYPESETTINGTOKEN{len(items)-1}END'
        return '\n\n'+token+'\n\n' if display else token
    text=re.sub(r'(?s)(?<!\\)\$\$(.+?)(?<!\\)\$\$',lambda m:save_math(m,True),text)
    text=re.sub(r'(?<![\\$])\$(?!\$)([^\n$]+?)(?<!\\)\$(?!\$)',lambda m:save_math(m,False),text)
    text=re.sub(r'(?s)\\\[(.+?)\\\]',lambda m:save_math(m,True),text)
    text=re.sub(r'\\\(([^\n]+?)\\\)',lambda m:save_math(m,False),text)
    for i,c in enumerate(codes):text=text.replace(f'CODEPROTECTEDTOKEN{i}END',c)
    out=MD(text)
    for i,answer in enumerate(render_math(items,source)):
        token=f'MATHTYPESETTINGTOKEN{i}END'
        result=answer.get('html','<span class="math-error">'+html.escape(answer.get('tex',''))+'</span>')
        if items[i]['display']:
            result='<div class="math-block">'+result+'</div>'
            out=out.replace('<p>'+token+'</p>',result)
        out=out.replace(token,result)
    return out


CANONICAL_MD=[]
for folder in [ROOT,ROOT/'teaching',ROOT/'research',ROOT/'interview',ROOT/'specs',ROOT/'verification',ROOT/'slides',ROOT/'notebooks/student_exercises']:
    if not folder.exists():continue
    iterator=folder.glob('*.md') if folder==ROOT else folder.rglob('*.md')
    CANONICAL_MD.extend(p for p in iterator if '.venv' not in p.parts and '/site/' not in str(p) and not (is_within(p,ROOT/'verification') and re.search(r'(github|git.?upload|upload.?evidence)',p.name,re.I)))
constitution=ROOT/'.specify/memory/constitution.md'
if constitution.exists():CANONICAL_MD.append(constitution)
CANONICAL_MD=sorted(set(CANONICAL_MD))
CANONICAL_NB=sorted((ROOT/'notebooks').glob('*.ipynb'))+sorted((ROOT/'notebooks/student_exercises').glob('*.ipynb'))
TARGETS={p.resolve():(SITE/p.relative_to(ROOT)).with_suffix('.html') for p in CANONICAL_MD+CANONICAL_NB}
for name in LEGACY_NAMES:TARGETS[(OLD_PACK/'docs'/name).resolve()]=SITE/'reference/legacy_teaching_pack/docs'/Path(name).with_suffix('.html')
SAFE_SUFFIX={'.pdf','.pptx','.png','.jpg','.jpeg','.svg','.gif','.py','.sh','.txt','.xml','.json','.code-workspace','.yaml','.yml','.toml','.ini','.cfg'}
SAFE_DIRS={'slides','scripts','src','tests','content','verification','specs','notebooks','configs'}


DIRECTORY_PAGES={}

def directory_page(source):
    if source.name=='notebook_html':return SITE/'notebooks/index.html'
    candidates=[source/'README.md',source/'index.md',source/'START_HERE.md']
    for p in candidates:
        if p.resolve() in TARGETS:return TARGETS[p.resolve()]
    if is_within(source,ROOT):
        dest=SITE/source.relative_to(ROOT)/'index.html'
        DIRECTORY_PAGES[dest]=source
        return dest
    return None


def resolve_url(raw,source,page,legacy=False):
    split=urlsplit(html.unescape(raw))
    if split.scheme in {'http','https','mailto','tel','data'} or raw.startswith('#'):return raw
    if split.scheme or not split.path:return None
    path=Path(unquote(split.path))
    original=(path if path.is_absolute() else source.parent/path).resolve()
    if is_within(original,ROOT) and excluded(original):return None
    if original==SITE/'index.html':return href_to(SITE/'index.html',page)
    if original in TARGETS:return href_to(TARGETS[original],page)+(('#'+quote(split.fragment,safe='-_.:')) if split.fragment else '')
    if original.is_dir() and is_within(original,ROOT):
        dest=directory_page(original);return href_to(dest,page) if dest else None
    # The old nbconvert preview links are routed to the new saved-output viewer.
    if original.suffix=='.html':
        nb=next((p for p in CANONICAL_NB if p.stem==original.stem),None)
        if nb:return href_to(TARGETS[nb.resolve()],page)
    if original.is_file() and is_within(original,ROOT) and (original.suffix.lower() in SAFE_SUFFIX or original.name=='LICENSE'):
        rel=original.relative_to(ROOT)
        if rel.parts[0] not in SAFE_DIRS and original.parent!=ROOT:return None
        # Keep large slide files only once. They travel inside this same package.
        return href_to(original,page)+(('#'+split.fragment) if split.fragment else '')
    return None


def rewrite_links(fragment,source,page,legacy=False):
    soup=BeautifulSoup(fragment,'html.parser')
    for tag in soup.find_all(['a','img']):
        attr='href' if tag.name=='a' else 'src';raw=tag.get(attr)
        if not raw:continue
        target=resolve_url(raw,source,page,legacy)
        if target is not None:tag[attr]=target
        elif tag.name=='a':
            replacement=soup.new_tag('span');replacement['class']='unbundled';replacement['title']='Private/local reference not bundled in this documentation browser.'
            replacement.string=tag.get_text()+' [private/local reference]';tag.replace_with(replacement)
            REPORT['unbundled_private_references'].append({'source':rel(source),'reason':'Reference is not in the standalone package; target omitted.'})
        else:
            tag.replace_with(soup.new_string('[Image reference unavailable in this portable copy: '+tag.get('alt','image')+']'))
    return str(soup)


def shell(title,body,page,assets_root=SITE,home=None,download=None,notice=''):
    home=home or SITE/'index.html'
    css=href_to(assets_root/'assets/docs.css',page);katex=href_to(assets_root/'assets/katex/katex.min.css',page)
    nav=f'<a href="{href_to(home,page)}">Rehearsal browser</a>'
    if assets_root==SITE:
        nav+=f'<a href="{href_to(SITE/"teaching/LECTURE_SCRIPT.html",page)}">Lecture</a><a href="{href_to(SITE/"research/RESEARCH_SCRIPT.html",page)}">Research</a><a href="{href_to(SITE/"notebooks/index.html",page)}">Worked notebooks</a>'
    download_html=f'<p class="download meta"><a href="{href_to(download,page)}" download>Download original source</a> · HTML is rendered for reading; notebook outputs are saved results.</p>' if download else ''
    return f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title><link rel="stylesheet" href="{css}"><link rel="stylesheet" href="{katex}"></head><body><header>{nav}</header><main>{notice}{download_html}{body}<footer>Local rehearsal materials · mathematics pre-rendered with KaTeX {KATEX_VERSION}; no network connection is needed to read these pages. Saved execution results do not certify human rehearsal or student understanding.</footer></main></body></html>'


def render_doc(source,page,legacy=False):
    text=source.read_text();body=math_markdown(text,source)
    body=rewrite_links(body,source,page,legacy)
    soup=BeautifulSoup(body,'html.parser')
    # Stable readable anchors for heading fragments.
    used=set()
    for h in soup.find_all(re.compile('^h[1-6]$')):
        if not h.get('id'):
            slug=re.sub(r'[^\w\s-]','',h.get_text().strip().lower());slug=re.sub(r'[\s-]+','-',slug)
            candidate=slug;i=1
            while candidate in used:i+=1;candidate=f'{slug}-{i}'
            h['id']=candidate;used.add(candidate)
    first=soup.find('h1');title=first.get_text() if first else source.stem.replace('_',' ')
    raw=page.with_suffix('.md');raw.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,raw)
    note=('<div class="notice"><strong>Legacy teaching reference.</strong> This renders the inherited document faithfully; working links and typeset equations do not validate every inherited scientific claim or task promise. Use the <a href="'+href_to(SITE/'index.html',page)+'">current rehearsal browser</a> and <a href="'+href_to(SITE/'START_HERE.html',page)+'">current start guide</a> for the corrected teaching scope, executed worked notebooks and evidence boundaries.</div>') if source.name in LEGACY_NAMES else ''
    assets=SITE
    home=SITE/'index.html'
    page.write_text(shell(title,str(soup),page,assets,home,raw,note))
    REPORT['markdown_pages'].append(rel(page))


def render_notebook(source,page,legacy=False):
    original=source.read_bytes();nb=json.loads(original);parts=[];code=0;outputs=0;errors=0
    for idx,c in enumerate(nb['cells']):
        text=''.join(c.get('source',[]))
        if c['cell_type']=='markdown':parts.append('<section class="cell markdown">'+rewrite_links(math_markdown(text,source),source,page,legacy)+'</section>')
        elif c['cell_type']=='code':
            code+=1;label=f'In [{c.get("execution_count") if c.get("execution_count") is not None else " "}]'
            parts.append('<section class="cell"><div class="cell-label">'+html.escape(label)+'</div>'+highlight(text,get_lexer_by_name('python'),HtmlFormatter(cssclass='codehilite')))
            for out in c.get('outputs',[]):
                outputs+=1;data=out.get('data',{});kind=out.get('output_type')
                if kind=='error':
                    errors+=1;msg=out.get('ename','Error')+': '+out.get('evalue','');parts.append('<div class="output error"><pre>'+html.escape(msg)+'</pre></div>')
                elif 'image/png' in data:
                    png=''.join(data['image/png']);parts.append('<div class="output"><figure><img alt="Saved notebook figure" src="data:image/png;base64,'+png+'"></figure></div>')
                elif 'image/svg+xml' in data:parts.append('<div class="output">'+''.join(data['image/svg+xml'])+'</div>')
                else:
                    value=out.get('text',data.get('text/plain',[]));value=''.join(value) if isinstance(value,list) else value
                    if value:parts.append('<div class="output"><pre>'+html.escape(value)+'</pre></div>')
            parts.append('</section>')
    page.parent.mkdir(parents=True,exist_ok=True)
    if not legacy:download=page.with_suffix('.ipynb');download.write_bytes(original)
    else:download=None
    meta=f'<p class="meta">Saved notebook view · {code} code cells · {outputs} saved output objects · {errors} error objects. This page does not execute code.</p>'
    notice=('<div class="notice"><strong>Legacy notebook snapshot.</strong> Rendering preserves the inherited source and saved results; it does not repair or certify every legacy code/content claim. Student TODO failures remain incomplete exercises. Use the <a href="'+href_to(SITE/'index.html',page)+'">current rehearsal browser</a> or <a href="'+href_to(SITE/'START_HERE.html',page)+'">current start guide</a> for the corrected rehearsable materials and separate learner tasks. Linked teaching Markdown now opens as HTML with offline mathematics.</div>') if legacy else ''
    page.write_text(shell(source.stem.replace('_',' '),meta+''.join(parts),page,SITE,None,download,notice))
    assert source.read_bytes()==original,'Notebook source or outputs changed unexpectedly'
    REPORT['legacy_pages' if legacy else 'notebook_pages'].append({'path':rel(page),'source_path':rel(source),'source_sha256':hashlib.sha256(original).hexdigest(),'code_sha256':hashlib.sha256('\n'.join(''.join(c.get('source',[])) for c in nb['cells'] if c['cell_type']=='code').encode()).hexdigest(),'notebook_unchanged':True,'code_cells':code,'outputs':outputs,'errors':errors})


def make_index():
    cards=[('30-minute lecture','teaching/LECTURE_SCRIPT.html','Read the timed lecture beside the PDF and worked examples.'),('20-minute research','research/RESEARCH_SCRIPT.html','Review supported group results and the proposed study.'),('Worked notebooks','notebooks/index.html','Inspect actual saved tensors, plots, generated outputs and errors.'),('Student pathway','teaching/STUDENT_PATHWAY.html','Follow prerequisites, independent tasks and optional projects.'),('Interview Q&A','interview/INTERVIEW_QA.html','Practice explanations and prepare factual personal answers.'),('Fully worked legacy reference','reference/legacy_teaching_pack/docs/INSTRUCTOR_FULLY_WORKED_SOLUTIONS.html','Read the inherited long mathematical derivations with offline typesetting.')]
    body='<h1>VGU rehearsal browser</h1><p>Read the teaching materials, equations and saved notebook results in one local browser. Start with the lecture, then rehearse the research orientation. The files below are the current corrected rehearsal package; legacy references are labelled.</p><div class="cards">'
    for title,url,desc in cards:body+=f'<article class="card"><h3><a href="{url}">{title}</a></h3><p>{desc}</p></article>'
    body+='</div><h2>Start and present</h2><ul><li><a href="START_HERE.html">Full start guide and requirement evidence</a></li><li><a href="../slides/Trial_Lecture_30min.pdf">Lecture PDF</a> · <a href="../slides/Trial_Lecture_30min.pptx">PowerPoint with notes</a></li><li><a href="../slides/Research_Orientation_20min.pdf">Research PDF</a> · <a href="../slides/Research_Orientation_20min.pptx">PowerPoint with notes</a></li><li><a href="interview/SUBMISSION_CHECKLIST.html">Personal rehearsal checklist</a></li></ul><div class="notice">Personal certificates, HR forms and private evidence scans are not bundled in this browser. Those records and their local filenames are omitted from this export. No message or submission has been sent.</div>'
    (SITE/'index.html').write_text(shell('VGU rehearsal browser',body,SITE/'index.html'))


def make_directory_indexes(root):
    for page,source in DIRECTORY_PAGES.items():
        if page.exists():continue
        page.parent.mkdir(parents=True,exist_ok=True);entries=[]
        for child in sorted(source.iterdir()):
            if excluded(child) or not child.is_file() or child.name.startswith('.') or child.suffix.lower() not in SAFE_SUFFIX|{'.ipynb','.md','.html'}:continue
            target=TARGETS.get(child.resolve(),child)
            entries.append(f'<li><a href="{href_to(target,page)}">{html.escape(child.name)}</a></li>')
        page.write_text(shell(source.name.replace('_',' '),f'<h1>{html.escape(source.name.replace("_"," "))}</h1><ul>'+''.join(entries)+'</ul>',page))
    folders={p.parent for p in root.rglob('*') if p.is_file() and 'assets' not in p.parts}
    for folder in sorted(folders,key=lambda p:len(p.parts),reverse=True):
        page=folder/'index.html'
        if page.exists():continue
        entries=[]
        for p in sorted(folder.iterdir()):
            if p.name.startswith('.') or p.name=='index.html':continue
            dest=p/'index.html' if p.is_dir() else p
            if dest.exists():entries.append(f'<li><a href="{href_to(dest,page)}">{html.escape(p.name)}</a></li>')
        page.write_text(shell(folder.name.replace('_',' '),f'<h1>{html.escape(folder.name.replace("_"," "))}</h1><ul>'+''.join(entries)+'</ul>',page))


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--bootstrap',action='store_true');ap.add_argument('--skip-legacy',action='store_true');args=ap.parse_args()
    setup_katex(args.bootstrap)
    if SITE.exists():shutil.rmtree(SITE)
    SITE.mkdir();install_assets(SITE)
    for source in CANONICAL_MD:render_doc(source,TARGETS[source.resolve()])
    for source in CANONICAL_NB:render_notebook(source,TARGETS[source.resolve()])
    for name in LEGACY_NAMES:render_doc(OLD_PACK/'docs'/name,TARGETS[(OLD_PACK/'docs'/name).resolve()])
    make_index();make_directory_indexes(SITE)
    out=ROOT/'verification/document_browser_build.json';out.write_text(json.dumps(REPORT,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'site':'site/index.html','markdown_pages':len(REPORT['markdown_pages']),'canonical_notebooks':len(REPORT['notebook_pages']),'legacy_notebooks':len(REPORT['legacy_pages']),'math_errors':len(REPORT['math_errors']),'unbundled_private_references':len(REPORT['unbundled_private_references']),'report':'verification/document_browser_build.json'},ensure_ascii=False))
    if REPORT['math_errors']:
        print(json.dumps(REPORT['math_errors'],ensure_ascii=False,indent=2));raise SystemExit(1)
if __name__=='__main__':main()
