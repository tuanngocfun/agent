#!/usr/bin/env python3
"""Check the standalone HTML package without executing notebooks or external requests.

A Chromium runtime is required for the visual checks. Browser/cache locations may
be supplied through the normal environment; no host-specific paths are recorded.
"""
from pathlib import Path
from urllib.parse import urljoin,urlsplit,unquote,quote
from urllib.request import urlopen,Request
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
import hashlib,json,os,re,threading
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
SITE=ROOT/'site'
CAPTURES=Path(os.environ.get('REHEARSAL_BROWSER_CAPTURE_DIR',str(ROOT/'.runtime/browser-captures')))
CAPTURES.mkdir(parents=True,exist_ok=True)

def rel(path):return Path(path).resolve().relative_to(ROOT).as_posix()

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

class LocalHandler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT),**kwargs)
    def log_message(self,*args):pass
    def translate_path(self,path):
        if path.startswith('/vgu-rehearsal/'):path=path[len('/vgu-rehearsal'):]
        return super().translate_path(path)

server=ThreadingHTTPServer(('127.0.0.1',0),LocalHandler)
threading.Thread(target=server.serve_forever,daemon=True).start()
origin=f'http://127.0.0.1:{server.server_address[1]}/'

def web(path,prefix=''):return origin+prefix+quote(rel(path),safe='/')

def report_target(url,prefix=''):
    text=unquote(urlsplit(url).path).lstrip('/')
    return text.removeprefix(prefix)


def crawl(prefix=''):
    seen=set();errors=[];escapes=[];fragments=[]
    def check(url,source):
        base=url.split('#')[0]
        if prefix and not base.startswith(origin+prefix):escapes.append({'page':rel(source),'target':report_target(base)})
        if base in seen:return
        seen.add(base)
        try:
            with urlopen(Request(base,method='HEAD'),timeout=10) as response:
                if response.status!=200:errors.append({'page':rel(source),'target':report_target(base,prefix),'status':response.status})
        except Exception:errors.append({'page':rel(source),'target':report_target(base,prefix),'error':'Local HTTP target unavailable'})
    for page in SITE.rglob('*.html'):
        soup=BeautifulSoup(page.read_text(),'html.parser')
        for tag in soup.find_all(['a','img','link','script']):
            attr='href' if tag.name in {'a','link'} else 'src';value=tag.get(attr)
            if not value or value.startswith(('http:','https:','data:','mailto:','tel:','javascript:')):continue
            if Path(value.split('#')[0]).is_absolute():escapes.append({'page':rel(page),'reason':'Absolute navigation path'})
            full=urljoin(web(page,prefix),value);check(full,page)
            parsed=urlsplit(full)
            if parsed.fragment and parsed.path.endswith('.html'):
                dest=ROOT/report_target(full,prefix)
                if dest.exists():
                    other=BeautifulSoup(dest.read_text(),'html.parser')
                    if not other.find(id=unquote(parsed.fragment)) and not other.find(attrs={'name':unquote(parsed.fragment)}):fragments.append({'page':rel(page),'target':value})
    css=SITE/'assets/katex/katex.min.css'
    for value in re.findall(r'url\(([^)]+)\)',css.read_text()):check(urljoin(web(css,prefix),value.strip('"\'')),css)
    return {'unique_internal_http_targets':len(seen),'http_errors':errors,'links_escaping_package':escapes,'fragment_errors':fragments,'passed':not errors and not escapes and not fragments}


def browser_check(browser,path):
    page=browser.new_page(viewport={'width':1440,'height':1000});events=[];outside=[]
    page.on('pageerror',lambda error:events.append('Browser script error'))
    def route(request):
        if urlsplit(request.request.url).hostname=='127.0.0.1':request.continue_()
        else:outside.append('Unexpected external browser request');request.abort()
    page.route('http**/*',route)
    response=page.goto(web(path),wait_until='networkidle');page.evaluate('document.fonts.ready')
    page.screenshot(path=str(CAPTURES/(path.stem+'.png')))
    row={'path':rel(path),'http_status':response.status,'katex_equations':page.locator('.katex').count(),'math_errors':page.locator('.math-error,.katex-error').count(),'broken_image_count':page.locator('img').evaluate_all('xs=>xs.filter(x=>!x.complete||!x.naturalWidth).length'),'page_errors':events,'external_requests':outside,'body_overflow_px':page.evaluate('Math.max(0,document.documentElement.scrollWidth-innerWidth)')}
    if path.name.startswith('INSTRUCTOR_'):
        head=page.get_by_role('heading',name='T1.A: Derive and compute scaled dot-product attention (6/6)',exact=True)
        if head.count():head.scroll_into_view_if_needed();page.screenshot(path=str(CAPTURES/'solution-math.png'))
    page.goto(path.as_uri(),wait_until='load');page.evaluate('document.fonts.ready')
    row['file_view_math_errors']=page.locator('.math-error,.katex-error').count()
    if path.name.startswith('INSTRUCTOR_'):
        page.set_viewport_size({'width':390,'height':844});page.evaluate('document.fonts.ready')
        row['mobile_body_overflow_px']=page.evaluate('Math.max(0,document.documentElement.scrollWidth-innerWidth)')
        page.screenshot(path=str(CAPTURES/'solution-mobile.png'))
    page.close()
    return row

try:
    main=crawl();renamed=crawl('vgu-rehearsal/')
    renamed['method']='Same package mounted read-only under the vgu-rehearsal URL prefix; tests relative navigation, not a fresh dependency installation.'
    targets=[SITE/'index.html',SITE/'teaching/LECTURE_SCRIPT.html',SITE/'notebooks/01_Core_Attention_Worked.html',SITE/'notebooks/04_Optional_Image_to_Sequence_Worked.html',SITE/'reference/legacy_teaching_pack/docs/INSTRUCTOR_FULLY_WORKED_SOLUTIONS.html']
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
        rows=[browser_check(browser,path) for path in targets]
        page=browser.new_page();response=page.goto(web(targets[-1],'vgu-rehearsal/'),wait_until='networkidle');page.evaluate('document.fonts.ready')
        renamed['solution_math_equations']=page.locator('.katex').count();renamed['http_status']=response.status
        renamed['passed']=renamed['passed'] and response.status==200 and renamed['solution_math_equations']>0
        browser.close()
    build=json.loads((ROOT/'verification/document_browser_build.json').read_text())
    notebooks=[]
    for item in build['notebook_pages']:
        source=ROOT/item['source_path'];notebooks.append({'path':rel(source),'sha256':sha(source),'matches_rendered_source':sha(source)==item['source_sha256'],'code_sha256':item['code_sha256']})
    documents=[]
    for name in build['markdown_pages']:
        page=ROOT/name;source=ROOT/page.relative_to(SITE).with_suffix('.md');snapshot=page.with_suffix('.md')
        if source.exists():documents.append({'path':rel(source),'sha256':sha(source),'rendered_source_sha256':sha(snapshot),'matches_rendered_source':sha(source)==sha(snapshot)})
    browser_pass=all(row['http_status']==200 and not row['math_errors'] and not row['file_view_math_errors'] and not row['broken_image_count'] and not row['page_errors'] and not row['external_requests'] and not row['body_overflow_px'] and not row.get('mobile_body_overflow_px',0) for row in rows)
    result={'policy':'Standalone loopback HTTP, offline file viewing, blocked external browser requests and package-relative evidence; no notebook execution or modification. Screenshots are retained locally outside the distributed artifact.','html_pages_checked':len(list(SITE.rglob('*.html'))),'unique_internal_http_targets':main['unique_internal_http_targets'],'http_errors':main['http_errors'],'fragment_errors':main['fragment_errors'],'absolute_navigation_paths':main['links_escaping_package'],'renamed_package_check':renamed,'browser_checks':rows,'math_parse_errors':build['math_errors'],'unbundled_reference_count':len(build['unbundled_private_references']),'notebook_source_hashes':notebooks,'all_notebook_hashes_match':all(x['matches_rendered_source'] for x in notebooks),'document_source_hashes':documents,'all_document_sources_match':all(x['matches_rendered_source'] for x in documents),'katex_license':'site/assets/katex/LICENSE'}
    result['all_passed']=main['passed'] and renamed['passed'] and browser_pass and not build['math_errors'] and not build['unbundled_private_references'] and result['all_notebook_hashes_match'] and result['all_document_sources_match']
    (ROOT/'verification/document_browser_checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in {'browser_checks','notebook_source_hashes','document_source_hashes'}},ensure_ascii=False))
    if not result['all_passed']:raise SystemExit(1)
finally:server.shutdown();server.server_close()
