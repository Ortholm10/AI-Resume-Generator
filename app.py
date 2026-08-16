import inspect
import uuid

import fitz
import streamlit as st

from src import ai_engine, docx_generator, pdf_generator

st.title("AI Resume Generator")


# ---------- Mount-in animation for conditionally shown blocks ----------

def _container_keys_supported():
    """True when this Streamlit build accepts st.container(key=...).

    Container keys are what put an addressable `st-key-<key>` class in the
    DOM for CSS to hook onto. Older builds lack the parameter, so probe
    rather than assume.
    """
    try:
        return "key" in inspect.signature(st.container).parameters
    except (TypeError, ValueError):
        return False


_CONTAINER_KEYS_SUPPORTED = _container_keys_supported()

# One rule for every animated block: containers are keyed "anim-*", which
# Streamlit renders as a class of "st-key-anim-*".
_MOUNT_ANIMATION_CSS = """
<style>
@keyframes resumeMountIn {
  from { opacity: 0; transform: translateY(-8px); }
  to   { opacity: 1; transform: translateY(0); }
}
[class*="st-key-anim-"] {
  animation: resumeMountIn 300ms ease-out both;
}
@media (prefers-reduced-motion: reduce) {
  [class*="st-key-anim-"] { animation: none; }
}
</style>
"""

if _CONTAINER_KEYS_SUPPORTED:
    if hasattr(st, "html"):
        st.html(_MOUNT_ANIMATION_CSS)
    else:
        st.markdown(_MOUNT_ANIMATION_CSS, unsafe_allow_html=True)

# Dark theme polish: card-style section containers, glowing buttons, and
# softer input borders. Pure CSS — no widget logic, keys, or state touched.
_DARK_THEME_CSS = """
<style>
div[data-testid="stVerticalBlockBorderWrapper"] {
  border-radius: 14px !important;
  box-shadow: 0 4px 18px rgba(0, 0, 0, 0.35);
  background: #1a1d27;
}
div[data-testid="stForm"] {
  border-radius: 14px !important;
  box-shadow: 0 4px 18px rgba(0, 0, 0, 0.35);
  background: #1a1d27;
}
.stButton > button, .stFormSubmitButton > button, .stDownloadButton > button {
  border-radius: 10px;
  transition: box-shadow 200ms ease, transform 150ms ease;
}
.stButton > button:hover, .stFormSubmitButton > button:hover,
.stDownloadButton > button:hover {
  box-shadow: 0 0 16px rgba(99, 102, 241, 0.55);
  transform: translateY(-1px);
}
div[data-baseweb="input"], div[data-baseweb="textarea"], div[data-baseweb="select"] {
  border-radius: 10px !important;
}
div[data-baseweb="input"]:focus-within, div[data-baseweb="textarea"]:focus-within,
div[data-baseweb="select"]:focus-within {
  box-shadow: 0 0 0 2px rgba(99, 102, 241, 0.45);
}
</style>
"""

if hasattr(st, "html"):
    st.html(_DARK_THEME_CSS)
else:
    st.markdown(_DARK_THEME_CSS, unsafe_allow_html=True)


def _animated_container(key):
    """A container that fades and slides in when it mounts.

    Degrades to a plain container (instant show/hide, no error) when the
    installed Streamlit cannot key containers.
    """
    if not _CONTAINER_KEYS_SUPPORTED:
        return st.container()
    return st.container(key=f"anim-{key}")


def _card_container(key):
    """A bordered, card-styled container for grouping a page section.

    Purely visual (see _DARK_THEME_CSS below); degrades to a plain
    container when the installed Streamlit cannot key/border containers.
    """
    if not _CONTAINER_KEYS_SUPPORTED:
        return st.container()
    return st.container(border=True, key=f"card-{key}")


def _run_ai_call(entry, func, *args, spinner_text, **kwargs):
    """Run a Gemini call with a spinner, capturing errors on the entry.

    Returns the call's result, or None if it raised AIEngineError (in which
    case entry["ai_error"] is set for inline display).
    """
    entry["ai_error"] = ""
    try:
        with st.spinner(spinner_text):
            return func(*args, **kwargs)
    except ai_engine.AIEngineError as error:
        entry["ai_error"] = str(error)
        return None


def _generate_and_store(entry, answers, source_key="responsibilities"):
    """Polish an entry's free text into bullets.

    ``source_key`` names the field holding the raw text, so work history
    ("responsibilities") and projects ("description") share this path.
    """
    result = _run_ai_call(
        entry,
        ai_engine.enhance_resume_content,
        entry[source_key],
        answers=answers,
        spinner_text="Polishing this entry with AI...",
    )
    if result is not None:
        entry["ai_result"] = "\n".join(result["bullet_points"])


def _uid():
    """Short, stable identifier for one repeatable list item.

    Widget keys are built from this rather than the list index. Index-based
    keys break on removal: Streamlit keeps the stored value for
    e.g. "work_company_1", but after a pop the entry at index 1 is a
    different record, so text jumps between entries or comes back blank.
    """
    return uuid.uuid4().hex[:8]


def _new_work_entry():
    return {
        "uid": _uid(),
        "company": "",
        "role": "",
        "dates": "",
        "responsibilities": "",
        # AI enhancement state
        "ai_questions": None,  # None = not fetched yet; [] once fetched with no questions
        "ai_answers": [],
        "ai_skipped": False,
        "ai_result": "",
        "ai_error": "",
    }


EDUCATION_SCHOOL = "School"
EDUCATION_COLLEGE = "College/University"
EDUCATION_TYPES = [EDUCATION_SCHOOL, EDUCATION_COLLEGE]


def _new_education_entry():
    return {
        "uid": _uid(),
        "entry_type": EDUCATION_COLLEGE,
        # Shared: the institution name, however it is labelled.
        "school": "",
        # College/University
        "degree": "",
        "field": "",
        "start_year": "",
        "end_year": "",
        "include_cgpa": False,
        "cgpa": "",
        # School
        "board": "",
        "year_of_completion": "",
        "include_grade": False,
        "grade": "",
        # Retained so entries created before the school/college split still
        # render their original date string.
        "dates": "",
    }


_EDUCATION_DEFAULTS = {
    "entry_type": EDUCATION_COLLEGE,
    "school": "", "degree": "", "field": "",
    "start_year": "", "end_year": "", "include_cgpa": False, "cgpa": "",
    "board": "", "year_of_completion": "", "include_grade": False, "grade": "",
    "dates": "",
}


def _normalise_education(entries):
    """Backfill the school/college fields on pre-existing entries."""
    for entry in entries:
        for key, default in _EDUCATION_DEFAULTS.items():
            entry.setdefault(key, default)
        if entry["entry_type"] not in EDUCATION_TYPES:
            entry["entry_type"] = EDUCATION_COLLEGE


def _new_project():
    return {
        "uid": _uid(),
        "name": "",
        "tech_stack": "",
        "description": "",
        "link": "",
        # AI enhancement state, mirroring a work history entry
        "ai_questions": None,
        "ai_answers": [],
        "ai_skipped": False,
        "ai_result": "",
        "ai_error": "",
    }


def _new_text_item():
    """A skill / achievement / certification record."""
    return {"uid": _uid(), "text": ""}


LINK_PLATFORMS = [
    "LinkedIn",
    "GitHub",
    "LeetCode",
    "Portfolio/Website",
    "Instagram",
    "Other",
]
OTHER_PLATFORM = "Other"


def _new_link():
    return {"uid": _uid(), "platform": LINK_PLATFORMS[0], "url": "", "custom_label": ""}


def _normalise_links(personal_info):
    """Ensure personal_info["links"] exists and every record is well formed.

    Also migrates the single "linkedin" string this list replaced, so a
    session opened before the change keeps its URL.
    """
    links = personal_info.get("links")
    if not isinstance(links, list):
        links = []
    legacy = personal_info.pop("linkedin", "")
    if isinstance(legacy, str) and legacy.strip():
        links.append({"uid": _uid(), "platform": "LinkedIn",
                      "url": legacy.strip(), "custom_label": ""})
    for i, link in enumerate(links):
        if not isinstance(link, dict):
            link = {"url": str(link)}
        links[i] = {
            "uid": link.get("uid") or _uid(),
            "platform": link.get("platform") or LINK_PLATFORMS[0],
            "url": link.get("url", ""),
            "custom_label": link.get("custom_label", ""),
        }
    if not links:
        links.append(_new_link())
    personal_info["links"] = links


def _ensure_uids(entries):
    """Give any entry that predates uid support one (in place)."""
    for entry in entries:
        if not entry.get("uid"):
            entry["uid"] = _uid()


def _normalise_text_items(field):
    """Upgrade a plain list[str] field to [{"uid", "text"}] records in place.

    Keeps an already-open browser session working after a reload.
    """
    items = st.session_state[field]
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            items[i] = {"uid": _uid(), "text": item}
        elif not item.get("uid"):
            item["uid"] = _uid()


def _texts(items):
    """The plain strings behind a list of text records (what the PDF wants)."""
    return [item["text"] for item in items]


# ---------- Export helpers ----------

_TEMPLATE_HELP = {
    "Classic": "Helvetica, left-aligned headings — the original layout.",
    "Professional": (
        "Noto Serif, centred name and contact block, ruled section headings, "
        "real bullet points, and dates right-aligned beside each employer."
    ),
}


def _resume_file_name():
    return (
        st.session_state.personal_info.get("name", "").strip().replace(" ", "_")
        or "resume"
    )


def _build_preview_pdf():
    """Same call the download flow makes, with the current session values."""
    return pdf_generator.generate_resume_pdf(
        st.session_state.personal_info,
        st.session_state.work_history,
        st.session_state.education,
        _texts(st.session_state.skills),
        _texts(st.session_state.achievements),
        projects=st.session_state.projects,
        certifications=_texts(st.session_state.certifications),
        include_certifications=st.session_state.include_certifications,
        template=st.session_state.template,
    )


def _build_resume_docx():
    """DOCX from the same session values, honouring the certifications toggle."""
    return docx_generator.generate_resume_docx(
        st.session_state.personal_info,
        st.session_state.work_history,
        st.session_state.education,
        _texts(st.session_state.skills),
        _texts(st.session_state.achievements),
        _texts(st.session_state.certifications)
        if st.session_state.include_certifications
        else [],
        st.session_state.projects,
        st.session_state.personal_info.get("links", []),
        template=st.session_state.template,
    )


def _pdf_bytes_to_page_images(pdf_bytes, zoom=2.0):
    """Render each page of a PDF (given as bytes) to PNG image bytes.

    Data-URI iframes are blocked by Chrome's iframe navigation restrictions,
    so the preview renders pages as images instead.
    """
    matrix = fitz.Matrix(zoom, zoom)
    images = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            pixmap = page.get_pixmap(matrix=matrix)
            images.append(pixmap.tobytes("png"))
    return images


# ---------- Session State Initialization ----------

if "personal_info" not in st.session_state:
    st.session_state.personal_info = {
        "name": "",
        "email": "",
        "phone": "",
        "location": "",
        "links": [_new_link()],
    }

if "work_history" not in st.session_state:
    st.session_state.work_history = [_new_work_entry()]

if "education" not in st.session_state:
    st.session_state.education = [_new_education_entry()]

if "skills" not in st.session_state:
    st.session_state.skills = [_new_text_item()]

if "achievements" not in st.session_state:
    st.session_state.achievements = [_new_text_item()]

if "projects" not in st.session_state:
    st.session_state.projects = [_new_project()]

if "certifications" not in st.session_state:
    st.session_state.certifications = [_new_text_item()]

if "include_certifications" not in st.session_state:
    st.session_state.include_certifications = True

if "template" not in st.session_state:
    st.session_state.template = pdf_generator.DEFAULT_TEMPLATE

if "errors" not in st.session_state:
    st.session_state.errors = []

if "submitted" not in st.session_state:
    st.session_state.submitted = False

if "current_step" not in st.session_state:
    st.session_state.current_step = 0

# Streamlit discards a keyed widget's session_state entry on any run where
# that widget is not drawn — which, now that one step renders at a time, is
# most runs. Every other field is mirrored into its own dict and re-seeded
# through value=, but the certifications toggle lives only in widget state,
# so re-assert it each run to stop an unchecked box springing back to True
# while the user is on another step.
if "include_certifications" in st.session_state:
    st.session_state.include_certifications = st.session_state.include_certifications

# Sessions started before uids existed keep working.
_ensure_uids(st.session_state.work_history)
_ensure_uids(st.session_state.education)
_ensure_uids(st.session_state.projects)
_normalise_education(st.session_state.education)
for _field in ("skills", "achievements", "certifications"):
    _normalise_text_items(_field)
_normalise_links(st.session_state.personal_info)


# ---------- Wizard scaffolding ----------

STEPS = [
    "Personal Info",
    "Work History",
    "Education",
    "Skills & Projects",
    "Certifications & Achievements",
    "Review & Export",
]
LAST_STEP = len(STEPS) - 1


def _render_step_nav():
    """Back / Next for the current step, with the ends trimmed off.

    Only the step counter moves; every answer stays in session_state, so
    stepping away and back re-renders the same data.
    """
    st.divider()
    step = st.session_state.current_step
    col_back, _gap, col_next = st.columns([1, 4, 1])
    with col_back:
        if step > 0:
            if st.button("Back", key=f"nav_back_{step}", width="stretch"):
                st.session_state.current_step = step - 1
                st.rerun()
    with col_next:
        if step < LAST_STEP:
            if st.button("Next", key=f"nav_next_{step}", type="primary",
                         width="stretch"):
                st.session_state.current_step = step + 1
                st.rerun()


# ---------- Live (text-only) preview ----------

def _md_escape(text):
    """Neutralise the markdown characters most likely to garble the preview."""
    out = str(text)
    for char in ("\\", "`", "*", "_", "[", "]"):
        out = out.replace(char, "\\" + char)
    return out


def _link_label(link):
    """How a link is titled: its platform, or the name typed for "Other"."""
    if link["platform"] == OTHER_PLATFORM:
        return link["custom_label"].strip() or OTHER_PLATFORM
    return link["platform"]


def _preview_bullets(entry, source_key):
    """The lines an entry contributes: AI output when present, else raw text."""
    text = (entry.get("ai_result") or "").strip()
    if not text:
        text = (entry.get(source_key) or "").strip()
    bullets = []
    for line in text.splitlines():
        cleaned = line.strip().lstrip("-*• ").strip()
        if cleaned:
            bullets.append(cleaned)
    return bullets


def _preview_education(entry):
    """(headline, detail line) for one education record, honouring its type."""
    school = entry["school"].strip()
    if entry["entry_type"] == EDUCATION_SCHOOL:
        head = school
        detail = [entry["board"].strip(), entry["year_of_completion"].strip()]
        if entry["include_grade"] and entry["grade"].strip():
            detail.append(entry["grade"].strip())
    else:
        qualification = " ".join(
            part for part in (entry["degree"].strip(), entry["field"].strip()) if part
        )
        head = " — ".join(part for part in (school, qualification) if part)
        years = " – ".join(
            part for part in (entry["start_year"].strip(), entry["end_year"].strip())
            if part
        )
        detail = [years]
        if entry["include_cgpa"] and entry["cgpa"].strip():
            detail.append(f"CGPA {entry['cgpa'].strip()}")
    detail = [part for part in detail if part]
    # Entries predating the school/college split only carry a date string.
    if not detail and entry["dates"].strip():
        detail = [entry["dates"].strip()]
    return head, " · ".join(detail)


def _titled_block(lines, bullets):
    """One preview record: title/subtitle lines above an optional bullet list."""
    block = "  \n".join(lines)
    if not bullets:
        return block
    bullet_md = "\n".join(f"- {_md_escape(b)}" for b in bullets)
    return f"{block}\n\n{bullet_md}" if block else bullet_md


def _live_preview_markdown():
    """A cheap text rendering of everything captured so far.

    Reads session_state straight through and returns markdown — no PDF is
    built, so this can redraw on every rerun. The full-fidelity page images
    still live on the Review & Export step.
    """
    info = st.session_state.personal_info
    blocks = []

    header = []
    if info["name"].strip():
        header.append(f"### {_md_escape(info['name'].strip())}")
    contact = [
        info[field].strip()
        for field in ("email", "phone", "location")
        if info[field].strip()
    ]
    if contact:
        header.append(_md_escape(" · ".join(contact)))
    if header:
        blocks.append("\n\n".join(header))

    link_lines = [
        f"- {_md_escape(_link_label(link))}: {_md_escape(link['url'].strip())}"
        for link in info.get("links", [])
        if link["url"].strip()
    ]
    if link_lines:
        blocks.append("\n".join(link_lines))

    work_blocks = []
    for entry in st.session_state.work_history:
        bullets = _preview_bullets(entry, "responsibilities")
        head = " — ".join(
            part for part in (entry["role"].strip(), entry["company"].strip()) if part
        )
        if not (head or bullets or entry["dates"].strip()):
            continue
        lines = []
        if head:
            lines.append(f"**{_md_escape(head)}**")
        if entry["dates"].strip():
            lines.append(f"*{_md_escape(entry['dates'].strip())}*")
        work_blocks.append(_titled_block(lines, bullets))
    if work_blocks:
        blocks.append("**EXPERIENCE**")
        blocks.extend(work_blocks)

    education_blocks = []
    for entry in st.session_state.education:
        head, detail = _preview_education(entry)
        if not (head or detail):
            continue
        lines = []
        if head:
            lines.append(f"**{_md_escape(head)}**")
        if detail:
            lines.append(f"*{_md_escape(detail)}*")
        education_blocks.append("  \n".join(lines))
    if education_blocks:
        blocks.append("**EDUCATION**")
        blocks.extend(education_blocks)

    skills = [item["text"].strip() for item in st.session_state.skills
              if item["text"].strip()]
    if skills:
        blocks.append("**SKILLS**")
        blocks.append(_md_escape(" · ".join(skills)))

    project_blocks = []
    for project in st.session_state.projects:
        bullets = _preview_bullets(project, "description")
        name = project["name"].strip()
        if not (name or bullets or project["tech_stack"].strip()):
            continue
        lines = []
        if name:
            lines.append(f"**{_md_escape(name)}**")
        if project["tech_stack"].strip():
            lines.append(f"*{_md_escape(project['tech_stack'].strip())}*")
        if project["link"].strip():
            lines.append(_md_escape(project["link"].strip()))
        project_blocks.append(_titled_block(lines, bullets))
    if project_blocks:
        blocks.append("**PROJECTS**")
        blocks.extend(project_blocks)

    if st.session_state.include_certifications:
        certifications = [item["text"].strip()
                          for item in st.session_state.certifications
                          if item["text"].strip()]
        if certifications:
            blocks.append("**CERTIFICATIONS**")
            blocks.append("\n".join(f"- {_md_escape(c)}" for c in certifications))

    achievements = [item["text"].strip() for item in st.session_state.achievements
                    if item["text"].strip()]
    if achievements:
        blocks.append("**ACHIEVEMENTS**")
        blocks.append("\n".join(f"- {_md_escape(a)}" for a in achievements))

    return "\n\n".join(blocks)


def _render_live_preview():
    """The right-hand column on every form step."""
    with _card_container("live_preview"):
        st.markdown("#### Live preview")
        st.caption(
            "Everything entered so far, across all steps. The formatted page "
            "preview is on Review & Export."
        )
        markdown = _live_preview_markdown()
        if markdown.strip():
            st.markdown(markdown)
        else:
            st.info("Nothing entered yet — start with your name and email.")


# ---------- Progress ----------

_step = st.session_state.current_step
st.progress(
    (_step + 1) / len(STEPS),
    text=f"Step {_step + 1} of {len(STEPS)}: {STEPS[_step]}",
)


# ---------- Step 1: Personal Info + Links ----------

if _step == 0:
    _form_col, _preview_col = st.columns([3, 2])

    with _form_col:
        st.header("Personal Information")

        with _card_container("personal_info"):
            # These fields are static, so they can live in a form: values commit once, on
            # "Save Personal Info", instead of needing Enter on each field. The sections
            # below stay outside any form because Streamlit disallows the add/remove
            # buttons they rely on inside one.
            with st.form(key="personal_info_form"):
                _name = st.text_input(
                    "Full Name *", value=st.session_state.personal_info["name"]
                )
                _email = st.text_input(
                    "Email *", value=st.session_state.personal_info["email"]
                )
                _phone = st.text_input(
                    "Phone", value=st.session_state.personal_info["phone"]
                )
                _location = st.text_input(
                    "Location", value=st.session_state.personal_info["location"]
                )
                _personal_info_saved = st.form_submit_button("Save Personal Info")

            if _personal_info_saved:
                # Update in place: the same dict object and keys the PDF generator and AI
                # enhancement already read from.
                st.session_state.personal_info["name"] = _name
                st.session_state.personal_info["email"] = _email
                st.session_state.personal_info["phone"] = _phone
                st.session_state.personal_info["location"] = _location
                st.success("Personal info saved")

            # Links replace the old single LinkedIn field. They sit outside the form
            # above because their add/remove buttons cannot live inside one, and they
            # save as you edit rather than on "Save Personal Info".
            st.subheader("Links")

            _links = st.session_state.personal_info["links"]
            for i, link in enumerate(_links):
                uid = link["uid"]
                col1, col2, col3 = st.columns([2, 3, 1])
                with col1:
                    link["platform"] = st.selectbox(
                        f"Platform {i + 1}",
                        LINK_PLATFORMS,
                        index=LINK_PLATFORMS.index(link["platform"])
                        if link["platform"] in LINK_PLATFORMS
                        else 0,
                        key=f"link_platform_{uid}",
                    )
                with col2:
                    link["url"] = st.text_input(
                        f"URL {i + 1}", value=link["url"], key=f"link_url_{uid}"
                    )
                with col3:
                    if len(_links) > 1:
                        if st.button("Remove", key=f"remove_link_{uid}"):
                            st.session_state.personal_info["links"] = [
                                l for l in _links if l["uid"] != uid
                            ]
                            st.rerun()
                if link["platform"] == OTHER_PLATFORM:
                    link["custom_label"] = st.text_input(
                        f"Custom label {i + 1}",
                        value=link["custom_label"],
                        key=f"link_label_{uid}",
                    )
                else:
                    # Only "Other" carries a custom label; clear it so a stale value
                    # cannot override a named platform in the PDF.
                    link["custom_label"] = ""

            if st.button("Add Link"):
                st.session_state.personal_info["links"].append(_new_link())
                st.rerun()

    with _preview_col:
        _render_live_preview()


# ---------- Step 2: Work History ----------

elif _step == 1:
    _form_col, _preview_col = st.columns([3, 2])

    with _form_col:
        st.header("Work History")

        with _card_container("work_history"):
            for i, entry in enumerate(st.session_state.work_history):
                uid = entry["uid"]
                st.subheader(f"Entry {i + 1}")
                entry["company"] = st.text_input(
                    "Company", value=entry["company"], key=f"work_company_{uid}"
                )
                entry["role"] = st.text_input(
                    "Role", value=entry["role"], key=f"work_role_{uid}"
                )
                entry["dates"] = st.text_input(
                    "Dates", value=entry["dates"], key=f"work_dates_{uid}"
                )
                entry["responsibilities"] = st.text_area(
                    "Responsibilities", value=entry["responsibilities"],
                    key=f"work_resp_{uid}",
                )

                # ----- AI Enhancement -----

                entry.setdefault("ai_questions", None)
                entry.setdefault("ai_answers", [])
                entry.setdefault("ai_skipped", False)
                entry.setdefault("ai_result", "")
                entry.setdefault("ai_error", "")

                if st.button("Enhance with AI", key=f"enhance_{uid}"):
                    entry["ai_result"] = ""
                    entry["ai_skipped"] = False
                    questions = _run_ai_call(
                        entry,
                        ai_engine.get_clarifying_questions,
                        entry["responsibilities"],
                        spinner_text="Checking this entry for gaps...",
                    )
                    if questions is not None:
                        entry["ai_questions"] = questions
                        entry["ai_answers"] = [""] * len(questions)
                        if not questions:
                            # Nothing to clarify — generate right away.
                            _generate_and_store(entry, [])
                    st.rerun()

                if entry["ai_error"]:
                    st.error(entry["ai_error"])

                awaiting_answers = (
                    entry["ai_questions"]
                    and not entry["ai_result"]
                    and not entry["ai_skipped"]
                )
                if awaiting_answers:
                    st.write("A few quick questions to make this entry more specific:")
                    for qi, question in enumerate(entry["ai_questions"]):
                        entry["ai_answers"][qi] = st.text_input(
                            question,
                            value=entry["ai_answers"][qi],
                            key=f"work_ai_answer_{uid}_{qi}",
                        )
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if st.button("Submit Answers", key=f"submit_answers_{uid}"):
                            _generate_and_store(entry, entry["ai_answers"])
                            st.rerun()
                    with col_b:
                        if st.button("Skip and generate anyway", key=f"skip_answers_{uid}"):
                            entry["ai_skipped"] = True
                            _generate_and_store(entry, [])
                            st.rerun()

                if entry["ai_result"]:
                    entry["ai_result"] = st.text_area(
                        "AI-polished version (edit before using)",
                        value=entry["ai_result"],
                        key=f"work_ai_result_{uid}",
                    )
                    if st.button("Regenerate", key=f"regenerate_{uid}"):
                        _generate_and_store(entry, entry["ai_answers"])
                        st.rerun()

                if len(st.session_state.work_history) > 1:
                    if st.button("Remove This Entry", key=f"remove_work_{uid}"):
                        st.session_state.work_history = [
                            e for e in st.session_state.work_history if e["uid"] != uid
                        ]
                        st.rerun()
                st.divider()

            if st.button("Add Work History Entry"):
                st.session_state.work_history.append(_new_work_entry())
                st.rerun()

    with _preview_col:
        _render_live_preview()


# ---------- Step 3: Education ----------

elif _step == 2:
    _form_col, _preview_col = st.columns([3, 2])

    with _form_col:
        st.header("Education")

        with _card_container("education"):
            for i, entry in enumerate(st.session_state.education):
                uid = entry["uid"]
                st.subheader(f"Entry {i + 1}")
                entry["entry_type"] = st.selectbox(
                    "Education Type",
                    EDUCATION_TYPES,
                    index=EDUCATION_TYPES.index(entry["entry_type"]),
                    key=f"edu_type_{uid}",
                )

                if entry["entry_type"] == EDUCATION_SCHOOL:
                    entry["school"] = st.text_input(
                        "School Name", value=entry["school"], key=f"edu_school_{uid}"
                    )
                    entry["board"] = st.text_input(
                        "Board", value=entry["board"], key=f"edu_board_{uid}"
                    )
                    entry["year_of_completion"] = st.text_input(
                        "Year of Completion", value=entry["year_of_completion"],
                        key=f"edu_year_{uid}",
                    )
                    entry["include_grade"] = st.checkbox(
                        "Include Grade/Percentage", value=entry["include_grade"],
                        key=f"edu_include_grade_{uid}",
                    )
                    if entry["include_grade"]:
                        with _animated_container(f"grade-{uid}"):
                            entry["grade"] = st.text_input(
                                "Grade / Percentage", value=entry["grade"],
                                key=f"edu_grade_{uid}",
                            )
                else:
                    entry["school"] = st.text_input(
                        "Institution Name", value=entry["school"], key=f"edu_school_{uid}"
                    )
                    entry["degree"] = st.text_input(
                        "Degree / Course", value=entry["degree"], key=f"edu_degree_{uid}"
                    )
                    entry["field"] = st.text_input(
                        "Field of Study", value=entry["field"], key=f"edu_field_{uid}"
                    )
                    col_start, col_end = st.columns(2)
                    with col_start:
                        entry["start_year"] = st.text_input(
                            "Start Year", value=entry["start_year"], key=f"edu_start_{uid}"
                        )
                    with col_end:
                        entry["end_year"] = st.text_input(
                            "End Year", value=entry["end_year"], key=f"edu_end_{uid}"
                        )
                    entry["include_cgpa"] = st.checkbox(
                        "Include CGPA/GPA", value=entry["include_cgpa"],
                        key=f"edu_include_cgpa_{uid}",
                    )
                    if entry["include_cgpa"]:
                        with _animated_container(f"cgpa-{uid}"):
                            entry["cgpa"] = st.text_input(
                                "CGPA / GPA", value=entry["cgpa"], key=f"edu_cgpa_{uid}"
                            )

                if len(st.session_state.education) > 1:
                    if st.button("Remove This Entry", key=f"remove_edu_{uid}"):
                        st.session_state.education = [
                            e for e in st.session_state.education if e["uid"] != uid
                        ]
                        st.rerun()
                st.divider()

            if st.button("Add Education Entry"):
                st.session_state.education.append(_new_education_entry())
                st.rerun()

    with _preview_col:
        _render_live_preview()


# ---------- Step 4: Skills + Projects ----------

elif _step == 3:
    _form_col, _preview_col = st.columns([3, 2])

    with _form_col:
        st.header("Skills")

        with _card_container("skills"):
            for i, skill in enumerate(st.session_state.skills):
                uid = skill["uid"]
                col1, col2 = st.columns([4, 1])
                with col1:
                    skill["text"] = st.text_input(
                        f"Skill {i + 1}", value=skill["text"], key=f"skill_{uid}"
                    )
                with col2:
                    if len(st.session_state.skills) > 1:
                        if st.button("Remove", key=f"remove_skill_{uid}"):
                            st.session_state.skills = [
                                s for s in st.session_state.skills if s["uid"] != uid
                            ]
                            st.rerun()

            if st.button("Add Skill"):
                st.session_state.skills.append(_new_text_item())
                st.rerun()

        st.header("Projects")

        with _card_container("projects"):
            for i, project in enumerate(st.session_state.projects):
                uid = project["uid"]
                st.subheader(f"Project {i + 1}")
                project["name"] = st.text_input(
                    "Project Name", value=project["name"], key=f"project_name_{uid}"
                )
                project["tech_stack"] = st.text_input(
                    "Tech Stack / Tools Used", value=project["tech_stack"],
                    key=f"project_tech_{uid}",
                )
                project["description"] = st.text_area(
                    "Description", value=project["description"], key=f"project_desc_{uid}"
                )
                project["link"] = st.text_input(
                    "Link (repo or live demo, optional)", value=project["link"],
                    key=f"project_link_{uid}",
                )

                # ----- AI Enhancement (same ai_engine calls as Work History) -----

                project.setdefault("ai_questions", None)
                project.setdefault("ai_answers", [])
                project.setdefault("ai_skipped", False)
                project.setdefault("ai_result", "")
                project.setdefault("ai_error", "")

                if st.button("Enhance with AI", key=f"project_enhance_{uid}"):
                    project["ai_result"] = ""
                    project["ai_skipped"] = False
                    questions = _run_ai_call(
                        project,
                        ai_engine.get_clarifying_questions,
                        project["description"],
                        spinner_text="Checking this project for gaps...",
                    )
                    if questions is not None:
                        project["ai_questions"] = questions
                        project["ai_answers"] = [""] * len(questions)
                        if not questions:
                            # Nothing to clarify — generate right away.
                            _generate_and_store(project, [], source_key="description")
                    st.rerun()

                if project["ai_error"]:
                    st.error(project["ai_error"])

                awaiting_answers = (
                    project["ai_questions"]
                    and not project["ai_result"]
                    and not project["ai_skipped"]
                )
                if awaiting_answers:
                    st.write("A few quick questions to make this project more specific:")
                    for qi, question in enumerate(project["ai_questions"]):
                        project["ai_answers"][qi] = st.text_input(
                            question,
                            value=project["ai_answers"][qi],
                            key=f"project_ai_answer_{uid}_{qi}",
                        )
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if st.button("Submit Answers", key=f"project_submit_answers_{uid}"):
                            _generate_and_store(project, project["ai_answers"],
                                                source_key="description")
                            st.rerun()
                    with col_b:
                        if st.button("Skip and generate anyway", key=f"project_skip_answers_{uid}"):
                            project["ai_skipped"] = True
                            _generate_and_store(project, [], source_key="description")
                            st.rerun()

                if project["ai_result"]:
                    project["ai_result"] = st.text_area(
                        "AI-polished version (edit before using)",
                        value=project["ai_result"],
                        key=f"project_ai_result_{uid}",
                    )
                    if st.button("Regenerate", key=f"project_regenerate_{uid}"):
                        _generate_and_store(project, project["ai_answers"],
                                            source_key="description")
                        st.rerun()

                if len(st.session_state.projects) > 1:
                    if st.button("Remove This Project", key=f"remove_project_{uid}"):
                        st.session_state.projects = [
                            p for p in st.session_state.projects if p["uid"] != uid
                        ]
                        st.rerun()
                st.divider()

            if st.button("Add Project"):
                st.session_state.projects.append(_new_project())
                st.rerun()

    with _preview_col:
        _render_live_preview()


# ---------- Step 5: Certifications + Achievements ----------

elif _step == 4:
    _form_col, _preview_col = st.columns([3, 2])

    with _form_col:
        st.header("Certifications")

        with _card_container("certifications_section"):
            # Bound by key rather than value=: passing a changing value= makes the
            # widget's generated id unstable, so toggling off and back on could fail to
            # restore the block. The session default above supplies the initial state.
            st.checkbox(
                "Include Certifications section",
                key="include_certifications",
                help=(
                    "Leave unchecked to omit the section entirely. When checked, it is "
                    "still skipped if no certifications have been entered."
                ),
            )

            if st.session_state.include_certifications:
                with _animated_container("certifications"):
                    for i, certification in enumerate(st.session_state.certifications):
                        uid = certification["uid"]
                        col1, col2 = st.columns([4, 1])
                        with col1:
                            certification["text"] = st.text_input(
                                f"Certification {i + 1}", value=certification["text"],
                                key=f"certification_{uid}",
                            )
                        with col2:
                            if len(st.session_state.certifications) > 1:
                                if st.button("Remove", key=f"remove_certification_{uid}"):
                                    st.session_state.certifications = [
                                        c for c in st.session_state.certifications
                                        if c["uid"] != uid
                                    ]
                                    st.rerun()

                    if st.button("Add Certification"):
                        st.session_state.certifications.append(_new_text_item())
                        st.rerun()

        st.header("Achievements")

        with _card_container("achievements"):
            for i, achievement in enumerate(st.session_state.achievements):
                uid = achievement["uid"]
                col1, col2 = st.columns([4, 1])
                with col1:
                    achievement["text"] = st.text_input(
                        f"Achievement {i + 1}", value=achievement["text"],
                        key=f"achievement_{uid}",
                    )
                with col2:
                    if len(st.session_state.achievements) > 1:
                        if st.button("Remove", key=f"remove_achievement_{uid}"):
                            st.session_state.achievements = [
                                a for a in st.session_state.achievements
                                if a["uid"] != uid
                            ]
                            st.rerun()

            if st.button("Add Achievement"):
                st.session_state.achievements.append(_new_text_item())
                st.rerun()

    with _preview_col:
        _render_live_preview()


# ---------- Step 6: Review & Export ----------

else:
    # ----- Validation & Submission -----

    st.header("Generate Resume")

    with _card_container("generate"):
        st.session_state.template = st.selectbox(
            "Template",
            pdf_generator.TEMPLATES,
            index=pdf_generator.TEMPLATES.index(st.session_state.template),
        )
        st.caption(_TEMPLATE_HELP[st.session_state.template])

        if st.session_state.template == "Professional" and not pdf_generator.serif_fonts_available():
            st.warning(
                "The Noto Serif font files are missing from the fonts/ folder, so the "
                "Professional template cannot be rendered. Choose Classic instead."
            )

        if st.button("Submit"):
            errors = []
            if not st.session_state.personal_info["name"].strip():
                errors.append("Name is required.")
            if not st.session_state.personal_info["email"].strip():
                errors.append("Email is required.")

            st.session_state.errors = errors
            st.session_state.submitted = not errors

            if errors:
                for error in errors:
                    st.error(error)
            else:
                st.success("Resume data is valid and ready to be generated!")

    # ----- Preview & Export -----

    st.header("Preview & Export")

    with _card_container("preview"):
        if st.button("Generate Preview"):
            try:
                st.session_state["preview_pdf_bytes"] = _build_preview_pdf()
                st.session_state["preview_template"] = st.session_state.template
                st.session_state["preview_error"] = ""
            except pdf_generator.FontFileMissing as error:
                st.session_state["preview_pdf_bytes"] = None
                st.session_state["preview_error"] = str(error)

        if st.session_state.get("preview_error"):
            st.error(st.session_state["preview_error"])

        if st.session_state.get("preview_pdf_bytes"):
            st.caption(
                f"Preview of the {st.session_state.get('preview_template', '')} template. "
                "Edit any field and press Generate Preview again to refresh it."
            )
            for page_image in _pdf_bytes_to_page_images(st.session_state["preview_pdf_bytes"]):
                st.image(page_image, use_container_width=True)

            col_pdf, col_docx = st.columns(2)
            with col_pdf:
                st.download_button(
                    "Download as PDF",
                    data=st.session_state["preview_pdf_bytes"],
                    file_name=f"{_resume_file_name()}.pdf",
                    mime="application/pdf",
                )
            with col_docx:
                st.download_button(
                    "Download as DOCX",
                    data=_build_resume_docx(),
                    file_name=f"{_resume_file_name()}.docx",
                    mime=(
                        "application/vnd.openxmlformats-officedocument"
                        ".wordprocessingml.document"
                    ),
                )
        else:
            st.info("Press Generate Preview to see your resume before downloading it.")


_render_step_nav()
