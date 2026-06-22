"""Review-workbook export for the local case workspace."""
from __future__ import annotations

import io
from typing import Any, Dict, Iterable, List, Sequence

import pandas as pd


def _frame(rows: Any) -> pd.DataFrame:
    if isinstance(rows, pd.DataFrame):
        return rows.copy()
    return pd.DataFrame(rows)


def export_case_workbook(
    case_summary: Dict[str, Any],
    documents: Sequence[Dict[str, Any]],
    traceability: Sequence[Dict[str, Any]],
    signals: Sequence[Dict[str, Any]],
    actions: Sequence[Dict[str, Any]],
    link_reviews: Sequence[Dict[str, Any]],
    decisions: Sequence[Dict[str, Any]],
    evidence: Sequence[Dict[str, Any]],
    structured_records: Sequence[Dict[str, Any]],
    recommendations: Dict[str, Any],
    product_context: Dict[str, Any] | None,
) -> bytes:
    """Build an Excel review package. It remains a review aid, not a controlled record."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame([case_summary]).to_excel(writer, sheet_name="Case Summary", index=False)
        _frame(documents).to_excel(writer, sheet_name="Documents", index=False)
        _frame(traceability).to_excel(writer, sheet_name="Traceability", index=False)
        _frame(signals).to_excel(writer, sheet_name="Rule Signals", index=False)
        _frame(actions).to_excel(writer, sheet_name="Actions", index=False)
        _frame(link_reviews).to_excel(writer, sheet_name="Link Reviews", index=False)
        _frame(decisions).to_excel(writer, sheet_name="Reviewer Decisions", index=False)
        _frame(evidence).to_excel(writer, sheet_name="Evidence", index=False)
        _frame(structured_records).to_excel(writer, sheet_name="Structured Records", index=False)
        if product_context:
            pd.DataFrame([product_context]).to_excel(writer, sheet_name="Product Context", index=False)
        recommendation_rows: List[Dict[str, str]] = []
        for section, values in recommendations.items():
            if isinstance(values, list):
                for value in values:
                    recommendation_rows.append({"Section": section, "Content": str(value)})
            else:
                recommendation_rows.append({"Section": section, "Content": str(values)})
        pd.DataFrame(recommendation_rows).to_excel(writer, sheet_name="Draft Brief", index=False)
        pd.DataFrame(
            [{
                "Notice": "Local decision-support prototype. Confirm all output against current controlled records and applicable procedures. This export is not an electronic record or approval.",
            }]
        ).to_excel(writer, sheet_name="Read Me", index=False)

        for worksheet in writer.book.worksheets:
            worksheet.freeze_panes = "A2"
            worksheet.auto_filter.ref = worksheet.dimensions
            for column_cells in worksheet.columns:
                width = min(55, max(11, max(len(str(cell.value or "")) for cell in column_cells) + 2))
                worksheet.column_dimensions[column_cells[0].column_letter].width = width
    return output.getvalue()
