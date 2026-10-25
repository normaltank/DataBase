"""Bounded subprocess parser. No network, database writes or source modifications."""
import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

MAX_BYTES = 10 * 1024 * 1024
MAX_CHARS = 1000000
MAX_SEGMENTS = 20000
MAX_PAGES = 300
MAX_EXPANDED = 20 * 1024 * 1024


class LimitReached(Exception):
    pass


def extract(path):
    if path.stat().st_size > MAX_BYTES:
        raise LimitReached()
    segments = []
    characters = 0

    def add(locator, text):
        nonlocal characters
        text = text.strip()
        characters += len(text)
        if characters > MAX_CHARS or len(segments) >= MAX_SEGMENTS:
            raise LimitReached()
        if text:
            segments.append({'locator': locator, 'text': text})

    suffix = path.suffix.lower()
    if suffix in {'.txt', '.md'}:
        for i, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
            add(f'第 {i} 行', line)
    elif suffix == '.docx':
        with zipfile.ZipFile(path) as archive:
            if len(archive.infolist()) > 2000 or sum(item.file_size for item in archive.infolist()) > MAX_EXPANDED:
                raise LimitReached()
            xml = archive.read('word/document.xml')
        if b'<!DOCTYPE' in xml.upper() or b'<!ENTITY' in xml.upper():
            raise ValueError('XML declarations are not supported')
        root = ElementTree.fromstring(xml)
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        body = root.find('w:body', ns)
        if body is None:
            raise ValueError('Missing document body')
        paragraph = table = 0
        def text(element):
            # Body paragraphs/table cells only; exclude text boxes, notes and pictures.
            parts = []
            for child in element:
                if child.tag == '{'+ns['w']+'}r':
                    parts.extend(node.text or '' for node in child if node.tag == '{'+ns['w']+'}t')
                elif child.tag == '{'+ns['w']+'}hyperlink':
                    parts.append(text(child))
            return ''.join(parts)
        for block in body:
            if block.tag == '{'+ns['w']+'}p':
                paragraph += 1
                add(f'DOCX 正文第 {paragraph} 段', text(block))
            elif block.tag == '{'+ns['w']+'}tbl':
                table += 1
                for row_number, row in enumerate(block.findall('w:tr', ns), 1):
                    cells = [' '.join(text(p) for p in cell.findall('w:p', ns)) for cell in row.findall('w:tc', ns)]
                    add(f'DOCX 表格 {table} 第 {row_number} 行', ' | '.join(cells))
    elif suffix == '.pdf':
        from pypdf import PdfReader, filters
        filters.ZLIB_MAX_OUTPUT_LENGTH = MAX_EXPANDED
        reader = PdfReader(path, strict=False)
        if reader.is_encrypted:
            raise ValueError('Encrypted PDF')
        if len(reader.pages) > MAX_PAGES:
            raise LimitReached()
        expanded = 0
        for number, page in enumerate(reader.pages, 1):
            contents = page.get_contents()
            if contents is not None:
                expanded += len(contents.get_data())
                if expanded > MAX_EXPANDED:
                    raise LimitReached()
            add(f'PDF 第 {number} 页（文件页码）', page.extract_text())
    else:
        return 'unsupported', []
    return ('ready' if segments else 'empty'), segments


if __name__ == '__main__':
    messages = {'ready': '已建立文字索引', 'empty': '无可提取文字（不支持 OCR）', 'unsupported': '格式不支持', 'limit': '超过索引处理限制', 'failed': '文字提取失败'}
    try:
        # A hard address-space ceiling is also available on Unix. Windows uses
        # input, expanded-stream, page, output and parent-enforced time limits.
        if sys.platform != 'win32':
            import resource
            resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
        code, segments = extract(Path(sys.argv[1]))
    except (LimitReached, MemoryError):
        code, segments = 'limit', []
    except Exception:
        code, segments = 'failed', []
    sys.stdout.buffer.write(json.dumps({'status': code, 'message': messages[code], 'segments': segments}, ensure_ascii=False).encode('utf-8'))
