"""Plugin bootstrap for Environmental Assessment Studio."""

from pathlib import Path

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction

from .environmental_assessment_dialog import EnvironmentalAssessmentDialog


class EnvironmentalAssessmentPlugin:
    """Registers plugin UI for Earth Engine powered environmental assessments."""

    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None

    def initGui(self):
        """Create toolbar and menu action."""
        icon_path = Path(__file__).with_name("icon.svg")
        self.action = QAction(QIcon(str(icon_path)), "Environmental Assessment Studio", self.iface.mainWindow())
        self.action.triggered.connect(self.show_dialog)

        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("&Environmental Assessment Studio", self.action)

    def unload(self):
        """Unregister plugin UI when the plugin unloads."""
        if self.dialog is not None:
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None

        if self.action is not None:
            self.iface.removeToolBarIcon(self.action)
            self.iface.removePluginMenu("&Environmental Assessment Studio", self.action)
            self.action.deleteLater()
            self.action = None

    def show_dialog(self):
        """Show or create the popup dialog."""
        if self.dialog is None:
            self.dialog = EnvironmentalAssessmentDialog(self.iface)

        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
