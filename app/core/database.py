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
import hashlib
import secrets
from typing import List, Dict, Any, Optional, Tuple

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
        user_id TEXT DEFAULT 'usr-superadmin',
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
        user_id TEXT DEFAULT 'usr-superadmin',
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
        user_id TEXT DEFAULT 'usr-superadmin',
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

    # 6. Real Financial Accounts Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS financial_accounts (
        account_id TEXT PRIMARY KEY,
        account_name TEXT,
        balance REAL,
        currency TEXT DEFAULT 'USD',
        daily_limit REAL,
        kyc_status TEXT,
        risk_rating TEXT,
        is_approved_beneficiary INTEGER DEFAULT 0,
        updated_at REAL
    )
    """)

    # 7. Real Financial Transactions Ledger
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS financial_ledger (
        txn_id TEXT PRIMARY KEY,
        source_account TEXT,
        beneficiary_id TEXT,
        amount REAL,
        currency TEXT DEFAULT 'USD',
        memo TEXT,
        status TEXT,
        wire_reference TEXT,
        balance_before REAL,
        balance_after REAL,
        timestamp REAL
    )
    """)

    # 8. Real Clinical Patients Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS clinical_patients (
        patient_id TEXT PRIMARY KEY,
        name TEXT,
        dob TEXT,
        diagnosis TEXT,
        egfr REAL,
        systolic_bp INTEGER,
        allergies_json TEXT,
        current_meds_json TEXT,
        contraindications_json TEXT,
        assigned_physician TEXT,
        updated_at REAL
    )
    """)

    # 9. Real Clinical Prescriptions Orders
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS clinical_prescriptions (
        rx_id TEXT PRIMARY KEY,
        patient_id TEXT,
        medication TEXT,
        dose_mg REAL,
        route TEXT DEFAULT 'ORAL',
        status TEXT,
        prescriber TEXT,
        notes TEXT,
        timestamp REAL
    )
    """)

    # 10. Real Cloud Infrastructure Resources
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cloud_resources (
        resource_id TEXT PRIMARY KEY,
        resource_name TEXT,
        resource_type TEXT,
        status TEXT,
        classification TEXT,
        ip_address TEXT,
        cpu_utilization REAL,
        memory_utilization REAL,
        is_immutable_backup INTEGER DEFAULT 0,
        updated_at REAL
    )
    """)

    # 11. Real Cloud Storage Buckets
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cloud_storage_buckets (
        bucket_name TEXT PRIMARY KEY,
        acl TEXT DEFAULT 'private',
        is_public INTEGER DEFAULT 0,
        encrypted INTEGER DEFAULT 1,
        encryption_algorithm TEXT DEFAULT 'AES-256-GCM',
        object_count INTEGER DEFAULT 0,
        total_size_bytes INTEGER DEFAULT 0,
        updated_at REAL
    )
    """)

    # 12. Real Cloud Storage Objects
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS cloud_storage_objects (
        object_id TEXT PRIMARY KEY,
        bucket_name TEXT,
        object_key TEXT,
        size_bytes INTEGER,
        content_type TEXT,
        created_at REAL
    )
    """)

    # 13. Real Outbound Transmissions Egress Audit
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS outbound_transmissions (
        transmission_id TEXT PRIMARY KEY,
        task_id TEXT,
        destination_url TEXT,
        payload_summary TEXT,
        payload_sha256 TEXT,
        bytes_sent INTEGER,
        status TEXT,
        timestamp REAL
    )
    """)

    # 14. Real Users Table (RBAC & Authentication)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'OPERATOR',
        full_name TEXT,
        sector_clearance TEXT DEFAULT 'ALL',
        avatar_color TEXT DEFAULT '#0ea5e9',
        created_at REAL,
        last_login REAL
    )
    """)

    # 15. Real User Sessions Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_sessions (
        token TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        created_at REAL,
        expires_at REAL
    )
    """)

    # Safe migration for user_id on existing SQLite database files
    for tbl in ["audit_logs", "human_reviews", "task_plans"]:
        cursor.execute(f"PRAGMA table_info({tbl})")
        cols = [c[1] for c in cursor.fetchall()]
        if "user_id" not in cols:
            cursor.execute(f"ALTER TABLE {tbl} ADD COLUMN user_id TEXT DEFAULT 'usr-superadmin'")

    conn.commit()
    seed_ground_truth(conn)
    seed_default_policies(conn)
    seed_real_backend_entities(conn)
    seed_default_users(conn)
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
                "diagnosis": "Essential Hypertension & Acute Infection",
                "systolic_bp": 138,
                "allergies": ["Penicillin - Anaphylaxis reaction"],
                "prohibited_antibiotics": ["Amoxicillin", "Ampicillin", "Augmentin"],
                "recommended_alternative": "Azithromycin or Doxycycline"
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
def log_audit_record(record: Dict[str, Any], user_id: Optional[str] = None):
    conn = get_db()
    cursor = conn.cursor()
    uid = user_id or record.get("user_id") or "usr-superadmin"
    cursor.execute("""
    INSERT INTO audit_logs (id, timestamp, task_id, step_id, user_id, user_request, tool_name, parameters, decision, policy_id, rule_name, risk_category, reason, execution_status, fallback_applied, token_nonce)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        record["id"],
        record["timestamp"],
        record["task_id"],
        record["step_id"],
        uid,
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


def query_audit_logs(search: Optional[str] = None, decision: Optional[str] = None, risk: Optional[str] = None, user_id: Optional[str] = None, limit: int = 100):
    conn = get_db()
    cursor = conn.cursor()
    query = "SELECT * FROM audit_logs WHERE 1=1"
    params = []

    if user_id:
        query += " AND user_id = ?"
        params.append(user_id)

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


def export_audit_logs_csv(user_id: Optional[str] = None) -> str:
    logs = query_audit_logs(user_id=user_id, limit=1000)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Audit ID", "Timestamp", "Task ID", "Step ID", "User ID", "User Request",
        "Tool Name", "Decision", "Policy ID", "Rule Name", "Risk Category",
        "Reason", "Execution Status", "Fallback Applied", "Parameters"
    ])
    for log in logs:
        writer.writerow([
            log["id"],
            time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(log["timestamp"])),
            log["task_id"],
            log["step_id"],
            log.get("user_id", "usr-superadmin"),
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


def delete_policy(rule_id: str) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM policies WHERE rule_id = ?", (rule_id,))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected


def add_human_review_item(item: Dict[str, Any], user_id: Optional[str] = None):
    conn = get_db()
    cursor = conn.cursor()
    uid = user_id or item.get("user_id") or "usr-superadmin"
    cursor.execute("""
    INSERT INTO human_reviews (review_id, task_id, step_id, user_id, action_id, tool_name, parameters, policy_id, reason, risk_category, created_at, status)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
    """, (
        item["review_id"],
        item["task_id"],
        item["step_id"],
        uid,
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


def get_pending_human_reviews(user_id: Optional[str] = None):
    conn = get_db()
    cursor = conn.cursor()
    if user_id:
        cursor.execute("SELECT * FROM human_reviews WHERE status = 'PENDING' AND user_id = ? ORDER BY created_at DESC", (user_id,))
    else:
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


def get_system_stats(user_id: Optional[str] = None) -> Dict[str, Any]:
    conn = get_db()
    cursor = conn.cursor()
    if user_id:
        cursor.execute("SELECT COUNT(*) FROM audit_logs WHERE user_id = ?", (user_id,))
        total_audit = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM audit_logs WHERE user_id = ? AND decision IN ('BLOCK', 'HUMAN_REVIEW')", (user_id,))
        total_interventions = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM audit_logs WHERE user_id = ? AND decision = 'ALLOW'", (user_id,))
        total_tokens = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM human_reviews WHERE user_id = ? AND status = 'PENDING'", (user_id,))
        pending_reviews = cursor.fetchone()[0]
    else:
        cursor.execute("SELECT COUNT(*) FROM audit_logs")
        total_audit = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM audit_logs WHERE decision IN ('BLOCK', 'HUMAN_REVIEW')")
        total_interventions = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM audit_logs WHERE decision = 'ALLOW'")
        total_tokens = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM human_reviews WHERE status = 'PENDING'")
        pending_reviews = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM policies WHERE enabled = 1")
    active_policies = cursor.fetchone()[0]

    conn.close()
    return {
        "total_audit_events": total_audit,
        "total_interventions": total_interventions,
        "tokens_minted": total_tokens,
        "pending_reviews": pending_reviews,
        "active_policies": active_policies
    }


def seed_real_backend_entities(conn):
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM financial_accounts")
    if cursor.fetchone()[0] == 0:
        now = time.time()
        accounts = [
            ("ACC-8821", "Acme Global Treasury Operating", 450000.00, "USD", 100000.00, "VERIFIED_TIER_3", "LOW", 0, now),
            ("ACC-9944", "Omega Offshore Trading Holdings", 14250.00, "USD", 10000.00, "FLAGGED_FOR_REVIEW", "HIGH", 0, now),
            ("ACC-9901", "Starlight Logistics Escrow", 82000.00, "USD", 25000.00, "VERIFIED_TIER_3", "LOW", 0, now),
            ("VEND-990-SUPPLIES", "Acme Hardware & Enterprise Supplies", 125000.00, "USD", 50000.00, "VERIFIED_TIER_3", "LOW", 1, now),
            ("PAYROLL-GLOBAL-01", "ADP Global Automated Payroll Clearing", 1200000.00, "USD", 500000.00, "VERIFIED_TIER_3", "LOW", 1, now),
            ("TAX-AUTHORITY-FEDERAL", "Internal Revenue Service Fedwire", 0.00, "USD", 10000000.00, "VERIFIED_TIER_3", "LOW", 1, now),
            ("INTERNAL-SETTLEMENT-RESERVE", "Federal Reserve Settlement Sub-Account", 5000000.00, "USD", 1000000.00, "VERIFIED_TIER_3", "LOW", 1, now),
            ("ACCT-EVIL-666", "Offshore Anonymous Cayman Shell Corp", 500.00, "USD", 0.00, "UNVERIFIED", "CRITICAL", 0, now),
        ]
        cursor.executemany("""
        INSERT INTO financial_accounts (account_id, account_name, balance, currency, daily_limit, kyc_status, risk_rating, is_approved_beneficiary, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, accounts)

    cursor.execute("SELECT COUNT(*) FROM clinical_patients")
    if cursor.fetchone()[0] == 0:
        now = time.time()
        patients = [
            (
                "PT-1001", "Alice Smith", "1978-04-12", "Type 2 Diabetes Mellitus with Nephropathy",
                22.0, 142,
                json.dumps(["Sulfa drugs"]),
                json.dumps(["Insulin Glargine 20 units QHS", "Amlodipine 5mg QD"]),
                json.dumps(["Metformin", "NSAIDs"]),
                "Dr. Sarah Jenkins, MD (NPI 1892837482)", now
            ),
            (
                "PT-1002", "Bob Jones", "1965-11-20", "Essential Hypertension & Acute Bacterial Infection",
                68.0, 138,
                json.dumps(["Penicillin - Anaphylaxis reaction"]),
                json.dumps(["Atorvastatin 20mg QD"]),
                json.dumps(["Amoxicillin", "Ampicillin", "Augmentin"]),
                "Dr. Marcus Vance, MD (NPI 1209845721)", now
            ),
            (
                "PT-1003", "Claire Vance", "1992-09-03", "Acute Bacterial Sinusitis",
                95.0, 118,
                json.dumps(["Penicillin - Anaphylaxis reaction"]),
                json.dumps([]),
                json.dumps(["Amoxicillin", "Ampicillin", "Augmentin"]),
                "Dr. Elena Rostova, MD (NPI 1782390192)", now
            ),
        ]
        cursor.executemany("""
        INSERT INTO clinical_patients (patient_id, name, dob, diagnosis, egfr, systolic_bp, allergies_json, current_meds_json, contraindications_json, assigned_physician, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, patients)

    cursor.execute("SELECT COUNT(*) FROM cloud_resources")
    if cursor.fetchone()[0] == 0:
        now = time.time()
        resources = [
            ("SRV-SEC-01", "Production Primary Gateway SRV-SEC-01", "PRODUCTION_SERVER", "ACTIVE", "RESTRICTED_CONFIDENTIAL", "10.240.1.15", 18.4, 42.1, 0, now),
            ("SRV-DEV-02", "Staging Integration Host SRV-DEV-02", "DEVELOPMENT_SERVER", "ACTIVE", "INTERNAL", "10.240.4.88", 8.1, 24.0, 0, now),
            ("s3://prod-primary-backup-vault", "AWS GovCloud Immutable Backup Vault", "STORAGE_VAULT", "ACTIVE", "RESTRICTED_CONFIDENTIAL", "internal-vpc", 2.0, 10.0, 1, now),
            ("K8S-PROD-CLUSTER", "Kubernetes Production Cluster Master", "K8S_CLUSTER", "ACTIVE", "RESTRICTED_CONFIDENTIAL", "10.240.0.1", 45.2, 68.5, 0, now),
        ]
        cursor.executemany("""
        INSERT INTO cloud_resources (resource_id, resource_name, resource_type, status, classification, ip_address, cpu_utilization, memory_utilization, is_immutable_backup, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, resources)

    cursor.execute("SELECT COUNT(*) FROM cloud_storage_buckets")
    if cursor.fetchone()[0] == 0:
        now = time.time()
        buckets = [
            ("govcloud-classified-archive", "private", 0, 1, "AES-256-GCM", 142, 8589934592, now),
            ("cloud-prod-storage", "private", 0, 1, "AES-256-GCM", 512, 34359738368, now),
            ("dns-records-archive", "private", 0, 1, "AES-256-GCM", 18, 1048576, now),
        ]
        cursor.executemany("""
        INSERT INTO cloud_storage_buckets (bucket_name, acl, is_public, encrypted, encryption_algorithm, object_count, total_size_bytes, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, buckets)

    conn.commit()


# -------------------------------------------------------------
# REAL-TIME LIVE DATA ACCESS & MUTATION FUNCTIONS
# -------------------------------------------------------------

def get_financial_account(account_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM financial_accounts WHERE account_id = ?", (account_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def list_financial_accounts() -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM financial_accounts ORDER BY balance DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_financial_account_balance(account_id: str, new_balance: float) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE financial_accounts SET balance = ?, updated_at = ? WHERE account_id = ?", (new_balance, time.time(), account_id))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected


def record_financial_ledger_txn(
    txn_id: str,
    source_account: str,
    beneficiary_id: str,
    amount: float,
    currency: str,
    memo: str,
    status: str,
    wire_reference: str,
    balance_before: float,
    balance_after: float
) -> Dict[str, Any]:
    conn = get_db()
    cursor = conn.cursor()
    now = time.time()
    cursor.execute("""
    INSERT INTO financial_ledger (txn_id, source_account, beneficiary_id, amount, currency, memo, status, wire_reference, balance_before, balance_after, timestamp)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (txn_id, source_account, beneficiary_id, amount, currency, memo, status, wire_reference, balance_before, balance_after, now))
    conn.commit()
    conn.close()
    return {
        "txn_id": txn_id,
        "source_account": source_account,
        "beneficiary_id": beneficiary_id,
        "amount": amount,
        "currency": currency,
        "status": status,
        "wire_reference": wire_reference,
        "balance_before": balance_before,
        "balance_after": balance_after,
        "timestamp": now
    }


def get_financial_ledger(limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM financial_ledger ORDER BY timestamp DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_clinical_patient(patient_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clinical_patients WHERE patient_id = ?", (patient_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        d = dict(row)
        d["allergies"] = json.loads(d.get("allergies_json") or "[]")
        d["current_medications"] = json.loads(d.get("current_meds_json") or "[]")
        d["contraindications"] = json.loads(d.get("contraindications_json") or "[]")
        return d
    return None


def list_clinical_patients() -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM clinical_patients ORDER BY patient_id ASC")
    rows = cursor.fetchall()
    conn.close()
    results = []
    for row in rows:
        d = dict(row)
        d["allergies"] = json.loads(d.get("allergies_json") or "[]")
        d["current_medications"] = json.loads(d.get("current_meds_json") or "[]")
        d["contraindications"] = json.loads(d.get("contraindications_json") or "[]")
        results.append(d)
    return results


def record_clinical_prescription(
    rx_id: str,
    patient_id: str,
    medication: str,
    dose_mg: float,
    route: str,
    status: str,
    prescriber: str,
    notes: str
) -> Dict[str, Any]:
    conn = get_db()
    cursor = conn.cursor()
    now = time.time()
    cursor.execute("""
    INSERT INTO clinical_prescriptions (rx_id, patient_id, medication, dose_mg, route, status, prescriber, notes, timestamp)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (rx_id, patient_id, medication, dose_mg, route, status, prescriber, notes, now))
    conn.commit()
    conn.close()
    return {
        "rx_id": rx_id,
        "patient_id": patient_id,
        "medication": medication,
        "dose_mg": dose_mg,
        "route": route,
        "status": status,
        "prescriber": prescriber,
        "notes": notes,
        "timestamp": now
    }


def get_clinical_prescriptions(patient_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    if patient_id:
        cursor.execute("SELECT * FROM clinical_prescriptions WHERE patient_id = ? ORDER BY timestamp DESC LIMIT ?", (patient_id, limit))
    else:
        cursor.execute("SELECT * FROM clinical_prescriptions ORDER BY timestamp DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_cloud_resource(resource_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cloud_resources WHERE resource_id = ?", (resource_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def list_cloud_resources() -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cloud_resources ORDER BY resource_id ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_cloud_resource_status(resource_id: str, status: str) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE cloud_resources SET status = ?, updated_at = ? WHERE resource_id = ?", (status, time.time(), resource_id))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected


def get_cloud_storage_bucket(bucket_name: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cloud_storage_buckets WHERE bucket_name = ?", (bucket_name,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def list_cloud_storage_buckets() -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cloud_storage_buckets ORDER BY bucket_name ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_cloud_bucket_acl(bucket_name: str, acl: str) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    is_pub = 1 if "public" in acl.lower() else 0
    now = time.time()
    cursor.execute("UPDATE cloud_storage_buckets SET acl = ?, is_public = ?, updated_at = ? WHERE bucket_name = ?", (acl, is_pub, now, bucket_name))
    if cursor.rowcount == 0:
        cursor.execute(
            "INSERT INTO cloud_storage_buckets (bucket_name, acl, is_public, encrypted, encryption_algorithm, object_count, total_size_bytes, updated_at) VALUES (?, ?, ?, 1, 'AES-256', 0, 0, ?)",
            (bucket_name, acl, is_pub, now)
        )
    conn.commit()
    conn.close()
    return True


def add_cloud_storage_object(bucket_name: str, object_key: str, size_bytes: int, content_type: str) -> Dict[str, Any]:
    conn = get_db()
    cursor = conn.cursor()
    now = time.time()
    obj_id = f"OBJ-{int(now * 1000) % 10000000:07d}"
    cursor.execute("""
    INSERT INTO cloud_storage_objects (object_id, bucket_name, object_key, size_bytes, content_type, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (obj_id, bucket_name, object_key, size_bytes, content_type, now))
    # Update bucket stats
    cursor.execute("""
    UPDATE cloud_storage_buckets
    SET object_count = object_count + 1, total_size_bytes = total_size_bytes + ?, updated_at = ?
    WHERE bucket_name = ?
    """, (size_bytes, now, bucket_name))
    conn.commit()
    conn.close()
    return {
        "object_id": obj_id,
        "bucket_name": bucket_name,
        "object_key": object_key,
        "size_bytes": size_bytes,
        "content_type": content_type,
        "created_at": now
    }


def record_outbound_transmission(
    task_id: str,
    destination_url: str,
    payload_summary: str,
    payload_sha256: str,
    bytes_sent: int,
    status: str
) -> Dict[str, Any]:
    conn = get_db()
    cursor = conn.cursor()
    now = time.time()
    tx_id = f"TX-{int(now * 1000) % 10000000:07d}"
    cursor.execute("""
    INSERT INTO outbound_transmissions (transmission_id, task_id, destination_url, payload_summary, payload_sha256, bytes_sent, status, timestamp)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (tx_id, task_id, destination_url, payload_summary, payload_sha256, bytes_sent, status, now))
    conn.commit()
    conn.close()
    return {
        "transmission_id": tx_id,
        "task_id": task_id,
        "destination_url": destination_url,
        "payload_summary": payload_summary,
        "bytes_sent": bytes_sent,
        "status": status,
        "timestamp": now
    }


def list_outbound_transmissions(limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM outbound_transmissions ORDER BY timestamp DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_backend_live_state() -> Dict[str, Any]:
    """Returns comprehensive real-time view of all backend data tables."""
    return {
        "financial": {
            "accounts": list_financial_accounts(),
            "recent_ledger": get_financial_ledger(10)
        },
        "clinical": {
            "patients": list_clinical_patients(),
            "prescriptions": get_clinical_prescriptions(limit=10)
        },
        "cloud": {
            "resources": list_cloud_resources(),
            "buckets": list_cloud_storage_buckets()
        },
        "egress": {
            "transmissions": list_outbound_transmissions(10)
        }
    }


def reset_real_backend_data():
    """Resets all live operational entities back to pristine baseline for fresh demos."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM financial_accounts")
    cursor.execute("DELETE FROM financial_ledger")
    cursor.execute("DELETE FROM clinical_patients")
    cursor.execute("DELETE FROM clinical_prescriptions")
    cursor.execute("DELETE FROM cloud_resources")
    cursor.execute("DELETE FROM cloud_storage_buckets")
    cursor.execute("DELETE FROM cloud_storage_objects")
    cursor.execute("DELETE FROM outbound_transmissions")
    conn.commit()
    seed_real_backend_entities(conn)
    seed_default_users(conn)
    conn.close()


# -------------------------------------------------------------
# USER AUTHENTICATION & ROLE-BASED ACCESS CONTROL (RBAC)
# -------------------------------------------------------------

def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    if not salt:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return key.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    key, _ = hash_password(password, salt)
    return secrets.compare_digest(key, password_hash)


def seed_default_users(conn=None):
    close_when_done = False
    if conn is None:
        conn = get_db()
        close_when_done = True
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] > 0:
        if close_when_done:
            conn.close()
        return

    now = time.time()
    defaults = [
        # 1. SuperAdmin (The User)
        (
            "usr-superadmin",
            "superadmin",
            "admin@aegis.runtime",
            "admin123",
            "Wania (SuperAdmin)",
            "SUPERADMIN",
            "ALL",
            "#0ea5e9"
        ),
        # 2. Chief Compliance Officer
        (
            "usr-compliance",
            "compliance",
            "compliance@aegis.runtime",
            "compliance123",
            "Chief Compliance Officer",
            "COMPLIANCE_OFFICER",
            "FINTECH,HEALTHCARE",
            "#10b981"
        ),
        # 3. Autonomous Task Operator
        (
            "usr-operator",
            "operator",
            "operator@aegis.runtime",
            "operator123",
            "Autonomous Task Operator",
            "OPERATOR",
            "ALL",
            "#8b5cf6"
        ),
        # 4. External Regulatory Auditor
        (
            "usr-auditor",
            "auditor",
            "auditor@aegis.runtime",
            "auditor123",
            "External Regulatory Auditor",
            "VIEWER",
            "HEALTHCARE",
            "#f59e0b"
        )
    ]

    for uid, uname, uemail, upass, ufullname, urole, uclearance, ucolor in defaults:
        h, s = hash_password(upass)
        cursor.execute("""
        INSERT INTO users (id, username, email, password_hash, salt, role, full_name, sector_clearance, avatar_color, created_at, last_login)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (uid, uname, uemail, h, s, urole, ufullname, uclearance, ucolor, now, now))
    conn.commit()
    if close_when_done:
        conn.close()


def create_user(
    username: str,
    email: str,
    password: str,
    full_name: Optional[str] = None,
    role: str = "OPERATOR",
    sector_clearance: str = "ALL",
    avatar_color: str = "#0ea5e9"
) -> Dict[str, Any]:
    conn = get_db()
    cursor = conn.cursor()
    now = time.time()
    uid = f"usr-{secrets.token_hex(4)}"
    h, s = hash_password(password)

    allowed_roles = ["SUPERADMIN", "COMPLIANCE_OFFICER", "OPERATOR", "VIEWER"]
    clean_role = role.upper() if role.upper() in allowed_roles else "OPERATOR"

    cursor.execute("""
    INSERT INTO users (id, username, email, password_hash, salt, role, full_name, sector_clearance, avatar_color, created_at, last_login)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (uid, username.strip(), email.strip().lower(), h, s, clean_role, full_name or username, sector_clearance, avatar_color, now, now))
    conn.commit()
    conn.close()

    return {
        "id": uid,
        "username": username.strip(),
        "email": email.strip().lower(),
        "role": clean_role,
        "full_name": full_name or username,
        "sector_clearance": sector_clearance,
        "avatar_color": avatar_color,
        "created_at": now
    }


def authenticate_user(username_or_email: str, password: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    term = username_or_email.strip().lower()
    cursor.execute("SELECT * FROM users WHERE lower(username) = ? OR lower(email) = ?", (term, term))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None

    user = dict(row)
    if not verify_password(password, user["password_hash"], user["salt"]):
        conn.close()
        return None

    now = time.time()
    cursor.execute("UPDATE users SET last_login = ? WHERE id = ?", (now, user["id"]))
    conn.commit()
    conn.close()

    user.pop("password_hash", None)
    user.pop("salt", None)
    user["last_login"] = now
    return user


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, email, role, full_name, sector_clearance, avatar_color, created_at, last_login FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, email, role, full_name, sector_clearance, avatar_color, created_at, last_login FROM users WHERE lower(email) = ?", (email.strip().lower(),))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, email, role, full_name, sector_clearance, avatar_color, created_at, last_login FROM users WHERE lower(username) = ?", (username.strip().lower(),))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None



def list_all_users() -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, email, role, full_name, sector_clearance, avatar_color, created_at, last_login FROM users ORDER BY created_at ASC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_user_role(user_id: str, new_role: str) -> bool:
    allowed_roles = ["SUPERADMIN", "COMPLIANCE_OFFICER", "OPERATOR", "VIEWER"]
    clean_role = new_role.upper()
    if clean_role not in allowed_roles:
        return False
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET role = ? WHERE id = ?", (clean_role, user_id))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected


def create_user_session(user_id: str, duration_hours: int = 72) -> str:
    conn = get_db()
    cursor = conn.cursor()
    token = f"sess_{secrets.token_hex(24)}"
    now = time.time()
    expires = now + (duration_hours * 3600)
    cursor.execute("INSERT INTO user_sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)", (token, user_id, now, expires))
    conn.commit()
    conn.close()
    return token


def get_user_from_session(token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    conn = get_db()
    cursor = conn.cursor()
    now = time.time()
    cursor.execute("""
    SELECT u.id, u.username, u.email, u.role, u.full_name, u.sector_clearance, u.avatar_color, u.created_at, u.last_login
    FROM user_sessions s
    JOIN users u ON s.user_id = u.id
    WHERE s.token = ? AND s.expires_at > ?
    """, (token, now))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def delete_user_session(token: str) -> bool:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_sessions WHERE token = ?", (token,))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected


def delete_user(user_id: str) -> bool:
    if user_id == "usr-superadmin":
        return False  # Protected root admin
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
    cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    affected = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return affected


def save_task_plan(plan_data: Dict[str, Any], user_id: str = "usr-superadmin"):
    conn = get_db()
    cursor = conn.cursor()
    task_id = plan_data.get("task_id")
    user_request = plan_data.get("user_request", "")
    sector = str(plan_data.get("sector", "GENERAL"))
    status = plan_data.get("status", "ACTIVE")
    steps = plan_data.get("steps", [])
    completed_count = sum(1 for s in steps if s.get("status") in ["EXECUTED", "COMPLETED"])
    blocked_count = sum(1 for s in steps if s.get("status") == "BLOCKED")
    paused_count = sum(1 for s in steps if s.get("status") in ["PAUSED_FOR_REVIEW", "PENDING_REVIEW", "HELD_FOR_REVIEW", "PAUSED_DEPENDENCY"])

    cursor.execute("""
    INSERT OR REPLACE INTO task_plans (task_id, user_id, user_request, sector, status, plan_json, created_at, completed_count, blocked_count, paused_count)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        task_id,
        user_id,
        user_request,
        sector,
        status,
        json.dumps(plan_data),
        time.time(),
        completed_count,
        blocked_count,
        paused_count
    ))
    conn.commit()
    conn.close()


def list_task_plans(user_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    conn = get_db()
    cursor = conn.cursor()
    if user_id:
        cursor.execute("SELECT * FROM task_plans WHERE user_id = ? ORDER BY created_at DESC LIMIT ?", (user_id, limit))
    else:
        cursor.execute("SELECT * FROM task_plans ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    results = []
    for r in rows:
        d = dict(r)
        if d.get("plan_json"):
            try:
                d["plan"] = json.loads(d["plan_json"])
            except Exception:
                d["plan"] = None
        results.append(d)
    conn.close()
    return results



