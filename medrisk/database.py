"""SQLite persistence for the local, non-validated prototype.

This module intentionally records source-derived content and reviewer input locally.
It is not an electronic-records or electronic-signatures implementation.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .models import CaseRecord, Evidence, StructuredRecord

APP_DIR = Path.home() / ".medrisk_intelligence_v5"
DB_PATH = APP_DIR / "workspace.sqlite3"
APP_DIR.mkdir(parents=True, exist_ok=True)


def utc_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def get_connection() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            filetype TEXT NOT NULL,
            uploaded_at TEXT NOT NULL,
            text TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            content_hash TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS evidence (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            source_file TEXT NOT NULL,
            locator TEXT NOT NULL,
            text TEXT NOT NULL,
            record_types_json TEXT NOT NULL,
            event_date TEXT,
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_evidence_doc_id ON evidence(doc_id);

        CREATE TABLE IF NOT EXISTS structured_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            source_file TEXT NOT NULL,
            locator TEXT NOT NULL,
            record_type TEXT NOT NULL,
            fields_json TEXT NOT NULL,
            risk_score REAL,
            risk_band TEXT NOT NULL,
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_structured_doc_id ON structured_records(doc_id);

        CREATE TABLE IF NOT EXISTS mapping_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            record_type TEXT NOT NULL,
            sheet_name TEXT,
            mapping_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_family TEXT,
            part_number TEXT NOT NULL UNIQUE,
            supplier TEXT,
            manufacturing_site TEXT,
            process_step TEXT,
            risk_file_id TEXT,
            notes TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_products_part ON products(part_number);

        CREATE TABLE IF NOT EXISTS cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            case_type TEXT NOT NULL,
            status TEXT NOT NULL,
            product_family TEXT,
            part_number TEXT,
            owner TEXT,
            severity_concern TEXT,
            description TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cases_case_id ON cases(case_id);

        CREATE TABLE IF NOT EXISTS case_documents (
            case_db_id INTEGER NOT NULL,
            doc_id TEXT NOT NULL,
            added_at TEXT NOT NULL,
            PRIMARY KEY(case_db_id, doc_id),
            FOREIGN KEY(case_db_id) REFERENCES cases(id) ON DELETE CASCADE,
            FOREIGN KEY(doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS case_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_db_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            priority TEXT NOT NULL,
            source_item TEXT,
            owner TEXT,
            due_date TEXT,
            status TEXT NOT NULL,
            notes TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(case_db_id) REFERENCES cases(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_case_actions_case ON case_actions(case_db_id);

        CREATE TABLE IF NOT EXISTS link_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_db_id INTEGER,
            link_key TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            shared_concepts TEXT,
            decision TEXT NOT NULL,
            reviewer TEXT,
            rationale TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(case_db_id) REFERENCES cases(id) ON DELETE SET NULL
        );
        CREATE INDEX IF NOT EXISTS idx_link_reviews_relation ON link_reviews(relation_type);

        CREATE TABLE IF NOT EXISTS reviewer_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_db_id INTEGER,
            item_kind TEXT NOT NULL,
            item_key TEXT NOT NULL,
            decision TEXT NOT NULL,
            reviewer TEXT,
            rationale TEXT,
            follow_up_due TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(case_db_id) REFERENCES cases(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS rule_definitions (
            rule_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            enabled INTEGER NOT NULL,
            priority TEXT NOT NULL,
            description TEXT NOT NULL,
            recommended_action TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            actor_role TEXT NOT NULL,
            action TEXT NOT NULL,
            details TEXT NOT NULL
        );
        """
    )
    con.commit()
    return con


def log_event(con: sqlite3.Connection, actor_role: str, action: str, details: str) -> None:
    con.execute(
        "INSERT INTO audit_log(timestamp, actor_role, action, details) VALUES(?,?,?,?)",
        (utc_now(), actor_role, action, details),
    )
    con.commit()


def document_exists(con: sqlite3.Connection, document_id: str) -> bool:
    return con.execute("SELECT 1 FROM documents WHERE id = ?", (document_id,)).fetchone() is not None


def store_document(
    con: sqlite3.Connection,
    document_id: str,
    name: str,
    filetype: str,
    text: str,
    metadata: Dict[str, Any],
    content_hash: str,
    evidence: Sequence[Evidence],
    structured_records: Sequence[StructuredRecord],
    actor_role: str,
) -> bool:
    if document_exists(con, document_id):
        return False
    now = utc_now()
    con.execute(
        """INSERT INTO documents(id,name,filetype,uploaded_at,text,metadata_json,content_hash)
        VALUES(?,?,?,?,?,?,?)""",
        (document_id, name, filetype, now, text, json.dumps(metadata), content_hash),
    )
    con.executemany(
        """INSERT INTO evidence(doc_id,source_file,locator,text,record_types_json,event_date)
        VALUES(?,?,?,?,?,?)""",
        [
            (item.doc_id, item.source_file, item.locator, item.text, json.dumps(item.record_types), item.event_date)
            for item in evidence
        ],
    )
    con.executemany(
        """INSERT INTO structured_records(doc_id,source_file,locator,record_type,fields_json,risk_score,risk_band)
        VALUES(?,?,?,?,?,?,?)""",
        [
            (
                item.doc_id,
                item.source_file,
                item.locator,
                item.record_type,
                json.dumps(item.fields),
                item.risk_score,
                item.risk_band,
            )
            for item in structured_records
        ],
    )
    con.commit()
    log_event(con, actor_role, "Ingest document", f"Added {name}; evidence={len(evidence)}; structured_records={len(structured_records)}")
    return True


def list_documents(con: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = con.execute("SELECT * FROM documents ORDER BY uploaded_at DESC").fetchall()
    output: List[Dict[str, Any]] = []
    for row in rows:
        metadata = json.loads(row["metadata_json"] or "{}")
        fields = metadata.get("fields", {})
        output.append(
            {
                "id": row["id"],
                "File": row["name"],
                "Type": row["filetype"],
                "Uploaded": row["uploaded_at"],
                "Document IDs": ", ".join(fields.get("document_id", [])),
                "Revisions": ", ".join(fields.get("revision", [])),
                "Part numbers": ", ".join(fields.get("part_number", [])),
                "Detected record types": ", ".join(metadata.get("record_types", [])),
                "Mapping profile": metadata.get("mapping_profile", "Auto-detect"),
                "Structured rows": metadata.get("structured_records", 0),
                "Evidence locations": metadata.get("extraction_locations", 0),
                "metadata": metadata,
                "content_hash": row["content_hash"],
            }
        )
    return output


def get_document_text(con: sqlite3.Connection, document_ids: Optional[Sequence[str]] = None) -> Dict[str, str]:
    if document_ids:
        placeholders = ",".join("?" for _ in document_ids)
        rows = con.execute(f"SELECT id,text FROM documents WHERE id IN ({placeholders})", list(document_ids)).fetchall()
    else:
        rows = con.execute("SELECT id,text FROM documents").fetchall()
    return {row["id"]: row["text"] for row in rows}


def load_evidence(con: sqlite3.Connection, document_ids: Optional[Sequence[str]] = None) -> List[Evidence]:
    if document_ids:
        placeholders = ",".join("?" for _ in document_ids)
        rows = con.execute(f"SELECT * FROM evidence WHERE doc_id IN ({placeholders})", list(document_ids)).fetchall()
    else:
        rows = con.execute("SELECT * FROM evidence").fetchall()
    return [
        Evidence(
            doc_id=row["doc_id"],
            source_file=row["source_file"],
            locator=row["locator"],
            text=row["text"],
            record_types=json.loads(row["record_types_json"]),
            event_date=row["event_date"],
        )
        for row in rows
    ]


def load_structured_records(con: sqlite3.Connection, document_ids: Optional[Sequence[str]] = None) -> List[StructuredRecord]:
    if document_ids:
        placeholders = ",".join("?" for _ in document_ids)
        rows = con.execute(f"SELECT * FROM structured_records WHERE doc_id IN ({placeholders})", list(document_ids)).fetchall()
    else:
        rows = con.execute("SELECT * FROM structured_records").fetchall()
    return [
        StructuredRecord(
            doc_id=row["doc_id"],
            source_file=row["source_file"],
            locator=row["locator"],
            record_type=row["record_type"],
            fields=json.loads(row["fields_json"]),
            risk_score=row["risk_score"],
            risk_band=row["risk_band"],
        )
        for row in rows
    ]


def save_mapping_profile(
    con: sqlite3.Connection,
    name: str,
    record_type: str,
    sheet_name: str,
    mapping: Dict[str, str],
    actor_role: str,
) -> None:
    now = utc_now()
    con.execute(
        """INSERT INTO mapping_profiles(name,record_type,sheet_name,mapping_json,created_at,updated_at)
        VALUES(?,?,?,?,?,?)
        ON CONFLICT(name) DO UPDATE SET
          record_type=excluded.record_type,
          sheet_name=excluded.sheet_name,
          mapping_json=excluded.mapping_json,
          updated_at=excluded.updated_at""",
        (name.strip(), record_type, sheet_name.strip(), json.dumps(mapping), now, now),
    )
    con.commit()
    log_event(con, actor_role, "Save mapping profile", f"Saved mapping profile {name}")


def list_mapping_profiles(con: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = con.execute("SELECT * FROM mapping_profiles ORDER BY name").fetchall()
    return [
        {
            "id": row["id"],
            "name": row["name"],
            "record_type": row["record_type"],
            "sheet_name": row["sheet_name"] or "",
            "mapping": json.loads(row["mapping_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def delete_mapping_profile(con: sqlite3.Connection, profile_id: int, actor_role: str) -> None:
    name_row = con.execute("SELECT name FROM mapping_profiles WHERE id=?", (profile_id,)).fetchone()
    con.execute("DELETE FROM mapping_profiles WHERE id=?", (profile_id,))
    con.commit()
    log_event(con, actor_role, "Delete mapping profile", f"Deleted mapping profile {name_row['name'] if name_row else profile_id}")


def upsert_product(con: sqlite3.Connection, values: Dict[str, Any], actor_role: str) -> None:
    now = utc_now()
    part_number = str(values.get("part_number", "")).strip().upper()
    if not part_number:
        raise ValueError("Part number is required.")
    con.execute(
        """INSERT INTO products(product_family,part_number,supplier,manufacturing_site,process_step,risk_file_id,notes,active,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?)
        ON CONFLICT(part_number) DO UPDATE SET
          product_family=excluded.product_family,
          supplier=excluded.supplier,
          manufacturing_site=excluded.manufacturing_site,
          process_step=excluded.process_step,
          risk_file_id=excluded.risk_file_id,
          notes=excluded.notes,
          active=excluded.active,
          updated_at=excluded.updated_at""",
        (
            str(values.get("product_family", "")).strip(),
            part_number,
            str(values.get("supplier", "")).strip(),
            str(values.get("manufacturing_site", "")).strip(),
            str(values.get("process_step", "")).strip(),
            str(values.get("risk_file_id", "")).strip(),
            str(values.get("notes", "")).strip(),
            1 if values.get("active", True) else 0,
            now,
        ),
    )
    con.commit()
    log_event(con, actor_role, "Upsert product knowledge", f"Saved product knowledge for {part_number}")


def list_products(con: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = con.execute("SELECT * FROM products ORDER BY product_family,part_number").fetchall()
    return [
        {
            "ID": row["id"],
            "Product family": row["product_family"],
            "Part number": row["part_number"],
            "Supplier": row["supplier"],
            "Manufacturing site": row["manufacturing_site"],
            "Process step": row["process_step"],
            "Risk file ID": row["risk_file_id"],
            "Notes": row["notes"],
            "Active": bool(row["active"]),
            "Updated": row["updated_at"],
        }
        for row in rows
    ]


def get_product_by_part(con: sqlite3.Connection, part_number: str) -> Optional[Dict[str, Any]]:
    if not part_number:
        return None
    row = con.execute("SELECT * FROM products WHERE part_number = ?", (part_number.strip().upper(),)).fetchone()
    if not row:
        return None
    return {
        "Product family": row["product_family"],
        "Part number": row["part_number"],
        "Supplier": row["supplier"],
        "Manufacturing site": row["manufacturing_site"],
        "Process step": row["process_step"],
        "Risk file ID": row["risk_file_id"],
        "Notes": row["notes"],
        "Active": bool(row["active"]),
    }


def create_case(con: sqlite3.Connection, values: Dict[str, Any], actor_role: str) -> CaseRecord:
    now = utc_now()
    con.execute(
        """INSERT INTO cases(case_id,title,case_type,status,product_family,part_number,owner,severity_concern,description,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            values["case_id"].strip(),
            values["title"].strip(),
            values.get("case_type", "Investigation"),
            values.get("status", "Open"),
            values.get("product_family", "").strip(),
            values.get("part_number", "").strip().upper(),
            values.get("owner", "").strip(),
            values.get("severity_concern", "").strip(),
            values.get("description", "").strip(),
            now,
            now,
        ),
    )
    con.commit()
    row = con.execute("SELECT * FROM cases WHERE case_id=?", (values["case_id"].strip(),)).fetchone()
    log_event(con, actor_role, "Create case", f"Created case {values['case_id'].strip()}")
    return row_to_case(row)


def update_case(con: sqlite3.Connection, case_db_id: int, values: Dict[str, Any], actor_role: str) -> None:
    con.execute(
        """UPDATE cases SET title=?,case_type=?,status=?,product_family=?,part_number=?,owner=?,severity_concern=?,description=?,updated_at=?
        WHERE id=?""",
        (
            values["title"].strip(),
            values.get("case_type", "Investigation"),
            values.get("status", "Open"),
            values.get("product_family", "").strip(),
            values.get("part_number", "").strip().upper(),
            values.get("owner", "").strip(),
            values.get("severity_concern", "").strip(),
            values.get("description", "").strip(),
            utc_now(),
            case_db_id,
        ),
    )
    con.commit()
    log_event(con, actor_role, "Update case", f"Updated case db id {case_db_id}")


def row_to_case(row: sqlite3.Row) -> CaseRecord:
    return CaseRecord(
        db_id=int(row["id"]), case_id=row["case_id"], title=row["title"], case_type=row["case_type"],
        status=row["status"], product_family=row["product_family"] or "", part_number=row["part_number"] or "",
        owner=row["owner"] or "", severity_concern=row["severity_concern"] or "", description=row["description"] or "",
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def list_cases(con: sqlite3.Connection) -> List[CaseRecord]:
    rows = con.execute("SELECT * FROM cases ORDER BY updated_at DESC").fetchall()
    return [row_to_case(row) for row in rows]


def get_case(con: sqlite3.Connection, case_db_id: int) -> Optional[CaseRecord]:
    row = con.execute("SELECT * FROM cases WHERE id=?", (case_db_id,)).fetchone()
    return row_to_case(row) if row else None


def set_case_documents(con: sqlite3.Connection, case_db_id: int, document_ids: Sequence[str], actor_role: str) -> None:
    con.execute("DELETE FROM case_documents WHERE case_db_id=?", (case_db_id,))
    now = utc_now()
    con.executemany(
        "INSERT INTO case_documents(case_db_id,doc_id,added_at) VALUES(?,?,?)",
        [(case_db_id, doc_id, now) for doc_id in document_ids],
    )
    con.commit()
    log_event(con, actor_role, "Attach case documents", f"Case {case_db_id}: attached {len(document_ids)} document(s)")


def get_case_document_ids(con: sqlite3.Connection, case_db_id: int) -> List[str]:
    rows = con.execute("SELECT doc_id FROM case_documents WHERE case_db_id=?", (case_db_id,)).fetchall()
    return [row["doc_id"] for row in rows]


def create_case_action(con: sqlite3.Connection, case_db_id: int, values: Dict[str, Any], actor_role: str) -> None:
    now = utc_now()
    con.execute(
        """INSERT INTO case_actions(case_db_id,title,priority,source_item,owner,due_date,status,notes,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (
            case_db_id, values["title"].strip(), values.get("priority", "Medium"), values.get("source_item", "").strip(),
            values.get("owner", "").strip(), values.get("due_date", ""), values.get("status", "Open"),
            values.get("notes", "").strip(), now, now,
        ),
    )
    con.commit()
    log_event(con, actor_role, "Create case action", f"Case {case_db_id}: {values['title'].strip()}")


def list_case_actions(con: sqlite3.Connection, case_db_id: int) -> List[Dict[str, Any]]:
    rows = con.execute("SELECT * FROM case_actions WHERE case_db_id=? ORDER BY due_date, created_at DESC", (case_db_id,)).fetchall()
    return [
        {
            "ID": row["id"], "Title": row["title"], "Priority": row["priority"], "Source item": row["source_item"],
            "Owner": row["owner"], "Due date": row["due_date"], "Status": row["status"], "Notes": row["notes"],
            "Created": row["created_at"], "Updated": row["updated_at"],
        }
        for row in rows
    ]


def update_case_action_status(con: sqlite3.Connection, action_id: int, status: str, actor_role: str) -> None:
    con.execute("UPDATE case_actions SET status=?,updated_at=? WHERE id=?", (status, utc_now(), action_id))
    con.commit()
    log_event(con, actor_role, "Update case action", f"Action {action_id} -> {status}")


def save_link_review(
    con: sqlite3.Connection,
    case_db_id: Optional[int],
    link_key: str,
    relation_type: str,
    shared_concepts: str,
    decision: str,
    reviewer: str,
    rationale: str,
    actor_role: str,
) -> None:
    con.execute(
        """INSERT INTO link_reviews(case_db_id,link_key,relation_type,shared_concepts,decision,reviewer,rationale,created_at)
        VALUES(?,?,?,?,?,?,?,?)""",
        (case_db_id, link_key, relation_type, shared_concepts, decision, reviewer, rationale, utc_now()),
    )
    con.commit()
    log_event(con, actor_role, "Save link review", f"{relation_type} reviewed as {decision}")


def list_link_reviews(con: sqlite3.Connection, case_db_id: Optional[int] = None) -> List[Dict[str, Any]]:
    if case_db_id:
        rows = con.execute("SELECT * FROM link_reviews WHERE case_db_id=? ORDER BY created_at DESC", (case_db_id,)).fetchall()
    else:
        rows = con.execute("SELECT * FROM link_reviews ORDER BY created_at DESC").fetchall()
    return [
        {
            "ID": row["id"], "Link key": row["link_key"], "Relation type": row["relation_type"],
            "Shared concepts": row["shared_concepts"], "Decision": row["decision"], "Reviewer": row["reviewer"],
            "Rationale": row["rationale"], "Created": row["created_at"],
        }
        for row in rows
    ]


def learning_stats(con: sqlite3.Connection, relation_type: str, shared_concepts: Iterable[str]) -> Dict[str, Any]:
    rows = con.execute("SELECT relation_type,shared_concepts,decision FROM link_reviews WHERE relation_type=?", (relation_type,)).fetchall()
    accepted = 0
    rejected = 0
    target = set(shared_concepts)
    for row in rows:
        saved_concepts = set(filter(None, (row["shared_concepts"] or "").split(",")))
        relevance = 1.0 if not target or not saved_concepts else (0.5 if target & saved_concepts else 0.2)
        if row["decision"] == "Accept":
            accepted += relevance
        elif row["decision"] == "Reject":
            rejected += relevance
    total = accepted + rejected
    adjustment = 0.0 if total == 0 else max(-0.12, min(0.12, 0.14 * (accepted - rejected) / (total + 3)))
    return {"accepted": round(accepted, 2), "rejected": round(rejected, 2), "adjustment": round(adjustment, 3)}


def save_reviewer_decision(
    con: sqlite3.Connection,
    case_db_id: Optional[int],
    item_kind: str,
    item_key: str,
    decision: str,
    reviewer: str,
    rationale: str,
    follow_up_due: str,
    actor_role: str,
) -> None:
    con.execute(
        """INSERT INTO reviewer_decisions(case_db_id,item_kind,item_key,decision,reviewer,rationale,follow_up_due,created_at)
        VALUES(?,?,?,?,?,?,?,?)""",
        (case_db_id, item_kind, item_key, decision, reviewer, rationale, follow_up_due, utc_now()),
    )
    con.commit()
    log_event(con, actor_role, "Save reviewer decision", f"{item_kind}: {decision}")


def list_reviewer_decisions(con: sqlite3.Connection, case_db_id: Optional[int] = None) -> List[Dict[str, Any]]:
    if case_db_id:
        rows = con.execute("SELECT * FROM reviewer_decisions WHERE case_db_id=? ORDER BY created_at DESC", (case_db_id,)).fetchall()
    else:
        rows = con.execute("SELECT * FROM reviewer_decisions ORDER BY created_at DESC").fetchall()
    return [
        {
            "ID": row["id"], "Item kind": row["item_kind"], "Item key": row["item_key"],
            "Decision": row["decision"], "Reviewer": row["reviewer"], "Rationale": row["rationale"],
            "Follow-up due": row["follow_up_due"], "Created": row["created_at"],
        }
        for row in rows
    ]


def seed_rules(con: sqlite3.Connection, rules: Sequence[Dict[str, str]]) -> None:
    now = utc_now()
    con.executemany(
        """INSERT INTO rule_definitions(rule_id,name,enabled,priority,description,recommended_action,updated_at)
        VALUES(?,?,?,?,?,?,?) ON CONFLICT(rule_id) DO NOTHING""",
        [
            (
                rule["rule_id"], rule["name"], 1 if rule.get("enabled", True) else 0, rule["priority"],
                rule["description"], rule["recommended_action"], now,
            )
            for rule in rules
        ],
    )
    con.commit()


def list_rules(con: sqlite3.Connection) -> List[Dict[str, Any]]:
    rows = con.execute("SELECT * FROM rule_definitions ORDER BY priority DESC, rule_id").fetchall()
    return [
        {
            "rule_id": row["rule_id"], "name": row["name"], "enabled": bool(row["enabled"]),
            "priority": row["priority"], "description": row["description"],
            "recommended_action": row["recommended_action"], "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def update_rule(con: sqlite3.Connection, values: Dict[str, Any], actor_role: str) -> None:
    con.execute(
        """UPDATE rule_definitions SET name=?, enabled=?, priority=?, description=?, recommended_action=?, updated_at=? WHERE rule_id=?""",
        (
            values["name"], 1 if values.get("enabled") else 0, values["priority"], values["description"],
            values["recommended_action"], utc_now(), values["rule_id"],
        ),
    )
    con.commit()
    log_event(con, actor_role, "Update rule", f"Updated rule {values['rule_id']}")


def list_audit(con: sqlite3.Connection, limit: int = 300) -> List[Dict[str, Any]]:
    rows = con.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [
        {"Timestamp": row["timestamp"], "Role": row["actor_role"], "Action": row["action"], "Details": row["details"]}
        for row in rows
    ]
