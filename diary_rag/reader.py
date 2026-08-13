"""Universal reader layer: any format → ParagraphStream."""
from dataclasses import dataclass, field
from typing import List, Optional, Type
import os
import re


@dataclass
class Paragraph:
    """Single paragraph from any source format."""
    idx: int
    style: str          # e.g. "Heading 3", "Normal", "paragraph"
    level: int          # heading level: 0=body text, 1=H1, 2=H2, ...
    text: str
    char_count: int

    def __post_init__(self):
        if self.char_count == 0 and self.text:
            self.char_count = len(self.text)


@dataclass
class ParagraphStream:
    """Unified intermediate representation from any reader."""
    file_path: str
    file_name: str
    paragraphs: List[Paragraph]


class BaseReader:
    """Abstract reader — implement for each file format."""

    @classmethod
    def can_read(cls, file_path: str) -> bool:
        raise NotImplementedError

    def read(self, file_path: str) -> ParagraphStream:
        raise NotImplementedError


# Registry of available readers
_READERS: List[Type[BaseReader]] = []


def register_reader(cls: Type[BaseReader]) -> Type[BaseReader]:
    _READERS.append(cls)
    return cls


def read_file(file_path: str) -> ParagraphStream:
    """Auto-detect format and read file into ParagraphStream."""
    for reader_cls in _READERS:
        if reader_cls.can_read(file_path):
            return reader_cls().read(file_path)
    ext = os.path.splitext(file_path)[1].lower()
    raise ValueError(f"No reader found for {file_path} (ext={ext})")


@register_reader
class DocxReader(BaseReader):
    """Read .docx files, preserving Word heading styles."""

    @classmethod
    def can_read(cls, file_path: str) -> bool:
        return file_path.lower().endswith('.docx')

    def read(self, file_path: str) -> ParagraphStream:
        from docx import Document

        doc = Document(file_path)
        paragraphs = []
        heading_re = re.compile(r'^Heading\s+(\d+)$', re.IGNORECASE)

        for i, p in enumerate(doc.paragraphs):
            text = p.text or ""
            style_name = p.style.name if p.style else "Normal"
            level = 0
            m = heading_re.match(style_name)
            if m:
                level = int(m.group(1))

            paragraphs.append(Paragraph(
                idx=i,
                style=style_name,
                level=level,
                text=text,
                char_count=len(text)
            ))

        return ParagraphStream(
            file_path=file_path,
            file_name=os.path.basename(file_path),
            paragraphs=paragraphs
        )
