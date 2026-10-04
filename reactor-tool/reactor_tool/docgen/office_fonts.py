"""Carry the OFL CJK fallback with DOCX while preserving theme font aliases."""
from pathlib import Path
import zipfile
from lxml import etree

W='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P='http://schemas.openxmlformats.org/package/2006/relationships'
C='http://schemas.openxmlformats.org/package/2006/content-types'


def embed_cjk(path: Path) -> None:
    with zipfile.ZipFile(path) as source:
        parts={name:source.read(name) for name in source.namelist()}
    # Embed under the existing East Asian aliases. Theme Latin fonts remain intact.
    aliases=set()
    for name,data in parts.items():
        if name.startswith('word/') and name.endswith('.xml'):
            xml=etree.fromstring(data)
            aliases.update(xml.xpath('//w:rFonts/@w:eastAsia',namespaces={'w':W}))
    if not aliases:return
    key='A06BF241-12FE-4C22-9031-5D9C6B4B8AF2'
    font=bytearray((Path(__file__).parent/'font_assets/NotoSansSC-Regular.ttf').read_bytes())
    mask=bytes.fromhex(key.replace('-',''))[::-1]
    for i in range(32):font[i]^=mask[i%16]
    parts['word/fonts/ReactorCJK.odttf']=bytes(font)
    fonts=etree.fromstring(parts['word/fontTable.xml'])
    relpath='word/_rels/fontTable.xml.rels'
    rels=etree.fromstring(parts[relpath]) if relpath in parts else etree.Element('{'+P+'}Relationships',nsmap={None:P})
    rid='ReactorCJK'
    etree.SubElement(rels,'{'+P+'}Relationship',Id=rid,Type=R+'/font',Target='fonts/ReactorCJK.odttf')
    for alias in sorted(aliases):
        matches=fonts.xpath('./w:font[@w:name=$name]',namespaces={'w':W},name=alias)
        item=matches[0] if matches else etree.SubElement(fonts,'{'+W+'}font',{'{'+W+'}name':alias})
        etree.SubElement(item,'{'+W+'}embedRegular',{'{'+R+'}id':rid,'{'+W+'}fontKey':'{'+key+'}'})
    types=etree.fromstring(parts['[Content_Types].xml'])
    etree.SubElement(types,'{'+C+'}Default',Extension='odttf',ContentType='application/vnd.openxmlformats-officedocument.obfuscatedFont')
    for name,xml in [('word/fontTable.xml',fonts),(relpath,rels),('[Content_Types].xml',types)]:
        parts[name]=etree.tostring(xml,encoding='UTF-8',xml_declaration=True,standalone=True)
    # Finish in memory before replacing the renderer's newly created artifact.
    import io
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as target:
        for name,data in parts.items():target.writestr(name,data)
    path.write_bytes(out.getvalue())
