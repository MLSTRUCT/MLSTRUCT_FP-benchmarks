"""
MLSTRUCTFP BENCHMARKS - ML - MODEL - ARCHITECTURES - FLOOR PHOTO

Photo data.
"""

__all__ = [
    '_SESSION_EXPORT_VERSION',
    'DataFloorPhotoXY',
    'load_floor_photo_data_from_session'
]

from MLStructFP_benchmarks.ml.utils import file_md5
from MLStructFP.utils import DEFAULT_PLOT_DPI, configure_figure

from datetime import datetime
from objsize import get_deep_size
from typing import List, Dict, Tuple, Any, Union
import cv2
import gc
import hashlib
import json
import math
import matplotlib.pyplot as plt
import numpy as np
import os
import time

_DATA_DTYPE: str = 'uint8'
_SESSION_EXPORT_VERSION: str = '1.1'


def _load_photo_parts(filename: str) -> Tuple[List[str], Dict[int, Tuple[int, int]], Dict[int, List[int]]]:
    """
    Load photo parts from file.

    :param filename: Data file
    :return: List of files, Dict of index inputs for each part, Dict of project ID for each part
    """
    assert os.path.isfile(filename), f'Floor photo file <{filename}> does not exist'

    def _get_part(line: str) -> int:
        """
        Get number of part from a given line.

        :param line: Line of text
        :return: Number of the part
        """
        return int(line.split('part')[1])

    def _get_id(line: str) -> int:
        """
        Get ID from a given line.

        :param line: Line of text
        :return: ID
        """
        return int(line.split(',')[0])

    def _get_project_id(line: str) -> int:
        """
        Get project ID from a given line.

        :param line: Line of text
        :return: Project ID
        """
        _k = line.split(',')[1].strip().split('-')
        if '[NULL]' not in line:
            return int(_k[1])
        return int(_k[2])

    # Load file names
    photo_files: List[str] = []
    floor_photo_files_names = open(filename, 'r')
    for j in floor_photo_files_names:
        n = j.strip()
        if n == 'ID,File' or len(n) == 0:
            continue
        photo_files.append(n)
    floor_photo_files_names.close()

    # Make ID range for each part
    total_parts = _get_part(photo_files[-1])
    assert total_parts > 1, 'Number of parts cannot be lower or equal than 1'
    partsid = {}
    projectid = {0: []}

    last_part = 0  # Last part number
    last_part_id = 0  # Initial ID of the part
    last_id = 0
    for j in photo_files:
        part_j: int = _get_part(j)
        if part_j != last_part:
            partsid[last_part] = (last_part_id, last_id)
            projectid[part_j] = []
            last_part = _get_part(j)
            last_part_id = _get_id(j)
        last_id = _get_id(j)
        project_id = _get_project_id(j)
        if project_id not in projectid[part_j]:
            projectid[part_j].append(project_id)
    partsid[last_part] = (last_part_id, last_id)
    del partsid[0]
    del projectid[0]

    # Check partsID
    parts_key = list(partsid.keys())
    assert len(parts_key) == total_parts, 'Number of parts does not match'
    for k in range(len(parts_key) - 1):
        assert parts_key[k + 1] - parts_key[k] == 1, 'Parts should diff in 1 unit'
        assert partsid[parts_key[k + 1]][0] == partsid[parts_key[k]][1] + 1, 'Invalid part lower continuity'
        assert partsid[parts_key[k]][1] - partsid[parts_key[k]][0] >= 1, 'Invalid part size'

    return photo_files, partsid, projectid


def _is_dict_equal(x: Dict[Any, Any], y: Dict[Any, Any]) -> bool:
    """
    Returns true if both dicts are equal.

    :param x: Dict
    :param y: Dict
    :return: True if equal
    """
    kx = list(x.keys())
    ky = list(y.keys())
    if len(kx) != len(ky):
        return False
    for i in range(len(kx)):
        if str(kx[i]) != str(ky[i]):  # Assert keys
            return False
        xki: Any = x[kx[i]]
        yki: Any = y[ky[i]]
        if isinstance(xki, (list, tuple)):
            assert isinstance(yki, (list, tuple))
            if len(xki) != len(yki):
                return False
            for j in range(len(xki)):
                if xki[j] != yki[j]:
                    return False
        else:
            if type(xki) != type(yki):
                return False
            if xki != yki:
                return False
    return True


class DataFloorPhotoXY(object):
    """
    Floor Photo XY.
    """
    _file_floor_photo_images_x: List[str]
    _file_floor_photo_images_y: List[str]
    _file_rect_images_x: str
    _file_rect_images_y: str
    _filename: str
    _floor_photo_ch: int
    _floor_photo_size: int
    _loaded_session: Dict[str, Any]
    _num_parts: int
    _parts_id: Dict[int, Tuple[int, int]]  # Stores initial and last index images for each part
    _parts_project_id: Dict[int, List[int]]
    _photo_files_x: List[str]
    _photo_files_y: List[str]
    _photo_x: 'np.ndarray'
    _photo_y: 'np.ndarray'
    _rect_image_ch: int
    _rect_image_size: int
    _rect_x: 'np.ndarray'
    _rect_y: 'np.ndarray'

    def __init__(
            self,
            filename: str,
            rect_image_size: int,
            floor_photo_size: int,
            rect_image_channels: int,
            floor_photo_channels: int
    ) -> None:
        """
        Constructor.

        :param filename: Data file
        :param rect_image_size: Rect image size (px)
        :param floor_photo_size: Rect floor photo size (px)
        :param rect_image_channels: Rect image number of channels
        :param floor_photo_channels: Rect floor photo number of channels
        """
        assert rect_image_size > 0, 'Rect image size must be greater than zero'
        assert math.log(rect_image_size, 2).is_integer(), 'Rect image size must be a power of 2'
        assert floor_photo_size > 0, 'Floor image size must be greater than zero'
        assert math.log(floor_photo_size, 2).is_integer(), 'Floor image size must be a power of 2'
        assert rect_image_channels >= 1
        assert floor_photo_channels >= 1

        self._filename = os.path.splitext(filename)[0]

        self._floor_photo_ch = floor_photo_channels
        self._floor_photo_size = floor_photo_size
        self._rect_image_ch = rect_image_channels
        self._rect_image_size = rect_image_size

        self._loaded_session = {}

        # Check file exists
        self._file_rect_images_x = filename + f'_images_x_{rect_image_size}.npz'
        self._file_rect_images_y = filename + f'_images_y_{rect_image_size}.npz'
        assert os.path.isfile(self._file_rect_images_x), \
            f'X rect images file <{self._file_rect_images_x}> does not exist'
        assert os.path.isfile(self._file_rect_images_y), \
            f'Y rect images file <{self._file_rect_images_y}> does not exist'

        # Load the files from floor photos
        self._photo_files_x, _parts_id_x, _parts_proj_x = \
            _load_photo_parts(filename + f'_rect_floor_photo_x_{floor_photo_size}_files.csv')
        self._photo_files_y, _parts_id_y, _parts_proj_y = \
            _load_photo_parts(filename + f'_rect_floor_photo_y_{floor_photo_size}_files.csv')

        # Compute the number of parts
        parts_x = int(self._photo_files_x[-1].split('part')[1])
        parts_y = int(self._photo_files_y[-1].split('part')[1])
        assert parts_x == parts_y, \
            'Number of parts are different between x and y photo files'
        assert _is_dict_equal(_parts_id_x, _parts_id_y), \
            'ID partition of parts are different between x and y photo files'
        assert _is_dict_equal(_parts_proj_x, _parts_proj_y), \
            'Project partition from parts are different between x and y'
        self._num_parts = parts_x
        self._parts_id = _parts_id_x
        self._parts_project_id = _parts_proj_x

        # Check parts files exists
        self._file_floor_photo_images_x = []
        self._file_floor_photo_images_y = []
        for i in range(self._num_parts):
            px = filename + f'_rect_floor_photo_x_{floor_photo_size}_part{i + 1}.npz'
            py = filename + f'_rect_floor_photo_y_{floor_photo_size}_part{i + 1}.npz'
            assert os.path.exists(px), f'Floor photo x file <{px}> does not exist'
            assert os.path.exists(py), f'Floor photo y file <{py}> does not exist'
            self._file_floor_photo_images_x.append(px)
            self._file_floor_photo_images_y.append(py)

    def get_image_shape(self) -> Tuple[int, int, int]:
        """
        Get image shape. As rect image channels are converted to target floor photo channels
        this dimension and number of channels with be equal in rect/floor photo data.

        :return: Tuple
        """
        return self._floor_photo_size, self._floor_photo_size, self._floor_photo_ch

    def get_total_parts(self) -> int:
        """
        :return: Total number of parts
        """
        return self._num_parts

    def load_part(
            self,
            part: int,
            xy: str,
            remove_null: bool,
            shuffle: bool
    ) -> Dict[str, Union[Union['np.ndarray'], str, float]]:
        """
        Load part and save into memory.

        :param part: Num part
        :param xy: Which data, "x", "y" or "xy"
        :param remove_null: Remove images from null rects
        :param shuffle: Shuffle data order
        :return: x/y from rect images, x/y from floor photo images
        """
        assert 1 <= part <= self._num_parts, f'Number of parts overflow, min:1, max:{self._num_parts}'
        assert xy in ['x', 'y', 'xy'], 'Invalid xy, expected "x", "y" or "xy"'

        out = {}

        if xy == 'x' or xy == 'xy':
            npr_x, fx, x_id, x_removed = self._load_data_part(part, 'x', remove_null=remove_null, shuffle=shuffle)
            out['x_len'] = len(fx)
            out['x_removed'] = x_removed
            out['x_rect'] = npr_x
            out['x_fphoto'] = fx
            out['x_id'] = x_id
        if xy == 'y' or xy == 'xy':
            npr_y, fy, y_id, y_removed = self._load_data_part(part, 'y', remove_null=remove_null, shuffle=shuffle)
            out['y_len'] = len(fy)
            out['y_removed'] = y_removed
            out['y_rect'] = npr_y
            out['y_fphoto'] = fy
            out['y_id'] = y_id

        out['part'] = part
        out['xy'] = xy
        out['size_mb'] = get_deep_size(out) / (1024 * 1024)
        gc.collect()
        time.sleep(1)

        return out

    def _load_data_part(
            self,
            part: int,
            xy: str,
            remove_null: bool,
            shuffle: bool
    ) -> Tuple['np.ndarray', 'np.ndarray', Dict[str, 'np.ndarray'], int]:
        """
        Load data from part.

        :param part: Part number to load from
        :param xy: Which data, x or y
        :param remove_null: Remove images from null object ID
        :param shuffle: Shuffle data order
        :return: Rect Image, Floor Photo, ID, and total removed elements
        """
        _un_xy = 'Unexpected value xy, valid "x" or "y"'

        # Load rect images
        fr: 'np.ndarray'
        if xy == 'x':
            fr = np.load(self._file_rect_images_x)['data']
        elif xy == 'y':
            fr = np.load(self._file_rect_images_y)['data']
        else:
            raise ValueError(_un_xy)

        # Get from part
        r: List['np.ndarray'] = []

        # Load only true rect images
        _min_err = 'Invalid rect image min value, it must be 0, current for pos <{0}> at part <{1}>: <{2}>'
        _max_err = 'Invalid rect image max value, it must be 1, current for pos <{0}> at part <{1}>: <{2}>'
        for i in range(self._parts_id[part][0], self._parts_id[part][1] + 1):
            fri: 'np.ndarray' = fr[i]
            assert fri.shape[0] == fri.shape[1] and fri.shape[0] == self._rect_image_size
            if len(fri.shape) == 2:
                assert self._rect_image_ch == 1
            else:
                assert fri.shape[2] == self._rect_image_ch
            if fri.dtype != _DATA_DTYPE:
                fri = fri.astype(_DATA_DTYPE)

            # Reshape to target image size
            if self._rect_image_size != self._floor_photo_size:
                fri = cv2.resize(
                    src=fri,
                    dsize=(self._floor_photo_size, self._floor_photo_size),
                    interpolation=cv2.INTER_AREA
                )

            # Make same number of channels
            if self._rect_image_ch != self._floor_photo_ch:
                fri = np.stack((fri,) * self._floor_photo_ch, axis=-1)

            # Make to range (0, 255)
            assert np.min(fri) == 0, _min_err.format(i, part, np.max(fri))
            assert np.max(fri) <= 1, _max_err.format(i, part, np.max(fri))

            fri = np.multiply(fri, 255, dtype=fri.dtype)

            r.append(fri)
        del fr

        # Load floor photos
        fp: 'np.ndarray'
        if xy == 'x':
            fp = np.load(self._file_floor_photo_images_x[part - 1])['data']
        elif xy == 'y':
            fp = np.load(self._file_floor_photo_images_y[part - 1])['data']
        else:
            raise ValueError(_un_xy)
        assert len(fp) == len(r), f'Floor photo size is different than rect image size at part <{part}>'

        # Assert shape of images
        for i in range(len(fp)):
            si = fp[i].shape
            assert si[0] == si[1], f'Floor photo must be square at pos <{i}>'
            assert si[0] == self._floor_photo_size, \
                f'Floor photo image size must be equal than constructor <{self._floor_photo_size}>'
            if len(si) == 2:
                assert self._floor_photo_ch == 1
            else:
                assert si[2] == self._floor_photo_ch, \
                    f'Invalid number of channels of floor x photo at pos <{i}>'

        # Convert to numpy ndarray
        npr = np.array(r, dtype=_DATA_DTYPE)
        del r

        # Load ID
        def _load_id(n: List[str]) -> Tuple['np.ndarray', 'np.ndarray', 'np.ndarray', 'np.ndarray']:
            """
            Load lists ID.

            :param n: File list
            :return: Image ID, Rect ID, Project ID, Mutator ID
            """
            _image_id: List[int] = []
            _rect_id: List[int] = []
            _project_id: List[int] = []
            _mutator_id: List[int] = []
            for j in range(self._parts_id[part][0], self._parts_id[part][1] + 1):
                # n[j] ~ 219712, 18581 - 61 - 6 - part119
                _image_id.append(int(n[j].split(',')[0]))
                k = n[j].split(',')[1].strip().split('-')
                if k[0].strip() == '[NULL]':
                    _rect_id.append(-1)
                    _project_id.append(int(k[2]))
                    _mutator_id.append(int(k[3]))
                else:
                    _rect_id.append(int(k[0]))
                    _project_id.append(int(k[1]))
                    _mutator_id.append(int(k[2]))

            return np.array(_image_id), np.array(_rect_id), np.array(_project_id), np.array(_mutator_id)

        _id: Tuple['np.ndarray', 'np.ndarray', 'np.ndarray', 'np.ndarray']
        if xy == 'x':
            _id = _load_id(self._photo_files_x)
        elif xy == 'y':
            _id = _load_id(self._photo_files_y)
        else:
            raise ValueError(_un_xy)
        nid = {
            'image': _id[0],
            'rect': _id[1],
            'project': _id[2],
            'mutator': _id[3]
        }

        # Remove from null ID
        total_removed: int = 0
        if remove_null:
            rem_id = list(np.where(nid['rect'] == -1)[0])
            total_removed = len(rem_id)
            if total_removed > 0:
                npr = np.delete(npr, rem_id, axis=0)
                fp = np.delete(fp, rem_id, axis=0)
                nid['image'] = np.delete(nid['image'], rem_id, axis=0)
                nid['rect'] = np.delete(nid['rect'], rem_id, axis=0)
                nid['project'] = np.delete(nid['project'], rem_id, axis=0)
                nid['mutator'] = np.delete(nid['mutator'], rem_id, axis=0)

        if shuffle:
            indices = np.arange(npr.shape[0])
            np.random.shuffle(indices)
            npr = npr[indices]
            fp = fp[indices]
            nid['image'] = nid['image'][indices]
            nid['rect'] = nid['rect'][indices]
            nid['project'] = nid['project'][indices]
            nid['mutator'] = nid['mutator'][indices]

        return npr, fp, nid, total_removed

    def plot_image_example_rect_id(
            self,
            o: Dict[str, Union[Union['np.ndarray'], str, float]],
            xy: str,
            rect_id: int,
            mutator_id: int
    ) -> None:
        """
        Plot image example from partition data.

        :param o: Partition data
        :param xy: Which data, "x" or "y"
        :param rect_id: Rect ID to plot
        :param mutator_id: Rect mutator ID to plot
        """
        assert xy in ['x', 'y'], 'Invalid xy, expected "x" or "y"'
        assert o['xy'] == xy or o['xy'] == 'xy', 'Invalid xy in given partition data'
        rect_id_part: 'np.ndarray' = o[xy + '_id']['rect']
        mutator_id_part: 'np.ndarray' = o[xy + '_id']['mutator']
        if rect_id not in rect_id_part:
            raise ValueError('Rect ID <{0}> does not exist in partition data')
        rid = np.where(rect_id_part == rect_id)
        ri = -1
        for j in rid[0]:
            if mutator_id_part[j] == mutator_id:
                ri = j
                break
        if ri == -1:
            raise ValueError(f'Rect with mutator ID <{mutator_id}> does not exist in partition data')
        title = 'Object Rect ID {0} Mutator {1}\nPartition {2} at Data {3}'.format(
            rect_id, mutator_id, o['part'], xy)
        return self.plot_image_example_id(o=o, xy=xy, imid=ri, title=title)

    # noinspection PyMethodMayBeStatic
    def plot_image_example_id(
            self,
            o: Dict[str, Union[Union['np.ndarray'], str, float]],
            xy: str,
            imid: int,
            title: str = ''
    ) -> None:
        """
        Plot image from ID.

        :param o: Partition data
        :param xy: Which data, "x" or "y"
        :param imid: Image ID, from 0 to len(o)
        :param title: Optional image title
        """
        assert xy in ['x', 'y'], 'Invalid xy, expected "x" or "y"'
        assert o['xy'] == xy or o['xy'] == 'xy', 'Invalid xy in given partition data'
        assert 0 <= imid <= o[xy + '_len'] - 1, 'Image ID overflows'
        if title == '':
            title = f"Object ID {imid}\nPartition {o['part']} at Data {xy}"

        kwargs = {'cfg_grid': False}
        fig = plt.figure(dpi=DEFAULT_PLOT_DPI)
        plt.title(title)
        # fig.subplots_adjust(hspace=.5)
        plt.axis('off')
        configure_figure()

        ax1: 'plt.Axes' = fig.add_subplot(121)
        ax1.title.set_text('Rect Image')
        ax1.imshow(o[xy + '_rect'][imid], cmap='gray')
        plt.xlabel('x $(px)$')
        plt.ylabel('y $(px)$')
        plt.axis('off')
        configure_figure(**kwargs)

        ax2 = fig.add_subplot(122)
        ax2.title.set_text('Floor Photo')
        ax2.imshow(o[xy + '_fphoto'][imid], cmap='gray')
        # plt.xlabel('x $(px)$')
        plt.axis('off')
        configure_figure(**kwargs)

        plt.show()

    def _get_file_hash(self, xy: str) -> str:
        """
        Get file hash (images).

        :param xy: Which dataframe to get images hash
        :return: Hash
        """
        if xy == 'rect':
            _hash = (file_md5(self._file_rect_images_x), file_md5(self._file_rect_images_y))
            h = hashlib.md5()
            h.update(_hash[0].encode())
            h.update(_hash[1].encode())
            return h.hexdigest()
        elif xy == 'fphoto':
            h = hashlib.md5()
            for i in range(self._num_parts):
                h.update(file_md5(self._file_floor_photo_images_x[i]).encode())
                h.update(file_md5(self._file_floor_photo_images_y[i]).encode())
            return h.hexdigest()
        else:
            raise ValueError('Invalid xy, expected "rect" or "fphoto')

    def save_session(self, filename: str, description: str = '') -> None:
        """
        Save current session.

        :param filename: File to save the session
        :param description: Session description
        """
        filename = os.path.splitext(filename)[0]
        if '.json' not in filename:
            filename += '.json'
        with open(filename, 'w', encoding='utf-8') as fp:
            data = {

                # Export version
                'version': _SESSION_EXPORT_VERSION,
                'class': 'DataFloorPhotoXY',
                'date_save': datetime.today().strftime('%Y-%m-%d %H:%M:%S'),
                'description': description,

                # Basic data
                'filename': self._filename,
                'floor_photo_ch': self._floor_photo_ch,
                'floor_photo_size': self._floor_photo_size,
                'num_parts': self._num_parts,
                'parts_id': self._parts_id,
                'parts_project_id': self._parts_project_id,
                'rect_image_ch': self._rect_image_ch,
                'rect_image_size': self._rect_image_size,

                # Hashes
                'hash_rect_images': self._get_file_hash('rect'),
                'hash_floor_images': self._get_file_hash('fphoto')

            }

            json.dump(data, fp, indent=2)
            self._loaded_session = {
                'file': filename,
                'description': description
            }

        # Collect garbage
        gc.collect()

    def load_session(self, filename: str) -> None:
        """
        Load session from file.

        :param filename: Load file from file
        """
        filename = os.path.splitext(filename)[0]
        if '.json' not in filename:
            filename += '.json'
        with open(filename, 'r') as fp:
            data = json.load(fp)

            # Check version of the export is the same
            assert data['version'] == _SESSION_EXPORT_VERSION, \
                'Outdated session export version, needed {0}, current {1}'.format(_SESSION_EXPORT_VERSION,
                                                                                  data['version'])

            # Check object data class is the same
            assert data['class'] == 'DataFloorPhotoXY', 'Data class is not valid'

            check_hash = True

            # Check hash after scaling is the same
            if check_hash:
                assert self._get_file_hash('rect') == data['hash_rect_images'], 'Rect image hash is not the same'
                assert self._get_file_hash('fphoto') == data['hash_floor_images'], 'Floor image hash is not the same'
            assert _is_dict_equal(self._parts_id, data['parts_id']), \
                'ID partition changed'
            assert _is_dict_equal(self._parts_project_id, data['parts_project_id']), \
                'Project ID partition changed'
            assert data['rect_image_size'] == self._rect_image_size, 'Rect image size changed'
            assert data['floor_photo_size'] == self._floor_photo_size, 'Floor image size changed'

            self._loaded_session = {
                'file': filename,
                'description': data['description']
            }

        # Collect garbage
        time.sleep(1)
        gc.collect()

    def update_session(self) -> None:
        """
        Updates session.
        """
        assert len(self._loaded_session.keys()) == 2, 'Session not loaded'
        print(f"Updating session <{self._loaded_session['file']}>")
        self.save_session(
            filename=self._loaded_session['file'],
            description=self._loaded_session['description']
        )


def load_floor_photo_data_from_session(filename: str) -> 'DataFloorPhotoXY':
    """
    Load data floor photo from session file.

    :param filename: Session file
    :return: Data
    """
    if '.json' not in filename:
        filename += '.json'
    assert os.path.isfile(filename), f'Session file <{filename}> does not exist'

    with open(filename, 'r') as fp:
        data = json.load(fp)
    assert data['version'] == _SESSION_EXPORT_VERSION, \
        'Outdated session export version, needed {0}, current {1}'.format(
            _SESSION_EXPORT_VERSION, data['version'])

    data = DataFloorPhotoXY(
        filename=data['filename'],
        rect_image_size=data['rect_image_size'],
        floor_photo_size=data['floor_photo_size'],
        rect_image_channels=data['rect_image_ch'],
        floor_photo_channels=data['floor_photo_ch']
    )
    data.load_session(filename=filename)

    return data
