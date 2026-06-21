"""MedRisk Intelligence v5.

Local, evidence-first decision support for quality-engineering review of DFMEA,
PFMEA, CAPA, Risk Management, Control Plan, validation, complaint/NCR, and
change records.

Important: this is a non-validated prototype. It must not autonomously approve
CAPAs, alter controlled documents, release product, establish compliance, or
make patient-safety decisions. A qualified reviewer must verify every output
against current controlled records and applicable procedures.
"""
from __future__ import annotations

import html
import io
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd
import plotly.express as px
import streamlit as st

from medrisk.database import (
    APP_DIR,
    create_case,
    create_case_action,
    delete_mapping_profile,
    get_case_document_ids,
    get_connection,
    get_product_by_part,
    list_audit,
    list_case_actions,
    list_cases,
    list_documents,
    list_link_reviews,
    list_mapping_profiles,
    list_products,
    list_reviewer_decisions,
    list_rules,
    load_evidence,
    load_structured_records,
    log_event,
    save_link_review,
    save_mapping_profile,
    save_reviewer_decision,
    seed_rules,
    set_case_documents,
    store_document,
    update_case,
    update_case_action_status,
    update_rule,
    upsert_product,
)
from medrisk.engine import (
    DEFAULT_RULES,
    build_investigation_brief,
    build_traceability_links,
    evaluate_rules,
    make_traceability_graph,
    retrieve_evidence,
    revision_conflicts,
    trend_frames,
)
from medrisk.extraction import CANONICAL_FIELDS, extract_upload, infer_column_mapping, safe_text, summary
from medrisk.reports import export_case_workbook

APP_NAME = "MedRisk Intelligence"
VERSION = "v5"
RECORD_TYPE_OPTIONS = ["Auto-detect", "DFMEA", "PFMEA", "CAPA", "RISK", "COMPLAINT/NCR", "CONTROL PLAN", "VALIDATION", "CHANGE"]
ROLE_OPTIONS = ["Analyst", "Quality Reviewer", "Quality Approver", "Administrator"]
CASE_TYPES = ["Investigation", "CAPA impact assessment", "NCR / deviation review", "Complaint trend review", "Design change review", "Supplier quality review"]
CASE_STATUSES = ["Open", "Under review", "Awaiting evidence", "Action in progress", "Closed"]
PRIORITIES = ["Critical", "High", "Medium", "Low"]

st.set_page_config(page_title=f"{APP_NAME} {VERSION}", page_icon="🛡️", layout="wide", initial_sidebar_state="expanded")


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
          --ink:#14263A; --navy:#0C2438; --navy2:#163C56; --teal:#0E9F9A; --teal-deep:#087C78;
          --canvas:#F3F7FA; --card:#FFFFFF; --line:#D8E3EA; --muted:#617286; --amber:#B7791F;
          --red:#B42318; --green:#147A59; --shadow:0 10px 26px rgba(18,43,68,.08);
        }
        html, body, [class*="css"] {font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;}
        .stApp {background:var(--canvas); color:var(--ink);}
        .block-container {max-width:1540px; padding-top:1.35rem; padding-bottom:2.2rem;}
        [data-testid="stSidebar"] {background:var(--navy); border-right:1px solid rgba(255,255,255,.08);}
        [data-testid="stSidebar"] * {color:#EEF5F9;}
        [data-testid="stSidebar"] .stCaption {color:#B9CBD9 !important;}
        [data-testid="stSidebar"] [data-baseweb="select"] > div {background:rgba(255,255,255,.08) !important; border-color:rgba(255,255,255,.2) !important;}
        .brand {padding:.4rem 0 1.1rem;border-bottom:1px solid rgba(255,255,255,.15);margin-bottom:1rem;}
        .brand-row {display:flex;gap:.72rem;align-items:center;}
        .brand-mark {width:37px;height:37px;border-radius:11px;background:linear-gradient(135deg,#1EC3B6,#198BC7);display:flex;align-items:center;justify-content:center;color:#062034 !important;font-weight:850;font-size:.76rem;letter-spacing:.05em;}
        .brand-name {font-size:1.02rem;font-weight:780;color:#F7FBFD !important;}
        .brand-sub {font-size:.73rem;color:#AFBFCC !important;margin-top:.08rem;}
        .workflow {font-size:.76rem;line-height:1.55;color:#BCD0DC !important;margin:.45rem 0 .65rem;}
        .workflow b {color:#83E2D8 !important;}
        .hero {background:linear-gradient(106deg,#0D273C 0%,#143E59 68%,#106D65 150%);border-radius:18px;padding:1.55rem 1.75rem;box-shadow:var(--shadow);position:relative;overflow:hidden;margin-bottom:1rem;}
        .hero:after {content:"";width:350px;height:350px;position:absolute;right:-150px;top:-255px;border:1px solid rgba(125,230,217,.20);border-radius:50%;box-shadow:0 0 0 38px rgba(125,230,217,.055),0 0 0 78px rgba(125,230,217,.03);}
        .eyebrow {color:#92E5DC;font-size:.70rem;font-weight:800;letter-spacing:.13em;text-transform:uppercase;}
        .hero h1 {color:#fff;font-size:2rem;font-weight:790;letter-spacing:-.045em;margin:.25rem 0 .35rem;}
        .hero p {color:#D8E7EE;max-width:850px;margin:0;font-size:.95rem;line-height:1.55;}
        .badges {display:flex;flex-wrap:wrap;gap:.42rem;margin-top:.85rem;}
        .badge {font-size:.68rem;font-weight:720;color:#F3FBFC;border:1px solid rgba(255,255,255,.2);border-radius:999px;background:rgba(255,255,255,.08);padding:.28rem .55rem;}
        .notice {display:flex;gap:.65rem;background:#FFF7E2;border:1px solid #ECD39B;border-left:4px solid #C8922D;border-radius:12px;padding:.73rem .85rem;margin:.15rem 0 1rem;color:#5C480F;font-size:.83rem;line-height:1.45;}
        .section {margin:1.05rem 0 .56rem;}
        .kicker {font-size:.69rem;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:var(--teal-deep);}
        .title {font-size:1.26rem;line-height:1.2;font-weight:780;letter-spacing:-.028em;color:var(--ink);margin:.12rem 0 .2rem;}
        .copy {font-size:.84rem;line-height:1.45;color:var(--muted);margin:0;}
        .metric {background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:0 5px 17px rgba(22,45,70,.045);padding:.88rem .92rem;min-height:106px;position:relative;overflow:hidden;}
        .metric:before {content:"";position:absolute;left:0;top:0;bottom:0;width:4px;background:var(--teal);}
        .metric.warn:before {background:#CE8B16;}.metric.critical:before {background:var(--red);}.metric.slate:before {background:#4D6B83;}
        .metric-label {font-size:.70rem;font-weight:780;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);}
        .metric-value {font-size:1.72rem;line-height:1.12;font-weight:830;letter-spacing:-.045em;color:var(--ink);margin-top:.32rem;}
        .metric-detail {font-size:.72rem;color:#7A8998;margin-top:.25rem;}
        .panel {background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:0 5px 17px rgba(22,45,70,.04);padding:.94rem 1.02rem;}
        .panel-title {font-size:.89rem;font-weight:780;color:var(--ink);margin:0 0 .25rem;}.panel-copy {font-size:.79rem;line-height:1.45;color:var(--muted);margin:0;}
        .pill {display:inline-flex;align-items:center;gap:.32rem;border-radius:999px;padding:.27rem .55rem;font-size:.68rem;font-weight:780;}
        .pill.ok {background:#E9F7F0;color:#137054;border:1px solid #B9E5D1;}.pill.review {background:#FFF4D8;color:#7B5605;border:1px solid #EBCF84;}.pill.critical {background:#FDEAE8;color:#9B2418;border:1px solid #F1BCB7;}
        .dot {height:6px;width:6px;border-radius:50%;background:currentColor;}
        .stTabs [data-baseweb="tab-list"] {gap:.25rem;border-bottom:1px solid var(--line);}.stTabs [data-baseweb="tab"] {height:43px;padding:0 .79rem;border-radius:9px 9px 0 0;font-size:.80rem;font-weight:700;color:#566A7D;}.stTabs [aria-selected="true"]{color:var(--teal-deep)!important;background:#EAF7F6!important;}.stTabs [data-baseweb="tab-highlight"]{background:var(--teal)!important;height:3px!important;}
        [data-testid="stDataFrame"] {border:1px solid var(--line);border-radius:12px;overflow:hidden;background:#fff;}[data-testid="stDataFrame"] [role="columnheader"]{background:#F0F5F8;color:#355168;font-weight:780;}
        .stButton>button,.stDownloadButton>button {background:var(--teal);border:1px solid var(--teal);border-radius:9px;color:#fff;font-weight:730;padding:.43rem .75rem;}.stButton>button:hover,.stDownloadButton>button:hover{background:var(--teal-deep);border-color:var(--teal-deep);box-shadow:0 5px 14px rgba(14,159,154,.2);}
        .stButton>button[kind="secondary"] {background:#fff;color:#29485E;border-color:#C6D4DD;}.stButton>button[kind="secondary"]:hover {background:#F4F8FA;border-color:#9EB5C3;box-shadow:none;}
        [data-testid="stForm"]{background:#fff;border:1px solid var(--line);border-radius:14px;padding:1rem 1.05rem;}.stExpander{background:#fff;border:1px solid var(--line)!important;border-radius:12px!important;}
        label,.stSelectbox label,.stTextInput label,.stTextArea label {color:#405469!important;font-size:.80rem!important;font-weight:690!important;}
        .footer {border-top:1px solid var(--line);margin-top:1.3rem;padding-top:.7rem;color:#7B8B9B;font-size:.71rem;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def h(value: Any) -> str:
    return html.escape(str(value))


def section(kicker: str, title: str, copy: str = "") -> None:
    st.markdown(f"<div class='section'><div class='kicker'>{h(kicker)}</div><div class='title'>{h(title)}</div><p class='copy'>{h(copy)}</p></div>", unsafe_allow_html=True)


def metric(label: str, value: Any, detail: str, tone: str = "") -> None:
    st.markdown(f"<div class='metric {tone}'><div class='metric-label'>{h(label)}</div><div class='metric-value'>{h(value)}</div><div class='metric-detail'>{h(detail)}</div></div>", unsafe_allow_html=True)


def panel(title: str, copy: str, tone: str = "ok", badge: str = "") -> None:
    badge_html = f"<div style='margin-top:.58rem'><span class='pill {tone}'><span class='dot'></span>{h(badge)}</span></div>" if badge else ""
    st.markdown(f"<div class='panel'><p class='panel-title'>{h(title)}</p><p class='panel-copy'>{h(copy)}</p>{badge_html}</div>", unsafe_allow_html=True)


def data_frame_evidence(evidence: Sequence[Any]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Source file": item.source_file,
            "Location": item.locator,
            "Record types": ", ".join(item.record_types),
            "Event date": item.event_date or "",
            "Evidence": summary(item.text, 420),
        }
        for item in evidence
    ])


def data_frame_records(records: Sequence[Any]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for record in records:
        row: Dict[str, Any] = {
            "Source file": record.source_file,
            "Location": record.locator,
            "Record type": record.record_type,
            "Risk score": record.risk_score,
            "Risk band": record.risk_band,
        }
        row.update(record.fields)
        rows.append(row)
    return pd.DataFrame(rows)


def document_choice_labels(documents: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    labels: Dict[str, str] = {}
    for doc in documents:
        ids = doc.get("Document IDs") or "no detected ID"
        labels[doc["id"]] = f"{doc['File']}  ·  {ids}"
    return labels


def select_profile(profiles: Sequence[Dict[str, Any]], selected_name: str) -> Optional[Dict[str, Any]]:
    return next((profile for profile in profiles if profile["name"] == selected_name), None)


def read_preview(uploaded: Any) -> Tuple[Dict[str, pd.DataFrame], str]:
    raw = uploaded.getvalue()
    suffix = Path(uploaded.name).suffix.lower()
    if suffix == ".csv":
        return {"CSV": pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False).fillna("")}, suffix
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(io.BytesIO(raw), sheet_name=None, dtype=str, keep_default_na=False), suffix
    raise ValueError("Choose an Excel (.xlsx/.xls) or CSV file for template mapping.")


def current_scope(
    con: Any,
    selected_case: Optional[Any],
    all_documents: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Any], List[Any], List[str]]:
    if selected_case:
        document_ids = get_case_document_ids(con, selected_case.db_id)
        if document_ids:
            documents = [doc for doc in all_documents if doc["id"] in set(document_ids)]
        else:
            documents = []
    else:
        document_ids = [doc["id"] for doc in all_documents]
        documents = list(all_documents)
    evidence = load_evidence(con, document_ids) if document_ids else []
    records = load_structured_records(con, document_ids) if document_ids else []
    return documents, evidence, records, document_ids


def main() -> None:
    inject_css()
    con = get_connection()
    seed_rules(con, DEFAULT_RULES)

    all_documents = list_documents(con)
    all_cases = list_cases(con)

    with st.sidebar:
        st.markdown("<div class='brand'><div class='brand-row'><div class='brand-mark'>MR</div><div><div class='brand-name'>MedRisk Intelligence</div><div class='brand-sub'>Case-based quality evidence workspace · v5</div></div></div></div>", unsafe_allow_html=True)
        st.caption("WORKFLOW")
        st.markdown("<div class='workflow'><b>1</b> Map templates and ingest current copies<br><b>2</b> Attach records to a review case<br><b>3</b> Verify evidence, links, signals, and actions<br><b>4</b> Document qualified reviewer decisions</div>", unsafe_allow_html=True)
        st.divider()
        role = st.selectbox("Working role", ROLE_OPTIONS, help="Prototype selector only. This is not authentication, authorization, or an electronic signature.")
        case_options = ["Workspace-wide review"] + [f"{case.case_id} — {case.title}" for case in all_cases]
        selected_case_label = st.selectbox("Active case", case_options, help="Case views use only attached documents. Workspace-wide review uses all local documents.")
        selected_case = None
        if selected_case_label != "Workspace-wide review":
            selected_id = selected_case_label.split(" — ", 1)[0]
            selected_case = next((case for case in all_cases if case.case_id == selected_id), None)
        similarity_threshold = st.slider("Candidate-link threshold", min_value=0.10, max_value=0.55, value=0.20, step=0.01, help="Higher threshold gives fewer, stronger candidate links. It does not create validated traceability.")
        st.divider()
        if selected_case:
            st.caption("ACTIVE CASE")
            st.markdown(f"**{selected_case.case_id}**")
            st.caption(selected_case.status)
            if selected_case.part_number:
                st.caption(f"Part: {selected_case.part_number}")
        else:
            st.caption("WORKSPACE-WIDE MODE")
            st.caption("Create a case to isolate an investigation and its records.")
        st.divider()
        st.caption("Local data path")
        st.code(str(APP_DIR), language=None)

    scope_documents, scope_evidence, scope_records, scope_document_ids = current_scope(con, selected_case, all_documents)
    product_context = get_product_by_part(con, selected_case.part_number) if selected_case and selected_case.part_number else None
    links = build_traceability_links(scope_evidence, con, similarity_threshold) if scope_evidence else []
    rules = list_rules(con)
    signals = evaluate_rules(rules, scope_documents, scope_evidence, scope_records, product_context, selected_case.part_number if selected_case else "") if scope_documents else []
    brief = build_investigation_brief(selected_case, scope_records, links, signals, product_context)
    actions = list_case_actions(con, selected_case.db_id) if selected_case else []
    link_reviews = list_link_reviews(con, selected_case.db_id if selected_case else None)
    reviewer_decisions = list_reviewer_decisions(con, selected_case.db_id if selected_case else None)

    st.markdown(
        f"""
        <div class='hero'>
          <div class='eyebrow'>Evidence-first quality intelligence</div>
          <h1>{APP_NAME} <span style='font-size:.65em;color:#93E5DD'>{VERSION}</span></h1>
          <p>Map your quality-record templates, build controlled review cases, generate transparent candidate traceability, and document reviewer-approved learning without allowing the tool to make autonomous quality decisions.</p>
          <div class='badges'><span class='badge'>LOCAL WORKSPACE</span><span class='badge'>EXACT SOURCE LOCATORS</span><span class='badge'>REVIEWER-APPROVED LEARNING</span><span class='badge'>ROLE: {h(role.upper())}</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("<div class='notice'><div>◐</div><div><strong>Prototype boundary.</strong> This software is not validated and does not approve CAPAs, establish compliance, release product, or make patient-safety decisions. Every result is a review aid and must be checked against current controlled records and applicable QMS procedures.</div></div>", unsafe_allow_html=True)

    tabs = st.tabs([
        "Overview",
        "Upload & Map",
        "Cases",
        "Traceability",
        "Investigation Brief",
        "Knowledge Base",
        "Signals & Trends",
        "Review & Export",
    ])

    with tabs[0]:
        section("Workspace overview", "Review readiness at a glance", "Start with controlled source documents, then use the case workflow to limit each investigation to relevant evidence.")
        critical = sum(1 for signal in signals if signal.get("Priority") in {"Critical", "High"})
        open_actions = sum(1 for action in actions if action.get("Status") != "Closed")
        c1, c2, c3, c4, c5 = st.columns(5, gap="small")
        with c1: metric("Documents in scope", len(scope_documents), "Attached to case" if selected_case else "Workspace-wide", "slate")
        with c2: metric("Evidence locations", len(scope_evidence), "Exact page / row / paragraph locators", "")
        with c3: metric("Candidate links", len(links), f"Threshold {similarity_threshold:.2f}", "")
        with c4: metric("High-priority signals", critical, "Rule-based review flags", "critical" if critical else "")
        with c5: metric("Open actions", open_actions, "Case actions requiring follow-through", "warn" if open_actions else "")
        left, right = st.columns([1.24, 1.0], gap="medium")
        with left:
            panel("Active review context", "Case scope prevents unrelated documents from altering the evidence set used for a specific investigation.", "ok", "Case scoped" if selected_case else "Workspace-wide")
            if selected_case:
                details = pd.DataFrame([{
                    "Case ID": selected_case.case_id, "Title": selected_case.title, "Type": selected_case.case_type,
                    "Status": selected_case.status, "Owner": selected_case.owner, "Part number": selected_case.part_number,
                    "Product family": selected_case.product_family, "Severity concern": selected_case.severity_concern,
                    "Description": selected_case.description,
                }])
                st.dataframe(details, use_container_width=True, hide_index=True)
            else:
                st.info("No active case selected. Create a case and attach relevant records to use the focused case-review workflow.")
        with right:
            if product_context:
                panel("Knowledge context matched", "The active part number matched a local product knowledge record. This is used only to contextualize review questions and rules.", "ok", "Local context available")
                st.dataframe(pd.DataFrame([product_context]), use_container_width=True, hide_index=True)
            elif selected_case and selected_case.part_number:
                panel("Knowledge context missing", "The case part number has no local product knowledge record. Add supplier, site, process step, and risk-file context before relying on ranking refinements.", "review", "Add product knowledge")
            else:
                panel("Evidence before inference", "Load source documents and create a case before interpreting candidate links or draft recommendations.", "review", "Awaiting case context")
        section("Document register", "Controlled-copy awareness", "Confirm current revision and approval status in the source system. The app can flag conflicts but cannot establish document control.")
        if all_documents:
            register = pd.DataFrame([{key: value for key, value in doc.items() if key not in {"id", "metadata", "content_hash"}} for doc in all_documents])
            st.dataframe(register, use_container_width=True, hide_index=True, height=330)
        else:
            st.info("No documents have been ingested. Use **Upload & Map** to add PDF, Word, Excel, CSV, or text records.")

    with tabs[1]:
        upload_tab, mapping_tab, mapping_library_tab = st.tabs(["Ingest controlled records", "Create mapping profile", "Mapping library"])
        with upload_tab:
            section("Document intake", "Ingest evidence with a visible mapping choice", "Use current controlled copies. The mapping profile determines how spreadsheet columns are interpreted; PDF and Word retain their page / paragraph / table locators.")
            profiles = list_mapping_profiles(con)
            profile_names = ["Auto-detect"] + [profile["name"] for profile in profiles]
            up1, up2 = st.columns(2)
            chosen_profile_name = up1.selectbox("Spreadsheet mapping profile", profile_names, help="Choose a profile only when its column mapping matches this document template.")
            classification_override = up2.selectbox("Record classification", RECORD_TYPE_OPTIONS, help="Use an override only when the record type is known. Auto-detect is the default.")
            uploads = st.file_uploader("Files to ingest", type=["pdf", "docx", "xlsx", "xls", "csv", "txt", "md"], accept_multiple_files=True, help="Supported: PDF, Word, Excel, CSV, TXT, and Markdown.")
            active_profile = select_profile(profiles, chosen_profile_name)
            if st.button("Ingest records", type="primary", use_container_width=True):
                if not uploads:
                    st.warning("Choose one or more files first.")
                else:
                    added = 0
                    results: List[str] = []
                    for upload in uploads:
                        try:
                            text, evidence, records, metadata = extract_upload(upload, active_profile, classification_override)
                            inserted = store_document(
                                con, evidence[0].doc_id if evidence else __import__("hashlib").sha256(upload.getvalue()).hexdigest(),
                                upload.name, Path(upload.name).suffix.lower().lstrip("."), text, metadata,
                                __import__("hashlib").sha256(upload.getvalue()).hexdigest(), evidence, records, role,
                            )
                            if inserted:
                                added += 1
                                results.append(f"Added {upload.name}: {len(evidence)} evidence location(s), {len(records)} structured record(s).")
                            else:
                                results.append(f"Skipped duplicate {upload.name}: identical file content already exists in this local workspace.")
                        except Exception as error:
                            results.append(f"Could not ingest {upload.name}: {error}")
                    for message in results:
                        st.caption("• " + message)
                    if added:
                        st.success(f"Added {added} new document(s).")
                        st.rerun()
            if active_profile:
                st.caption(f"Using profile: **{active_profile['name']}** · Record type: **{active_profile['record_type']}** · Sheet constraint: **{active_profile['sheet_name'] or 'Any sheet'}**")
        with mapping_tab:
            section("Template mapping", "Map your organization’s spreadsheet columns once", "This mapping is transparent and saved locally. It improves structured extraction without asking the tool to guess your FMEA or CAPA template.")
            mapping_upload = st.file_uploader("Template spreadsheet preview", type=["xlsx", "xls", "csv"], key="mapping_preview")
            if mapping_upload:
                try:
                    preview_sheets, _ = read_preview(mapping_upload)
                    sheet_name = st.selectbox("Sheet to map", list(preview_sheets.keys()), key="mapping_sheet")
                    preview = preview_sheets[sheet_name].fillna("")
                    st.dataframe(preview.head(15), use_container_width=True, hide_index=True)
                    inferred = infer_column_mapping(preview.columns)
                    p1, p2, p3 = st.columns([1.2, 1, 1])
                    profile_name = p1.text_input("Profile name", value=f"{Path(mapping_upload.name).stem} profile")
                    profile_record_type = p2.selectbox("Record type for this profile", RECORD_TYPE_OPTIONS[1:], index=1)
                    profile_sheet = p3.text_input("Sheet constraint", value=str(sheet_name), help="Leave as shown to limit the profile to this sheet name. Clear it to apply to any sheet with matching columns.")
                    st.caption("Map only fields you want extracted. Blank selections are intentionally ignored.")
                    mapping: Dict[str, str] = {}
                    columns = [""] + [str(column) for column in preview.columns]
                    map_columns = st.columns(3)
                    for index, canonical in enumerate(CANONICAL_FIELDS.keys()):
                        default_column = inferred.get(canonical, "")
                        default_index = columns.index(default_column) if default_column in columns else 0
                        chosen = map_columns[index % 3].selectbox(canonical.replace("_", " ").title(), columns, index=default_index, key=f"map_{canonical}")
                        if chosen:
                            mapping[canonical] = chosen
                    if st.button("Save mapping profile", type="primary"):
                        if not profile_name.strip():
                            st.warning("Enter a profile name.")
                        elif not mapping:
                            st.warning("Select at least one column mapping.")
                        else:
                            save_mapping_profile(con, profile_name, profile_record_type, profile_sheet, mapping, role)
                            st.success("Mapping profile saved locally.")
                            st.rerun()
                except Exception as error:
                    st.error(f"Could not preview the template: {error}")
            else:
                panel("Start with a blank template copy", "Upload a representative Excel or CSV file. The preview lets you explicitly map fields such as Failure Mode, Cause, Severity, RPN, Action, Owner, and Due Date.", "review", "No template selected")
        with mapping_library_tab:
            section("Mapping library", "Saved column interpretation profiles", "Review profiles before using them. A wrong mapping can produce inaccurate structured fields even if source text extraction succeeds.")
            profiles = list_mapping_profiles(con)
            if profiles:
                display = pd.DataFrame([{
                    "ID": profile["id"], "Name": profile["name"], "Record type": profile["record_type"],
                    "Sheet constraint": profile["sheet_name"] or "Any sheet", "Mapped fields": ", ".join(profile["mapping"].keys()),
                    "Updated": profile["updated_at"],
                } for profile in profiles])
                st.dataframe(display, use_container_width=True, hide_index=True)
                with st.expander("View or delete a saved profile"):
                    profile_id = st.selectbox("Profile", [profile["id"] for profile in profiles], format_func=lambda value: next(profile["name"] for profile in profiles if profile["id"] == value))
                    selected_profile = next(profile for profile in profiles if profile["id"] == profile_id)
                    st.json(selected_profile["mapping"])
                    if st.button("Delete selected mapping profile"):
                        delete_mapping_profile(con, int(profile_id), role)
                        st.success("Mapping profile deleted.")
                        st.rerun()
            else:
                st.info("No saved mapping profiles yet.")

    with tabs[2]:
        create_tab, manage_tab = st.tabs(["Create a case", "Manage active case"])
        with create_tab:
            section("Case investigation workspace", "Create a focused review case", "A case holds the issue statement, product context, attached source records, actions, traceability review, and reviewer decisions.")
            with st.form("create_case_form", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                new_case_id = c1.text_input("Case ID", placeholder="INV-2026-001")
                new_case_type = c2.selectbox("Case type", CASE_TYPES)
                new_case_status = c3.selectbox("Initial status", CASE_STATUSES, index=0)
                title = st.text_input("Case title", placeholder="Barcode version identifier investigation")
                d1, d2, d3 = st.columns(3)
                product_family = d1.text_input("Product family")
                part_number = d2.text_input("Part number")
                owner = d3.text_input("Case owner")
                severity_concern = st.selectbox("Severity / risk concern", ["Not assessed", "Low", "Medium", "High", "Potential patient / user impact"], index=0)
                description = st.text_area("Problem statement / scope", placeholder="Describe the observed issue, known scope, and why review is needed. Do not treat this field as a formal complaint or CAPA record unless it is entered into the controlled system of record.")
                submitted = st.form_submit_button("Create case", type="primary")
                if submitted:
                    if not new_case_id.strip() or not title.strip():
                        st.warning("Case ID and case title are required.")
                    else:
                        try:
                            create_case(con, {
                                "case_id": new_case_id, "title": title, "case_type": new_case_type, "status": new_case_status,
                                "product_family": product_family, "part_number": part_number, "owner": owner,
                                "severity_concern": severity_concern, "description": description,
                            }, role)
                            st.success("Case created. Select it in the left sidebar to attach documents and analyze the case scope.")
                            st.rerun()
                        except Exception as error:
                            st.error(f"Could not create the case: {error}")
        with manage_tab:
            if not selected_case:
                st.info("Select a case from the left sidebar to edit it and attach documents.")
            else:
                section("Active case", f"{selected_case.case_id} — {selected_case.title}", "Update the case statement only as a local review aid. Confirm formal records in the approved system of record.")
                with st.form("update_case_form"):
                    ec1, ec2, ec3 = st.columns(3)
                    edit_type = ec1.selectbox("Case type", CASE_TYPES, index=CASE_TYPES.index(selected_case.case_type) if selected_case.case_type in CASE_TYPES else 0)
                    edit_status = ec2.selectbox("Status", CASE_STATUSES, index=CASE_STATUSES.index(selected_case.status) if selected_case.status in CASE_STATUSES else 0)
                    edit_owner = ec3.text_input("Case owner", value=selected_case.owner)
                    edit_title = st.text_input("Case title", value=selected_case.title)
                    ed1, ed2, ed3 = st.columns(3)
                    edit_family = ed1.text_input("Product family", value=selected_case.product_family)
                    edit_part = ed2.text_input("Part number", value=selected_case.part_number)
                    edit_severity = ed3.text_input("Severity / risk concern", value=selected_case.severity_concern)
                    edit_description = st.text_area("Problem statement / scope", value=selected_case.description)
                    if st.form_submit_button("Save case changes"):
                        update_case(con, selected_case.db_id, {
                            "title": edit_title, "case_type": edit_type, "status": edit_status, "product_family": edit_family,
                            "part_number": edit_part, "owner": edit_owner, "severity_concern": edit_severity, "description": edit_description,
                        }, role)
                        st.success("Case updated.")
                        st.rerun()
                section("Evidence scope", "Attach only the records that belong to this review", "The case traceability and recommendations use attached documents only. This helps prevent unrelated documents from affecting findings.")
                labels = document_choice_labels(all_documents)
                existing = get_case_document_ids(con, selected_case.db_id)
                selected_documents = st.multiselect("Attached documents", list(labels.keys()), default=[doc_id for doc_id in existing if doc_id in labels], format_func=lambda doc_id: labels[doc_id])
                if st.button("Save attached documents", type="primary"):
                    set_case_documents(con, selected_case.db_id, selected_documents, role)
                    st.success(f"Attached {len(selected_documents)} document(s) to {selected_case.case_id}.")
                    st.rerun()
                if selected_case.part_number:
                    context = get_product_by_part(con, selected_case.part_number)
                    if context:
                        st.success("A local product knowledge record matches this case part number.")
                    else:
                        st.warning("No local product knowledge record matches this case part number. Add it in Knowledge Base.")

    with tabs[3]:
        section("Evidence graph", "Candidate traceability with reviewable source citations", "Each candidate link is based on text similarity, shared identifiers, shared concepts, record-type logic, and a bounded adjustment from prior explicit reviewer Accept/Reject decisions.")
        if not scope_documents:
            st.info("Attach documents to the active case, or use workspace-wide review, before generating traceability.")
        elif len(scope_evidence) < 2:
            st.info("At least two evidence locations from different documents are required for candidate traceability.")
        else:
            graph_col, note_col = st.columns([1.65, .7], gap="medium")
            with graph_col:
                st.plotly_chart(make_traceability_graph(links), use_container_width=True, config={"displaylogo": False})
            with note_col:
                panel("How to use the graph", "Node labels represent source files. Lines represent candidate relationships, not validated links. Select the source table below to inspect citations and record a reviewer decision.", "review", "Human review required")
                panel("Controlled learning", "Only a reviewer’s explicit Accept or Reject decision adjusts future ranking. The source content, link type, and citations remain visible; no automatic FMEA/CAPA updates occur.", "ok", "Ranking only")
            if links:
                link_display_columns = ["Relation type", "Confidence", "Match score", "Reviewer-learning adjustment", "Shared concepts", "Shared IDs / parts", "Citation A", "Citation B"]
                st.dataframe(pd.DataFrame(links)[link_display_columns], use_container_width=True, hide_index=True, height=390)
                section("Link review", "Accept, reject, or investigate a candidate relationship", "Your decision is saved locally and may make the ranking slightly more or less conservative for comparable future candidate links.")
                review_options = {f"{index + 1}. {link['Relation type']} · {link['Citation A']} ↔ {link['Citation B']}": link for index, link in enumerate(links[:80])}
                selected_link_label = st.selectbox("Candidate link", list(review_options.keys()))
                selected_link = review_options[selected_link_label]
                with st.expander("Inspect selected source evidence", expanded=True):
                    st.markdown(f"**Source A:** {selected_link['Citation A']}")
                    st.write(selected_link["Evidence A"])
                    st.markdown(f"**Source B:** {selected_link['Citation B']}")
                    st.write(selected_link["Evidence B"])
                    st.caption(f"Scoring detail — base similarity: {selected_link['Base text similarity']}; rule/concept bonus: {selected_link['Rule / concept bonus']}; reviewer-learning adjustment: {selected_link['Reviewer-learning adjustment']}.")
                with st.form("link_review_form", clear_on_submit=True):
                    lr1, lr2 = st.columns(2)
                    link_decision = lr1.selectbox("Reviewer decision", ["Accept", "Reject", "Needs investigation"])
                    link_reviewer = lr2.text_input("Reviewer")
                    link_rationale = st.text_area("Rationale and evidence verified")
                    if st.form_submit_button("Save link review"):
                        save_link_review(
                            con, selected_case.db_id if selected_case else None, selected_link["Link key"], selected_link["Relation type"],
                            selected_link["Shared concepts"], link_decision, link_reviewer, link_rationale, role,
                        )
                        st.success("Link review saved locally. The next ranking run will reflect reviewer feedback within the bounded adjustment.")
                        st.rerun()
            else:
                st.info("No candidate link exceeded the current threshold. Lower the threshold carefully or add more relevant documents to the scope.")

    with tabs[4]:
        section("Investigation assistant", "Evidence-grounded draft for a qualified reviewer", "This draft is deterministic and intentionally tentative. It identifies review questions and actions; it does not determine root cause, risk acceptability, corrective action adequacy, or compliance.")
        if not scope_documents:
            st.info("Attach documents to the active case before generating a scoped investigation brief.")
        else:
            brief_columns = st.columns(2, gap="medium")
            with brief_columns[0]:
                panel("Case and product context", " | ".join(brief["context"]) or "No active case context. Workspace-wide evidence is used.", "ok", "Context loaded")
                st.subheader("Candidate failure modes")
                for item in brief["candidate_failure_modes"]:
                    st.markdown(f"- {item}")
                st.subheader("Candidate cause statements to verify")
                for item in brief["candidate_causes"]:
                    st.markdown(f"- {item}")
                st.subheader("Visible controls / actions")
                for item in brief["existing_controls"]:
                    st.markdown(f"- Control: {item}")
                for item in brief["existing_actions"]:
                    st.markdown(f"- Action: {item}")
            with brief_columns[1]:
                st.subheader("Draft containment questions")
                for item in brief["containment_draft"]:
                    st.markdown(f"- {item}")
                st.subheader("Root-cause questions")
                for item in brief["root_cause_questions"]:
                    st.markdown(f"- {item}")
                st.subheader("FMEA / risk-file review prompts")
                for item in brief["pfmea_dfmea_risk_review"]:
                    st.markdown(f"- {item}")
                st.subheader("Effectiveness-check draft")
                for item in brief["effectiveness_check_draft"]:
                    st.markdown(f"- {item}")
            section("Supporting citations", "Source locations to verify before you document any conclusion", "These are evidence samples, not a complete review of the record set.")
            for citation in brief["citations"]:
                st.caption("• " + citation)
            section("Ask the scoped records", "Evidence retrieval, not an ungrounded answer", "Ask a focused question. The app returns top matching source snippets and their exact locations for your review.")
            question = st.text_input("Question", placeholder="Does the attached CAPA show a PFMEA and risk-management impact assessment?")
            if question:
                retrieved = retrieve_evidence(question, scope_evidence, top_n=10)
                if retrieved:
                    for item in retrieved:
                        with st.expander(f"{item['Citation']}  ·  relevance {item['Relevance']}"):
                            st.write(item["Evidence"])
                            st.caption(f"Record types: {item['Record types']} · Concepts: {item['Concepts']}")
                else:
                    st.info("No strong evidence match was found. Use specific document IDs, part numbers, failure modes, controls, or CAPA terms.")

    with tabs[5]:
        section("Local product knowledge", "Controlled context for more specific review prompts", "Add part-level context only after checking the approved source of truth. This local table does not replace PLM, eQMS, ERP, or supplier-quality systems.")
        kb_form, kb_view = st.columns([.95, 1.35], gap="medium")
        with kb_form:
            with st.form("product_knowledge_form", clear_on_submit=True):
                st.subheader("Add or update part context")
                k1, k2 = st.columns(2)
                product_family = k1.text_input("Product family")
                part_number = k2.text_input("Part number *")
                supplier = st.text_input("Supplier")
                k3, k4 = st.columns(2)
                manufacturing_site = k3.text_input("Manufacturing site")
                process_step = k4.text_input("Process step")
                risk_file_id = st.text_input("Risk file ID / reference")
                notes = st.text_area("Notes")
                active = st.checkbox("Active", value=True)
                if st.form_submit_button("Save product knowledge", type="primary"):
                    try:
                        upsert_product(con, {
                            "product_family": product_family, "part_number": part_number, "supplier": supplier,
                            "manufacturing_site": manufacturing_site, "process_step": process_step, "risk_file_id": risk_file_id,
                            "notes": notes, "active": active,
                        }, role)
                        st.success("Product knowledge saved locally.")
                        st.rerun()
                    except Exception as error:
                        st.error(f"Could not save product knowledge: {error}")
        with kb_view:
            products = list_products(con)
            if products:
                st.subheader("Product knowledge register")
                st.dataframe(pd.DataFrame(products), use_container_width=True, hide_index=True, height=430)
            else:
                panel("No knowledge entries", "Add a part number and its product family, supplier, site, process step, and risk-file reference. Cases with a matching part number will show this context.", "review", "Awaiting local context")

    with tabs[6]:
        section("Signals and trends", "Deterministic rules, recurrence signals, and dated-record visibility", "Trend outputs rely only on dates and fields extracted from attached records. Missing dates or mappings limit the analysis.")
        signals_col, trends_col = st.columns([1.15, 1.0], gap="medium")
        with signals_col:
            st.subheader("Rule-based review signals")
            if signals:
                st.dataframe(pd.DataFrame(signals), use_container_width=True, hide_index=True, height=380)
            else:
                st.info("No rules were evaluated because no scoped documents are attached.")
            conflicts = revision_conflicts(scope_documents)
            if conflicts:
                st.subheader("Potential revision conflicts")
                st.dataframe(pd.DataFrame(conflicts), use_container_width=True, hide_index=True)
        with trends_col:
            frames = trend_frames(scope_evidence, scope_records)
            events = frames["events"]
            concepts_frame = frames["concepts"]
            risk_frame = frames["risk"]
            if not events.empty:
                fig = px.line(events, x="Month", y="Count", color="Record type", markers=True, title="Dated evidence by month")
                fig.update_layout(paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF", margin={"l": 12, "r": 12, "t": 48, "b": 12}, legend={"orientation": "h", "y": 1.12})
                st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})
            else:
                panel("No dated-record trend yet", "Map Event Date / Complaint Date / NCR Date columns or include dates in the source text to enable time-series signals.", "review", "Date data required")
            if not concepts_frame.empty:
                fig = px.bar(concepts_frame.head(10), x="Count", y="Concept", orientation="h", title="Repeated extracted concepts")
                fig.update_layout(paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF", margin={"l": 12, "r": 12, "t": 48, "b": 12}, yaxis={"categoryorder": "total ascending"})
                st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False})
            if not risk_frame.empty:
                st.caption("Structured risk-band distribution")
                st.dataframe(risk_frame.groupby(["Risk band", "Record type"], as_index=False).size().rename(columns={"size": "Count"}), use_container_width=True, hide_index=True)
        section("Rule configuration", "Adjust deterministic rules under change control", "Rule edits affect local recommendation prompts. They do not validate or approve a quality-system decision.")
        if rules:
            selected_rule_id = st.selectbox("Rule to edit", [rule["rule_id"] for rule in rules], format_func=lambda rule_id: next(rule["name"] for rule in rules if rule["rule_id"] == rule_id))
            selected_rule = next(rule for rule in rules if rule["rule_id"] == selected_rule_id)
            with st.form("rule_form"):
                r1, r2 = st.columns([1.2, .5])
                rule_name = r1.text_input("Rule name", value=selected_rule["name"])
                enabled = r2.checkbox("Enabled", value=selected_rule["enabled"])
                rule_priority = st.selectbox("Priority", PRIORITIES, index=PRIORITIES.index(selected_rule["priority"]) if selected_rule["priority"] in PRIORITIES else 2)
                rule_description = st.text_area("Rule logic description", value=selected_rule["description"])
                rule_action = st.text_area("Recommended human action", value=selected_rule["recommended_action"])
                if st.form_submit_button("Save rule configuration"):
                    update_rule(con, {"rule_id": selected_rule_id, "name": rule_name, "enabled": enabled, "priority": rule_priority, "description": rule_description, "recommended_action": rule_action}, role)
                    st.success("Rule saved locally.")
                    st.rerun()

    with tabs[7]:
        section("Qualified review and export", "Actions, reviewer decisions, reviewer-approved learning, and a case workbook", "The app stores local prototype records. It does not provide electronic signatures, validated audit trails, controlled approvals, or source-system integration.")
        if not selected_case:
            st.info("Select or create a case to save actions and reviewer decisions against a focused investigation. You can still export workspace-wide evidence only after records are loaded.")
        else:
            action_col, decision_col = st.columns([1.03, 1.0], gap="medium")
            with action_col:
                st.subheader("Create case action")
                with st.form("case_action_form", clear_on_submit=True):
                    action_title = st.text_input("Action title")
                    a1, a2, a3 = st.columns(3)
                    action_priority = a1.selectbox("Priority", PRIORITIES, index=2)
                    action_owner = a2.text_input("Owner")
                    action_due = a3.date_input("Due date", value=date.today())
                    action_source = st.text_input("Source signal, link, or record")
                    action_status = st.selectbox("Status", ["Open", "In progress", "Blocked", "Closed"])
                    action_notes = st.text_area("Notes and evidence reviewed")
                    if st.form_submit_button("Save case action", type="primary"):
                        if not action_title.strip():
                            st.warning("Enter an action title.")
                        else:
                            create_case_action(con, selected_case.db_id, {"title": action_title, "priority": action_priority, "owner": action_owner, "due_date": str(action_due), "source_item": action_source, "status": action_status, "notes": action_notes}, role)
                            st.success("Case action saved locally.")
                            st.rerun()
            with decision_col:
                st.subheader("Save reviewer decision")
                items = ["Case scope", "Investigation brief"]
                items.extend(["Signal: " + signal["Finding"] for signal in signals[:30]])
                items.extend(["Traceability: " + link["Relation type"] + " | " + link["Citation A"] + " ↔ " + link["Citation B"] for link in links[:30]])
                with st.form("reviewer_decision_form", clear_on_submit=True):
                    review_item = st.selectbox("Review item", items)
                    d1, d2 = st.columns(2)
                    review_decision = d1.selectbox("Decision", ["Not reviewed", "Accept", "Reject", "Needs investigation", "Escalate"])
                    reviewer = d2.text_input("Reviewer")
                    follow_up = st.date_input("Follow-up due", value=date.today())
                    rationale = st.text_area("Rationale and evidence verified")
                    if st.form_submit_button("Save reviewer decision"):
                        save_reviewer_decision(con, selected_case.db_id, "Case review", review_item, review_decision, reviewer, rationale, str(follow_up), role)
                        st.success("Reviewer decision saved locally.")
                        st.rerun()
            section("Action tracker", "Update execution state after confirmation in the system of record", "Action status here is a local review aid only.")
            if actions:
                st.dataframe(pd.DataFrame(actions), use_container_width=True, hide_index=True)
                ua1, ua2, ua3 = st.columns([1.2, 1.1, .6])
                action_id = ua1.selectbox("Action to update", [action["ID"] for action in actions])
                new_status = ua2.selectbox("New status", ["Open", "In progress", "Blocked", "Closed"])
                if ua3.button("Update action"):
                    update_case_action_status(con, int(action_id), new_status, role)
                    st.success("Action status updated.")
                    st.rerun()
            else:
                st.info("No local case actions have been saved.")
            section("Reviewer records", "Saved decisions and controlled-learning feedback", "Accept/Reject link feedback affects only a small bounded ranking adjustment for similar future candidates.")
            review_a, review_b = st.columns(2, gap="medium")
            with review_a:
                st.subheader("Link review history")
                if link_reviews:
                    st.dataframe(pd.DataFrame(link_reviews), use_container_width=True, hide_index=True, height=260)
                else:
                    st.info("No link reviews saved for this case.")
            with review_b:
                st.subheader("Decision history")
                if reviewer_decisions:
                    st.dataframe(pd.DataFrame(reviewer_decisions), use_container_width=True, hide_index=True, height=260)
                else:
                    st.info("No reviewer decisions saved for this case.")
        section("Export", "Create an evidence-backed case review workbook", "The export includes citations, candidate links, rule signals, draft prompts, actions, and local reviewer records. It is a review package, not a controlled record.")
        if scope_documents:
            docs_export = [{key: value for key, value in document.items() if key not in {"id", "metadata", "content_hash"}} for document in scope_documents]
            export = export_case_workbook(
                case_summary={
                    "Case ID": selected_case.case_id if selected_case else "Workspace-wide review",
                    "Title": selected_case.title if selected_case else "All local documents",
                    "Status": selected_case.status if selected_case else "N/A",
                    "Owner": selected_case.owner if selected_case else "N/A",
                    "Part number": selected_case.part_number if selected_case else "N/A",
                    "Scope documents": len(scope_documents), "Evidence locations": len(scope_evidence), "Candidate links": len(links), "Rule signals": len(signals),
                },
                documents=docs_export,
                traceability=links,
                signals=signals,
                actions=actions,
                link_reviews=link_reviews,
                decisions=reviewer_decisions,
                evidence=data_frame_evidence(scope_evidence).to_dict(orient="records"),
                structured_records=data_frame_records(scope_records).to_dict(orient="records"),
                recommendations=brief,
                product_context=product_context,
            )
            filename = f"medrisk_{selected_case.case_id if selected_case else 'workspace'}_review_package.xlsx".replace("/", "-")
            st.download_button("Download case review workbook (.xlsx)", export, file_name=filename, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.info("Attach or ingest documents before creating an export package.")
        with st.expander("Local activity log"):
            audit = list_audit(con)
            if audit:
                st.dataframe(pd.DataFrame(audit), use_container_width=True, hide_index=True, height=300)
            else:
                st.info("No local activity has been logged yet.")

    st.markdown("<div class='footer'>MedRisk Intelligence v5 · Local, evidence-first, human-review-gated quality-engineering prototype · Not validated for production use</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
