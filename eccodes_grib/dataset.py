#
# Copyright 2017-2018 B-Open Solutions srl.
# Copyright 2017-2018 European Centre for Medium-Range Weather Forecasts (ECMWF).
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import, division, print_function, unicode_literals
from builtins import list, object, str

import collections
import datetime
import functools
import logging
import pkg_resources
import typing as T  # noqa

import attr
import numpy as np

from . import eccodes
from . import messages

LOG = logging.getLogger(__name__)
VERSION = pkg_resources.get_distribution("eccodes_grib").version

#
# Edition-independent keys in ecCodes namespaces. Documented in:
#   https://software.ecmwf.int/wiki/display/ECC/GRIB%3A+Namespaces
#
GLOBAL_ATTRIBUTES_KEYS = ['edition', 'centre', 'centreDescription']

# NOTE: 'dataType' may have multiple values for the same variable, i.e. ['an', 'fc']
VARIABLE_ATTRIBUTES_KEYS = ['paramId', 'shortName', 'units', 'name', 'cfName', 'missingValue']

SPATIAL_COORDINATES_ATTRIBUTES_KEYS = ['gridType', 'numberOfPoints']

GRID_TYPE_MAP = {
    'regular_ll': [
        'Ni', 'iDirectionIncrementInDegrees', 'iScansNegatively',
        'longitudeOfFirstGridPointInDegrees', 'longitudeOfLastGridPointInDegrees',
        'Nj', 'jDirectionIncrementInDegrees', 'jPointsAreConsecutive', 'jScansPositively',
        'latitudeOfFirstGridPointInDegrees', 'latitudeOfLastGridPointInDegrees',
    ],
    'reduced_ll': [
        'Nj', 'jDirectionIncrementInDegrees', 'jPointsAreConsecutive', 'jScansPositively',
        'latitudeOfFirstGridPointInDegrees', 'latitudeOfLastGridPointInDegrees',
        'pl',
    ],
    'regular_gg': [
        'Ni', 'iDirectionIncrementInDegrees', 'iScansNegatively',
        'longitudeOfFirstGridPointInDegrees', 'longitudeOfLastGridPointInDegrees',
        'N',
    ],
    'lambert': [
        'LaDInDegrees', 'LoVInDegrees', 'iScansNegatively',
        'jPointsAreConsecutive', 'jScansPositively',
        'latitudeOfFirstGridPointInDegrees', 'latitudeOfSouthernPoleInDegrees',
        'longitudeOfFirstGridPointInDegrees', 'longitudeOfSouthernPoleInDegrees',
        'DyInMetres', 'DxInMetres', 'Latin2InDegrees', 'Latin1InDegrees', 'Ny', 'Nx',
    ],
    'reduced_gg': ['N',  'pl'],
    'sh': ['M', 'K', 'J'],
}
GRID_TYPE_KEYS = list(set(k for _, ks in GRID_TYPE_MAP.items() for k in ks))

HEADER_COORDINATES_MAP = [
    ('number', ['totalNumber']),
    ('dataDate', []),
    ('dataTime', []),
    ('endStep', ['stepUnits', 'stepType']),
    ('topLevel', ['typeOfLevel']),  # NOTE: no support for mixed 'isobaricInPa' / 'isobaricInhPa'.
]
HEADER_COORDINATES_KEYS = [k for k, _ in HEADER_COORDINATES_MAP]
HEADER_COORDINATES_KEYS += [k for _, ks in HEADER_COORDINATES_MAP for k in ks]

ALL_KEYS = GLOBAL_ATTRIBUTES_KEYS + VARIABLE_ATTRIBUTES_KEYS + \
    SPATIAL_COORDINATES_ATTRIBUTES_KEYS + GRID_TYPE_KEYS + HEADER_COORDINATES_KEYS


class CoordinateNotFound(Exception):
    pass


def enforce_unique_attributes(
        index,  # type: messages.Index
        attributes_keys,  # type: T.Sequence[str]
):
    # type: (...) -> T.Dict[str, T.Any]
    attributes = collections.OrderedDict()  # type: T.Dict[str, T.Any]
    for key in attributes_keys:
        values = index[key]
        if len(values) > 1:
            raise ValueError("multiple values for unique attribute %r: %r" % (key, values))
        if values:
            attributes[key] = values[0]
    return attributes


def simple_header_coordinate(index, coordinate_key, attributes_keys):
    data = index[coordinate_key]
    if len(data) == 1 and data[0] == 'undef':
        raise CoordinateNotFound("missing from GRIB stream: %r" % coordinate_key)

    attributes = enforce_unique_attributes(index, attributes_keys)
    return data, attributes


def from_grib_date_time(date, time):
    # type: (int, int) -> int
    """
    Convert the date and time as encoded in a GRIB file in standard numpy-compatible
    datetime64 string.

    :param int date: the content of "dataDate" key
    :param int time: the content of "dataTime" key

    :rtype: str
    """
    # (int, int) -> int
    hour = time // 100
    minute = time % 100
    year = date // 10000
    month = date // 100 % 100
    day = date % 100
    data_datetime = datetime.datetime(year, month, day, hour, minute)
    # Python 2 compatible timestamp implementation without timezone hurdle
    # see: https://docs.python.org/3/library/datetime.html#datetime.datetime.timestamp
    return int((data_datetime - datetime.datetime(1970, 1, 1)).total_seconds())


def data_date_time(index):
    reverse_index = {}
    data = []
    idate = index.index_keys.index('dataDate')
    itime = index.index_keys.index('dataTime')
    for header_values in index.offsets:
        date = header_values[idate]
        time = header_values[itime]
        seconds = from_grib_date_time(date, time)
        if seconds not in data:
            data.append(seconds)
        reverse_index[seconds] = (date, time)
    attributes = {
        'units': 'seconds since 1970-01-01T00:00:00+00:00',
        'calendar': 'proleptic_gregorian',
        'axis': 'T',
        'standard_name': 'forecast_reference_time',
    }
    return data, attributes, reverse_index


@attr.attrs(cmp=False)
class Variable(object):
    dimensions = attr.attrib(type=T.Sequence[str])
    data = attr.attrib(type=np.ndarray)
    attributes = attr.attrib(default={}, type=T.Mapping[str, T.Any])

    def __eq__(self, other):
        if other.__class__ is not self.__class__:
            return NotImplemented
        equal = (self.dimensions, self.attributes) == (other.dimensions, other.attributes)
        return equal and np.array_equal(self.data, other.data)


@attr.attrs()
class DataArray(object):
    # array_index = attr.attrib(default=None)

    @property
    def data(self):
        if not hasattr(self, '_data'):
            self._data = self.build_array()
        return self._data

    def build_array(self):
        # type: () -> np.ndarray
        data = np.full(self.array_index.shape, fill_value=np.nan, dtype='float32')
        with open(self.array_index.path) as file:
            for header_values, offset in sorted(self.array_index.offsets.items(), key=lambda x: x[1]):
                header_indexes = []  # type: T.List[int]
                for dim in self.dimensions[:-1]:
                    header_value = header_values[self.array_index.index_keys.index(dim)]
                    header_indexes.append(self.coordinates[dim].data.tolist().index(header_value))
                # NOTE: fill a single field as found in the message
                message = messages.Message.fromfile(file, offset=offset[0])
                values = message.message_get('values', eccodes.CODES_TYPE_DOUBLE)
                data.__setitem__(tuple(header_indexes + [slice(None, None)]), values)
        missing_value = self.attributes.get('missingValue', 9999)
        data[data == missing_value] = np.nan
        return data

    def __getitem__(self, item):
        return self.data[item]


@attr.attrs()
class DataVariable(DataArray):
    index = attr.attrib()
    stream = attr.attrib()

    @classmethod
    def fromstream(cls, paramId, *args, **kwargs):
        stream = messages.Stream(*args, **kwargs)
        index = stream.index(ALL_KEYS).subindex(paramId=paramId)
        return cls(index=index, stream=stream)

    def __attrs_post_init__(self, log=LOG):
        # FIXME: the order of the instructions until the end of the function is significant.
        #   A refactor is sorely needed.
        leader = next(iter(self.stream))

        self.attributes = enforce_unique_attributes(self.index, VARIABLE_ATTRIBUTES_KEYS)

        spatial_attributes_keys = SPATIAL_COORDINATES_ATTRIBUTES_KEYS[:]
        spatial_attributes_keys.extend(GRID_TYPE_MAP.get(leader['gridType'], []))
        self.attributes.update(enforce_unique_attributes(self.index, spatial_attributes_keys))

        self.coordinates = collections.OrderedDict()
        for coord_key, attrs_keys in HEADER_COORDINATES_MAP:
            try:
                values, attributes = simple_header_coordinate(
                    self.index, coordinate_key=coord_key, attributes_keys=attrs_keys,
                )
            except CoordinateNotFound:
                log.exception("coordinate %r failed", coord_key)
                continue
            data = np.array(values)
            dimensions = (coord_key,)
            if len(values) == 1:
                data = data[0]
                dimensions = ()
            self.coordinates[coord_key] = Variable(
                dimensions=dimensions, data=data, attributes=attributes,
            )

        # FIXME: move to a function
        self.attributes['coordinates'] = ' '.join(self.coordinates.keys()) + ' lat lon'
        self.dimensions = tuple(d for d, c in self.coordinates.items() if c.data.size > 1) + ('i',)
        self.ndim = len(self.dimensions)
        self.shape = tuple(self.coordinates[d].data.size for d in self.dimensions[:-1])
        self.shape += (leader['numberOfPoints'],)

        # add secondary coordinates
        latitude = leader['latitudes']
        self.coordinates['lat'] = Variable(
            dimensions=('i',), data=np.array(latitude), attributes={'units': 'degrees_north'},
        )
        longitude = leader['longitudes']
        self.coordinates['lon'] = Variable(
            dimensions=('i',), data=np.array(longitude), attributes={'units': 'degrees_east'},
        )

        # Variable attributes
        self.dtype = np.dtype('float32')
        self.scale = True
        self.mask = False
        self.size = functools.reduce(lambda x, y: x * y, self.shape, 1)

    def build_array(self):
        # type: () -> np.ndarray
        data = np.full(self.shape, fill_value=np.nan, dtype=self.dtype)
        with open(self.stream.path) as file:
            for header_values, offset in sorted(self.index.offsets.items(), key=lambda x: x[1]):
                header_indexes = []  # type: T.List[int]
                for dim in self.dimensions[:-1]:
                    header_value = header_values[self.index.index_keys.index(dim)]
                    header_indexes.append(self.coordinates[dim].data.tolist().index(header_value))
                # NOTE: fill a single field as found in the message
                message = messages.Message.fromfile(file, offset=offset[0])
                values = message.message_get('values', eccodes.CODES_TYPE_DOUBLE)
                data.__setitem__(tuple(header_indexes + [slice(None, None)]), values)
        missing_value = self.attributes.get('missingValue', 9999)
        data[data == missing_value] = np.nan
        return data

    # def build_array(self):
    #     # type: () -> np.ndarray
    #     data = np.full(self.shape, fill_value=np.nan, dtype=self.dtype)
    #     for message in self.stream:
    #         if message.message_get('paramId', eccodes.CODES_TYPE_LONG) != self.paramId:
    #             continue
    #         header_indexes = []  # type: T.List[int]
    #         header_values = []
    #         for dim in self.dimensions[:-1]:
    #             header_values.append(message.message_get(dim, eccodes.CODES_TYPE_LONG))
    #             header_indexes.append(self.coordinates[dim].data.index(header_values[-1]))
    #         # NOTE: fill a single field as found in the message
    #         values = message.message_get('values', eccodes.CODES_TYPE_DOUBLE)
    #         data.__setitem__(tuple(header_indexes + [slice(None, None)]), values)
    #     missing_value = self.attributes.get('missingValue', 9999)
    #     data[data == missing_value] = np.nan
    #     return data


def dict_merge(master, update):
    for key, value in update.items():
        if key not in master:
            master[key] = value
        elif master[key] == value:
            pass
        else:
            raise ValueError("key present and new value is different: "
                             "key=%r value=%r new_value=%r" % (key, master[key], value))


def build_dataset_components(stream, global_attributes_keys=GLOBAL_ATTRIBUTES_KEYS):
    index = stream.index(ALL_KEYS)
    param_ids = index['paramId']
    dimensions = collections.OrderedDict()
    variables = collections.OrderedDict()
    for param_id, short_name in zip(param_ids, index['shortName']):
        var = DataVariable(index=index.subindex(paramId=param_id), stream=stream)
        vars = collections.OrderedDict([(short_name, var)])
        vars.update(var.coordinates)
        dims = collections.OrderedDict((d, s) for d, s in zip(var.dimensions, var.shape))
        dict_merge(dimensions, dims)
        dict_merge(variables, vars)
    attributes = enforce_unique_attributes(index, global_attributes_keys)
    attributes['eccodesGribVersion'] = VERSION
    return dimensions, variables, attributes


@attr.attrs()
class Dataset(object):
    stream = attr.attrib()
    encode = attr.attrib(default=True)

    @classmethod
    def fromstream(cls, path, encode=True, **kwagrs):
        return cls(stream=messages.Stream(path, **kwagrs), encode=encode)

    def __attrs_post_init__(self):
        dimensions, variables, attributes = build_dataset_components(self.stream)
        self.dimensions = dimensions  # type: T.Dict[str, T.Optional[int]]
        self.variables = variables  # type: T.Dict[str, Variable]
        self.attributes = attributes  # type: T.Dict[str, T.Any]
