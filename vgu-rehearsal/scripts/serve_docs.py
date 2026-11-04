#!/usr/bin/env python3
"""Read rendered Markdown and saved results through a loopback-only HTTP server.

Ordinary .md requests redirect to their rendered HTML, preserving relative assets.
Use ?raw=1 for the original UTF-8 source. No packages or internet are required.
"""
from __future__ import annotations
import argparse
from functools import partial
import html
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import mimetypes
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

PROJECT_ROOT=Path(__file__).resolve().parents[1]


def contained(path:Path,root:Path)->bool:
    try:path.resolve().relative_to(root.resolve());return True
    except (ValueError,OSError,RuntimeError):return False


class ReaderHandler(SimpleHTTPRequestHandler):
    def __init__(self,*args,root:Path,project_root:Path=PROJECT_ROOT,**kwargs):
        self.reader_root=root.resolve()
        self.project_root=project_root.resolve()
        super().__init__(*args,directory=str(self.reader_root),**kwargs)

    def end_headers(self):
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Cache-Control','no-store')
        super().end_headers()

    def _resolve(self):
        parsed=urlsplit(self.path)
        if parsed.scheme or parsed.netloc:raise ValueError('Use a path within the configured reading root.')
        decoded=unquote(parsed.path,errors='strict')
        if '\x00' in decoded or '\\' in decoded:raise ValueError('Invalid document path.')
        parts=Path(decoded.lstrip('/')).parts
        if '..' in parts:raise PermissionError('Parent-directory traversal is not allowed.')
        if any((p.startswith('.') and p!='.specify') or p=='__pycache__' for p in parts):
            raise PermissionError('Runtime and repository-internal files are not served.')
        path=(self.reader_root/decoded.lstrip('/')).resolve()
        if not contained(path,self.reader_root):raise PermissionError('The requested path escapes the configured reading root.')
        return path,parse_qs(parsed.query)

    def _url(self,path:Path):
        return '/'+quote(path.resolve().relative_to(self.reader_root).as_posix(),safe='/')

    def _redirect(self,path:Path):
        self.send_response(302)
        self.send_header('Location',self._url(path))
        self.send_header('Content-Length','0')
        self.end_headers()
        return None

    def _error(self,status:int,message:str):
        title='Document reader'
        index=self.project_root/'site/index.html'
        home=(f'<p><a href="{html.escape(self._url(index))}">Open the rendered reading index</a></p>'
              if contained(index,self.reader_root) and index.is_file() else '')
        body=(f'<!doctype html><html lang="en"><meta charset="utf-8"><title>{title}</title>'
              f'<h1>{title}</h1><p>{html.escape(message)}</p>{home}'
              '<p>For Markdown source, add <code>?raw=1</code>. Render the package pages before requesting a reading view.</p></html>').encode()
        self.send_response(status)
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Content-Length',str(len(body)))
        self.end_headers()
        if self.command!='HEAD':self.wfile.write(body)
        return None

    def _rendered(self,path:Path):
        candidates=[path.with_suffix('.html')]
        # The script's own package remains identifiable even when --root is wider.
        for package in (self.project_root,self.reader_root):
            if contained(path,package):
                candidates.append((package/'site'/path.relative_to(package)).with_suffix('.html'))
        for candidate in candidates:
            if contained(candidate,self.reader_root) and candidate.is_file():return candidate
        return None

    def send_head(self):
        try:path,query=self._resolve()
        except PermissionError as exc:return self._error(403,str(exc))
        except (ValueError,UnicodeError,OSError,RuntimeError):return self._error(400,'Invalid document path.')
        raw=query.get('raw',['0'])[0]=='1'
        if path.suffix.lower()=='.md' and not raw:
            rendered=self._rendered(path)
            if rendered:return self._redirect(rendered)
            return self._error(404,'No rendered HTML is available for this Markdown document.')
        if path.is_dir():
            index=path/'index.html'
            if index.is_file() and contained(index,self.reader_root):return self._redirect(index)
            if path==self.reader_root:
                for index in (self.reader_root/'site/index.html',self.project_root/'site/index.html'):
                    if contained(index,self.reader_root) and index.is_file():return self._redirect(index)
            return self._error(404,'This folder has no reading index. Directory listings are disabled.')
        if not path.is_file():return self._error(404,'The requested document is not present in the reading root.')
        try:handle=path.open('rb')
        except OSError:return self._error(404,'The requested document could not be opened.')
        content_type=mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        if path.suffix.lower()=='.md':content_type='text/plain; charset=utf-8'
        elif content_type.startswith('text/') or path.suffix.lower() in {'.json','.ipynb'}:
            content_type+='; charset=utf-8'
        self.send_response(200)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(path.stat().st_size))
        self.send_header('Last-Modified',self.date_time_string(path.stat().st_mtime))
        self.end_headers()
        return handle


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=PROJECT_ROOT,help='Reading root; defaults to this package. Paths outside it are refused.')
    parser.add_argument('--port',type=int,default=8766,help='Loopback port (default: 8766).')
    args=parser.parse_args()
    root=args.root.expanduser().resolve()
    if not root.is_dir():parser.error('--root must be an existing directory')
    if not 0<=args.port<=65535:parser.error('--port must be between 0 and 65535')
    handler=partial(ReaderHandler,root=root)
    with ThreadingHTTPServer(('127.0.0.1',args.port),handler) as server:
        port=server.server_address[1]
        print(f'Reader: http://127.0.0.1:{port}/',flush=True)
        print('Markdown opens as rendered HTML; ?raw=1 returns source. Press Ctrl+C to stop.',flush=True)
        try:server.serve_forever()
        except KeyboardInterrupt:pass

if __name__=='__main__':main()
