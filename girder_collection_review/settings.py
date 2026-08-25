from girder.exceptions import ValidationException
from girder.utility import setting_utilities

from .constants import PluginSettings


@setting_utilities.default(PluginSettings.DEFAULT_DURATION)
def _defaultDuration():
    return 90


@setting_utilities.validator(PluginSettings.DEFAULT_DURATION)
def _validateDefaultDuration(doc):
    try:
        value = float(doc['value'])
    except (TypeError, ValueError):
        raise ValidationException('Default review duration must be a number.', 'value')

    if value <= 0:
        raise ValidationException('Default review duration must be positive.', 'value')

    doc['value'] = value
