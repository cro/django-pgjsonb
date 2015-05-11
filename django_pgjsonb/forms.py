from __future__ import unicode_literals

from json_field.utils import is_aware
from json_field.forms import JSONFormField

try:
    import json
except ImportError:  # python < 2.6
    from django.utils import simplejson as json
from django.forms import fields, util

import datetime
from decimal import Decimal

import re
import decimal
import datetime
import six
try:
    from dateutil import parser as date_parser
except ImportError:
    raise ImproperlyConfigured('The "dateutil" library is required and was not found.')

try:
    JSON_DECODE_ERROR = json.JSONDecodeError # simplejson
except AttributeError:
    JSON_DECODE_ERROR = ValueError # other

TIME_FMT = r'\d{2}:\d{2}:\d{2}(\.\d+)?'
DATE_FMT = r'\d{4}-\d{2}-\d{2}'
TIMEZONE_FMT = r'(\+|\-)\d{2}:\d{2}'

TIME_RE = re.compile(r'^(%s)$' % TIME_FMT)
DATE_RE = re.compile(r'^(%s)$' % DATE_FMT)
DATETIME_RE = re.compile(r'^(%s)T(%s)(%s)?$' % (DATE_FMT, TIME_FMT, TIMEZONE_FMT))


def is_aware(value): # taken from django/utils/timezone.py
    """
    Determines if a given datetime.datetime is aware.

    The logic is described in Python's docs:
    http://docs.python.org/library/datetime.html#datetime.tzinfo
    """
    return value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None

class JSONEncoder(json.JSONEncoder):
    """
    JSONEncoder subclass that knows how to encode date/time and decimal types.
    """
    def default(self, o):
        # See "Date Time String Format" in the ECMA-262 specification.
        if isinstance(o, datetime.datetime):
            r = o.isoformat()
            if o.microsecond:
                r = r[:23] + r[26:]
            if r.endswith('+00:00'):
                r = r[:-6] + 'Z'
            return r
        elif isinstance(o, datetime.date):
            return o.isoformat()
        elif isinstance(o, datetime.time):
            if is_aware(o):
                raise ValueError("JSON can't represent timezone-aware times.")
            r = o.isoformat()
            if o.microsecond:
                r = r[:12]
            return r
        elif isinstance(o, decimal.Decimal):
            return str(o)
        else:
            return super(JSONEncoder, self).default(o)

class JSONDecoder(json.JSONDecoder):
    """ Recursive JSON to Python deserialization. """

    _recursable_types = ([str] if six.PY3 else [str, unicode]) + [list, dict]

    def _is_recursive(self, obj):
        return type(obj) in JSONDecoder._recursable_types

    def decode(self, obj, *args, **kwargs):
        if not kwargs.get('recurse', False):
            obj = super(JSONDecoder, self).decode(obj, *args, **kwargs)
        if isinstance(obj, list):
            for i in six.moves.xrange(len(obj)):
                item = obj[i]
                if self._is_recursive(item):
                    obj[i] = self.decode(item, recurse=True)
        elif isinstance(obj, dict):
            for key, value in obj.items():
                if self._is_recursive(value):
                    obj[key] = self.decode(value, recurse=True)
        elif isinstance(obj, six.string_types):
            if TIME_RE.match(obj):
                try:
                    return date_parser.parse(obj).time()
                except ValueError:
                    pass
            if DATE_RE.match(obj):
                try:
                    return date_parser.parse(obj).date()
                except ValueError:
                    pass
            if DATETIME_RE.match(obj):
                try:
                    return date_parser.parse(obj)
                except ValueError:
                    pass
        return obj



class JSONFormField(fields.Field):

    def __init__(self, *args, **kwargs):
        from .fields import JSONEncoder, JSONDecoder

        self.evaluate = kwargs.pop('evaluate', False)
        self.encoder_kwargs = kwargs.pop('encoder_kwargs', {'cls':JSONEncoder})
        self.decoder_kwargs = kwargs.pop('decoder_kwargs', {'cls':JSONDecoder, 'parse_float':Decimal})

        kwargs.pop('max_length', None)

        super(JSONFormField, self).__init__(*args, **kwargs)

    def clean(self, value):
        # Have to jump through a few hoops to make this reliable
        value = super(JSONFormField, self).clean(value)

        # allow an empty value on an optional field
        if value is None:
            return value

        ## Got to get rid of newlines for validation to work
        # Data newlines are escaped so this is safe
        value = value.replace('\r', '').replace('\n', '')

        if self.evaluate:
            json_globals = { # "safety" first!
                '__builtins__': None,
                'datetime': datetime,
            }
            json_locals = { # value compatibility
                'null': None,
                'true': True,
                'false': False,
            }
            try:
                value = json.dumps(eval(value, json_globals, json_locals), **self.encoder_kwargs)
            except Exception as e: # eval can throw many different errors
                raise util.ValidationError(str(e))

        try:
            return json.loads(value, **self.decoder_kwargs)
        except ValueError as e:
            raise util.ValidationError(str(e))
