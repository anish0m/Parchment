"""Builds small PDFs for tests, so no binary fixtures live in the repo."""

import io


def _escape(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages):
    """Returns PDF bytes with one page per item; each item is a list of text lines.

    A page given as None has no text at all, like a scanned image. A page can also
    be a list of (x, y, lines) blocks to place text, e.g. in two columns.
    """
    objects = []

    def add(body):
        objects.append(body)
        return len(objects)

    catalog = add(None)
    pages_obj = add(None)
    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    page_ids = []
    for lines in pages:
        if lines is None:
            stream = b"0.5 g 72 72 468 648 re f"  # a filled box, no text
        else:
            # A page is a list of lines, or a list of (x, y, lines) blocks for layouts.
            blocks = lines if lines and isinstance(lines[0], tuple) else [(72, 740, lines)]
            ops = []
            for x, y, block_lines in blocks:
                ops += ["BT", "/F1 11 Tf", "14 TL", f"{x} {y} Td"]
                ops += [f"({_escape(line)}) Tj T*" for line in block_lines]
                ops.append("ET")
            stream = "\n".join(ops).encode("latin-1")
        content = add(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
        page_ids.append(
            add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] "
                b"/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
                % (pages_obj, font, content)
            )
        )

    kids = b" ".join(b"%d 0 R" % i for i in page_ids)
    objects[catalog - 1] = b"<< /Type /Catalog /Pages %d 0 R >>" % pages_obj
    objects[pages_obj - 1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_ids))

    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n%s\nendobj\n" % (number, body))
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(
        b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objects) + 1, catalog, xref)
    )
    return out.getvalue()


def make_encrypted_pdf(pages, password="secret"):
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(make_pdf(pages))))
    writer.encrypt(user_password=password, algorithm="RC4-128")
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


LECTURE = [
    [
        "Biology 101 - Lecture Notes",
        "Photosynthesis",
        "Photosynthesis converts light energy into chemical energy. It takes",
        "place in the chloroplasts of plant cells.",
        "1",
    ],
    [
        "Biology 101 - Lecture Notes",
        "The light reactions happen in the thylakoid membranes and produce ATP",
        "and NADPH. Oxygen is released as a by-product.",
        "2",
    ],
    [
        "Biology 101 - Lecture Notes",
        "The Calvin cycle uses ATP and NADPH to fix carbon dioxide into sugar.",
        "3",
    ],
]


LEFT_COLUMN = [
    "Enzymes are proteins that speed up",
    "chemical reactions in living cells.",
    "They lower the activation energy",
    "needed for a reaction to start.",
    "Each enzyme binds a specific substrate",
    "at a region called the active site.",
]
RIGHT_COLUMN = [
    "Temperature and pH both affect how",
    "well an enzyme works in the body.",
    "Too much heat changes the shape of",
    "the active site and denatures it.",
    "Inhibitors can block the active site",
    "and slow the reaction right down.",
]
TWO_COLUMNS = [
    (180, 750, ["Enzymes and Reaction Rates: Week Three Overview"]),
    (72, 700, LEFT_COLUMN),
    (320, 700, RIGHT_COLUMN),
]

GLOSSARY_TERMS = ["Osmosis", "Diffusion", "Enzyme", "Substrate", "Catalyst", "Inhibitor"]
GLOSSARY_DEFINITIONS = [
    "Water moving across a membrane towards more solute.",
    "Particles spreading from high to low concentration.",
    "A protein that speeds up a chemical reaction.",
    "The molecule an enzyme binds to and changes.",
    "Anything that speeds up a reaction without being used.",
    "A molecule that slows or stops an enzyme working.",
]
GLOSSARY_TABLE = [(72, 700, GLOSSARY_TERMS), (200, 700, GLOSSARY_DEFINITIONS)]
