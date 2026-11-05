"""Export the current reviewed report as a Word document in memory."""
from io import BytesIO
from network_document import validate


def export_word(blocks):
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    blocks=validate(blocks)
    doc=Document()
    section=doc.sections[0]
    wide=any(b['type']=='table' and len(b['headers'])>=8 for b in blocks)
    if wide:
        section.orientation=WD_ORIENT.LANDSCAPE
        section.page_width,section.page_height=section.page_height,section.page_width
    section.top_margin=section.bottom_margin=Cm(1.6)
    section.left_margin=section.right_margin=Cm(1.4)
    normal=doc.styles['Normal']
    normal.font.name='Microsoft YaHei'
    normal._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'Microsoft YaHei')
    normal.font.size=Pt(10.5)
    normal.paragraph_format.line_spacing=1.4
    normal.paragraph_format.space_after=Pt(6)
    for index,block in enumerate(blocks):
        if block['type']=='text':
            p=doc.add_paragraph()
            if index==0:
                p.alignment=WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_after=Pt(12)
            for part in block.get('runs',[{'text':block['text']}]):
                run=p.add_run(part['text'])
                if index==0: run.bold=True;run.font.size=Pt(13.5)
                if part.get('font'):
                    run.font.name=part['font']
                    run._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),part['font'])
                if part.get('size'): run.font.size=Pt(part['size']*0.75)
                if part.get('color'): run.font.color.rgb=RGBColor.from_string(part['color'][1:].upper())
                if part.get('bold'): run.bold=True
                if part.get('italic'): run.italic=True
                if part.get('underline'): run.underline=True
        else:
            heading=doc.add_paragraph();heading.paragraph_format.space_before=Pt(6)
            heading.add_run(block['title']).bold=True
            table=doc.add_table(rows=1,cols=len(block['headers']))
            table.style='Table Grid'
            table.alignment=WD_TABLE_ALIGNMENT.CENTER
            table.autofit=True
            first=table.rows[0]
            tr_pr=first._tr.get_or_add_trPr();repeat=OxmlElement('w:tblHeader');repeat.set(qn('w:val'),'true');tr_pr.append(repeat)
            for i,label in enumerate(block['headers']):
                first.cells[i].text=label
            for row in block['rows']:
                cells=table.add_row().cells
                for i,value in enumerate(row):cells[i].text=value
            for row in table.rows:
                for cell in row.cells:
                    cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
                    for p in cell.paragraphs:
                        p.paragraph_format.space_before=Pt(0);p.paragraph_format.space_after=Pt(0);p.paragraph_format.line_spacing=1.15
                        for run in p.runs:
                            run.font.name='Microsoft YaHei';run._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'Microsoft YaHei')
                            run.font.size=Pt(7.5 if len(block['headers'])>=8 else 9)
            for cell in first.cells:
                for p in cell.paragraphs:
                    for run in p.runs:run.bold=True
            doc.add_paragraph().paragraph_format.space_after=Pt(2)
    output=BytesIO();doc.save(output);output.seek(0);return output
