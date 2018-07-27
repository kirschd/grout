from dateutil.parser import parse
import json

import mock

from django.test import TestCase
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth.models import User
from django.http import HttpRequest

from rest_framework.test import APIRequestFactory, force_authenticate


from grout import models
from grout.views import RecordViewSet
from grout.filters import DateRangeFilterBackend


class DateFilterBackendTestCase(TestCase):
    """ Test serializer field for dates """

    def setUp(self):
        try:
            self.user = User.objects.get(username='admin')
        except ObjectDoesNotExist:
            self.user = User.objects.create_user('admin',
                                                 'grout@azavea.com',
                                                 '123')

        self.factory = APIRequestFactory()
        self.queryset = models.RecordSchema.objects.all()

        self.item_type = models.RecordType.objects.create(label='item', plural_label='items')

        self.item_schema = {
            "$schema": "http://json-schema.org/draft-04/schema#",
            "title": "Item",
            "description": "An item",
            "type": "object",
            "properties": {
                "id": {
                    "description": "The unique identifier for a product",
                    "type": "integer"
                },
                "name": {
                    "description": "Name of the product",
                    "type": "string"
                }
            },
            "required": ["id", "name"]
        }

        self.schema = models.RecordSchema.objects.create(record_type=self.item_type,
                                                  version=1,
                                                  schema=self.item_schema)

        self.a_date       = parse('2015-01-01T00:00:00+00:00')
        self.a_later_date = parse('2015-02-22T00:00:00+00:00')

        self.early_record = models.Record.objects.create(
            occurred_from=self.a_date,  # A DATE
            occurred_to=self.a_date,
            geom='POINT (0 0)',
            schema=self.schema,
            data={}
        )
        self.later_record = models.Record.objects.create(
            occurred_from=self.a_later_date,  # A LATER DATE
            occurred_to=self.a_later_date,
            geom='POINT (0 0)',
            schema=self.schema,
            data={}
        )

        # Create a Record without temporal data.
        self.nontemporal_record = models.PointRecord.objects.create(
            geom='POINT (0 0)',
            schema=self.schema,
            data={}
        )

        self.view = RecordViewSet.as_view({'get': 'list'})

    def test_valid_datefilter(self):
        """ Test filtering on dates """
        self.assertEqual(len(self.queryset), 1)

        req1 = self.factory.get('/foo/', {'occurred_max': self.a_date})
        force_authenticate(req1, self.user)
        res1 = self.view(req1).render()
        self.assertEqual(json.loads(res1.content.decode('utf-8'))['count'], 1)

        req2 = self.factory.get('/foo/', {'occurred_max': self.a_later_date})
        force_authenticate(req2, self.user)
        res2 = self.view(req2).render()
        self.assertEqual(json.loads(res2.content.decode('utf-8'))['count'], 2)

    def test_missing_min_max(self):
        """Test that forgetting both `occurred_min` and `occurred_max` returns all records."""
        missing_range_req = self.factory.get('/foo/')
        force_authenticate(missing_range_req, self.user)
        missing_range_res = self.view(missing_range_req).render()

        self.assertEqual(json.loads(missing_range_res.content.decode('utf-8'))['count'], 2)

    def test_missing_timezone(self):
        """Test that forgetting timezone information raises an error."""
        date_no_time = '2015-01-01'
        missing_tz_req = self.factory.get('/foo/', {'occurred_max': date_no_time})
        force_authenticate(missing_tz_req, self.user)
        missing_tz_res = self.view(missing_tz_req).render()

        msg = 'Invalid value for parameter datetimes, value must be ' + DateRangeFilterBackend.ERR_MSG
        self.assertEqual(str(json.loads(missing_tz_res.content.decode('utf-8'))['detail']), msg)

    def test_range_parse_errors(self):
        """Test that parse errors get thrown when the date range is improperly formatted."""
        # Test a bad `occurred_min` parameter.
        bad_min_req = self.factory.get('/foo/', {'occurred_min': 'foobarbaz'})
        force_authenticate(bad_min_req, self.user)
        bad_min_res = self.view(bad_min_req).render()

        msg = 'Invalid value for parameter occurred_min, value must be ' + DateRangeFilterBackend.ERR_MSG
        self.assertEqual(str(json.loads(bad_min_res.content.decode('utf-8'))['detail']), msg)

        # Test a bad `occurred_max` parameter.
        bad_max_req = self.factory.get('/foo/', {'occurred_max': 'foobarbaz'})
        force_authenticate(bad_max_req, self.user)
        bad_max_res = self.view(bad_max_req).render()

        msg = 'Invalid value for parameter occurred_max, value must be ' + DateRangeFilterBackend.ERR_MSG
        self.assertEqual(str(json.loads(bad_max_res.content.decode('utf-8'))['detail']), msg)

    def test_min_max_is_none(self):
        """Test that the user can filter for nontemporal Records."""
        min_is_none_req = self.factory.get('/foo/', {'occurred_min': 'none'})
        force_authenticate(min_is_none_req, self.user)
        min_is_none_res = self.view(min_is_none_req).render()

        self.assertEqual(json.loads(min_is_none_res.content.decode('utf-8'))['count'], 1)

        max_is_none_req = self.factory.get('/foo/', {'occurred_max': 'none'})
        force_authenticate(max_is_none_req, self.user)
        max_is_none_res = self.view(max_is_none_req).render()

        self.assertEqual(json.loads(max_is_none_res.content.decode('utf-8'))['count'], 1)

    def test_invalid_min_max_filter(self):
        """Test that one of `min` or `max` cannot be 'none' while the other is a datetime."""
        bad_min_req = self.factory.get('/foo/', {'occurred_min': 'none', 'occurred_max': self.a_date})
        bad_max_req = self.factory.get('/foo/', {'occurred_max': 'none', 'occurred_min': self.a_date})

        for bad_req, param in ((bad_min_req, 'occurred_min'), (bad_max_req, 'occurred_max')):
            force_authenticate(bad_req, self.user)
            bad_res = self.view(bad_req).render()

            self.assertEqual(bad_res.status_code, 400)
            msg = ('Invalid value for parameter %s: ' % param +
                   'value cannot be "none" while another param is a valid datetime.')
            self.assertEqual(str(json.loads(bad_res.content.decode('utf-8'))['detail']), msg)
