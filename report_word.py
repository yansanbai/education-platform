import io

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from PIL import Image

from pipeline import WRONG, question_key


def make_report(title, report, get_figure):
    document = Document()
    section = document.sections[0]
    section.top_margin = section.bottom_margin = Inches(0.8)
    section.left_margin = section.right_margin = Inches(0.85)
    for name in ("Normal", "Title", "Heading 1", "Heading 2"):
        style = document.styles[name]
        style.font.name = "Microsoft YaHei"
        style.element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Microsoft YaHei")
        style.font.color.rgb = RGBColor(0, 0, 0)
        for attribute in ("themeColor","themeTint","themeShade"):
            style.element.rPr.color.attrib.pop(qn("w:"+attribute),None)
        for border in style.element.xpath("./w:pPr/w:pBdr"):
            border.getparent().remove(border)
    normal = document.styles["Normal"]
    normal.font.size = Pt(11)
    normal.paragraph_format.line_spacing = 1.25
    normal.paragraph_format.space_after = Pt(6)
    document.add_paragraph(title, style="Title")
    if report.get("demo"):
        document.add_paragraph("演示报告")
    document.add_heading("一、错题批改", level=1)
    wrong = [item for item in report["questions"] if item["verdict"] in WRONG]
    if not wrong:
        document.add_paragraph("本次未发现可确认的错题。")
    for item in wrong:
        document.add_heading(f'第 {question_key(item)} 题', level=2)
        document.add_paragraph(f'学生作答　{item["student_answer"]}')
        document.add_paragraph(f'正确答案　{item["correct_answer"]}')
        document.add_paragraph(f'错误分析　{item["feedback"]}')
    for state in ("未作答", "未拍到", "待复核"):
        numbers = [question_key(item) for item in report["questions"] if item["verdict"] == state]
        if numbers:
            document.add_paragraph(f'{state}　{"、".join(numbers)}')
    for item in report.get("coverage_warnings", []):
        document.add_paragraph(f'第 {question_key(item)} 题部分作答待复核　{item["evidence"]}')
    if report.get("unlinked"):
        document.add_heading("未关联的初读作答（待复核）", level=2)
        for item in report["unlinked"]:
            document.add_paragraph(f'照片 {item["photo"]}　{item["evidence"]}')
            for text in [*item["steps"], item["final"]]:
                if text:
                    document.add_paragraph(text)

    document.add_heading("二、延伸练习", level=1)
    if not report["exercises"]:
        document.add_paragraph("暂无延伸练习。")
    for number, item in enumerate(report["exercises"], 1):
        document.add_heading(f'{number}. 对应原卷第 {item["source"]} 题', level=2)
        prompt = document.add_paragraph(item["question"])
        images = item.get("images")
        if images is None:
            images = [item["image"]] if item.get("image") else []
        prompt.paragraph_format.keep_with_next = bool(images or item["options"])
        for label, image_id in enumerate(images, 1):
            image = get_figure(image_id)
            with Image.open(io.BytesIO(image)) as dimensions:
                width, height = dimensions.size
            size = Inches(min(4.65, 2.55 * width / height))
            figure = document.add_picture(io.BytesIO(image), width=size)
            figure._inline.docPr.set("descr", f'练习 {number} 图 {label}')
            figure_paragraph = document.paragraphs[-1]
            figure_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            figure_paragraph.paragraph_format.keep_with_next = len(images) > 1 or bool(item["options"])
            if len(images) > 1:
                caption = document.add_paragraph(f"图 {label}")
                caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for option in item["options"]:
            document.add_paragraph(option)

    if report["exercises"]:
        document.add_heading("延伸练习参考答案", level=2)
        for number, item in enumerate(report["exercises"], 1):
            paragraph = document.add_paragraph()
            paragraph.add_run(f'{number}. {item["answer"]}').bold = True
            paragraph.add_run(f'\n{item["solution"]}')
    for paragraph in document.paragraphs:
        if paragraph.style.name in ("Title","Heading 1","Heading 2"):
            for run in paragraph.runs:
                run.font.color.rgb = RGBColor(0,0,0)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()
