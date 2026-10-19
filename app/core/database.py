"""
AegisRuntime - SQLite Persistence Layer
Stores policies, audit trails, human reviews, tasks, and ground-truth evidence records.
Stored independently from LLM contexts to prevent memory tampering.
"""

import sqlite3
import json
import os
import csv
import io
import time
from typing import List, Dict, Any, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "aegis.db")


def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # 1. Audit Logs Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        id TEXT PRIMARY KEY,
        timestamp REAL,
        task_id TEXT,
        step_id TEXT,
        user_request TEXT,
        tool_name TEXT,
        parameters TEXT,
        decision TEXT,
        policy_id TEXT,
        rule_name TEXT,
        risk_category TEXT,
        reason TEXT,
        execution_status TEXT,
        fallback_applied TEXT,
        token_nonce TEXT
    )
    """)

    # 2. Policies Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS policies (
        rule_id TEXT PRIMARY KEY,
        sector TEXT,
        name TEXT,
        category TEXT,
        description TEXT,
        target_tool TEXT,
        condition_code TEXT,
        action TEXT,
        enabled INTEGER DEFAULT 1,
        priority INTEGER DEFAULT 100
    )
    """)

    # 3. Human Review Queue Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS human_reviews (
        review_id TEXT PRIMARY KEY,
        task_id TEXT,
        step_id TEXT,
        action_id TEXT,
        tool_name TEXT,
        parameters TEXT,
        policy_id TEXT,
        reason TEXT,
        risk_category TEXT,
        created_at REAL,
        status TEXT,
        reviewer_decision TEXT,
        reviewer_comment TEXT
    )
    """)

    # 4. Evidence Ground Truth Records (Approved Sources)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS evidence_records (
        record_id TEXT PRIMARY KEY,
        sector TEXT,
        entity_id TEXT,
        entity_type TEXT,
        data_json TEXT,
        last_verified_source TEXT,
        updated_at REAL
    )
    """)

    # 5. Task Plans & DAG State
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS task_plans (
        task_id TEXT PRIMARY KEY,
        user_request TEXT,
        sector TEXT,
        status TEXT,
        plan_json TEXT,
        created_at REAL,
        completed_count INTEGER,
        blocked_count INTEGER,
        paused_count INTEGER
    )
    """)

    conn.commit()
    seed_ground_truth(conn)
    seed_default_policies(conn)
    conn.close()


def seed_ground_truth(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM evidence_records")
    if cursor.fetchone()[0] > 0:
        return

    now = time.time()
    records = [
        # Healthcare Ground Truth Records
        (
            "EV-MED-001",
            "HEALTHCARE",
            "PT-1001",
            "PATIENT_RECORD",
            json.dumps({
                "patient_name": "Alice Smith",
                "dob": "1978-04-12",
                "diagnosis": "Type 2 Diabetes Mellitus with Nephropathy",
                "eGFR": 22,  # mL/min/1.73m2 (Severe Kidney Impairment)
                "metformin_contraindication": True,
                "max_metformin_dose_mg": 0,
                "current_medications": ["Insulin Glargine 20 units QHS", "Amlodipine 5mg QD"],
                "allergies": ["Sulfa drugs"],
                "assigned_physician": "Dr. Sarah Jenkins, MD (NPI 1892837482)"
            }),
            "Verified Hospital Epic EHR v14.2 & LabCorp Serum Panel",
            now
        ),
        (
            "EV-MED-002",
            "HEALTHCARE",
            "PT-1002",
            "PATIENT_RECORD",
            json.dumps({
                "patient_name": "Bob Jones",
                "dob": "1965-11-20",
                "diagnosis": "Essential Hypertension",
                "systolic_bp": 138,
                "potassium_level": 4.7,
                "max_lisinopril_dose_mg": 20,
                "allergies": ["None known"]
            }),
            "Cerner Millennium Clinical Database",
            now
        ),
        (
            "EV-MED-003",
            "HEALTHCARE",
            "PT-1003",
            "PATIENT_RECORD",
            json.dumps({
                "patient_name": "Claire Vance",
                "dob": "1992-09-03",
                "diagnosis": "Acute Bacterial Sinusitis",
                "allergies": ["Penicillin - Anaphylaxis reaction"],
                "prohibited_antibiotics": ["Amoxicillin", "Ampicillin", "Augmentin"],
                "recommended_alternative": "Azithromycin or Doxycycline"
            }),
            "Mayo Clinic Health Core Registry",
            now
        ),

        # Fintech Ground Truth Records
        (
            "EV-FIN-001",
            "FINTECH",
            "ACC-8821",
            "FINANCIAL_ACCOUNT",
            json.dumps({
                "account_name": "Acme Global Treasury",
                "ledger_balance": 450000.00,
                "available_funds": 420000.00,
                "currency": "USD",
                "daily_wire_limit": 100000.00,
                "approved_beneficiaries": ["VEND-990-SUPPLIES", "PAYROLL-GLOBAL-01"],
                "kyc_status": "VERIFIED_TIER_3",
                "risk_rating": "LOW"
            }),
            "Core Banking Ledger (FIS Systematics GL)",
            now
        ),
        (
            "EV-FIN-002",
            "FINTECH",
            "ACC-9944",
            "FINANCIAL_ACCOUNT",
            json.dumps({
                "account_name": "Omega Trading Holdings",
                "ledger_balance": 14250.00,
                "available_funds": 14250.00,
                "currency": "USD",
                "daily_wire_limit": 10000.00,
                "compliance_flag": "OFAC_ENHANCED_DUE_DILIGENCE",
                "kyc_status": "FLAGGED_FOR_REVIEW"
            }),
            "JPMorgan Chase Settlement Network Feed",
            now
        ),

        # Defense / Cloud SecOps Ground Truth
        (
            "EV-SEC-001",
            "DEFENSE_SECOPS",
            "SRV-SEC-01",
            "CLOUD_INFRASTRUCTURE",
            json.dumps({
                "asset_tag": "SRV-SEC-01-PROD",
                "classification_level": "RESTRICTED_CONFIDENTIAL",
                "encryption_at_rest": "AES-256-GCM",
                "public_ip_permitted": False,
                "allowed_egress_subnets": ["10.240.0.0/16"],
                "authorized_admin_roles": ["ROLE_SECOPS_LEAD"],
                "immutable_backup_retention_days": 90
            }),
            "AWS GovCloud CloudTrail & FedRAMP Asset Inventory",
            now
        )
    ]

    cursor.executemany("""
    INSERT INTO evidence_records (record_id, sector, entity_id, entity_type, data_json, last_verified_source, updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, records)
    conn.commit()


def seed_default_policies(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM policies")
    if cursor.fetchone()[0] > 0:
        return

    policies = [
        # Healthcare Policies
        (
            "POL-HC-001",
            "HEALTHCARE",
            "Prohibit PHI Export to External/Public Destinations",
            "UNAUTHORISED_ACTION",
            "Blocks any transmission of Protected Health Information (PHI) to non-whitelisted external URLs or email domains under HIPAA Privacy Rule 45 CFR § 164.502.",
            "export_data",
            "phi_export_check",
            "BLOCK",
            1,
            10
        ),
        (
            "POL-HC-002",
            "HEALTHCARE",
            "Controlled Prescription Requires Physician Human Approval",
            "DECEPTIVE_BEHAVIOUR",
            "Any automated action ordering scheduled drugs, high-risk medication, or dosage adjustments requires licensed clinical oversight.",
            "prescribe_medication",
            "controlled_substance_check",
            "HUMAN_REVIEW",
            1,
            20
        ),
        (
            "POL-HC-003",
            "HEALTHCARE",
            "Dosage Contraindication Enforcement",
            "HALLUCINATION",
            "Blocks dosage orders exceeding approved maximums or prescribed to patients with kidney/liver contraindications.",
            "prescribe_medication",
            "contraindication_check",
            "BLOCK",
            1,
            15
        ),

        # Fintech Policies
        (
            "POL-FIN-001",
            "FINTECH",
            "Block Unregistered External Wire Routing",
            "EXPLOITATION",
            "Prevents routing funds or balance drains to offshore, non-whitelisted IBANs or suspicious destinations.",
            "wire_transfer",
            "unregistered_destination_check",
            "BLOCK",
            1,
            10
        ),
        (
            "POL-FIN-002",
            "FINTECH",
            "High Value Wire Transfer Requires Dual Authorization",
            "UNAUTHORISED_ACTION",
            "All outbound wire transfers or disbursements exceeding $10,000.00 USD must be held in the human clearinghouse queue.",
            "wire_transfer",
            "high_value_wire_threshold",
            "HUMAN_REVIEW",
            1,
            20
        ),
        (
            "POL-FIN-003",
            "FINTECH",
            "Prevent PII and Cardholder Leakage in External Export",
            "UNAUTHORISED_ACTION",
            "Blocks raw exports containing unmasked PAN (credit card) or SSN data under PCI-DSS Requirement 3.",
            "export_data",
            "pci_dss_pii_check",
            "BLOCK",
            1,
            12
        ),

        # Defense / Cloud SecOps Policies
        (
            "POL-SEC-001",
            "DEFENSE_SECOPS",
            "Prohibit Public Bucket Exposure and ACL Tampering",
            "EXPLOITATION",
            "Blocks any operation modifying storage bucket ACLs to 'public-read' or disabling bucket encryption.",
            "cloud_storage",
            "public_bucket_acl_check",
            "BLOCK",
            1,
            5
        ),
        (
            "POL-SEC-002",
            "DEFENSE_SECOPS",
            "Destructive Backup Deletion Requires Human Multi-Sig",
            "EXPLOITATION",
            "Deleting immutable server snapshots, backups, or production logs requires manual approval with two-factor justification.",
            "delete_resource",
            "destructive_operation_check",
            "HUMAN_REVIEW",
            1,
            15
        ),
        (
            "POL-SEC-003",
            "DEFENSE_SECOPS",
            "Privilege Escalation & Unauthorized IAM Grants",
            "EXPLOITATION",
            "Blocks automated attempts to grant AdministratorAccess or wildcards ('*:*') to agent service accounts.",
            "iam_permission",
            "iam_wildcard_grant_check",
            "BLOCK",
            1,
            8
        ),

        # Universal Safety Policies across all sectors
        (
            "POL-GEN-INJ",
            "HEALTHCARE",
            "Prompt Injection & Jailbreak Override Defense",
            "PROMPT_INJECTION",
            "Detects instruction manipulation, delimiter smuggling, and attempts to override system safeguards.",
            "*",
            "prompt_injection_guard",
            "BLOCK",
            1,
            1
        ),
        (
            "POL-GEN-INJ-FIN",
            "FINTECH",
            "Prompt Injection & Jailbreak Override Defense",
            "PROMPT_INJECTION",
            "Detects instruction manipulation, delimiter smuggling, and attempts to override system safeguards.",
            "*",
            "prompt_injection_guard",
            "BLOCK",
            1,
            1
        ),
        (
            "POL-GEN-INJ-SEC",
            "DEFENSE_SECOPS",
            "Prompt Injection & Jailbreak Override Defense",
            "PROMPT_INJECTION",
            "Detects instruction manipulation, delimiter smuggling, and attempts to override system safeguards.",
            "*",
            "prompt_injection_guard",
            "BLOCK",
            1,
            1
        )
    ]

    cursor.executemany("""
    INSERT INTO policies (rule_id, sector, name, category, description, target_tool, condition_code, action, enabled, priority)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, policies)
    conn.commit()


# Helper DB operations
def log_audit_record(record: Dict[str, Any]):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO audit_logs (id, timestamp, task_id, step_id, user_request, tool_name, parameters, decision, policy_id, rule_name, risk_category, reason, execution_status, fallback_applied, token_nonce)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        record["id"],
        record["timestamp"],
        record["task_id"],
        record["step_id"],
        record["user_request"],
        record["tool_name"],
        json.dumps(record.get("parameters", {})),
        record["decision"],
        record["policy_id"],
        record["rule_name"],
        record["risk_category"],
        record["reason"],
        record["execution_status"],
        record.get("fallback_applied"),
        record.get("token_nonce")
    ))
    conn.commit()
    conn.close()


def query_audit_logs(search: Optional[str] = None, decision: Optional[str] = None, risk: Optional[str] = None, limit: int = 100):
    conn = get_db()
    cursor = conn.cursor()
    query = "SELECT * FROM audit_logs WHERE 1=1"
    params = []

    if decision and decision != "ALL":
        query += " AND decision = ?"
        params.append(decision)

    if risk and risk != "ALL":
        query += " AND risk_category = ?"
        params.append(risk)

    if search:
        query += " AND (user_request LIKE ? OR tool_name LIKE ? OR reason LIKE ? OR policy_id LIKE ?)"
        term = f"%{search}%"
        params.extend([term, term, term, term])

    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    results = [dict(row) for row in rows]
    conn.close()
    return results


def export_audit_logs_csv() -> str:
    logs = query_audit_logs(limit=1000)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Audit ID", "Timestamp", "Task ID", "Step ID", "User Request",
        "Tool Name", "Decision", "Policy ID", "Rule Name", "Risk Category",
        "Reason", "Execution Status", "Fallback Applied", "Parameters"
    ])
    for log in logs:
        writer.writerow([
            log["id"],
            time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(log["timestamp"])),
            log["task_id"],
            log["step_id"],
            log["user_request"],
            log["tool_name"],
            log["decision"],
            log["policy_id"],
            log["rule_name"],
            log["risk_category"],
            log["reason"],
            log["execution_status"],
            log.get("fallback_applied") or "None",
            log["parameters"]
        ])
    return output.getvalue()


def get_all_policies(sector: Optional[str] = None):
    conn = get_db()
    cursor = conn.cursor()
    if sector and sector != "ALL":
        cursor.execute("SELECT * FROM policies WHERE sector = ? ORDER BY priority ASC", (sector,))
    else:
        cursor.execute("SELECT * FROM policies ORDER BY sector, priority ASC")
    rows = cursor.fetchall()
    results = [dict(row) for row in rows]
    conn.close()
    return results


def update_policy_status(rule_id: str, enabled: bool):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE policies SET enabled = ? WHERE rule_id = ?", (1 if enabled else 0, rule_id))
    conn.commit()
    conn.close()


def add_or_update_policy(policy_data: Dict[str, Any]):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR REPLACE INTO policies (rule_id, sector, name, category, description, target_tool, condition_code, action, enabled, priority)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        policy_data["rule_id"],
        policy_data["sector"],
        policy_data["name"],
        policy_data["category"],
        policy_data["description"],
        policy_data["target_tool"],
        policy_data["condition_code"],
        policy_data["action"],
        1 if policy_data.get("enabled", True) else 0,
        policy_data.get("priority", 100)
    ))
    conn.commit()
    conn.close()


def add_human_review_item(item: Dict[str, Any]):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO human_reviews (review_id, task_id, step_id, action_id, tool_name, parameters, policy_id, reason, risk_category, created_at, status)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
    """, (
        item["review_id"],
        item["task_id"],
        item["step_id"],
        item["action_id"],
        item["tool_name"],
        json.dumps(item.get("parameters", {})),
        item["policy_id"],
        item["reason"],
        item["risk_category"],
        item.get("created_at", time.time())
    ))
    conn.commit()
    conn.close()


def get_pending_human_reviews():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM human_reviews WHERE status = 'PENDING' ORDER BY created_at DESC")
    rows = cursor.fetchall()
    results = [dict(row) for row in rows]
    conn.close()
    return results


def resolve_human_review(review_id: str, decision: str, comment: Optional[str] = None):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE human_reviews
    SET status = ?, reviewer_decision = ?, reviewer_comment = ?
    WHERE review_id = ?
    """, (decision, decision, comment or "", review_id))
    conn.commit()
    cursor.execute("SELECT * FROM human_reviews WHERE review_id = ?", (review_id,))
    row = cursor.fetchone()
    res = dict(row) if row else None
    conn.close()
    return res


def get_evidence_record(entity_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM evidence_records WHERE entity_id = ?", (entity_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        res = dict(row)
        res["data"] = json.loads(res["data_json"])
        return res
    return None
