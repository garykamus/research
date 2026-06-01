# PyInstaller spec for Release Orchestration Dashboard
# Build: cd release-orchestration && pyinstaller packaging/app.spec
# Output: dist/ReleaseOrchestration.exe
#
# Phase 4 notes:
#   - console=False  → windowed app, no terminal
#   - Data directory for DB/logs: %APPDATA%\ReleaseOrchestration  (see ui/main.py)
#   - Config YAML bundled into the exe via datas; resolved via sys._MEIPASS at runtime
#   - Playwright excluded (open decision §06.6 — bundle/download/exclude)
#   - Credentials: Windows DPAPI via core.credentials.dpapi_store (no key in exe)
#   - Version info: set via version_info dict below; also readable at runtime via importlib.metadata

import sys
from pathlib import Path

block_cipher = None
root = Path(SPECPATH).parent  # release-orchestration/

# ---------------------------------------------------------------------------
# Version info embedded in the Windows PE header
# ---------------------------------------------------------------------------
version_info = {
    "version": (0, 1, 0, 0),
    "company_name": "ReleaseOrch",
    "file_description": "AS400 Multi-Market Release Orchestration Dashboard",
    "internal_name": "ReleaseOrchestration",
    "original_filename": "ReleaseOrchestration.exe",
    "product_name": "Release Orchestration Dashboard",
    "product_version": "0.1.0",
}

a = Analysis(
    [str(root / 'ui' / 'main.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / 'config'), 'config'),           # bundle all config YAML
        (str(root / 'ui' / 'resources'), 'ui/resources'),   # stylesheet
    ],
    hiddenimports=[
        # Qt
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        # stdlib used at runtime
        'yaml',
        'sqlite3',
        'csv',
        'io',
        'ctypes',
        'ctypes.wintypes',
        # core — config
        'core',
        'core.models',
        'core.service',
        'core.config.loader',
        'core.config.resolver',
        'core.config.templating',
        # core — persistence
        'core.persistence.context',
        'core.persistence.database',
        'core.persistence.dal',
        'core.persistence.schema',
        'core.persistence.migrations',
        # core — engine
        'core.engine.lifecycle',
        'core.engine.audit',
        'core.engine.value_bag',
        'core.engine.advancement',
        # core — triggers (all executors must be listed so registry can load them)
        'core.triggers.registry',
        'core.triggers.base',
        'core.triggers.none_executor',
        'core.triggers.http_executor',
        'core.triggers.http_flow_executor',
        'core.triggers.webhook_executor',
        'core.triggers.script_executor',
        'core.triggers.browser_executor',
        # core — integrations (Phase 2/3)
        'core.integrations.base',
        'core.integrations.jenkins',
        'core.integrations.github',
        'core.integrations.servicenow',
        'core.integrations.confluence',
        'core.integrations.jira',
        # core — credentials (DPAPI — Phase 2/4)
        'core.credentials.base',
        'core.credentials.dpapi_store',
        'core.credentials.stub_store',
        # core — worker + webhook
        'core.worker.poller',
        'core.webhook.receiver',
        # migrations
        'migrations.initial_schema',
        'migrations.migration_002',
        # ui — shared widgets
        'ui.widgets',
        # ui — views
        'ui.matrix_view',
        'ui.lane_detail_view',
        'ui.stepviews.registry',
        'ui.stepviews.generic_view',
        'ui.stepviews.external_hold_view',
        'ui.stepviews.cr_creation_view',
        'ui.stepviews.evidence_update_view',
        'ui.stepviews.confluence_release_view',
        # ui — dialogs (Phase 1/2/3/4)
        'ui.dialogs.new_lane_dialog',
        'ui.dialogs.override_dialog',
        'ui.dialogs.rename_dialog',
        'ui.dialogs.resume_hold_dialog',
        'ui.dialogs.credential_dialog',
        'ui.dialogs.first_run_dialog',
    ],
    hookspath=[],
    runtime_hooks=[],
    # Playwright is excluded — open decision (see packaging/playwright_notes.md).
    # If browser triggers are needed locally, choose bundle / first-run-download strategy.
    excludes=['playwright', 'tkinter', 'matplotlib', 'numpy', 'pandas', 'scipy'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ReleaseOrchestration',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,           # windowed — no console terminal
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(Path(SPECPATH) / 'icon.ico') if (Path(SPECPATH) / 'icon.ico').exists() else None,
    version=None,            # set to a VS_VERSION_INFO file path for full PE version embedding
)
