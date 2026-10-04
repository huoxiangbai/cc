"""Independent, text-first Java GenUI export contract. Never fetches tree URLs."""
import io
import json
import zipfile
from html import escape
from reactor_backend.projection.genui import tree
from importlib.resources import files

FONT=files("reactor_backend").joinpath("resources/fonts/NotoSansSC-Regular.ttf")


def string(value):
    if value is None:return ''
    if isinstance(value,bool):return str(value).lower()
    if isinstance(value,(dict,list)):return json.dumps(value,ensure_ascii=False,separators=(',',':'))
    return str(value)


def first(props,*keys):
    return next((string(props[k]) for k in keys if string(props.get(k)).strip()),'')


def primary(props):return first(props,'value','label','title','message','description','subtitle','name','quote','content','text','code')


def blocks(node,format):
    kind=node['kind'];p=node.get('props',{});children=node.get('children',[])
    def paragraph(text,style='body'):return (style,string(text))
    if kind=='Heading':yield paragraph(primary(p),'h'+str(max(1,min(4,int(p.get('level',2))))) if format=='pdf' else 'h2')
    elif kind in ('Text','Markdown','Callout','Alert','AlertCard'):yield paragraph(primary(p))
    elif kind=='SectionHeader':
        if p.get('eyebrow'):yield paragraph(string(p['eyebrow']).upper(),'muted' if format=='pdf' else 'h2')
        yield paragraph(primary(p),'h2')
        if p.get('subtitle'):yield paragraph(p['subtitle'])
    elif kind in ('Card','DataCard','MetricCard','ProfileCard','MediaCard','QuoteCard','WeatherCard'):
        title=first(p,'title','name','quote','location');body=first(p,'value','description','bio','message','condition','subtitle')
        if title:yield paragraph(title,'h3')
        if body:yield paragraph(body)
        for child in children:yield from blocks(child,format)
    elif kind=='Stat':yield paragraph(string(p.get('label'))+': '+string(p.get('value'))+(' ('+string(p['delta'])+')' if p.get('delta') else ''),'h3')
    elif kind=='List':
        for i,child in enumerate(children,1):yield paragraph((str(i)+'. ' if string(p.get('ordered')).lower()=='true' else '• ')+primary(child.get('props',{})))
    elif kind=='ListItem':yield paragraph('• '+primary(p))
    elif kind=='Table':
        headers=p.get('headers') if isinstance(p.get('headers'),list) else []
        values=[[primary(cell.get('props',{})) for cell in row.get('children',[])] for row in children]
        if format=='pdf':yield ('table',(headers,values))
        else:
            if headers:yield paragraph(' | '.join(map(string,headers)),'h3')
            for row in values:yield paragraph(' | '.join(row))
    elif kind=='CodeBlock':yield paragraph(p.get('code'),'code')
    elif kind=='Chart':yield paragraph('Chart('+string(p.get('chart'))+'): '+string(p.get('title')))
    elif kind in ('ParametricLab','PythagorasLab','GeometryLab','InteractiveLab'):
        yield paragraph('Interactive lab: '+first(p,'title','scene','preset')+(' — '+string(p['formulaNote']) if format=='pdf' and p.get('formulaNote') else ''))
    elif kind in ('ConceptDemo','AnimStepLab','KnowledgeDemo'):yield paragraph('Concept demo: '+first(p,'title','scene','preset'))
    elif kind in (('Quiz','WorkedExample') if format=='pdf' else ('Quiz','WorkedExample','BeforeAfter','NumberLine','CoordinateGrid','BindScope')):
        yield paragraph(kind+': '+first(p,'title','prompt','problem',*(['question'] if format=='pdf' else [])))
    elif format=='pdf' and kind in ('BeforeAfter','CompareSlider','NumberLine','CoordinateGrid','BindScope','ReactiveScope'):yield paragraph(kind+': '+first(p,'title','beforeLabel','afterLabel'))
    elif kind in ('Image','Video','Model3D'):yield paragraph('['+kind+'] '+string(p.get('src')))
    elif kind in ('Button','LinkButton','InteractiveButton','ToggleButton'):yield paragraph('['+first(p,'label','value','text')+']','h3')
    elif kind=='KeyValueList':
        for item in p.get('items',[]) if isinstance(p.get('items'),list) else []:
            if isinstance(item,dict):yield paragraph(string(item.get('key'))+': '+string(item.get('value')))
        for child in children:yield from blocks(child,format)
    elif kind=='Slide':
        if p.get('eyebrow'):yield paragraph(string(p['eyebrow']).upper(),'muted' if format=='pdf' else 'h2')
        if p.get('title'):yield paragraph(p['title'],'h1')
        if p.get('subtitle'):yield paragraph(p['subtitle'])
        for child in children:yield from blocks(child,format)
    elif kind=='Divider':yield paragraph('—— '+string(p.get('label'))+' ——')
    elif kind=='JsonDebug':yield paragraph(p.get('value',''))
    else:
        if primary(p):yield paragraph(primary(p))
        for child in children:yield from blocks(child,format)


def contents(raw,mode,format):
    normalized=tree(raw);root=normalized['root']
    slides=[c for c in root.get('children',[]) if c['kind']=='Slide'] or root.get('children',[])
    if string(mode).lower()=='deck' and root['kind']=='SlideDeck':
        for i,slide in enumerate(slides):
            if i:yield ('page','')
            yield from blocks(slide,format)
    else:yield from blocks(root,format)


def pdf(raw,mode='document'):
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Table,TableStyle,PageBreak,Spacer
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    # Packaged OFL font is embedded: rendering never depends on a viewer CID pack.
    if "ReactorNotoSC" not in pdfmetrics.getRegisteredFontNames():pdfmetrics.registerFont(TTFont("ReactorNotoSC",str(FONT)))
    styles={k:ParagraphStyle(k,fontName='ReactorNotoSC',fontSize=s,leading=16 if k=='body' else s+4,spaceBefore=8 if k.startswith('h') else 0,spaceAfter=4,textColor=colors.Color(.39,.39,.43) if k=='muted' else colors.black,wordWrap='CJK') for k,s in {'body':11,'h1':18,'h2':15,'h3':13,'h4':12,'code':9,'muted':9}.items()}
    def p(value,style='body'):return Paragraph(escape(string(value)).replace('\n','<br/>'),styles[style])
    flow=[]
    for kind,value in contents(raw,mode,'pdf'):
        if kind=='page':flow.append(PageBreak())
        elif kind=='table':
            headers,values=value;count=len(headers) or max([len(row) for row in values]+[1]);rows=([headers] if headers else [])+values
            if rows:
                t=Table([[p(row[i] if i<len(row) else '') for i in range(count)] for row in rows],colWidths=[(A4[0]-84)/count]*count,repeatRows=1 if headers else 0,hAlign='LEFT')
                cmds=[('GRID',(0,0),(-1,-1),.5,colors.lightgrey),('VALIGN',(0,0),(-1,-1),'TOP'),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]
                if headers:cmds.append(('BACKGROUND',(0,0),(-1,0),colors.Color(245/255,245/255,247/255)))
                t.setStyle(TableStyle(cmds));flow.append(t)
        else:flow.append(p(value,kind))
    if not flow:flow.append(Spacer(1,1))
    output=io.BytesIO();SimpleDocTemplate(output,pagesize=A4,leftMargin=42,rightMargin=42,topMargin=48,bottomMargin=48).build(flow)
    return output.getvalue()


def docx(raw,mode='document'):
    paragraphs=[]
    for kind,value in contents(raw,mode,'docx'):
        if kind=='page':paragraphs.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>');continue
        paragraphs.append('<w:p><w:r><w:rPr><w:rFonts w:ascii="Noto Sans SC" w:hAnsi="Noto Sans SC" w:eastAsia="Noto Sans SC"/>'+('<w:b/>' if kind.startswith('h') else '')+'</w:rPr>'+'<w:t xml:space="preserve">'+escape(string(value))+'</w:t></w:r></w:p>')
    prefix='<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    parts={'[Content_Types].xml':prefix+'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
           '_rels/.rels':prefix+'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
           'word/_rels/document.xml.rels':prefix+'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>',
           'word/document.xml':prefix+'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+''.join(paragraphs)+'<w:sectPr/></w:body></w:document>'}
    font_key='A06BF241-12FE-4C22-9031-5D9C6B4B8AF2'
    embedded=bytearray(FONT.read_bytes());key=bytes.fromhex(font_key.replace('-',''))[::-1]
    for i in range(32):embedded[i]^=key[i%16]
    parts['word/fonts/NotoSansSC.odttf']=bytes(embedded)
    parts['word/fontTable.xml']=prefix+'<w:fonts xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><w:font w:name="Noto Sans SC"><w:family w:val="swiss"/><w:embedRegular r:id="font1" w:fontKey="{'+font_key+'}"/></w:font></w:fonts>'
    parts['word/_rels/fontTable.xml.rels']=prefix+'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="font1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/font" Target="fonts/NotoSansSC.odttf"/></Relationships>'
    parts['word/_rels/document.xml.rels']=parts['word/_rels/document.xml.rels'].replace('/>', '><Relationship Id="fonts" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/fontTable" Target="fontTable.xml"/></Relationships>')
    parts['[Content_Types].xml']=parts['[Content_Types].xml'].replace('</Types>','<Default Extension="odttf" ContentType="application/vnd.openxmlformats-officedocument.obfuscatedFont"/><Override PartName="/word/fontTable.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml"/></Types>')
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        for name,value in parts.items():z.writestr(name,value)
    return output.getvalue()
