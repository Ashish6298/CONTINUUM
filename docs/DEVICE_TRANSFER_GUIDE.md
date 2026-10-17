# Project Continuum — Offline Device Transfer Guide

> **Milestone 43**: Export, Backup, Import and Transfer  
> **Phase 79**: Device Transfer Guide  
> **Philosophy**: 100% Local-First, Offline, Privacy-Guaranteed, Zero-Cloud Work Continuity

---

## 1. Overview & Core Philosophy

Project Continuum is architected for strict offline independence. Moving your work, activity histories, checkpoint timelines, and decisions between different computers (e.g. workstation to laptop, air-gapped lab to development machine) **never requires**:
- Cloud accounts or third-party servers
- Live sync daemons or network listeners
- Centralized database credentials
- External internet access or telemetry

All transfers occur explicitly through self-contained, integrity-hashed **Transfer Packages** (`.continuum-transfer.tar.gz`) that can be safely copied via USB flash drive, external hard drive, local LAN share, or secure air-gapped media.

---

## 2. Exact Data Included vs. Excluded

Transfer packages follow deterministic, minimal-scope boundary rules:

### ✅ Included in Transfer Package
| Category | Storage Path | Description |
| :--- | :--- | :--- |
| **Activity Ground Truth** | `activities/<id>/activity.json` | Core metadata: title, domain type, status, tags, custom attributes, collections. |
| **Checkpoint History** | `activities/<id>/checkpoints/<id>.json` | Full DAG ancestry, completed work, tactical next actions, decisions, and progress. |
| **Integrity Manifest** | `manifest.json` | 64KB chunk-streamed SHA-256 checksums of every member file and format version metadata. |
| **Subsystem Configurations**| `settings.json`, `privacy.json`, `retention.json`, `triggers.json` | Local workspace policies, secret redaction rules, and trigger configurations. |
| **Permitted Artifacts** | `artifacts/...` | User-approved artifact snapshots captured during work sessions. |

### ❌ Excluded from Transfer Package
| Category | Reason for Exclusion |
| :--- | :--- |
| **Derived SQLite Databases** (`*.db`, `*.db-wal`) | Rebuilt automatically on destination device from authoritative JSON files. |
| **Temporary / Cache Files** (`*.tmp`, `*.cache`) | Non-authoritative transient state. |
| **Session & Daemon Lockfiles** (`session.token`, `*.pid`) | Ephemeral process security tokens unique to each host. |
| **Local Retention Trash Backups** (`retention_backups/*`) | Device-specific pruning undo buffers. |
| **High-Risk Secret Files** (`.env`, `*.pem`, `*.key`) | Stripped automatically by Continuum Sanitizer to prevent accidental secret leakage. |

---

## 3. Version Compatibility Matrix

Transfer packages use Semantic Versioning for format structures:

| Format Version | Compatibility Level | Behavior |
| :--- | :--- | :--- |
| `1.0.0` (Current) | **Full Match** | Direct, lossless staged import with 100% feature preservation. |
| `1.0.x` (Minor Patch) | **Compatible** | Automatically accepted with informative audit notice in transfer log. |
| `2.x.x` (Major Delta) | **Incompatible** | Blocked pre-mutation. Prevents state corruption until destination is upgraded. |

---

## 4. Step-by-Step Manual Transfer Workflow

### Step 1: Export on Source Machine
On your source device, generate an offline transfer package:

```bash
# Using Continuum Python CLI / Engine
python -c "from core.device_transfer import DeviceTransferManager; print(DeviceTransferManager('.').create_transfer_package())"
```
Or via REST API:
```http
POST /api/v1/backup/create
Content-Type: application/json

{
  "backup_name": "continuum_transfer_mywork.tar.gz"
}
```
*Output*: A single compressed file at `.continuum/backups/continuum_transfer_mywork.tar.gz`.

### Step 2: Transport the File
Copy `continuum_transfer_mywork.tar.gz` to your removable drive, local folder, or external media.

### Step 3: Inspect on Destination Machine (Pre-Flight)
Before modifying your destination workspace, inspect the archive to verify integrity and detect any conflicting records:

```python
from core.device_transfer import DeviceTransferManager

mgr = DeviceTransferManager("path/to/destination/workspace")
inspection = mgr.inspect_package("path/to/continuum_transfer_mywork.tar.gz")
print(f"Activities: {inspection.total_activities}, Checkpoints: {inspection.total_checkpoints}")
print(f"Format Compatible: {inspection.is_version_compatible}")
```

### Step 4: Import on Destination Machine
Execute the atomic staged import choosing an explicit conflict strategy:

```python
from core.device_transfer import DeviceTransferManager
from core.enums import ConflictResolutionStrategy

mgr = DeviceTransferManager("path/to/destination/workspace")
result = mgr.import_transfer_package(
    package_path="path/to/continuum_transfer_mywork.tar.gz",
    conflict_strategy=ConflictResolutionStrategy.RENAME_NEW, # or REJECT, OVERWRITE, SKIP
    handle_missing_artifacts=True
)
print("Transfer Successful:", result.success)
```

---

## 5. Conflict Resolution Options

When importing on a destination machine where an activity or checkpoint ID already exists:

1. **`DEDUPLICATE`**: If ID and content checksum match identically, it is safely skipped without error.
2. **`REJECT` (Default Fail-Safe)**: Halts import before modifying any destination files if divergent records exist.
3. **`RENAME_NEW`**: Assigns fresh UUIDs to conflicting incoming records and rewires child checkpoints, keeping both local and incoming versions.
4. **`OVERWRITE`**: Requires explicit `confirm_overwrite=True`. Backs up prior local files to rollback before replacing.
5. **`SKIP`**: Keeps local records intact and skips conflicting incoming items.

---

## 6. Missing Destination Artifacts

If a checkpoint references an external file on the source machine (e.g. `C:\Users\Alice\Projects\doc.pdf`) that does not exist on the destination machine (e.g. `/home/bob/projects/`):
- Continuum's `DeviceTransferManager` automatically detects the missing path.
- The reference is marked with `missing_on_device: true` and `device_origin_path`.
- **Continuity and DAG timeline remain 100% unbroken.** Checkpoint resumption and history navigation continue working without disruption.
- A summary of reconciled missing artifacts is returned in `TransferImportResult.missing_artifacts_detected`.

---

## 7. Security & Privacy Guarantees

- **No Remote Telemetry**: Zero data is transmitted to external servers.
- **Pre-Mutation Validation**: Archives with corrupted tar headers, altered checksums, or malicious path-traversal members (Zip Slip) are rejected immediately.
- **No Unverifiable Encryption Claims**: Archives are stored in standard gzip-compressed tar format; integrity is protected by SHA-256 cryptographic hashes.
