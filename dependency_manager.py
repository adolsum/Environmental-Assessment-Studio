"""Helpers for dependency setup inside the QGIS Python environment."""

from __future__ import annotations

import importlib
import os
import re
import shutil
import site
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

try:
    from qgis.core import QgsApplication
except Exception:  # pragma: no cover - only used outside QGIS during packaging checks.
    QgsApplication = None
from qgis.PyQt.QtCore import QSettings


class DependencyManager:
    """Checks and installs plugin Python dependencies."""

    EARTH_ENGINE_PACKAGE = "earthengine-api"
    PLUGIN_DEPENDENCY_DIRNAME = f"_python_deps_py{sys.version_info.major}{sys.version_info.minor}"
    PROFILE_DEPENDENCY_DIRNAME = "environmental_assessment_studio"
    ACTIVE_DEPENDENCY_MARKER = f"active_dependency_py{sys.version_info.major}{sys.version_info.minor}.txt"
    SETTINGS_KEY_PROJECT_ID = "qgis_environmental_assessment_qgis4/earth_engine_project_id"
    PROJECT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
    _last_import_error = ""

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
        """Persistent dependency cache that survives plugin uninstall/reinstall."""
        dependency_root = cls.profile_dependency_root()
        marker_path = dependency_root / cls.ACTIVE_DEPENDENCY_MARKER
        if marker_path.exists():
            try:
                marked_path = Path(marker_path.read_text(encoding="utf-8").strip())
                if marked_path.exists():
                    return marked_path
            except Exception:
                pass
        return cls.stable_dependency_path()

    @classmethod
    def stable_dependency_path(cls):
        return cls.profile_dependency_root() / cls.PLUGIN_DEPENDENCY_DIRNAME

    @classmethod
    def profile_dependency_root(cls):
        if QgsApplication is not None:
            settings_path = QgsApplication.qgisSettingsDirPath()
            if settings_path:
                return (
                    Path(settings_path)
                    / "python"
                    / cls.PROFILE_DEPENDENCY_DIRNAME
                )

        appdata = os.environ.get("APPDATA")
        if appdata:
            return (
                Path(appdata)
                / "QGIS"
                / cls.PROFILE_DEPENDENCY_DIRNAME
            )

        return cls.plugin_root()

    @classmethod
    def legacy_plugin_dependency_path(cls):
        return cls.plugin_root() / cls.PLUGIN_DEPENDENCY_DIRNAME

    @classmethod
    def legacy_unversioned_dependency_path(cls):
        if QgsApplication is not None:
            settings_path = QgsApplication.qgisSettingsDirPath()
            if settings_path:
                return (
                    Path(settings_path)
                    / "python"
                    / cls.PROFILE_DEPENDENCY_DIRNAME
                    / "_python_deps"
                )

        appdata = os.environ.get("APPDATA")
        if appdata:
            return (
                Path(appdata)
                / "QGIS"
                / cls.PROFILE_DEPENDENCY_DIRNAME
                / "_python_deps"
            )

        return cls.plugin_root() / "_python_deps"

    @staticmethod
    def user_site_path():
        try:
            return site.getusersitepackages()
        except Exception:
            return None

    def earth_engine_available(self):
        self._refresh_dependency_paths()
        self._clear_dependency_import_cache()
        self._last_import_error = ""
        try:
            module = importlib.import_module("ee")
            if not hasattr(module, "Initialize"):
                module_file = getattr(module, "__file__", None) or getattr(module, "__path__", None)
                self._last_import_error = (
                    "The Earth Engine package folder was found, but it did not load as the real API "
                    f"(missing ee.Initialize). Loaded module location: {module_file}"
                )
                return False
            return True
        except Exception as exc:
            self._last_import_error = str(exc)
            return False

    def earth_engine_import_error(self):
        return self._last_import_error

    def install_earth_engine(self):
        """Install or upgrade Earth Engine into a persistent QGIS-profile dependency folder."""
        dependency_root = self.profile_dependency_root()
        dependency_root.mkdir(parents=True, exist_ok=True)
        dependency_path = dependency_root / f"{self.PLUGIN_DEPENDENCY_DIRNAME}_{int(time.time())}"
        if dependency_path.exists():
            try:
                shutil.rmtree(dependency_path)
            except Exception:
                pass
        dependency_path.mkdir(parents=True, exist_ok=True)

        command = [
            self.qgis_python_path(),
            "-m",
            "pip",
            "install",
            "--upgrade",
            "--force-reinstall",
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
            timeout=900,
        )
        if completed.returncode != 0:
            try:
                shutil.rmtree(dependency_path)
            except Exception:
                pass
        stdout = (completed.stdout or "").strip()
        if completed.returncode == 0:
            marker_path = dependency_root / self.ACTIVE_DEPENDENCY_MARKER
            marker_path.write_text(str(dependency_path), encoding="utf-8")
            self._refresh_dependency_paths()
            self._clear_dependency_import_cache()
            stdout = (
                f"{stdout}\n\nInstalled into persistent dependency folder: {dependency_path}\n"
                "The plugin has switched to this fresh dependency folder. You can authenticate immediately. "
                "Restart QGIS only if it still reports an old or incompatible dependency."
            ).strip()
        else:
            self._refresh_dependency_paths()
            self._clear_dependency_import_cache()
        return completed.returncode == 0, stdout, (completed.stderr or "").strip()

    def authenticate_earth_engine(self):
        """Run Earth Engine authentication from inside QGIS."""
        self._refresh_dependency_paths()
        self._clear_dependency_import_cache()
        ee = importlib.import_module("ee")
        ee.Authenticate()
        self.initialize_earth_engine()

    def initialize_earth_engine(self):
        """Initialize Earth Engine after a successful install/auth step."""
        self._refresh_dependency_paths()
        self._clear_dependency_import_cache()
        ee = importlib.import_module("ee")
        project_id = self.project_id()
        if project_id:
            ee.Initialize(project=project_id)
        else:
            ee.Initialize()

    def project_id(self):
        value = QSettings().value(self.SETTINGS_KEY_PROJECT_ID, "", type=str)
        return self.normalize_project_id(value)

    def set_project_id(self, project_id):
        normalized = self.validate_project_id(project_id)
        QSettings().setValue(self.SETTINGS_KEY_PROJECT_ID, normalized)
        return normalized

    @classmethod
    def normalize_project_id(cls, project_id):
        value = unicodedata.normalize("NFKC", (project_id or ""))
        for character in ("\u200b", "\u200c", "\u200d", "\ufeff"):
            value = value.replace(character, "")
        for dash in ("\u2010", "\u2011", "\u2012", "\u2013", "\u2014", "\u2212"):
            value = value.replace(dash, "-")
        return value.strip().lower()

    @classmethod
    def validate_project_id(cls, project_id):
        normalized = cls.normalize_project_id(project_id)
        if not normalized:
            raise ValueError("Enter the Google Cloud project ID registered for Earth Engine.")
        if any(character.isspace() for character in normalized):
            raise ValueError(
                "Project IDs cannot contain spaces. Enter the actual Google Cloud project ID, not the display name."
            )
        if "_" in normalized:
            raise ValueError("Project IDs cannot contain underscores. Use the Google Cloud project ID exactly as shown.")
        if not cls.PROJECT_ID_PATTERN.match(normalized):
            raise ValueError(
                "Project IDs must be 6 to 30 characters, start with a letter, use only lowercase letters, numbers, "
                "or hyphens, and cannot end with a hyphen."
            )
        return normalized

    def _refresh_dependency_paths(self):
        persistent_path = self.plugin_dependency_path()
        stable_path = self.stable_dependency_path()
        legacy_path = self.legacy_plugin_dependency_path()
        legacy_unversioned_path = self.legacy_unversioned_dependency_path()
        legacy_unversioned_text = str(legacy_unversioned_path)
        dependency_root_text = str(self.profile_dependency_root()).lower()
        sys.path[:] = [
            path
            for path in sys.path
            if path != legacy_unversioned_text and not str(path).lower().startswith(dependency_root_text)
        ]
        if legacy_path.exists() and not stable_path.exists() and persistent_path == stable_path:
            try:
                shutil.copytree(legacy_path, stable_path)
            except Exception:
                pass

        dependency_paths = [
            persistent_path,
            legacy_path,
        ]
        for dependency_path in dependency_paths:
            if dependency_path.exists() and str(dependency_path) not in sys.path:
                sys.path.insert(0, str(dependency_path))

        user_site = self.user_site_path()
        if user_site and user_site not in sys.path:
            site.addsitedir(user_site)
        importlib.invalidate_caches()

    def _clear_dependency_import_cache(self):
        dependency_roots = [
            str(self.profile_dependency_root()).lower(),
            str(self.legacy_unversioned_dependency_path()).lower(),
            str(self.legacy_plugin_dependency_path()).lower(),
        ]
        prefixes = (
            "ee",
            "google",
            "cryptography",
            "jwt",
            "rsa",
            "httplib2",
            "oauth2client",
        )
        for module_name, module in list(sys.modules.items()):
            if module_name != prefixes and not module_name.startswith(tuple(f"{prefix}." for prefix in prefixes)):
                if module_name not in prefixes:
                    continue
            module_file = str(getattr(module, "__file__", "") or "").lower()
            if not module_file or any(root and module_file.startswith(root) for root in dependency_roots):
                sys.modules.pop(module_name, None)
        importlib.invalidate_caches()
