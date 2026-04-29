"""QGIS plugin entry point for Environmental Assessment Studio."""


def classFactory(iface):
    """Load EnvironmentalAssessmentPlugin from file environmental_assessment_plugin."""
    from .environmental_assessment_plugin import EnvironmentalAssessmentPlugin

    return EnvironmentalAssessmentPlugin(iface)
