# MedRisk Intelligence v5

A local, evidence-first quality-engineering prototype for reviewing DFMEA, PFMEA, CAPA, Risk Management, Control Plan, validation, complaint/NCR, and change records.

## What v5 adds

- **Template mapping:** map local Excel/CSV columns to structured fields such as Failure Mode, Cause, Severity, RPN, Action, Owner, and Due Date.
- **Case workspaces:** keep issue statement, selected documents, actions, reviewer decisions, and exports together.
- **Product knowledge base:** add part-level product family, supplier, manufacturing site, process-step, and risk-file context.
- **Traceability graph:** create candidate DFMEA ↔ PFMEA, PFMEA ↔ Control Plan, CAPA ↔ Risk, CAPA ↔ PFMEA, Complaint/NCR ↔ Risk, and FMEA ↔ validation links with exact source citations.
- **Controlled reviewer learning:** only explicit reviewer Accept/Reject link reviews change future ranking, and the adjustment is bounded and visible.
- **Investigation brief:** creates transparent containment, root-cause, FMEA/risk-file, and effectiveness-check prompts from scoped evidence.
- **Rule signals:** editable local deterministic rules for missing links, high-risk records, revision conflicts, recurrence, and missing product context.
- **Review workbook export:** creates an Excel package with source citations, candidate traceability, signals, draft review prompts, local actions, and reviewer decisions.

## macOS / VS Code start

1. Unzip this folder into `Downloads`.
2. Open **VS Code** → **File** → **Open Folder…** → select `medrisk-ai-agent-v5`.
3. Open **Terminal** → **New Terminal** in VS Code.
4. Run:

```bash
cd ~/Downloads/medrisk-ai-agent-v5
bash run_app.sh
```

5. Open the Local URL shown in the terminal, usually `http://localhost:8501` or the next available port.

To diagnose an existing environment:

```bash
cd ~/Downloads/medrisk-ai-agent-v5
source .venv/bin/activate
python diagnose.py
```

## First-use workflow

1. Open **Upload & Map**.
2. Use **Create mapping profile** for your FMEA/CAPA spreadsheet layout.
3. Ingest only current controlled copies of PDFs, Word documents, Excel files, CSVs, or text records.
4. Create a case in **Cases** and attach the documents relevant to that investigation.
5. Add part-level context in **Knowledge Base**.
6. Review **Traceability**, inspect each citation, and record Accept / Reject / Needs Investigation decisions.
7. Use **Investigation Brief** for draft review questions; verify all statements in source records.
8. Save actions and reviewer decisions in **Review & Export**.
9. Export an Excel review package only after checking evidence, current revision, and applicable procedures.

## Important quality-system boundary

This is a local decision-support prototype. It is **not validated** and does not provide document control, electronic signatures, authentication, role-based authorization, validated audit trails, source-system integration, or automated quality decisions.

Do **not** use it to autonomously approve CAPAs, make regulatory conclusions, release product, establish risk acceptability, or make patient-safety decisions. Before production use, follow your organization’s software lifecycle, CSV/CSA, cybersecurity, privacy, supplier, document-control, data-integrity, and change-control procedures.

## GitHub / Streamlit Cloud warning

Do not upload controlled medical-device records, CAPAs, FMEAs, complaint information, patient information, secrets, or internal company documents to GitHub or Streamlit Community Cloud. Use only code for public deployment tests. Keep protected quality records in an approved private environment.

## Safe demo files

The `sample_data` folder contains fictional CSV files only. They are included to test mapping, traceability, case attachment, and export without using controlled or confidential records.
