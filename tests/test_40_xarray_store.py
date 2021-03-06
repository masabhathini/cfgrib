
from __future__ import absolute_import, division, print_function, unicode_literals

import os.path

import pytest
import xarray as xr

from cfgrib import eccodes
from cfgrib import xarray_store

SAMPLE_DATA_FOLDER = os.path.join(os.path.dirname(__file__), 'sample-data')
TEST_DATA = os.path.join(SAMPLE_DATA_FOLDER, 'era5-levels-members.grib')
TEST_CORRUPTED = os.path.join(SAMPLE_DATA_FOLDER, 'era5-levels-corrupted.grib')


def test_GribDataStore():
    datastore = xarray_store.GribDataStore.frompath(TEST_DATA, flavour_name='eccodes')
    expected = {'number': 10, 'dataDate': 2, 'dataTime': 2, 'topLevel': 2, 'i': 7320}
    assert datastore.get_dimensions() == expected


def test_xarray_open_dataset():
    datastore = xarray_store.GribDataStore.frompath(TEST_DATA, flavour_name='eccodes')
    res = xr.open_dataset(datastore)

    assert res.attrs['GRIB_edition'] == 1
    assert res['t'].attrs['GRIB_gridType'] == 'regular_ll'
    assert res['t'].attrs['units'] == 'K'
    assert res['t'].dims == ('number', 'dataDate', 'dataTime', 'topLevel', 'i')

    assert res['t'].mean() > 0.


def test_open_dataset():
    res = xarray_store.open_dataset(TEST_DATA)

    assert res.attrs['GRIB_edition'] == 1

    var = res['t']
    assert var.attrs['GRIB_gridType'] == 'regular_ll'
    assert var.attrs['units'] == 'K'
    assert var.dims == \
        ('number', 'time', 'air_pressure', 'latitude', 'longitude')

    assert var.mean() > 0.


def test_open_dataset_corrupted():
    res = xarray_store.open_dataset(TEST_CORRUPTED)

    assert res.attrs['GRIB_edition'] == 1
    assert len(res.data_vars) == 1

    with pytest.raises(eccodes.EcCodesError):
        xarray_store.open_dataset(TEST_CORRUPTED, errors='strict')


def test_open_dataset_encode_time():
    res = xarray_store.open_dataset(TEST_DATA, flavour_name='eccodes', encode_time=True)

    assert res.attrs['GRIB_edition'] == 1
    assert res['t'].attrs['GRIB_gridType'] == 'regular_ll'
    assert res['t'].attrs['units'] == 'K'
    assert res['t'].dims == ('number', 'time', 'topLevel', 'i')

    assert res['t'].mean() > 0.


def test_open_dataset_encode_vertical():
    res = xarray_store.open_dataset(TEST_DATA, flavour_name='eccodes', encode_vertical=True)

    var = res['t']
    assert var.dims == ('number', 'dataDate', 'dataTime', 'air_pressure', 'i')

    assert var.mean() > 0.


def test_open_dataset_encode_geography():
    res = xarray_store.open_dataset(TEST_DATA, flavour_name='eccodes', encode_geography=True)

    assert res.attrs['GRIB_edition'] == 1

    var = res['t']
    assert var.attrs['GRIB_gridType'] == 'regular_ll'
    assert var.attrs['units'] == 'K'
    assert var.dims == ('number', 'dataDate', 'dataTime', 'topLevel', 'latitude', 'longitude')

    assert var.mean() > 0.


def test_open_dataset_eccodes():
    res = xarray_store.open_dataset(TEST_DATA, flavour_name='ecmwf')

    assert res.attrs['GRIB_edition'] == 1

    var = res['t']
    assert var.attrs['GRIB_gridType'] == 'regular_ll'
    assert var.attrs['units'] == 'K'
    assert var.dims == ('number', 'time', 'air_pressure', 'latitude', 'longitude')

    assert var.mean() > 0.


def test_open_dataset_cds():
    res = xarray_store.open_dataset(TEST_DATA, flavour_name='cds')

    assert res.attrs['GRIB_edition'] == 1

    var = res['t']
    assert var.attrs['GRIB_gridType'] == 'regular_ll'
    assert var.attrs['units'] == 'K'
    assert var.dims == ('realization', 'forecast_reference_time', 'plev', 'lat', 'lon')

    assert var.mean() > 0.
