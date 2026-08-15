"""Renders structured resume data into a single-column, ATS-safe PDF.

Two templates are available:

* ``Classic`` - the original layout, using the standard Helvetica core font.
* ``Professional`` - Noto Serif throughout, centred name/contact block,
  ruled section headings, real bullet characters, and entry headers with
  right-aligned dates.

Both use only real text (no images), plain section headings, and keep
contact details in the document body - no tables, text boxes, or
header/footer placement, since ATS parsers frequently drop content from
those areas.
"""

import os
import unicodedata
from functools import lru_cache

from fpdf import FPDF

TEMPLATES = ("Classic", "Professional")
DEFAULT_TEMPLATE = "Classic"

# ---------------------------------------------------------------------------
# Classic template metrics (core font)
# ---------------------------------------------------------------------------

FONT_FAMILY = "Helvetica"
NAME_SIZE = 18
CONTACT_SIZE = 10
HEADING_SIZE = 13
BODY_SIZE = 11
MARGIN_MM = 18
LINE_HEIGHT_MM = 6

# Body copy is left-aligned (ragged right) rather than justified: justification
# stretches word spacing on short resume lines and hurts readability.
BODY_ALIGN = "L"

# Vertical breathing room, in mm.
ENTRY_GAP_MM = 4    # between work/education entries
SECTION_GAP_MM = 5  # above each section heading

# ---------------------------------------------------------------------------
# Professional template metrics (Noto Serif TTF)
# ---------------------------------------------------------------------------

SERIF_FAMILY = "NotoSerif"
FONTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts"
)

# Each style maps to the filenames accepted for it, in preference order. The
# first name is the canonical one; later names are tolerated fallbacks so a
# differently-packaged Noto download still produces a working PDF.
_SERIF_FILES = {
    "": ("NotoSerif-Regular.ttf",),
    "B": ("NotoSerif-Bold.ttf", "NotoSerif_Condensed-Bold.ttf"),
    "I": ("NotoSerif-Italic.ttf",),
}

BULLET_CHAR = "•"  # real bullet, rendered with Noto Serif

PRO_NAME_SIZE = 20
PRO_CONTACT_SIZE = 10
PRO_HEADING_SIZE = 12
PRO_BODY_SIZE = 10.5
PRO_LINE_HEIGHT_MM = 5.6
PRO_ENTRY_GAP_MM = 4.5
PRO_SECTION_GAP_MM = 5.5
PRO_RULE_WIDTH_MM = 0.2  # "thin" horizontal rule under section headings


class FontFileMissing(RuntimeError):
    """Raised when a Professional-template font file cannot be located."""


def serif_font_path(style):
    """Absolute path to the Noto Serif file for ``style`` ("", "B", "I")."""
    for filename in _SERIF_FILES[style]:
        path = os.path.join(FONTS_DIR, filename)
        if os.path.isfile(path):
            return path
    wanted = " or ".join(_SERIF_FILES[style])
    raise FontFileMissing(
        f"Professional template needs {wanted} in {FONTS_DIR}. "
        "Use the Classic template, or add the missing font file."
    )


def serif_fonts_available():
    """True when every Noto Serif style needed by Professional is present."""
    try:
        for style in _SERIF_FILES:
            serif_font_path(style)
    except FontFileMissing:
        return False
    return True


# ---------------------------------------------------------------------------
# Text sanitisation
# ---------------------------------------------------------------------------

_UNICODE_REPLACEMENTS = {
    "–": "-",   # en dash
    "—": "-",   # em dash
    "‘": "'",   # left single quote
    "’": "'",   # right single quote
    "‚": "'",   # single low-9 quote
    "“": '"',   # left double quote
    "”": '"',   # right double quote
    "„": '"',   # double low-9 quote
    "…": "...", # ellipsis
    "•": "-",   # bullet
    "‣": "-",   # triangular bullet
    "◦": "-",   # white bullet
    "⁃": "-",   # hyphen bullet
    "∙": "-",   # bullet operator
}

# Characters fpdf2 handles as layout instructions rather than glyphs; they are
# never looked up in the font's character map.
_LAYOUT_CHARS = "\n\r\t"


@lru_cache(maxsize=1)
def serif_charset():
    """Codepoints supported by *every* registered Noto Serif style.

    Intersecting the styles means a character is only ever passed through if
    it will render in regular, bold and italic alike - the caller does not
    have to know which style is active at the time.

    Returns an empty frozenset if the fonts or fontTools are unavailable, in
    which case sanitisation falls back to the conservative Latin-1 path.
    """
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return frozenset()

    common = None
    for style in _SERIF_FILES:
        try:
            path = serif_font_path(style)
        except FontFileMissing:
            return frozenset()
        try:
            font = TTFont(path, fontNumber=0, lazy=True)
            try:
                codepoints = set(font.getBestCmap())
            finally:
                font.close()
        except Exception:
            return frozenset()
        common = codepoints if common is None else (common & codepoints)
    return frozenset(common or ())


def _ascii_fallback(char):
    """Best-effort ASCII stand-in for a character the active font lacks."""
    replacement = _UNICODE_REPLACEMENTS.get(char)
    if replacement is not None:
        return replacement
    folded = unicodedata.normalize("NFKD", char)
    folded = folded.encode("ascii", errors="ignore").decode("ascii")
    return folded


def sanitize_text(text, charset=None):
    """Make text safe to render, without ever raising during PDF output.

    ``charset`` is the set of codepoints the active font can display:

    * ``None`` (default) - the standard PDF core font (Helvetica) used by the
      Classic template. Common Unicode typography is mapped to ASCII, then
      anything left outside Latin-1 is replaced.
    * a set of codepoints - a Unicode TTF such as Noto Serif. Characters the
      font really supports (bullets, dashes, curly quotes, ellipsis) are kept
      as-is; only genuinely unsupported characters fall back to ASCII, so
      nothing can crash generation regardless of template or font.
    """
    if text is None:
        return ""
    text = str(text)

    if not charset:
        for unicode_char, ascii_equivalent in _UNICODE_REPLACEMENTS.items():
            text = text.replace(unicode_char, ascii_equivalent)
        return text.encode("latin-1", errors="replace").decode("latin-1")

    out = []
    for char in text:
        if char in _LAYOUT_CHARS or ord(char) in charset:
            out.append(char)
            continue
        # Unsupported by this font - substitute, then keep only the part of
        # the substitution the font can actually draw.
        fallback = "".join(c for c in _ascii_fallback(char) if ord(c) in charset)
        out.append(fallback or ("?" if ord("?") in charset else ""))
    return "".join(out)


def _work_entry_bullets(entry):
    """Return the bullet lines to render for a work history entry.

    Prefers the AI-polished result (including any user edits made after
    generation) over the original raw responsibilities text.
    """
    text = entry.get("ai_result") or entry.get("responsibilities") or ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines


def _clean_items(values):
    """Non-empty, stripped strings from a list-of-strings field."""
    return [v.strip() for v in (values or []) if v and v.strip()]


def _education_lines(entry):
    """(name, secondary, dates) for one education entry.

    Both templates already draw exactly these three strings, so branching on
    the school/college type happens here rather than in the renderers.

    An entry with no recognised "entry_type" (one built before the split, or
    passed straight to this module) keeps its original degree/field/dates
    behaviour untouched.
    """
    def field(key):
        return str(entry.get(key) or "").strip()

    name = field("school")
    entry_type = field("entry_type").lower()
    degree_line = " - ".join(p for p in (field("degree"), field("field")) if p)

    if entry_type.startswith("school"):
        secondary = field("board")
        dates = field("year_of_completion") or field("dates")
        grade = field("grade") if entry.get("include_grade") else ""
        extra = f"Grade: {grade}" if grade else ""
    else:
        secondary = degree_line
        years = " - ".join(p for p in (field("start_year"), field("end_year")) if p)
        dates = years or field("dates")
        cgpa = field("cgpa") if entry.get("include_cgpa") else ""
        extra = f"GPA: {cgpa}" if cgpa else ""

    if extra:
        secondary = f"{secondary}  |  {extra}" if secondary else extra
    return name, secondary, dates


def _education_with_content(entries):
    """Education entries worth rendering."""
    kept = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        name, secondary, dates = _education_lines(entry)
        if name or secondary or dates:
            kept.append(entry)
    return kept


def _project_bullets(project):
    """Description lines for a project, AI-polished version preferred."""
    text = project.get("ai_result") or project.get("description") or ""
    return [line.strip() for line in text.splitlines() if line.strip()]


def _projects_with_content(projects):
    """Projects worth rendering; an untouched blank row contributes nothing."""
    kept = []
    for project in projects or []:
        if not isinstance(project, dict):
            continue
        if (str(project.get("name") or "").strip()
                or str(project.get("tech_stack") or "").strip()
                or str(project.get("link") or "").strip()
                or _project_bullets(project)):
            kept.append(project)
    return kept


def _contact_line(personal_info):
    """The email / phone / location line shared by both templates."""
    parts = [
        personal_info.get("email", "").strip(),
        personal_info.get("phone", "").strip(),
        personal_info.get("location", "").strip(),
    ]
    return "  |  ".join(part for part in parts if part)


def _links_line(personal_info):
    """"Label: url" for each provided link, joined for the header.

    A link with no URL is skipped, so an untouched blank row in the UI adds
    nothing to the PDF. The label is the entry's custom label when it has
    one (the "Other" platform), otherwise the platform name.
    """
    rendered = []
    for link in personal_info.get("links") or []:
        if not isinstance(link, dict):
            continue
        url = str(link.get("url") or "").strip()
        if not url:
            continue
        label = str(link.get("custom_label") or "").strip()
        if not label:
            label = str(link.get("platform") or "").strip()
        rendered.append(f"{label}: {url}" if label else url)
    return "  |  ".join(rendered)


# ---------------------------------------------------------------------------
# Classic template
# ---------------------------------------------------------------------------


class ResumePDF(FPDF):
    """FPDF subclass that sanitizes text on every cell/multi_cell call.

    All rendering in this module goes through self.cell/self.multi_cell, so
    overriding them here is sufficient to guarantee no unsanitized text
    (personal info, work history, education, skills, achievements, or
    Gemini-generated content) ever reaches the underlying font renderer.

    The same hook applies the document-wide left alignment: fpdf2's
    multi_cell defaults to justified, so the default is overridden in one
    place rather than at every call site.
    """

    def cell(self, w=None, h=None, text="", *args, **kwargs):
        if "text" in kwargs:
            kwargs["text"] = sanitize_text(kwargs["text"])
        else:
            text = sanitize_text(text)
        return super().cell(w, h, text, *args, **kwargs)

    def multi_cell(self, w, h=None, text="", *args, **kwargs):
        if "text" in kwargs:
            kwargs["text"] = sanitize_text(kwargs["text"])
        else:
            text = sanitize_text(text)
        kwargs.setdefault("align", BODY_ALIGN)
        return super().multi_cell(w, h, text, *args, **kwargs)

    def section_heading(self, title):
        self.ln(SECTION_GAP_MM)
        self.set_font(FONT_FAMILY, "B", HEADING_SIZE)
        self.cell(0, LINE_HEIGHT_MM, title.upper(), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(0, 0, 0)
        y = self.get_y()
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.ln(3)
        self.set_font(FONT_FAMILY, "", BODY_SIZE)


def _render_classic(pdf, personal_info, work_history, education, skills,
                    achievements, certification_items, projects):
    """Original Classic layout. Unchanged except for the optional
    Certifications section, which emits nothing when the caller has not
    enabled it - so default output is byte-identical to before."""

    # ----- Name & contact info (in document body, not header/footer) -----

    pdf.set_font(FONT_FAMILY, "B", NAME_SIZE)
    name = personal_info.get("name", "").strip() or "Resume"
    pdf.cell(0, LINE_HEIGHT_MM + 2, name, new_x="LMARGIN", new_y="NEXT")

    contact_line = _contact_line(personal_info)
    if contact_line:
        pdf.set_font(FONT_FAMILY, "", CONTACT_SIZE)
        pdf.multi_cell(0, LINE_HEIGHT_MM - 1, contact_line)
    links_line = _links_line(personal_info)
    if links_line:
        pdf.set_font(FONT_FAMILY, "", CONTACT_SIZE)
        # multi_cell leaves x at the right margin; reset or the next one has
        # no width to render into.
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, LINE_HEIGHT_MM - 1, links_line)
    pdf.ln(2)

    # ----- Experience -----

    entries_with_content = [
        entry
        for entry in work_history
        if entry.get("company") or entry.get("role") or _work_entry_bullets(entry)
    ]
    if entries_with_content:
        pdf.section_heading("Experience")
        for entry in entries_with_content:
            pdf.set_font(FONT_FAMILY, "B", BODY_SIZE)
            title_line = " - ".join(
                part
                for part in (entry.get("role", "").strip(), entry.get("company", "").strip())
                if part
            )
            if title_line:
                pdf.cell(0, LINE_HEIGHT_MM, title_line, new_x="LMARGIN", new_y="NEXT")

            dates = entry.get("dates", "").strip()
            if dates:
                pdf.set_font(FONT_FAMILY, "I", BODY_SIZE - 1)
                pdf.cell(0, LINE_HEIGHT_MM - 1, dates, new_x="LMARGIN", new_y="NEXT")

            pdf.set_font(FONT_FAMILY, "", BODY_SIZE)
            for bullet in _work_entry_bullets(entry):
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(0, LINE_HEIGHT_MM - 1, f"- {bullet}")
            pdf.ln(ENTRY_GAP_MM)

    # ----- Education -----

    education_entries = _education_with_content(education)
    if education_entries:
        pdf.section_heading("Education")
        for entry in education_entries:
            name, secondary, dates = _education_lines(entry)
            pdf.set_font(FONT_FAMILY, "B", BODY_SIZE)
            pdf.cell(0, LINE_HEIGHT_MM, name, new_x="LMARGIN", new_y="NEXT")
            pdf.set_font(FONT_FAMILY, "", BODY_SIZE)
            if secondary:
                pdf.cell(0, LINE_HEIGHT_MM - 1, secondary, new_x="LMARGIN", new_y="NEXT")
            if dates:
                pdf.set_font(FONT_FAMILY, "I", BODY_SIZE - 1)
                pdf.cell(0, LINE_HEIGHT_MM - 1, dates, new_x="LMARGIN", new_y="NEXT")
                pdf.set_font(FONT_FAMILY, "", BODY_SIZE)
            pdf.ln(ENTRY_GAP_MM)

    # ----- Skills -----

    skill_items = [s.strip() for s in skills if s and s.strip()]
    if skill_items:
        pdf.section_heading("Skills")
        pdf.multi_cell(0, LINE_HEIGHT_MM - 1, ", ".join(skill_items))
        pdf.ln(ENTRY_GAP_MM)

    # ----- Projects -----

    project_entries = _projects_with_content(projects)
    if project_entries:
        pdf.section_heading("Projects")
        for project in project_entries:
            name = str(project.get("name") or "").strip()
            if name:
                pdf.set_font(FONT_FAMILY, "B", BODY_SIZE)
                pdf.cell(0, LINE_HEIGHT_MM, name, new_x="LMARGIN", new_y="NEXT")

            tech_stack = str(project.get("tech_stack") or "").strip()
            if tech_stack:
                pdf.set_font(FONT_FAMILY, "I", BODY_SIZE - 1)
                pdf.cell(0, LINE_HEIGHT_MM - 1, tech_stack,
                         new_x="LMARGIN", new_y="NEXT")

            pdf.set_font(FONT_FAMILY, "", BODY_SIZE)
            for bullet in _project_bullets(project):
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(0, LINE_HEIGHT_MM - 1, f"- {bullet}")

            link = str(project.get("link") or "").strip()
            if link:
                pdf.set_font(FONT_FAMILY, "", BODY_SIZE - 1)
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(0, LINE_HEIGHT_MM - 1, f"Link: {link}")
            pdf.ln(ENTRY_GAP_MM)

    # ----- Certifications (optional, opt-in) -----

    if certification_items:
        pdf.section_heading("Certifications")
        for certification in certification_items:
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(0, LINE_HEIGHT_MM - 1, f"- {certification}")
        pdf.ln(ENTRY_GAP_MM)

    # ----- Achievements -----

    achievement_items = [a.strip() for a in achievements if a and a.strip()]
    if achievement_items:
        pdf.section_heading("Achievements")
        for achievement in achievement_items:
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(0, LINE_HEIGHT_MM - 1, f"- {achievement}")


# ---------------------------------------------------------------------------
# Professional template
# ---------------------------------------------------------------------------


class ProfessionalResumePDF(FPDF):
    """Noto Serif resume renderer.

    Deliberately a sibling of ResumePDF rather than a subclass: keeping the
    two templates' rendering hooks independent guarantees that work here can
    never alter Classic's output.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        for style in _SERIF_FILES:
            self.add_font(SERIF_FAMILY, style, serif_font_path(style))
        self._charset = serif_charset()

    # -- sanitising hooks --------------------------------------------------

    def clean(self, text):
        return sanitize_text(text, self._charset)

    def cell(self, w=None, h=None, text="", *args, **kwargs):
        if "text" in kwargs:
            kwargs["text"] = self.clean(kwargs["text"])
        else:
            text = self.clean(text)
        return super().cell(w, h, text, *args, **kwargs)

    def multi_cell(self, w, h=None, text="", *args, **kwargs):
        if "text" in kwargs:
            kwargs["text"] = self.clean(kwargs["text"])
        else:
            text = self.clean(text)
        kwargs.setdefault("align", BODY_ALIGN)
        return super().multi_cell(w, h, text, *args, **kwargs)

    # -- layout helpers ----------------------------------------------------

    @property
    def usable_width(self):
        return self.w - self.l_margin - self.r_margin

    def body_font(self, style="", size=PRO_BODY_SIZE):
        self.set_font(SERIF_FAMILY, style, size)

    def section_heading(self, title):
        """Bold heading with a thin horizontal rule underneath."""
        self.ln(PRO_SECTION_GAP_MM)
        self.set_font(SERIF_FAMILY, "B", PRO_HEADING_SIZE)
        self.cell(0, PRO_LINE_HEIGHT_MM, title.upper(),
                  new_x="LMARGIN", new_y="NEXT")
        previous_width = self.line_width
        self.set_line_width(PRO_RULE_WIDTH_MM)
        self.set_draw_color(0, 0, 0)
        y = self.get_y()
        self.line(self.l_margin, y, self.w - self.r_margin, y)
        self.set_line_width(previous_width)
        self.ln(2.6)
        self.body_font()

    def entry_header(self, primary, dates):
        """Bold ``primary`` on the left, ``dates`` right-aligned, one line."""
        primary = primary.strip()
        dates = (dates or "").strip()
        if not primary and not dates:
            return

        # Measure the dates in the font they will actually be drawn with, so
        # the bold left-hand cell gets exactly the remaining width.
        dates_width = 0.0
        if dates:
            self.body_font("", PRO_BODY_SIZE - 0.5)
            dates_width = self.get_string_width(self.clean(dates)) + 1.5

        self.set_font(SERIF_FAMILY, "B", PRO_BODY_SIZE)
        left_width = max(self.usable_width - dates_width, 1.0)
        if dates:
            self.cell(left_width, PRO_LINE_HEIGHT_MM, primary,
                      new_x="RIGHT", new_y="TOP")
            self.body_font("", PRO_BODY_SIZE - 0.5)
            self.cell(dates_width, PRO_LINE_HEIGHT_MM, dates, align="R",
                      new_x="LMARGIN", new_y="NEXT")
        else:
            self.cell(self.usable_width, PRO_LINE_HEIGHT_MM, primary,
                      new_x="LMARGIN", new_y="NEXT")

    def subtitle(self, text):
        """Italic secondary line (role / degree)."""
        text = (text or "").strip()
        if not text:
            return
        self.body_font("I")
        self.cell(0, PRO_LINE_HEIGHT_MM, text, new_x="LMARGIN", new_y="NEXT")

    def bullet(self, text):
        """One list item using the real bullet character."""
        self.body_font()
        self.set_x(self.l_margin)
        self.multi_cell(0, PRO_LINE_HEIGHT_MM, f"{BULLET_CHAR} {text}")


def _render_professional(pdf, personal_info, work_history, education, skills,
                         achievements, certification_items, projects):
    """Serif template: centred header, ruled sections, real bullets."""

    # ----- Name & contact, centred (still body text, not a header) -----

    pdf.set_font(SERIF_FAMILY, "B", PRO_NAME_SIZE)
    name = personal_info.get("name", "").strip() or "Resume"
    pdf.cell(0, PRO_LINE_HEIGHT_MM + 3, name, align="C",
             new_x="LMARGIN", new_y="NEXT")

    contact_line = _contact_line(personal_info)
    if contact_line:
        pdf.body_font("", PRO_CONTACT_SIZE)
        pdf.multi_cell(0, PRO_LINE_HEIGHT_MM - 0.6, contact_line, align="C")
    links_line = _links_line(personal_info)
    if links_line:
        pdf.body_font("", PRO_CONTACT_SIZE)
        # multi_cell leaves x at the right margin; reset or the next one has
        # no width to render into.
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, PRO_LINE_HEIGHT_MM - 0.6, links_line, align="C")
    pdf.ln(1.5)

    # ----- Experience -----

    entries_with_content = [
        entry
        for entry in work_history
        if entry.get("company") or entry.get("role") or _work_entry_bullets(entry)
    ]
    if entries_with_content:
        pdf.section_heading("Experience")
        for entry in entries_with_content:
            pdf.entry_header(entry.get("company", ""), entry.get("dates", ""))
            pdf.subtitle(entry.get("role", ""))
            for bullet in _work_entry_bullets(entry):
                pdf.bullet(bullet)
            pdf.ln(PRO_ENTRY_GAP_MM)

    # ----- Education -----

    education_entries = _education_with_content(education)
    if education_entries:
        pdf.section_heading("Education")
        for entry in education_entries:
            name, secondary, dates = _education_lines(entry)
            pdf.entry_header(name, dates)
            pdf.subtitle(secondary)
            pdf.ln(PRO_ENTRY_GAP_MM)

    # ----- Skills -----

    skill_items = _clean_items(skills)
    if skill_items:
        pdf.section_heading("Skills")
        pdf.body_font()
        pdf.multi_cell(0, PRO_LINE_HEIGHT_MM, ", ".join(skill_items))
        pdf.ln(PRO_ENTRY_GAP_MM)

    # ----- Projects -----

    project_entries = _projects_with_content(projects)
    if project_entries:
        pdf.section_heading("Projects")
        for project in project_entries:
            pdf.entry_header(str(project.get("name") or ""), "")
            pdf.subtitle(str(project.get("tech_stack") or ""))
            for bullet in _project_bullets(project):
                pdf.bullet(bullet)

            link = str(project.get("link") or "").strip()
            if link:
                pdf.body_font("", PRO_BODY_SIZE - 0.5)
                pdf.set_x(pdf.l_margin)
                pdf.multi_cell(0, PRO_LINE_HEIGHT_MM, f"Link: {link}")
            pdf.ln(PRO_ENTRY_GAP_MM)

    # ----- Certifications (optional, opt-in) -----

    if certification_items:
        pdf.section_heading("Certifications")
        for certification in certification_items:
            pdf.bullet(certification)
        pdf.ln(PRO_ENTRY_GAP_MM)

    # ----- Achievements -----

    achievement_items = _clean_items(achievements)
    if achievement_items:
        pdf.section_heading("Achievements")
        for achievement in achievement_items:
            pdf.bullet(achievement)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def generate_resume_pdf(personal_info, work_history, education, skills,
                        achievements, certifications=None,
                        include_certifications=False,
                        projects=None,
                        template=DEFAULT_TEMPLATE):
    """Build an ATS-safe resume PDF and return it as bytes.

    All arguments use the same structures held in Streamlit session_state
    (see app.py), so AI-polished/edited work bullets are used as-is.

    ``template`` selects the layout: "Classic" (default) or "Professional".
    The Certifications section is rendered only when ``include_certifications``
    is true *and* ``certifications`` holds at least one non-empty entry.
    ``projects`` renders between Skills and Certifications, and is skipped
    entirely when no project has any content.
    """
    if template not in TEMPLATES:
        raise ValueError(
            f"Unknown template {template!r}; expected one of {', '.join(TEMPLATES)}"
        )

    certification_items = (
        _clean_items(certifications) if include_certifications else []
    )

    if template == "Professional":
        pdf = ProfessionalResumePDF(format="Letter")
        render = _render_professional
    else:
        pdf = ResumePDF(format="Letter")
        render = _render_classic

    pdf.set_auto_page_break(auto=True, margin=MARGIN_MM)
    pdf.set_margins(MARGIN_MM, MARGIN_MM, MARGIN_MM)
    pdf.add_page()

    render(pdf, personal_info, work_history, education, skills, achievements,
           certification_items, projects)

    return bytes(pdf.output())
