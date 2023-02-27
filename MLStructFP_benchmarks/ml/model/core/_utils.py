"""
MLSTRUCTFP BENCHMARKS - ML - MODEL - CORE - UTILS

Core utils.
"""

__all__ = [
    'load_data_from_session',
    'load_model_from_session'
]

import MLStructFP_benchmarks.ml.model.architectures as fparch
from MLStructFP_benchmarks.ml.model.core import ModelDataXY, GenericModel

# Import versions
from MLStructFP_benchmarks.ml.model.core._data_xy import _SESSION_EXPORT_VERSION as SESSION_DATA_VERSION
from MLStructFP_benchmarks.ml.model.core._model import _SESSION_EXPORT_VERSION as SESSION_MODEL_VERSION

from pathlib import Path
from typing import Union, Any, Optional
import json
import os
import tensorflow as tf


def load_data_from_session(
        filename: str,
        load_images: bool = True,
        check_hash: bool = True
) -> 'ModelDataXY':
    """
    Load data from a session.

    :param filename: Session file
    :param load_images: Load images
    :param check_hash: Checks file hash
    """
    if '.json' not in filename:
        filename += '.json'
    _err_msg = 'Session file <{0}> does not exist in path <{1}>'
    assert os.path.isfile(filename), _err_msg.format(filename, os.getcwd())
    parent_dir = Path(os.path.abspath(filename)).parent

    with open(filename, 'r') as fp:
        data = json.load(fp)
    assert data['version'] == SESSION_DATA_VERSION, \
        'Outdated session export version, needed {0}, current {1}'.format(
            SESSION_DATA_VERSION, data['version'])

    img_col = data['image_col']
    if not load_images:
        img_col = ''

    data = ModelDataXY(
        filename=data['filename'],
        column_id=data['id_col'],
        image_col=img_col,
        image_size=data['image_size'],
        drop_id=data['drop_id'],
        path=parent_dir  # This search the parent folder recursively until finding the data
    )
    data._load_images = load_images
    data.load_session(filename=filename, check_hash=check_hash)

    return data


def load_model_from_session(
        filename: str,
        enable_memory_growth: Optional[bool] = None,
        check_hash: bool = True
) -> Union['GenericModel', Any]:
    """
    Load a model from a session.
    This model will be in production mode, aka, it cannot be modified
    and train/test/data will not be loaded.

    :param filename: Session filename
    :param enable_memory_growth: Enable tensorflow memory growth
    :param check_hash: Checks file hash
    :return: Loaded model
    """
    if enable_memory_growth is not None:
        assert isinstance(enable_memory_growth, bool)
        physical_devices = tf.config.experimental.list_physical_devices('GPU')
        tf.config.experimental.set_memory_growth(physical_devices[0], enable_memory_growth)

    if '.json' not in filename:
        filename += '.json'
    assert os.path.isfile(filename), f'Session file <{filename}> does not exist'
    parent_dir = Path(os.path.abspath(filename)).parent.parent

    with open(filename, 'r') as fp:
        data = json.load(fp)
    assert data['version'] == SESSION_MODEL_VERSION, \
        'Outdated session export version, needed {0}, current {1}'.format(
            SESSION_MODEL_VERSION, data['version'])

    # Create model
    session_class = data['class']
    sdata = data['session_data']  # Session data

    model: 'GenericModel'

    if session_class == 'UNETFloorPhotoModel':
        model = fparch.UNETFloorPhotoModel(
            data=None, name=data['name'], path=parent_dir,
            xy=sdata['xy'], image_shape=tuple(sdata['image_shape'])
        )
    elif session_class == 'Pix2PixFloorPhotoModModel':
        model = fparch.Pix2PixFloorPhotoModModel(
            data=None, name=data['name'], path=parent_dir,
            direction=sdata['dir'], image_shape=tuple(sdata['image_shape'])
        )
    elif session_class == 'Pix2PixPatchGANFloorPhotoModel':
        model = fparch.Pix2PixPatchGANFloorPhotoModel(
            data=None, name=data['name'], path=parent_dir,
            xy=sdata['xy'], direction=sdata['dir'], image_shape=tuple(sdata['image_shape'])
        )
    elif session_class == 'Pix2PixFloorPhotoModel':
        model = fparch.Pix2PixFloorPhotoModel(
            data=None, name=data['name'], path=parent_dir,
            xy=sdata['xy'], image_shape=tuple(sdata['image_shape'])
        )
    else:
        raise ValueError(f'Model session class <{session_class}> not supported')

    # Configure model
    model._is_compiled = True  # Production model cannot be compiled

    # model.info()
    model.load_session(filename, check_hash=check_hash)
    model.enable_production()

    return model