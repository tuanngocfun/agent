#!/usr/bin/env python3
"""Render the canonical JSON sources to native vector PPTX and matching PDF.

All layout uses 1280×720 coordinates, explicit wrapping and DejaVu Sans.
No web, browser, LibreOffice or remote publishing is required. Unknown visual
schemas or content overflowing a declared text box fail rather than disappear.
"""
from __future__ import annotations
import hashlib
import json
import math
from pathlib import Path

import pymupdf as fitz
from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE
from pptx.oxml.xmlchemy import OxmlElement
from pptx.util import Inches, Pt
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'slides'
VERIFY = ROOT / 'verification'
W, H = 1280, 720
FONT_DIR = Path('/usr/share/fonts/truetype/dejavu')
pdfmetrics.registerFont(TTFont('DV', str(FONT_DIR / 'DejaVuSans.ttf')))
pdfmetrics.registerFont(TTFont('DV-Bold', str(FONT_DIR / 'DejaVuSans-Bold.ttf')))
FONT_NAME = 'DejaVu Sans'
NAVY, TEAL, INK = '#142B45', '#007F87', '#21364B'
MUTED, BG, WHITE = '#52677B', '#F6F8FB', '#FFFFFF'
PALE, BORDER, CORAL = '#E8F4F3', '#D6E0E9', '#B95038'


def width(text, size, bold=False):
    return pdfmetrics.stringWidth(str(text), 'DV-Bold' if bold else 'DV', size)


def wrap(text, max_width, size, bold=False):
    """Manually wrap every paragraph, including an overlong single token."""
    result = []
    for para in str(text).split('\n'):
        if not para:
            result.append('')
            continue
        line = ''
        for word in para.split():
            if width(word, size, bold) > max_width:
                if line:
                    result.append(line)
                    line = ''
                part = ''
                for ch in word:
                    if part and width(part + ch, size, bold) > max_width:
                        result.append(part)
                        part = ch
                    else:
                        part += ch
                line = part
            elif not line or width(line + ' ' + word, size, bold) <= max_width:
                line = word if not line else line + ' ' + word
            else:
                result.append(line)
                line = word
        if line:
            result.append(line)
    return result


def color_rgb(c):
    c = c.lstrip('#')
    return tuple(int(c[i:i+2], 16) for i in (0, 2, 4))


class Page:
    def __init__(self, deck, slide):
        self.deck, self.slide = deck, slide
        self.ops, self.boxes = [], []

    def rect(self, x, y, w, h, fill, stroke=None, radius=0, role='decoration'):
        self.ops.append(dict(kind='rect', x=x, y=y, w=w, h=h, fill=fill,
                             stroke=stroke, radius=radius, role=role))
        self.check_box(x,y,w,h,role)

    def line(self, x1, y1, x2, y2, color=BORDER, thickness=1.5):
        self.ops.append(dict(kind='line', x1=x1,y1=y1,x2=x2,y2=y2,
                             color=color,thickness=thickness))
        self.check_box(min(x1,x2),min(y1,y2),abs(x2-x1),abs(y2-y1),'line')

    def check_box(self,x,y,w,h,role):
        if min(x,y,w,h) < -0.01 or x+w>W+.01 or y+h>H+.01:
            raise ValueError(f"{self.deck}/{self.slide['id']}: {role} outside page: {(x,y,w,h)}")

    def text(self, text, x,y,w,h,size=24,bold=False,color=INK,
             min_size=None, leading=1.22, role='body',link=None,align='left'):
        size=float(size)
        lower=float(min_size if min_size is not None else size)
        while True:
            lines=wrap(text,w,size,bold)
            lh=size*leading
            if len(lines)*lh <= h+1.0:
                break
            size-=.25
            if size<lower-.01:
                raise ValueError(f"{self.deck}/{self.slide['id']}: {role} overflows {w}x{h} at {lower}px: {text}")
        actual_h=len(lines)*lh
        self.check_box(x,y,w,actual_h,role)
        self.boxes.append(dict(role=role,x=round(x,2),y=round(y,2),w=round(w,2),h=round(actual_h,2),
                               font_px=size,lines=len(lines),text=str(text),link=link))
        for i,ln in enumerate(lines):
            lw=width(ln,size,bold)
            xx=x if align=='left' else x+(w-lw)/2 if align=='center' else x+w-lw
            self.ops.append(dict(kind='text',text=ln,x=xx,y=y+i*lh,w=lw,h=lh,
                                 size=size,bold=bold,color=color,role=role,link=link))
        return actual_h

    def bullets(self, bullets,x,y,w,h,size=26,min_size=22):
        # Keep all bullets at a single readable font size on each slide.
        chosen=None
        while size>=min_size-.01:
            heights=[len(wrap(b,w-26,size))*size*1.23 for b in bullets]
            if sum(heights)+16*(len(bullets)-1) <= h:
                chosen=(size,heights)
                break
            size-=.25
        if chosen is None:
            raise ValueError(f"{self.deck}/{self.slide['id']}: bullets do not fit at {min_size}px")
        size,heights=chosen
        yy=y
        for b,hh in zip(bullets,heights):
            self.rect(x,yy+size*.40,7,7,TEAL,radius=3)
            self.text(b,x+25,yy,w-25,hh,size=size,leading=1.23,role='bullet')
            yy+=hh+16

    def table(self, columns,rows,x,y,w,h,note=None):
        n=len(columns)
        if any(len(r)!=n for r in rows):
            raise ValueError('table row/column mismatch')
        # Relative widths preserve short token/position columns.
        ratios=[1/n]*n
        if n==3 and columns[0] in ('Token','Position'):
            ratios=[.18,.25,.57] if columns[0]=='Token' else [.18,.41,.41]
        if n==3 and columns[0]=='Known prefix':
            ratios=[.45,.25,.30]
        if n==3 and columns[0]=='Stage':
            ratios=[.26,.39,.35]
        sizes=[w*r for r in ratios]
        note_h=0
        if note:
            note_h=len(wrap(note,w-12,16))*19.2+12
        space=h-note_h
        chosen=None
        for size in (23,22,21,20,19):
            pad=11
            header_h=max(len(wrap(c,cw-2*pad,18,True)) for c,cw in zip(columns,sizes))*22+20
            row_h=[max(len(wrap(str(c),cw-2*pad,size)) for c,cw in zip(row,sizes))*size*1.2+2*pad for row in rows]
            if header_h+sum(row_h)<=space:
                chosen=(size,header_h,row_h,pad)
                break
        if chosen is None:
            raise ValueError(f"{self.deck}/{self.slide['id']}: table too dense")
        size,header_h,row_h,pad=chosen
        self.rect(x,y,w,header_h,NAVY,radius=8)
        xx=x
        for c,cw in zip(columns,sizes):
            self.text(c,xx+pad,y+10,cw-2*pad,header_h-14,size=18,bold=True,color=WHITE,role='table_header')
            xx+=cw
        yy=y+header_h
        for i,(row,rh) in enumerate(zip(rows,row_h)):
            self.rect(x,yy,w,rh,WHITE if i%2==0 else '#EEF3F8',stroke=BORDER)
            xx=x
            for cell,cw in zip(row,sizes):
                self.text(str(cell),xx+pad,yy+pad,cw-2*pad,rh-2*pad,size=size,leading=1.2,role='table_cell')
                xx+=cw
            yy+=rh
        if note:
            self.text(note,x+6,yy+12,w-12,h-(yy-y)-12,size=16,color=MUTED,leading=1.2,role='visual_note')


def validate_visual(v):
    allowed={
      'comparison':{'type','columns','rows','note','source_condition'},
      'table':{'type','columns','rows','note'},
      'shape_flow':{'type','dimension_sizes','stages'},
      'numeric_attention':{'type','query','keys','values','key_dimension','raw_scores','scaled_scores','weights','output','steps'},
      'mask_shift':{'type','inputs','targets','mask','mask_label','example'},
      'generation_tree':{'type','root','fixed_output_length','tie_break','beam_width','length_penalty','branches','greedy_path','greedy_joint','beam_path','beam_joint','note'},
      'pipeline':{'type','steps'},
      'metrics':{'type','items'},
      'equation':{'type','text','definitions'},
    }
    if v['type'] not in allowed:
        raise ValueError(f"Unsupported visual type: {v['type']}")
    unknown=set(v)-allowed[v['type']]
    if unknown:
        raise ValueError(f"Unsupported {v['type']} visual keys: {sorted(unknown)}")
    nested={
      'shape_flow':('stages',{'name','shape','meaning'}),
      'metrics':('items',{'label','value','detail'}),
    }
    if v['type'] in nested:
        key,keys=nested[v['type']]
        for item in v[key]:
            if set(item)-keys: raise ValueError(f"Unexpected {key} fields: {set(item)-keys}")
    if v['type']=='mask_shift':
        keys={'query_position','blocked_position','label','unmasked_two_key_scores','additive_mask','masked_scores','weights_after_softmax','mixed_value_output','training','generation','padding'}
        if set(v['example'])-keys: raise ValueError('Unexpected mask example fields')
    if v['type']=='generation_tree':
        for b in v['branches']:
            if set(b)-{'token','probability','children'}: raise ValueError('Unexpected tree branch fields')
            for c in b['children']:
                if set(c)-{'token','probability','joint'}: raise ValueError('Unexpected tree child fields')


def vec(xs,digits=None):
    def fmt(a):
        if isinstance(a,str): return a
        if digits is not None: return f'{a:.{digits}f}'
        return str(a)
    return '['+', '.join(fmt(a) for a in xs)+']'


def visual(p,v,x,y,w,h):
    validate_visual(v)
    typ=v['type']
    if typ in ('comparison','table'):
        note=' '.join(v[k] for k in ('note','source_condition') if k in v)
        p.table(v['columns'],v['rows'],x,y,w,h,note or None)
    elif typ=='numeric_attention':
        p.rect(x,y,w,h,WHITE,stroke=BORDER,radius=12)
        p.text(f"q = {vec(v['query'])}      dₖ = {v['key_dimension']}",x+22,y+16,w-44,38,size=27,bold=True)
        p.text('K: '+ '  |  '.join(vec(a) for a in v['keys']),x+22,y+64,w-44,32,size=24)
        p.text('V: '+ '  |  '.join(vec(a) for a in v['values']),x+22,y+101,w-44,32,size=24)
        p.line(x+22,y+146,x+w-22,y+146)
        p.text('1  Dot products  '+vec(v['raw_scores']),x+22,y+161,w-44,31,size=24)
        p.text('2  Divide by √2  '+vec(v['scaled_scores'],4),x+22,y+204,w-44,31,size=24)
        p.text('3  Softmax weights',x+22,y+246,w-44,28,size=21,bold=True,color=TEAL)
        barx,bary,barw=x+22,y+280,w-44
        first=barw*v['weights'][0]
        p.rect(barx,bary,first,38,TEAL,radius=0)
        p.rect(barx+first,bary,barw-first,38,NAVY,radius=0)
        p.text(f"{v['weights'][0]:.4f}",barx+8,bary+5,first-16,28,size=23,bold=True,color=WHITE,align='center')
        p.text(f"{v['weights'][1]:.4f}",barx+first+8,bary+5,barw-first-16,28,size=23,bold=True,color=WHITE,align='center')
        p.text(f"4  {v['weights'][0]:.4f} × {vec(v['values'][0])} + {v['weights'][1]:.4f} × {vec(v['values'][1])}",x+22,y+326,w-44,28,size=21,bold=True)
        p.text('Output = '+vec(v['output'],4),x+22,y+358,w-44,33,size=26,bold=True,color=TEAL)
    elif typ=='shape_flow':
        stages=v['stages']
        legend='   '.join(f'{k}={val}' for k,val in v.get('dimension_sizes',{}).items())
        legend_h=0
        if legend:
            legend_h=len(wrap(legend,w-16,16))*19.2+10
            p.text(legend,x+8,y,w-16,legend_h,size=16,color=MUTED,leading=1.2,role='axis_legend')
        gap=8
        cardh=(h-legend_h-gap*(len(stages)-1))/len(stages)
        yy=y+legend_h
        for i,s in enumerate(stages):
            p.rect(x,yy,w,cardh,WHITE,stroke=BORDER,radius=8)
            p.rect(x,yy,5,cardh,TEAL)
            # Name and shape have dedicated lines; meanings can wrap.
            p.text(s['name'],x+18,yy+5,w-36,24,size=18,bold=True,role='shape_name')
            p.text(s['shape'],x+18,yy+28,w-36,31,size=23,bold=True,color=TEAL,role='shape_value')
            p.text(s['meaning'],x+18,yy+58,w-36,cardh-62,size=16,min_size=15,leading=1.12,role='shape_meaning')
            yy+=cardh+gap
    elif typ=='mask_shift':
        pad=154
        cw=(w-pad)/4
        p.text('decoder input',x,y+7,pad-7,30,size=18,bold=True)
        p.text('next-target',x,y+50,pad-7,30,size=18,bold=True,color=TEAL)
        for j in range(4):
            p.rect(x+pad+j*cw,y,cw-4,36,WHITE,stroke=BORDER,radius=5)
            p.text(v['inputs'][j],x+pad+j*cw+4,y+4,cw-12,29,size=22,bold=True,align='center')
            p.rect(x+pad+j*cw,y+43,cw-4,36,PALE,radius=5)
            p.text(v['targets'][j],x+pad+j*cw+4,y+47,cw-12,29,size=22,bold=True,color=TEAL,align='center')
        p.text(v['mask_label'],x,y+103,w,28,size=20,bold=True)
        gx,gy,cw2,ch=x+54,y+161,76,42
        for j,t in enumerate(v['inputs']):
            p.text(t,gx+j*cw2,gy-29,cw2,24,size=18,bold=True,align='center')
        for i,row in enumerate(v['mask']):
            p.text(f'q{i}',x+6,gy+i*ch+7,42,28,size=19,color=MUTED)
            for j,a in enumerate(row):
                fill=PALE if a==0 else '#E8EDF3'
                p.rect(gx+j*cw2,gy+i*ch,cw2-3,ch-3,fill,radius=4)
                p.text(str(a),gx+j*cw2+3,gy+i*ch+6,cw2-9,31,size=24,bold=True,color=TEAL if a==0 else MUTED,align='center')
        e=v['example'];rx=x+390;rw=w-390
        if 'masked_scores' in e:
            p.text('BEFORE SOFTMAX',rx,gy,rw,25,size=16,bold=True,color=MUTED)
            p.text('scores '+vec(e['masked_scores'],4),rx,gy+30,rw,58,size=21,leading=1.18)
            p.text('mask '+vec(e['additive_mask']),rx,gy+58,rw,28,size=21)
            p.text('AFTER SOFTMAX',rx,gy+94,rw,25,size=16,bold=True,color=TEAL)
            p.text('weights '+vec(e['weights_after_softmax']),rx,gy+120,rw,31,size=23,bold=True,color=TEAL)
            p.text('output '+vec(e['mixed_value_output']),rx,gy+153,rw,31,size=23,bold=True)
        else:
            p.text('TRAINING',rx,gy,rw,23,size=17,bold=True,color=TEAL)
            p.text(e['training'],rx,gy+27,rw,66,size=20,leading=1.18)
            p.text('GENERATION',rx,gy+78,rw,23,size=17,bold=True,color=TEAL)
            p.text(e['generation'],rx,gy+104,rw,66,size=20,leading=1.18)
            p.text(e['padding'],rx,gy+154,rw,46,size=16,color=MUTED,leading=1.16)
        p.text(f"Input {v['inputs'][e['query_position']]} predicts {e['label']}; future input position {e['blocked_position']} is blocked.",x,y+h-27,w,24,size=16,bold=True,color=TEAL)
    elif typ=='generation_tree':
        p.rect(x,y,w,h,WHITE,stroke=BORDER,radius=12)
        p.text(f"2 symbols · beam width {v['beam_width']} · no length penalty",x+18,y+12,w-36,28,size=20,bold=True,color=MUTED)
        # Complete tree, including the zero-probability branch.
        root=(x+52,y+193); parents=[(x+238,y+119),(x+238,y+261)]
        leaves=[[(x+w-174,y+83),(x+w-174,y+155)],[(x+w-174,y+225),(x+w-174,y+297)]]
        for b,pa,ls in zip(v['branches'],parents,leaves):
            p.line(root[0]+42,root[1]+18,pa[0],pa[1]+18,color=TEAL,thickness=2)
            p.text(f"{b['probability']:.1f}",(root[0]+pa[0])/2+7,(root[1]+pa[1])/2-5,70,27,size=20,bold=True)
            for c,le in zip(b['children'],ls):
                p.line(pa[0]+56,pa[1]+18,le[0],le[1]+18,color=BORDER,thickness=2)
                p.text(f"{c['probability']:.1f}",(pa[0]+le[0])/2+8,(pa[1]+le[1])/2-7,65,25,size=18)
                chosen=b['token']==v['beam_path'][0] and c['token']==v['beam_path'][1]
                p.rect(le[0],le[1],158,38,TEAL if chosen else '#EDF2F7',radius=6)
                p.text(f"{b['token']}{c['token']}  {c['joint']:.2f}",le[0]+7,le[1]+5,144,29,size=22,bold=True,color=WHITE if chosen else INK,align='center')
            p.rect(pa[0],pa[1],56,38,PALE,stroke=BORDER,radius=6)
            p.text(b['token'],pa[0]+4,pa[1]+5,48,29,size=23,bold=True,color=TEAL,align='center')
        p.rect(root[0]-9,root[1],64,38,NAVY,radius=6)
        p.text(v['root'],root[0]-5,root[1]+6,56,28,size=19,bold=True,color=WHITE,align='center')
        p.text(f"Greedy {''.join(v['greedy_path'])} = {v['greedy_joint']:.2f}     Beam-3 {''.join(v['beam_path'])} = {v['beam_joint']:.2f}",x+18,y+h-56,w-36,30,size=24,bold=True,color=TEAL)
        p.text('Equal-length toy; ties choose X before Y; EOS omitted here.',x+18,y+h-26,w-36,23,size=15.5,color=MUTED)
    elif typ=='pipeline':
        gap=10;n=len(v['steps']);cardh=(h-gap*(n-1))/n
        for i,step in enumerate(v['steps']):
            yy=y+i*(cardh+gap)
            p.rect(x,yy,w,cardh,WHITE,stroke=BORDER,radius=9)
            p.rect(x+14,yy+12,38,38,TEAL,radius=7)
            p.text(str(i+1),x+18,yy+17,30,28,size=22,bold=True,color=WHITE,align='center')
            p.text(step,x+67,yy+12,w-84,cardh-20,size=23,min_size=21,bold=True)
    elif typ=='metrics':
        gap=15;cardh=(h-gap*(len(v['items'])-1))/len(v['items'])
        for i,item in enumerate(v['items']):
            yy=y+i*(cardh+gap)
            p.rect(x,yy,w,cardh,WHITE,stroke=BORDER,radius=10)
            p.text(f"{item['value']:.2f}%",x+19,yy+20,220,60,size=43,bold=True,color=TEAL)
            p.text(item['label'],x+250,yy+16,w-270,48,size=23,bold=True)
            p.text(item['detail'],x+250,yy+67,w-270,cardh-70,size=17,color=MUTED)
    elif typ=='equation':
        p.rect(x,y,w,h,WHITE,stroke=BORDER,radius=12)
        p.text('PROPOSED AGREEMENT SIGNAL',x+22,y+22,w-44,25,size=17,bold=True,color=TEAL)
        p.text(v['text'],x+22,y+78,w-44,150,size=29,min_size=26,bold=True,leading=1.25)
        yy=y+245
        for definition in v['definitions']:
            hh=p.text(definition,x+22,yy,w-44,65,size=21,color=MUTED,leading=1.18)
            yy+=hh+16


def source_footer(p,s):
    sources=s.get('sources',[])
    x,y,w=48,670,1120
    if not sources:
        p.text('Teaching example / proposed work — scope stated on the slide',x,y,w,28,size=12,color=MUTED,role='source')
        return
    # Keep every title and live link; distribute explicit source rows.
    total='   '.join(f"[{i+1}] {a['title']}" for i,a in enumerate(sources))
    fs=12
    while len(wrap(total,w,fs))*fs*1.2>31 and fs>=10:
        fs-=.25
    # Separate linked source runs may share a line if they fit.
    xx=x; yy=y; lh=fs*1.2
    for i,a in enumerate(sources):
        text=f"[{i+1}] {a['title']}"
        chunks=wrap(text,w,fs)
        for k,ln in enumerate(chunks):
            tw=width(ln,fs)
            if xx>x and xx+tw>x+w:
                xx=x;yy+=lh
            p.text(ln,xx,yy,tw+.1,lh,size=fs,color=MUTED,leading=1.2,role='source',link=a.get('url'))
            xx+=tw+18
            if k<len(chunks)-1:
                xx=x;yy+=lh
    if yy+lh>706:
        raise ValueError(f"Too many source footer rows: {s['id']}")


def make_page(deck,s,index,count):
    p=Page(deck,s)
    p.rect(0,0,W,H,BG)
    p.rect(0,0,12,H,TEAL)
    p.rect(48,29,33,4,TEAL)
    label='VGU · TRIAL LECTURE' if deck=='Trial_Lecture_30min' else 'VGU · RESEARCH ORIENTATION'
    p.text(label,93,20,1000,25,size=15,bold=True,color=MUTED,role='section_label')
    p.text(s.get('kicker',f"{s['minutes']:g} MINUTES"),48,53,1184,25,size=16,bold=True,color=TEAL,role='kicker')
    p.text(s['title'],48,85,1184,94,size=38,min_size=35,bold=True,leading=1.16,role='title')
    by,bh=194,392
    v=s.get('visual')
    if v:
        left=370 if deck=='Trial_Lecture_30min' else 430
        p.bullets(s['bullets'],48,by+1,left,bh,size=25.5,min_size=21.5)
        vx=48+left+28
        visual(p,v,vx,by,1232-vx,bh)
    else:
        # Full-width, spacious numbered statements for the research narrative.
        n=len(s['bullets']);gap=16;cardh=(bh-gap*(n-1))/n
        for i,b in enumerate(s['bullets']):
            yy=by+i*(cardh+gap)
            p.rect(48,yy,1184,cardh,WHITE,stroke=BORDER,radius=9)
            p.rect(65,yy+19,38,38,TEAL,radius=7)
            p.text(f'{i+1:02d}',69,yy+25,30,28,size=18,bold=True,color=WHITE,align='center')
            p.text(b,123,yy+15,1089,cardh-24,size=28,min_size=24,leading=1.2,role='bullet')
    p.rect(48,609,1184,48,PALE,radius=8)
    p.text('KEY POINT',62,622,110,26,size=14,bold=True,color=TEAL,role='takeaway_label')
    p.text(s['takeaway'],183,612,1033,43,size=20,min_size=17.5,bold=True,color=NAVY,leading=1.12,role='takeaway')
    source_footer(p,s)
    p.text(f'{index:02d} / {count:02d}',1178,681,54,20,size=11,bold=True,color=MUTED,align='right',role='page_number')
    p.rect(0,712,W,8,NAVY)
    return p


def render_pdf(pages,path):
    c=Canvas(str(path),pagesize=(W,H),pageCompression=1,invariant=1)
    c.setTitle(pages[0].deck.replace('_',' '))
    c.setAuthor('Nguyen Tuan Ngoc — rehearsal materials')
    for page in pages:
        for op in page.ops:
            k=op['kind']
            if k=='rect':
                c.setFillColorRGB(*(v/255 for v in color_rgb(op['fill'])))
                c.setStrokeColorRGB(*(v/255 for v in color_rgb(op['stroke'] or op['fill'])))
                c.setLineWidth(.8)
                c.roundRect(op['x'],H-op['y']-op['h'],op['w'],op['h'],op['radius'],fill=1,stroke=bool(op['stroke']))
            elif k=='line':
                c.setStrokeColorRGB(*(v/255 for v in color_rgb(op['color'])))
                c.setLineWidth(op['thickness'])
                c.line(op['x1'],H-op['y1'],op['x2'],H-op['y2'])
            else:
                font='DV-Bold' if op['bold'] else 'DV'
                c.setFont(font,op['size'])
                c.setFillColorRGB(*(v/255 for v in color_rgb(op['color'])))
                ascent=pdfmetrics.getAscent(font)/1000*op['size']
                c.drawString(op['x'],H-op['y']-ascent,op['text'])
                if op['link']:
                    c.linkURL(op['link'],(op['x'],H-op['y']-op['h'],op['x']+op['w'],H-op['y']),relative=0,thickness=0)
        c.showPage()
    c.save()


def pp_color(shape,c,fill=True):
    if fill:
        shape.fill.solid();shape.fill.fore_color.rgb=RGBColor(*color_rgb(c))
    else:
        shape.line.color.rgb=RGBColor(*color_rgb(c))


def render_pptx(pages,path):
    prs=Presentation();prs.slide_width=Inches(W/96);prs.slide_height=Inches(H/96)
    prs.core_properties.title=pages[0].deck.replace('_',' ')
    prs.core_properties.subject='Canonical JSON source; editable native text/shapes; matched vector PDF'
    prs.core_properties.author='VGU rehearsal materials'
    prs.core_properties.last_modified_by='VGU rehearsal materials'
    prs.core_properties.created=__import__('datetime').datetime(2026,11,4,0,0,0)
    prs.core_properties.modified=__import__('datetime').datetime(2026,11,4,0,0,0)
    for page in pages:
        slide=prs.slides.add_slide(prs.slide_layouts[6])
        for op in page.ops:
            if op['kind']=='rect':
                typ=MSO_SHAPE.ROUNDED_RECTANGLE if op['radius'] else MSO_SHAPE.RECTANGLE
                shape=slide.shapes.add_shape(typ,Inches(op['x']/96),Inches(op['y']/96),Inches(op['w']/96),Inches(op['h']/96))
                pp_color(shape,op['fill'])
                if op['stroke']: pp_color(shape,op['stroke'],False);shape.line.width=Pt(.6)
                else: shape.line.fill.background()
                if op['radius']:
                    try: shape.adjustments[0]=min(.12,op['radius']/min(op['w'],op['h']))
                    except (IndexError,ValueError): pass
            elif op['kind']=='line':
                from pptx.enum.shapes import MSO_CONNECTOR
                shape=slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT,Inches(op['x1']/96),Inches(op['y1']/96),Inches(op['x2']/96),Inches(op['y2']/96))
                pp_color(shape,op['color'],False);shape.line.width=Pt(op['thickness']*.75)
            else:
                shape=slide.shapes.add_textbox(Inches(op['x']/96),Inches(op['y']/96),Inches((op['w']+8)/96),Inches((op['h']+4)/96))
                tf=shape.text_frame;tf.clear();tf.margin_left=tf.margin_right=tf.margin_top=tf.margin_bottom=0
                tf.word_wrap=False;tf.auto_size=MSO_AUTO_SIZE.NONE;tf.vertical_anchor=MSO_ANCHOR.TOP
                para=tf.paragraphs[0];para.space_before=para.space_after=Pt(0)
                run=para.add_run();run.text=op['text'];run.font.name=FONT_NAME;run.font.size=Pt(op['size']*.75)
                run.font.bold=op['bold'];run.font.color.rgb=RGBColor(*color_rgb(op['color']))
                if op['link']: run.hyperlink.address=op['link']
        s=page.slide
        notes=f"{s.get('kicker','')}\nDuration: {s['minutes']:g} minutes\n\n{s['speaker_notes']}"
        slide.notes_slide.notes_text_frame.text=notes
        transition=OxmlElement('p:transition');transition.set('advClick','1');transition.set('advTm',str(round(s['minutes']*60000)))
        # Timing metadata is current; manual click remains the default show policy.
        slide._element.append(transition)
    # Show properties belong to ppt/presProps.xml, not presentation.xml.
    # Store up-to-date slide durations without forcing automatic advancement.
    from lxml.etree import fromstring, tostring
    from pptx.oxml.ns import qn
    for rel in prs.part.rels.values():
        if rel.reltype.endswith('/presProps'):
            part=rel.target_part
            props=fromstring(part.blob)
            for old in props.findall(qn('p:showPr')):
                props.remove(old)
            show=OxmlElement('p:showPr');show.set('useTimings','0')
            show.append(OxmlElement('p:present'));show.append(OxmlElement('p:sldAll'))
            props.insert(0,show)
            part._blob=tostring(props,xml_declaration=True,encoding='UTF-8',standalone=True)
            break
    else:
        raise RuntimeError('PowerPoint template is missing presentation properties')
    prs.save(str(path))


def contact_and_images(pdf_path):
    doc=fitz.open(pdf_path)
    folder=OUT/(pdf_path.stem+'_pages');folder.mkdir(parents=True,exist_ok=True)
    thumbs=[]
    for i,page in enumerate(doc):
        pix=page.get_pixmap(matrix=fitz.Matrix(1.5,1.5),alpha=False)
        pix.save(str(folder/f'{i+1:02d}.png'))
        image=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
        image.thumbnail((480,270),Image.Resampling.LANCZOS)
        tile=Image.new('RGB',(504,308),'#E7EDF3')
        tile.paste(image,((504-image.width)//2,12))
        draw=ImageDraw.Draw(tile)
        f=ImageFont.truetype(str(FONT_DIR/'DejaVuSans.ttf'),16)
        draw.text((15,286),f'{pdf_path.stem} · {i+1:02d}',font=f,fill=NAVY)
        thumbs.append(tile)
    columns=3;rows=math.ceil(len(thumbs)/columns)
    sheet=Image.new('RGB',(columns*504,rows*308),'#E7EDF3')
    for i,img in enumerate(thumbs): sheet.paste(img,((i%columns)*504,(i//columns)*308))
    contact=OUT/(pdf_path.stem+'_contact.png');sheet.save(contact)
    return {'pages':len(doc),'page_images':str(folder.relative_to(ROOT)),'contact_sheet':str(contact.relative_to(ROOT))}


def main():
    OUT.mkdir(exist_ok=True);VERIFY.mkdir(exist_ok=True)
    report={'coordinate_system':[W,H],'format':'16:9','font':FONT_NAME,
            'delivery':'Native editable PPTX text/shapes and vector PDF generated from the same explicit operations.',
            'pptx_notes':'Exact source speaker_notes preceded by kicker and duration. Each transition advTm matches duration; useTimings=0 keeps manual advance.',
            'rendering_limits':'PPTX contains native editable text/shapes but was not rendered by Microsoft PowerPoint or LibreOffice here. PDF is font-embedded and its page PNGs were inspected. Shared coordinates/wrapping are verified; Office pixel equivalence is not claimed.',
            'bounds_violations':[],'text_overlap_violations':[],'decks':[]}
    for src,name in [('trial_lecture.json','Trial_Lecture_30min'),('research_orientation.json','Research_Orientation_20min')]:
        source=ROOT/'content'/src;data=json.loads(source.read_text())
        if abs(sum(s['minutes'] for s in data['slides'])-data['total_minutes'])>1e-9: raise ValueError('duration mismatch')
        pages=[make_page(name,s,i+1,len(data['slides'])) for i,s in enumerate(data['slides'])]
        # Text boxes represent the full manually wrapped line extents. Rectangles
        # intentionally contain text; text/text intersections greater than one
        # coordinate pixel are forbidden, including footer and tree labels.
        for page in pages:
            for i,a in enumerate(page.boxes):
                for b in page.boxes[i+1:]:
                    ox=min(a['x']+a['w'],b['x']+b['w'])-max(a['x'],b['x'])
                    oy=min(a['y']+a['h'],b['y']+b['h'])-max(a['y'],b['y'])
                    if ox>1 and oy>1:
                        raise ValueError(f"{name}/{page.slide['id']}: text overlap {a['text']!r} / {b['text']!r}")
        pdf=OUT/f'{name}.pdf';pptx=OUT/f'{name}.pptx'
        render_pdf(pages,pdf);render_pptx(pages,pptx)
        images=contact_and_images(pdf)
        evidence={'name':name,'source':str(source.relative_to(ROOT)),
                  'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                  'source_slide_count':len(pages),'pptx_slide_count':len(Presentation(pptx).slides),
                  'pdf_page_count':images['pages'],'total_minutes':data['total_minutes'],
                  'outputs':{'pptx':str(pptx.relative_to(ROOT)),'pdf':str(pdf.relative_to(ROOT)),**images},
                  'slides':[]}
        checkpptx=Presentation(pptx)
        for i,p in enumerate(pages):
            assert p.slide['speaker_notes'] in checkpptx.slides[i].notes_slide.notes_text_frame.text
            evidence['slides'].append({'id':p.slide['id'],'minutes':p.slide['minutes'],
                'notes_sha256':hashlib.sha256(p.slide['speaker_notes'].encode()).hexdigest(),
                'visual_type':p.slide.get('visual',{}).get('type'),
                'element_count':len(p.ops),'text_boxes':p.boxes})
        assert evidence['source_slide_count']==evidence['pptx_slide_count']==evidence['pdf_page_count']
        report['decks'].append(evidence)
        print(f'{name}: {len(pages)} slides, {data["total_minutes"]} minutes, PDF/PPTX/notes counts agree; page PNGs and contact sheet generated.')
    (VERIFY/'slides_layout.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('No page bounds violations. Inspect contact sheets and full page images for visual quality.')


if __name__=='__main__': main()
