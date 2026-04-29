"""Helpers for dependency setup inside the QGIS Python environment."""

from __future__ import annotations

import importlib
import os
import site
import subprocess
import sys
from pathlib import Path

from qgis.PyQt.QtCore import QSettings


class DependencyManager:
    """Checks and installs plugin Python dependencies."""

    EARTH_ENGINE_PACKAGE = "earthengine-api"
    PLUGIN_DEPENDENCY_DIRNAME = "_python_deps"
    SETTINGS_KEY_PROJECT_ID = "qgis_environmental_assessment_qgis4/earth_engine_project_id"

    @classmethod
    def qgis_python_path(cls):
        """Return the actual Python interpreter for the active QGIS install."""
        executable = Path(sys.executable)
        candidates = []

        if executable.name.lower().startswith("python"):
            candidates.append(executable)

        prefix_path = Path(sys.prefix)
        candidates.extend(
            [
                prefix_path / "python.exe",
                prefix_path.parent.parent / "bin" / "python.exe",
                executable.parent / "python.exe",
            ]
        )

        seen = set()
        for candidate in candidates:
            resolved = str(candidate)
            if resolved in seen:
                continue
            seen.add(resolved)
            if candidate.exists():
                return str(candidate)

        return sys.executable

    @classmethod
    def plugin_root(cls):
        return Path(__file__).resolve().parent

    @classmethod
    def plugin_dependency_path(cls):
        return cls.plugin_root() / cls.PLUGIN_DEPENDENCY_DIRNAME

    @staticmethod
    def user_site_path():
        try:
            return site.getusersitepackages()
        except Exception:
            return None

    def earth_engine_available(self):
        self._refresh_dependency_paths()
        try:
            importlib.import_module("ee")
            return True
        except ImportError:
            return False

    def install_earth_engine(self):
        """Install or upgrade Earth Engine into the plugin-managed dependency folder."""
        dependency_path = self.plugin_dependency_path()
        dependency_path.mkdir(parents=True, exist_ok=True)

        command = [
            self.qgis_python_path(),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--target",
            str(dependency_path),
            self.EARTH_ENGINE_PACKAGE,
        ]
        environment = os.environ.copy()
        existing_python_path = environment.get("PYTHONPATH", "")
        paths = [str(dependency_path)]
        if existing_python_path:
            paths.append(existing_python_path)
        environment["PYTHONPATH"] = os.pathsep.join(paths)

        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            env=environment,
        )
        self._refresh_dependency_paths()
        return completed.returncode == 0, (completed.stdout or "").strip(), (completed.stderr or "").strip()

    def authenticate_earth_engine(self):
        """Run Earth Engine authentication from inside QGIS."""
        self._refresh_dependency_paths()
        ee = importlib.import_module("ee")
        ee.Authenticate()
        self.initialize_earth_engine()

    def initialize_earth_engine(self):
        """Initialize Earth Engine after a successful install/auth step."""
        self._refresh_dependency_paths()
        ee = importlib.import_module("ee")
        project_id = self.project_id()
        if project_id:
            ee.Initialize(project=project_id)
        else:
            ee.Initialize()

    def project_id(self):
        value = QSettings().value(self.SETTINGS_KEY_PROJECT_ID, "", type=str)
        return (value or "").strip()

    def set_project_id(self, project_id):
        QSettings().setValue(self.SETTINGS_KEY_PROJECT_ID, (project_id or "").strip())

    def _refresh_dependency_paths(self):
        dependency_path = self.plugin_dependency_path()
        if dependency_path.exists() and str(dependency_path) not in sys.path:
            sys.path.insert(0, str(dependency_path))

        user_site = self.user_site_path()
        if user_site and user_site not in sys.path:
            site.addsitedir(user_site)
        importlib.invalidate_caches()
