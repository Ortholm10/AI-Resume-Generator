import streamlit as st

from src import ai_engine

st.title("AI Resume Generator")


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


def _generate_and_store(entry, answers):
    result = _run_ai_call(
        entry,
        ai_engine.enhance_resume_content,
        entry["responsibilities"],
        answers=answers,
        spinner_text="Polishing this entry with AI...",
    )
    if result is not None:
        entry["ai_result"] = "\n".join(result["bullet_points"])


def _new_work_entry():
    return {
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


# ---------- Session State Initialization ----------

if "personal_info" not in st.session_state:
    st.session_state.personal_info = {
        "name": "",
        "email": "",
        "phone": "",
        "location": "",
        "linkedin": "",
    }

if "work_history" not in st.session_state:
    st.session_state.work_history = [_new_work_entry()]

if "education" not in st.session_state:
    st.session_state.education = [
        {"school": "", "degree": "", "field": "", "dates": ""}
    ]

if "skills" not in st.session_state:
    st.session_state.skills = [""]

if "achievements" not in st.session_state:
    st.session_state.achievements = [""]

if "errors" not in st.session_state:
    st.session_state.errors = []


# ---------- Personal Info Section ----------

st.header("Personal Information")

st.session_state.personal_info["name"] = st.text_input(
    "Full Name *", value=st.session_state.personal_info["name"]
)
st.session_state.personal_info["email"] = st.text_input(
    "Email *", value=st.session_state.personal_info["email"]
)
st.session_state.personal_info["phone"] = st.text_input(
    "Phone", value=st.session_state.personal_info["phone"]
)
st.session_state.personal_info["location"] = st.text_input(
    "Location", value=st.session_state.personal_info["location"]
)
st.session_state.personal_info["linkedin"] = st.text_input(
    "LinkedIn", value=st.session_state.personal_info["linkedin"]
)


# ---------- Work History Section ----------

st.header("Work History")

for i, entry in enumerate(st.session_state.work_history):
    st.subheader(f"Entry {i + 1}")
    entry["company"] = st.text_input(
        "Company", value=entry["company"], key=f"work_company_{i}"
    )
    entry["role"] = st.text_input(
        "Role", value=entry["role"], key=f"work_role_{i}"
    )
    entry["dates"] = st.text_input(
        "Dates", value=entry["dates"], key=f"work_dates_{i}"
    )
    entry["responsibilities"] = st.text_area(
        "Responsibilities", value=entry["responsibilities"], key=f"work_resp_{i}"
    )

    # ----- AI Enhancement -----

    entry.setdefault("ai_questions", None)
    entry.setdefault("ai_answers", [])
    entry.setdefault("ai_skipped", False)
    entry.setdefault("ai_result", "")
    entry.setdefault("ai_error", "")

    if st.button("Enhance with AI", key=f"enhance_{i}"):
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
                key=f"work_ai_answer_{i}_{qi}",
            )
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Submit Answers", key=f"submit_answers_{i}"):
                _generate_and_store(entry, entry["ai_answers"])
                st.rerun()
        with col_b:
            if st.button("Skip and generate anyway", key=f"skip_answers_{i}"):
                entry["ai_skipped"] = True
                _generate_and_store(entry, [])
                st.rerun()

    if entry["ai_result"]:
        entry["ai_result"] = st.text_area(
            "AI-polished version (edit before using)",
            value=entry["ai_result"],
            key=f"work_ai_result_{i}",
        )
        if st.button("Regenerate", key=f"regenerate_{i}"):
            _generate_and_store(entry, entry["ai_answers"])
            st.rerun()

    if len(st.session_state.work_history) > 1:
        if st.button("Remove This Entry", key=f"remove_work_{i}"):
            st.session_state.work_history.pop(i)
            st.rerun()
    st.divider()

if st.button("Add Work History Entry"):
    st.session_state.work_history.append(_new_work_entry())
    st.rerun()


# ---------- Education Section ----------

st.header("Education")

for i, entry in enumerate(st.session_state.education):
    st.subheader(f"Entry {i + 1}")
    entry["school"] = st.text_input(
        "School", value=entry["school"], key=f"edu_school_{i}"
    )
    entry["degree"] = st.text_input(
        "Degree", value=entry["degree"], key=f"edu_degree_{i}"
    )
    entry["field"] = st.text_input(
        "Field of Study", value=entry["field"], key=f"edu_field_{i}"
    )
    entry["dates"] = st.text_input(
        "Dates", value=entry["dates"], key=f"edu_dates_{i}"
    )
    if len(st.session_state.education) > 1:
        if st.button("Remove This Entry", key=f"remove_edu_{i}"):
            st.session_state.education.pop(i)
            st.rerun()
    st.divider()

if st.button("Add Education Entry"):
    st.session_state.education.append(
        {"school": "", "degree": "", "field": "", "dates": ""}
    )
    st.rerun()


# ---------- Skills Section ----------

st.header("Skills")

for i, skill in enumerate(st.session_state.skills):
    col1, col2 = st.columns([4, 1])
    with col1:
        st.session_state.skills[i] = st.text_input(
            f"Skill {i + 1}", value=skill, key=f"skill_{i}"
        )
    with col2:
        if len(st.session_state.skills) > 1:
            if st.button("Remove", key=f"remove_skill_{i}"):
                st.session_state.skills.pop(i)
                st.rerun()

if st.button("Add Skill"):
    st.session_state.skills.append("")
    st.rerun()


# ---------- Achievements Section ----------

st.header("Achievements")

for i, achievement in enumerate(st.session_state.achievements):
    col1, col2 = st.columns([4, 1])
    with col1:
        st.session_state.achievements[i] = st.text_input(
            f"Achievement {i + 1}", value=achievement, key=f"achievement_{i}"
        )
    with col2:
        if len(st.session_state.achievements) > 1:
            if st.button("Remove", key=f"remove_achievement_{i}"):
                st.session_state.achievements.pop(i)
                st.rerun()

if st.button("Add Achievement"):
    st.session_state.achievements.append("")
    st.rerun()


# ---------- Validation & Submission ----------

st.header("Generate Resume")

if st.button("Submit"):
    errors = []
    if not st.session_state.personal_info["name"].strip():
        errors.append("Name is required.")
    if not st.session_state.personal_info["email"].strip():
        errors.append("Email is required.")

    st.session_state.errors = errors

    if errors:
        for error in errors:
            st.error(error)
    else:
        st.success("Resume data is valid and ready to be generated!")
