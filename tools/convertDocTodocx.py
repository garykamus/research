"""
convert_doc_to_docx.py
======================
Batch-convert legacy .doc files to .docx on Windows using the installed
Microsoft Word, while satisfying mandatory Microsoft Purview / MIP
sensitivity-labeling (the MSIP_Label_* properties) so the save does not
block on the in-pane classification prompt.

Behaviour
---------
For each .doc found:
  1. Open in Word (headless, add-in code disabled via AutomationSecurity).
  2. Read the source document's existing MIP label, if any.
       - If present  -> re-apply that same label (preserve classification).
       - If missing  -> apply the configured DEFAULT label.
  3. SaveAs2 to .docx (FileFormat = 16).
  4. Log success / failure and move on.

Requires
--------
  - Windows with Microsoft Word (Office 365 / 2016+) installed.
  - pip install pywin32

Usage
-----
  python convert_doc_to_docx.py --input "C:\\docs" --output "C:\\docs_out"

  # dry run (open + read label, but do not save):
  python convert_doc_to_docx.py --input "C:\\docs" --dry-run

  # overwrite existing .docx outputs:
  python convert_doc_to_docx.py --input "C:\\docs" --overwrite

IMPORTANT
---------
Set DEFAULT_LABEL_ID / DEFAULT_LABEL_NAME below to YOUR tenant's default
label (get the GUID from an already-labelled .docx: unzip it and read
docProps/custom.xml -> MSIP_Label_<GUID>_Name). Confirm the correct default
with whoever owns your Purview labelling policy before running at scale.
"""

import os
import re
import sys
import glob
import time
import argparse
import logging
from datetime import datetime

try:
    import win32com.client as win32
    import pythoncom
    from win32com.client import constants
except ImportError:
    sys.exit("pywin32 is required:  pip install pywin32")


# ──────────────────────────────────────────────────────────────────────────
# CONFIG — EDIT THESE FOR YOUR TENANT
# ──────────────────────────────────────────────────────────────────────────

# The default label applied ONLY when a source .doc has no MIP label.
# Get the GUID + name from an already-labelled .docx (docProps/custom.xml).
DEFAULT_LABEL_ID   = "00000000-0000-0000-0000-000000000000"  # <-- replace
DEFAULT_LABEL_NAME = "Internal"                              # <-- replace

# Word SaveAs format code: 16 = wdFormatXMLDocument (.docx)
WD_FORMAT_DOCX = 16

# AssignmentMethod for SetLabel: 1 = Standard (user), 2 = Privileged, 0 = Auto.
# Start with 1. If your tenant rejects programmatic Standard, try 2.
LABEL_ASSIGNMENT_METHOD = 1

# Office automation security: 3 = msoAutomationSecurityForceDisable
# (stops add-in / macro code — incl. the in-house footer add-in — from running).
MSO_AUTOMATION_SECURITY = 3

# ──────────────────────────────────────────────────────────────────────────


def setup_logging(log_path):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def read_existing_mip_label(doc):
    """
    Return (label_id, label_name) if the document already carries a MIP label,
    else (None, None). Reads the MSIP_Label_<GUID>_* custom document properties.
    """
    label_id = None
    label_name = None
    try:
        props = doc.CustomDocumentProperties
        # Property names look like: MSIP_Label_<GUID>_Name / _Enabled / etc.
        name_re = re.compile(
            r"^MSIP_Label_([0-9a-fA-F-]{36})_Name$"
        )
        for p in props:
            try:
                m = name_re.match(p.Name)
            except Exception:
                continue
            if m:
                label_id = m.group(1)
                try:
                    label_name = str(p.Value)
                except Exception:
                    label_name = None
                break
    except Exception as e:
        logging.debug("Could not read custom properties: %s", e)
    return label_id, label_name


def apply_label(doc, label_id, label_name):
    """Apply a MIP sensitivity label to the open document via the Office API."""
    sl = doc.SensitivityLabel
    info = sl.CreateLabelInfo()
    info.LabelId = label_id
    info.LabelName = label_name
    info.AssignmentMethod = LABEL_ASSIGNMENT_METHOD
    # SetLabel(newLabel, oldLabel). Passing the same info for both is fine when
    # there is no meaningful prior label to reconcile against.
    sl.SetLabel(info, info)


def ensure_label(doc):
    """
    Make sure the document has a label before saving. Preserve an existing one,
    otherwise stamp the configured default. Returns the (id, name) used.
    """
    label_id, label_name = read_existing_mip_label(doc)
    if label_id:
        logging.info("    existing label found: %s (%s) — preserving",
                     label_name, label_id)
    else:
        label_id, label_name = DEFAULT_LABEL_ID, DEFAULT_LABEL_NAME
        logging.info("    no label on source — applying default: %s (%s)",
                     label_name, label_id)
    try:
        apply_label(doc, label_id, label_name)
    except Exception as e:
        # Some tenants reject Standard assignment; retry once as Privileged.
        logging.warning("    SetLabel failed with method %s (%s); retrying as Privileged",
                        LABEL_ASSIGNMENT_METHOD, e)
        sl = doc.SensitivityLabel
        info = sl.CreateLabelInfo()
        info.LabelId = label_id
        info.LabelName = label_name
        info.AssignmentMethod = 2  # Privileged
        sl.SetLabel(info, info)
    return label_id, label_name


def out_path_for(src, input_root, output_root):
    """Mirror the input folder tree under output_root, swapping .doc -> .docx."""
    rel = os.path.relpath(src, input_root)
    rel_docx = os.path.splitext(rel)[0] + ".docx"
    dst = os.path.join(output_root, rel_docx)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    return dst


def convert_one(word, src, dst, dry_run=False):
    doc = None
    try:
        doc = word.Documents.Open(
            os.path.abspath(src),
            ConfirmConversions=False,
            ReadOnly=False,
            AddToRecentFiles=False,
        )
        ensure_label(doc)
        if dry_run:
            logging.info("    [dry-run] would save -> %s", dst)
        else:
            doc.SaveAs2(os.path.abspath(dst), FileFormat=WD_FORMAT_DOCX)
            logging.info("    saved -> %s", dst)
        return True
    finally:
        if doc is not None:
            try:
                doc.Close(SaveChanges=0)  # 0 = wdDoNotSaveChanges
            except Exception:
                pass


def main():
    ap = argparse.ArgumentParser(
        description="Batch convert .doc -> .docx via Word, handling MIP labels."
    )
    ap.add_argument("--input", required=True, help="Folder containing .doc files")
    ap.add_argument("--output", help="Output folder (default: <input>_docx)")
    ap.add_argument("--overwrite", action="store_true",
                    help="Overwrite existing .docx outputs")
    ap.add_argument("--dry-run", action="store_true",
                    help="Open and label-check but do not save")
    ap.add_argument("--visible", action="store_true",
                    help="Show Word UI (useful for first test)")
    args = ap.parse_args()

    input_root = os.path.abspath(args.input)
    if not os.path.isdir(input_root):
        sys.exit(f"Input folder not found: {input_root}")
    output_root = os.path.abspath(args.output) if args.output else input_root + "_docx"
    os.makedirs(output_root, exist_ok=True)

    log_path = os.path.join(
        output_root, f"convert_log_{datetime.now():%Y%m%d_%H%M%S}.txt"
    )
    setup_logging(log_path)

    if DEFAULT_LABEL_ID == "00000000-0000-0000-0000-000000000000":
        logging.warning("DEFAULT_LABEL_ID is still the placeholder — edit the "
                        "CONFIG block before running on unlabelled files.")

    # Gather .doc files (exclude .docx and Word temp/owner files ~$...).
    pattern = os.path.join(input_root, "**", "*.doc")
    files = [
        f for f in glob.glob(pattern, recursive=True)
        if f.lower().endswith(".doc")
        and not os.path.basename(f).startswith("~$")
    ]
    logging.info("Found %d .doc file(s) under %s", len(files), input_root)
    if not files:
        return

    pythoncom.CoInitialize()
    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = bool(args.visible)
    word.DisplayAlerts = 0  # wdAlertsNone
    try:
        word.AutomationSecurity = MSO_AUTOMATION_SECURITY
    except Exception as e:
        logging.warning("Could not set AutomationSecurity: %s", e)

    ok = fail = skipped = 0
    t0 = time.time()
    try:
        for i, src in enumerate(files, 1):
            dst = out_path_for(src, input_root, output_root)
            logging.info("[%d/%d] %s", i, len(files), src)
            if os.path.exists(dst) and not args.overwrite and not args.dry_run:
                logging.info("    exists, skipping (use --overwrite to replace)")
                skipped += 1
                continue
            try:
                convert_one(word, src, dst, dry_run=args.dry_run)
                ok += 1
            except Exception as e:
                logging.error("    FAILED: %s", e, exc_info=False)
                fail += 1
    finally:
        try:
            word.Quit()
        except Exception:
            pass
        pythoncom.CoUninitialize()

    dt = time.time() - t0
    logging.info("─" * 60)
    logging.info("Done in %.1fs  |  ok=%d  failed=%d  skipped=%d",
                 dt, ok, fail, skipped)
    logging.info("Log written to: %s", log_path)


if __name__ == "__main__":
    main()