"""Transparent scoring, traceability, trends, rules, and investigation drafting.

All scoring in this module is deterministic and reviewable. It does not make a
medical, regulatory, release, or safety decision.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import pandas as pd
import plotly.graph_objects as go
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .database import learning_stats
from .extraction import concepts, enhanced_text, extract_fields_from_text, safe_text, summary
from .models import Evidence, StructuredRecord

DEFAULT_RULES: List[Dict[str, Any]] = [
    {
        "rule_id": "CAPA_RISK_LINK",
        "name": "CAPA without visible risk-management linkage",
        "enabled": True,
        "priority": "High",
        "description": "Flag when CAPA evidence is in scope but no risk-management evidence is linked to the case.",
        "recommended_action": "Assess hazards, hazardous situations, harms, risk controls, residual risk, and post-production information impact using current controlled records.",
    },
    {
        "rule_id": "DFMEA_PFMEA_TRANSFER",
        "name": "DFMEA without visible PFMEA transfer",
        "enabled": True,
        "priority": "Medium",
        "description": "Flag when DFMEA is in scope but no PFMEA evidence is linked to the case.",
        "recommended_action": "Confirm relevant design failure modes and controls are transferred to the PFMEA, control plan, verification, and validation evidence.",
    },
    {
        "rule_id": "PFMEA_CONTROL_PLAN",
        "name": "PFMEA without visible control-plan linkage",
        "enabled": True,
        "priority": "Medium",
        "description": "Flag when PFMEA is in scope but no Control Plan / inspection evidence is linked to the case.",
        "recommended_action": "Verify prevention and detection controls are implemented and traceable to a current controlled plan.",
    },
    {
        "rule_id": "HIGH_RISK_ACTION",
        "name": "High-risk structured record may lack action/control",
        "enabled": True,
        "priority": "High",
        "description": "Flag Severity ≥ 8 or RPN ≥ 150 records with no mapped action or control.",
        "recommended_action": "Verify an appropriate action/control, owner, due date, and effectiveness evidence; update the controlled FMEA only after approved review.",
    },
    {
        "rule_id": "REVISION_CONFLICT",
        "name": "Possible document revision conflict",
        "enabled": True,
        "priority": "High",
        "description": "Flag multiple documents that share a detected identifier but have differing revision/content signals.",
        "recommended_action": "Confirm the currently effective controlled copy and remove obsolete sources from the review scope.",
    },
    {
        "rule_id": "RECURRENCE_SIGNAL",
        "name": "Potential recurring issue concept",
        "enabled": True,
        "priority": "Medium",
        "description": "Flag the same normalized quality concept across multiple source files or dated events.",
        "recommended_action": "Review recurrence, scope, common supplier/process contributors, CAPA effectiveness, and risk-management impact.",
    },
    {
        "rule_id": "KNOWLEDGE_CONTEXT",
        "name": "Case part number missing from product knowledge base",
        "enabled": True,
        "priority": "Low",
        "description": "Flag a case with a part number not found in local product knowledge.",
        "recommended_action": "Add or verify product family, supplier, site, process step, and applicable risk-file context before relying on recommendation ranking.",
    },
]


def _shared_identifiers(left: Evidence, right: Evidence) -> List[str]:
    fields_left = extract_fields_from_text(left.text)
    fields_right = extract_fields_from_text(right.text)
    shared: List[str] = []
    for field in ("document_id", "part_number"):
        matches = sorted(set(fields_left.get(field, [])) & set(fields_right.get(field, [])))
        shared.extend(matches)
    return shared[:8]


def _relation_type(left_types: Set[str], right_types: Set[str]) -> str:
    all_types = left_types | right_types
    if {"DFMEA", "PFMEA"}.issubset(all_types):
        return "DFMEA ↔ PFMEA transfer"
    if {"PFMEA", "CONTROL PLAN"}.issubset(all_types):
        return "PFMEA ↔ Control Plan control"
    if "CAPA" in all_types and "RISK" in all_types:
        return "CAPA ↔ Risk impact review"
    if "CAPA" in all_types and "PFMEA" in all_types:
        return "CAPA ↔ PFMEA update review"
    if "COMPLAINT/NCR" in all_types and "RISK" in all_types:
        return "Complaint/NCR ↔ Risk review"
    if "COMPLAINT/NCR" in all_types and "CAPA" in all_types:
        return "Complaint/NCR ↔ CAPA recurrence review"
    if "VALIDATION" in all_types and ("PFMEA" in all_types or "DFMEA" in all_types):
        return "FMEA ↔ Verification/Validation evidence"
    if "CHANGE" in all_types and ("DFMEA" in all_types or "PFMEA" in all_types or "RISK" in all_types):
        return "Change ↔ Risk / FMEA impact review"
    return "Candidate cross-record traceability"


def _confidence(score: float) -> str:
    if score >= 0.55:
        return "High"
    if score >= 0.31:
        return "Medium"
    return "Low"


def _link_key(left: Evidence, right: Evidence, relation_type: str) -> str:
    stable = "|".join(sorted([left.doc_id + left.locator, right.doc_id + right.locator])) + "|" + relation_type
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:20]


def build_traceability_links(
    evidence: Sequence[Evidence],
    database_connection: Any,
    threshold: float = 0.18,
    max_evidence: int = 260,
) -> List[Dict[str, Any]]:
    """Build candidate links with exact citations and review-approved score adjustment.

    The optional learning adjustment is a small bounded ranking change based on
    prior explicit Accept/Reject reviews of comparable link types. It does not
    generate unreviewed content or change source evidence.
    """
    if len(evidence) < 2:
        return []
    # Avoid an O(n²) experience when large workbooks contain thousands of rows.
    selected = list(evidence[:max_evidence])
    texts = [enhanced_text(item.text[:3500]) for item in selected]
    try:
        matrix = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=18000).fit_transform(texts)
    except ValueError:
        return []
    similarities = cosine_similarity(matrix)
    links: List[Dict[str, Any]] = []
    for i, left in enumerate(selected):
        for j in range(i + 1, len(selected)):
            right = selected[j]
            if left.doc_id == right.doc_id:
                continue
            base_similarity = float(similarities[i, j])
            shared_concepts = sorted(set(concepts(left.text)) & set(concepts(right.text)))
            shared_ids = _shared_identifiers(left, right)
            left_types = set(left.record_types)
            right_types = set(right.record_types)
            relation_type = _relation_type(left_types, right_types)
            relation_bonus = 0.05 if relation_type != "Candidate cross-record traceability" else 0.0
            structure_bonus = min(0.18, (0.10 * len(shared_ids)) + (0.035 * len(shared_concepts)))
            learning = learning_stats(database_connection, relation_type, shared_concepts)
            score = min(1.0, max(0.0, base_similarity + relation_bonus + structure_bonus + learning["adjustment"]))
            if score < threshold:
                continue
            key = _link_key(left, right, relation_type)
            links.append(
                {
                    "Link key": key,
                    "Relation type": relation_type,
                    "Confidence": _confidence(score),
                    "Match score": round(score, 3),
                    "Base text similarity": round(base_similarity, 3),
                    "Rule / concept bonus": round(relation_bonus + structure_bonus, 3),
                    "Reviewer-learning adjustment": learning["adjustment"],
                    "Prior accepts": learning["accepted"],
                    "Prior rejects": learning["rejected"],
                    "Shared concepts": ", ".join(shared_concepts),
                    "Shared IDs / parts": ", ".join(shared_ids),
                    "Source A": left.source_file,
                    "Citation A": f"{left.source_file} — {left.locator}",
                    "Evidence A": summary(left.text),
                    "Source B": right.source_file,
                    "Citation B": f"{right.source_file} — {right.locator}",
                    "Evidence B": summary(right.text),
                }
            )
    return sorted(links, key=lambda item: item["Match score"], reverse=True)[:240]


def revision_conflicts(documents: Sequence[Dict[str, Any]]) -> List[Dict[str, str]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for document in documents:
        identifiers = [value.strip() for value in str(document.get("Document IDs", "")).split(",") if value.strip()]
        for identifier in identifiers:
            grouped[identifier].append(document)
    output: List[Dict[str, str]] = []
    for identifier, group in grouped.items():
        revisions = {document.get("Revisions") or "(revision not detected)" for document in group}
        hashes = {document.get("content_hash", "") for document in group}
        if len(group) > 1 and (len(revisions) > 1 or len(hashes) > 1):
            output.append(
                {
                    "Document ID": identifier,
                    "Files": " | ".join(document["File"] for document in group),
                    "Detected revisions": " | ".join(sorted(revisions)),
                    "Finding": "Multiple documents share a detected identifier with differing revision or content signals.",
                }
            )
    return output


def recurring_concepts(evidence: Sequence[Evidence]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Evidence]] = defaultdict(list)
    for item in evidence:
        for concept in concepts(item.text):
            grouped[concept].append(item)
    output: List[Dict[str, Any]] = []
    for concept, items in grouped.items():
        source_files = sorted({item.source_file for item in items})
        if len(items) >= 3 and len(source_files) >= 2:
            output.append(
                {
                    "Concept": concept,
                    "Evidence locations": len(items),
                    "Files": len(source_files),
                    "Example citations": "; ".join(f"{item.source_file} — {item.locator}" for item in items[:5]),
                }
            )
    return sorted(output, key=lambda item: (item["Files"], item["Evidence locations"]), reverse=True)


def evaluate_rules(
    rules: Sequence[Dict[str, Any]],
    documents: Sequence[Dict[str, Any]],
    evidence: Sequence[Evidence],
    structured_records: Sequence[StructuredRecord],
    product_context: Optional[Dict[str, Any]] = None,
    case_part_number: str = "",
) -> List[Dict[str, Any]]:
    enabled = {rule["rule_id"]: rule for rule in rules if rule.get("enabled", True)}
    available_types = {
        record_type
        for document in documents
        for record_type in str(document.get("Detected record types", "")).split(", ")
        if record_type
    }
    results: List[Dict[str, Any]] = []

    def add(rule_id: str, finding: str, reason: str, citations: Sequence[str]) -> None:
        rule = enabled.get(rule_id)
        if not rule:
            return
        results.append(
            {
                "Priority": rule["priority"],
                "Rule": rule["name"],
                "Finding": finding,
                "Why flagged": reason,
                "Recommended human action": rule["recommended_action"],
                "Evidence citations": " | ".join(citations[:6]),
            }
        )

    if "CAPA" in available_types and "RISK" not in available_types:
        citations = [f"{item.source_file} — {item.locator}" for item in evidence if "CAPA" in item.record_types]
        add("CAPA_RISK_LINK", "CAPA content is in scope but no risk-management source was detected.", "Risk-file impact cannot be assessed from the currently attached sources.", citations)
    if "DFMEA" in available_types and "PFMEA" not in available_types:
        citations = [f"{item.source_file} — {item.locator}" for item in evidence if "DFMEA" in item.record_types]
        add("DFMEA_PFMEA_TRANSFER", "DFMEA content is in scope but no PFMEA source was detected.", "Design-to-process transfer cannot be verified from the current scope.", citations)
    if "PFMEA" in available_types and "CONTROL PLAN" not in available_types:
        citations = [f"{item.source_file} — {item.locator}" for item in evidence if "PFMEA" in item.record_types]
        add("PFMEA_CONTROL_PLAN", "PFMEA content is in scope but no control/inspection-plan source was detected.", "Current prevention/detection controls may not be traceable to implementation evidence.", citations)

    for record in structured_records:
        control = safe_text(record.fields.get("control"))
        action = safe_text(record.fields.get("action"))
        if record.risk_band in {"Critical", "High"} and not (control or action):
            score = "not calculated" if record.risk_score is None else f"{record.risk_score:g}"
            add(
                "HIGH_RISK_ACTION",
                f"{record.risk_band}-risk structured record may have no visible action/control.",
                f"Risk score={score}; mapped action and control fields were blank or not available.",
                [f"{record.source_file} — {record.locator}"],
            )

    for conflict in revision_conflicts(documents):
        add("REVISION_CONFLICT", f"Possible revision conflict for {conflict['Document ID']}.", conflict["Finding"], [conflict["Files"]])

    for item in recurring_concepts(evidence)[:8]:
        add(
            "RECURRENCE_SIGNAL",
            f"Potential recurring concept: {item['Concept']}.",
            f"Found in {item['Evidence locations']} evidence locations across {item['Files']} file(s).",
            item["Example citations"].split("; "),
        )

    if case_part_number and not product_context:
        add(
            "KNOWLEDGE_CONTEXT",
            f"No local product knowledge entry was found for part {case_part_number}.",
            "Supplier, site, process, and risk-file context cannot be used to improve case-specific review prompts.",
            [],
        )
    if not results:
        results.append(
            {
                "Priority": "Review",
                "Rule": "No deterministic rule gap detected",
                "Finding": "The active rule set did not identify a high-confidence cross-record gap.",
                "Why flagged": "This does not establish completeness, compliance, risk acceptability, or control effectiveness.",
                "Recommended human action": "Review source citations, controlled revisions, and applicable procedures before documenting a conclusion.",
                "Evidence citations": "",
            }
        )
    priority_sort = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3, "Review": 4}
    return sorted(results, key=lambda item: priority_sort.get(item["Priority"], 9))


def trend_frames(evidence: Sequence[Evidence], records: Sequence[StructuredRecord]) -> Dict[str, pd.DataFrame]:
    events: List[Dict[str, Any]] = []
    for item in evidence:
        if item.event_date:
            parsed = pd.to_datetime(item.event_date, errors="coerce")
            if not pd.isna(parsed):
                events.append({"Month": parsed.to_period("M").astype(str), "Record type": ", ".join(item.record_types), "Source": item.source_file})
    event_frame = pd.DataFrame(events)
    if not event_frame.empty:
        event_frame = event_frame.groupby(["Month", "Record type"], as_index=False).size().rename(columns={"size": "Count"})

    risk_rows = []
    for record in records:
        if record.risk_score is not None:
            risk_rows.append({"Risk band": record.risk_band, "Risk score": record.risk_score, "Record type": record.record_type, "Source": record.source_file})
    risk_frame = pd.DataFrame(risk_rows)

    concept_rows: List[Dict[str, Any]] = []
    for item in evidence:
        for concept in concepts(item.text):
            concept_rows.append({"Concept": concept, "Source": item.source_file})
    concept_frame = pd.DataFrame(concept_rows)
    if not concept_frame.empty:
        concept_frame = concept_frame.groupby("Concept", as_index=False).size().rename(columns={"size": "Count"}).sort_values("Count", ascending=False)
    return {"events": event_frame, "risk": risk_frame, "concepts": concept_frame}


def retrieve_evidence(question: str, evidence: Sequence[Evidence], top_n: int = 8) -> List[Dict[str, Any]]:
    if not question.strip() or not evidence:
        return []
    corpus = [enhanced_text(item.text[:4000]) for item in evidence]
    try:
        vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=18000)
        matrix = vectorizer.fit_transform(corpus + [enhanced_text(question)])
    except ValueError:
        return []
    scores = cosine_similarity(matrix[-1], matrix[:-1]).flatten()
    ranked = scores.argsort()[::-1][:top_n]
    output = []
    for index in ranked:
        if scores[index] <= 0:
            continue
        item = evidence[int(index)]
        output.append(
            {
                "Relevance": round(float(scores[index]), 3),
                "Source file": item.source_file,
                "Location": item.locator,
                "Record types": ", ".join(item.record_types),
                "Concepts": ", ".join(concepts(item.text)),
                "Evidence": summary(item.text, 900),
                "Citation": f"{item.source_file} — {item.locator}",
            }
        )
    return output


def _top_field_values(records: Sequence[StructuredRecord], field: str, count: int = 4) -> List[str]:
    values = [safe_text(record.fields.get(field)) for record in records if safe_text(record.fields.get(field))]
    return [value for value, _ in Counter(values).most_common(count)]


def build_investigation_brief(
    case: Optional[Any],
    records: Sequence[StructuredRecord],
    links: Sequence[Dict[str, Any]],
    signals: Sequence[Dict[str, Any]],
    product_context: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Create a deterministic, evidence-oriented investigation draft.

    It deliberately uses tentative wording and directs a qualified reviewer to
    check current controlled records.
    """
    causes = _top_field_values(records, "cause")
    failure_modes = _top_field_values(records, "failure_mode")
    controls = _top_field_values(records, "control")
    actions = _top_field_values(records, "action")
    all_text = " ".join(" ".join(map(str, record.fields.values())) for record in records)
    active_concepts = concepts(all_text)
    citations = []
    for record in records[:10]:
        citations.append(f"{record.source_file} — {record.locator}")
    citations.extend([str(link.get("Citation A", "")) for link in links[:4]])
    citations = [citation for citation in dict.fromkeys(citations) if citation]

    containment = [
        "Confirm scope using the current controlled part, lot, supplier, site, and affected-record population.",
        "Document objective acceptance criteria before performing any screening, inspection, or disposition activity.",
    ]
    if "identification" in active_concepts or "mixed_product" in active_concepts:
        containment.append("Consider verified segregation and record-by-record identity verification; confirm the released specification and scan/inspection coverage.")
    if "supplier" in active_concepts:
        containment.append("Confirm supplier notification, incoming-control status, and containment responsibilities under the approved supplier-quality process.")
    if "functional_failure" in active_concepts:
        containment.append("Confirm functional verification method, sample rationale, and whether the test represents the intended-use condition.")

    root_cause_questions = [
        "What changed immediately before the event (document, supplier, material, equipment, software, operator method, inspection, or labeling)?",
        "Which process step could create the condition, and which step should detect it?",
        "Was the issue detected by a specified control or by an unintended downstream check?",
        "Does the documented cause explain all observed evidence and recurrence pattern?",
    ]
    if causes:
        root_cause_questions.insert(0, f"Validate or challenge the mapped potential cause(s): {'; '.join(causes[:3])}.")

    pfmea_update = [
        "Confirm whether the failure mode, cause, effect, and controls are explicitly represented in the current PFMEA.",
        "Verify occurrence and detection ratings use approved rating criteria and current evidence.",
        "Trace prevention and detection controls to the Control Plan, work instructions, inspection method, and validation/verification evidence.",
    ]
    if failure_modes:
        pfmea_update.insert(0, f"Candidate PFMEA review topic: {'; '.join(failure_modes[:3])}.")

    effectiveness = [
        "Define measurable pass/fail criteria before implementation, including recurrence-monitoring interval and record population.",
        "Confirm the sample rationale, independent data source, and approval requirements under the applicable CAPA procedure.",
        "Check that the chosen effectiveness evidence tests the intended failure mechanism and escape point, not only completion of the action.",
    ]

    linked_types = sorted({link.get("Relation type", "") for link in links})
    signal_summary = [f"{signal['Priority']}: {signal['Finding']}" for signal in signals[:6]]
    context = []
    if case:
        context.append(f"Case {case.case_id}: {case.title}")
        if case.part_number:
            context.append(f"Part: {case.part_number}")
    if product_context:
        details = [
            product_context.get("Product family", ""), product_context.get("Supplier", ""),
            product_context.get("Manufacturing site", ""), product_context.get("Process step", ""), product_context.get("Risk file ID", ""),
        ]
        context.append("Product context: " + " | ".join(part for part in details if part))

    return {
        "context": context,
        "candidate_failure_modes": failure_modes or ["No mapped failure mode found; review source evidence and template mapping."],
        "candidate_causes": causes or ["No mapped cause found; use source citations to establish the problem statement before root-cause analysis."],
        "existing_controls": controls or ["No mapped control found; verify whether controls exist in the controlled source."],
        "existing_actions": actions or ["No mapped action found; do not infer that no action exists without source review."],
        "containment_draft": containment,
        "root_cause_questions": root_cause_questions,
        "pfmea_dfmea_risk_review": pfmea_update,
        "effectiveness_check_draft": effectiveness,
        "candidate_traceability": linked_types or ["No candidate cross-record link exceeded the current threshold."],
        "signals": signal_summary or ["No rule signals available."],
        "citations": citations[:14],
    }


def make_traceability_graph(links: Sequence[Dict[str, Any]]) -> go.Figure:
    """Create a compact, citation-preserving source-file graph without extra dependencies."""
    top_links = list(links[:32])
    node_names = sorted({link["Source A"] for link in top_links} | {link["Source B"] for link in top_links})
    if not node_names:
        figure = go.Figure()
        figure.add_annotation(text="No candidate links available for graphing.", showarrow=False, font={"size": 16})
        figure.update_xaxes(visible=False).update_yaxes(visible=False)
        return figure
    positions: Dict[str, Tuple[float, float]] = {}
    for index, name in enumerate(node_names):
        angle = (2 * math.pi * index / max(1, len(node_names))) - math.pi / 2
        positions[name] = (math.cos(angle), math.sin(angle))

    figure = go.Figure()
    for link in top_links:
        x0, y0 = positions[link["Source A"]]
        x1, y1 = positions[link["Source B"]]
        figure.add_trace(
            go.Scatter(
                x=[x0, x1], y=[y0, y1], mode="lines", line={"width": 1 + 3 * float(link["Match score"]), "color": "#86A9BD"},
                hovertemplate=(
                    f"<b>{link['Relation type']}</b><br>Score: {link['Match score']}<br>"
                    f"{link['Citation A']}<br>{link['Citation B']}<extra></extra>"
                ),
                showlegend=False,
            )
        )
    x_values = [positions[name][0] for name in node_names]
    y_values = [positions[name][1] for name in node_names]
    figure.add_trace(
        go.Scatter(
            x=x_values, y=y_values, mode="markers+text", text=node_names, textposition="top center",
            marker={"size": 23, "color": "#0E9F9A", "line": {"color": "#0C2438", "width": 1.4}},
            hovertemplate="<b>%{text}</b><extra></extra>",
            showlegend=False,
        )
    )
    figure.update_layout(
        height=510,
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF", margin={"l": 18, "r": 18, "t": 18, "b": 18},
        xaxis={"visible": False, "range": [-1.4, 1.4]}, yaxis={"visible": False, "range": [-1.35, 1.35], "scaleanchor": "x"},
    )
    return figure
