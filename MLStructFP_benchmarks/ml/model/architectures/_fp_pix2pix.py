"""
MLSTRUCTFP BENCHMARKS - ML - MODEL - ARCHITECTURES - PIX2PIX

Pix2Pix generation.
"""

__all__ = ['Pix2PixFloorPhotoModel']

# noinspection PyProtectedMember
from MLStructFP_benchmarks.ml.model.core._model import GenericModel, _PATH_SESSION, _PATH_LOGS
from MLStructFP_benchmarks.ml.utils import scale_array_to_range
from MLStructFP_benchmarks.ml.utils.plot.architectures import Pix2PixFloorPhotoModelPlot
from MLStructFP.utils import DEFAULT_PLOT_DPI, DEFAULT_PLOT_STYLE

from keras.initializers import RandomNormal
from keras.layers import Input, Dropout, LeakyReLU, BatchNormalization, \
    Conv2D, Concatenate, Layer, Activation, Conv2DTranspose
from keras.models import Model
from keras.optimizers import Adam

from typing import List, Tuple, Union, TYPE_CHECKING, Any, Dict, Optional
import datetime
import gc
import matplotlib.pyplot as plt
import numpy as np
import os
import random
import time

if TYPE_CHECKING:
    from MLStructFP_benchmarks.ml.model.architectures._data_floor_photo_xy import DataFloorPhotoXY

_DISCRIMINATOR_LOSS: str = 'binary_crossentropy'  # 'binary_crossentropy'


def _free() -> None:
    """
    Free memory fun.
    """
    time.sleep(1)
    gc.collect()
    time.sleep(1)


class Pix2PixFloorPhotoModel(GenericModel):
    """
    Pix2Pix floor photo model image generation.
    """
    _data: 'DataFloorPhotoXY'
    _samples: Dict[int, Dict[str, 'np.ndarray']]  # Samples for each part
    _xy: str

    # Train
    _current_train_date: str
    _current_train_part: int

    # Image properties
    _img_channels: int
    _img_size: int
    _image_shape: Tuple[int, int, int]

    # Models
    _d_model: 'Model'
    _g_model: 'Model'
    _patch: int

    plot: 'Pix2PixFloorPhotoModelPlot'

    def __init__(
            self,
            data: Optional['DataFloorPhotoXY'],
            name: str,
            xy: str,
            image_shape: Optional[Tuple[int, int, int]] = None,
            **kwargs
    ) -> None:
        """
        Constructor.

        :param data: Model data
        :param name: Model name
        :param xy: Which data use, if "x" learn from Architectural pictures, "y" from Structure
        :param image_shape: Input shape
        :param kwargs: Optional keyword arguments
        """
        assert xy in ['x', 'y'], 'Invalid xy, use "x" or "y"'

        # Load data
        GenericModel.__init__(self, name=name, path=kwargs.get('path', ''))

        self._output_layers = ['discriminator', 'generator']

        # Input shape
        if data is not None:
            assert data.__class__.__name__ == 'DataFloorPhotoXY', \
                f'Invalid data class <{data.__class__.__name__}>'
            self._data = data
            self._image_shape = data.get_image_shape()
        else:
            assert image_shape is not None, 'If data is none, input_shape must be provided'
            assert isinstance(image_shape, tuple)
            assert len(image_shape) == 3
            assert image_shape[0] == image_shape[1]
            self._image_shape = image_shape

        self._img_size = self._image_shape[0]
        self._info(f'Image shape {self._image_shape}')

        self._samples = {}
        self._xy = xy
        self._info(f'Learning representation from {xy}')

        # Register constructor data
        self._register_session_data('xy', xy)
        self._register_session_data('image_shape', self._image_shape)

        # Number of filters in the first layer of G and D
        df: int = 64
        gf: int = 64

        self._current_train_date: str = ''
        self._current_train_part: int = -1
        self._info(f'Discriminator filters ({df}), generator filters ({gf})')
        self._register_session_data('df', df)
        self._register_session_data('gf', gf)

        # Create models
        self._d_model = self._define_discriminator(
            input_shape=self._image_shape,
            output_shape=self._image_shape,
            df=df
        )
        self._g_model = self._define_generator(
            input_shape=self._image_shape,
            output_shape=self._image_shape,
            gf=gf
        )

        # Make d model not trainable while we put into GAN
        self._d_model.trainable = False

        # Define the source image
        in_src = Input(shape=self._image_shape, name='source_image')

        # Connect the source image to the generator input
        gen_out: 'Layer' = self._g_model(in_src)

        # Connect the source input and generator output to the discriminator input
        # Discriminators determines validity of translated images / condition pairs
        dis_out: 'Layer' = self._d_model([in_src, gen_out])

        # Src image as input, generated image and classification output
        self._model = Model(inputs=in_src, outputs=[dis_out, gen_out], name=self.get_name())

        # Compile the model
        self.compile(
            optimizer=Adam(lr=0.0002, beta_1=0.5),
            loss={
                self._output_layers[0]: _DISCRIMINATOR_LOSS,  # Discriminator
                self._output_layers[1]: 'mae'  # Generator
            },
            loss_weights={
                self._output_layers[0]: 1,  # Discriminator
                self._output_layers[1]: 100  # Generator
            },
            metrics={
                self._output_layers[0]: None,  # Discriminator
                self._output_layers[1]: 'accuracy'  # Generator
            }
        )
        self._check_compilation = False

        # Enable weights discriminator again
        self._d_model.trainable = True

        # Compile discriminator model
        self._d_model.compile(
            loss=_DISCRIMINATOR_LOSS,
            optimizer=Adam(lr=0.0002, beta_1=0.5),
            loss_weights=[0.5]
        )

        # Compute patch shape
        # self._patch = int(self._img_size / 2 ** 4)  # self._d_model.output_shape[1]
        self._patch = self._d_model.output_shape[1]

        # assert self._patch == self._d_model.output_shape[1], 'Invalid patch size'
        self._info('Patch shape ({0},{0}) ({1}/16)'.format(self._patch, self._image_shape[0]))
        self._register_session_data('patch', self._patch)

        # Add custom metrics, used by custom loss
        self._add_custom_metric('d_real_loss')  # Discriminator loss on real samples
        self._add_custom_metric('d_fake_loss')  # Discriminator loss on fake samples

        # Set stateful metrics
        self._custom_stateful_metrics = []

        # As this model does not converge, this will enable checkpoint
        # self.enable_model_checkpoint(epochs=1)
        self.plot = Pix2PixFloorPhotoModelPlot(self)

    def _info(self, msg: str) -> None:
        """
        Information to console.

        :param msg: Message
        """
        if self._production:
            return
        self._print(f'Pix2PixFloorPhoto: {msg}')

    def get_patch_size(self) -> int:
        """
        :return: Model patch size
        """
        return self._patch

    @staticmethod
    def unscale_image_range(
            image: 'np.ndarray',
            to_range: Tuple[Union[int, float], Union[int, float]]
    ) -> 'np.ndarray':
        """
        Scale back to normal image range.

        :param image: Scaled image
        :param to_range: Scale range
        :return: Unscaled image
        """
        return scale_array_to_range(
            array=image,
            to=to_range,
            dtype=None
        )

    def enable_early_stopping(self, *args, **kwargs) -> None:
        """
        See upper doc.
        """
        raise RuntimeError('Callback not available on current Model')

    def enable_reduce_lr_on_plateau(self, *args, **kwargs) -> None:
        """
        See upper doc.
        """
        raise RuntimeError('Callback not available on current Model')

    def _define_discriminator(self, input_shape: Tuple, output_shape: Tuple, df: int) -> 'Model':
        """
        Define discriminator model.

        :param input_shape: Input image shape (from input)
        :param output_shape: Generator output image shape
        :param df: Discriminator filters
        :return: Keras model
        """
        # Weight initialization
        init = RandomNormal(stddev=0.02)

        # Source image input
        in_src_image = Input(shape=input_shape)  # Input image

        # Target image input
        in_target_image = Input(shape=output_shape)  # Input from generator

        # Concatenate images channel-wise
        merged = Concatenate()([in_src_image, in_target_image])

        # C64
        d = Conv2D(df, (4, 4), strides=(2, 2), padding='same', kernel_initializer=init)(merged)
        d = LeakyReLU(alpha=0.2)(d)

        # C128
        d = Conv2D(2 * df, (4, 4), strides=(2, 2), padding='same', kernel_initializer=init)(d)
        d = BatchNormalization()(d)
        d = LeakyReLU(alpha=0.2)(d)

        # C256
        d = Conv2D(4 * df, (4, 4), strides=(2, 2), padding='same', kernel_initializer=init)(d)
        d = BatchNormalization()(d)
        d = LeakyReLU(alpha=0.2)(d)

        # C512
        d = Conv2D(8 * df, (4, 4), strides=(2, 2), padding='same', kernel_initializer=init)(d)
        d = BatchNormalization()(d)
        d = LeakyReLU(alpha=0.2)(d)

        # Second last output layer
        d = Conv2D(8 * df, (4, 4), padding='same', kernel_initializer=init)(d)
        d = BatchNormalization()(d)
        d = LeakyReLU(alpha=0.2)(d)

        # Patch output
        d = Conv2D(1, (4, 4), padding='same', kernel_initializer=init)(d)
        patch_out = Activation('sigmoid', name='out_' + self._output_layers[0])(d)

        # Define model
        model = Model(inputs=[in_src_image, in_target_image], outputs=patch_out, name=self._output_layers[0])
        return model

    def _define_generator(self, input_shape: Tuple, output_shape: Tuple, gf: int) -> 'Model':
        """
        Define the standalone generator model.

        :param input_shape: Image input shape
        :param output_shape: Image output shape
        :param gf: Number of filters
        :return: Keras model
        """

        def define_encoder_block(
                layer_in: 'Layer',
                n_filters: int,
                batchnorm: bool = True
        ) -> 'Layer':
            """
            Encoder block.

            :param layer_in: Input layer
            :param n_filters: Number of filters
            :param batchnorm: Use batch normalization
            :return: Layer
            """
            # weight initialization
            _init = RandomNormal(stddev=0.02)
            # add downsampling layer
            _g = Conv2D(n_filters, (4, 4), strides=(2, 2), padding='same', kernel_initializer=_init)(layer_in)
            # conditionally add batch normalization
            if batchnorm:
                _g = BatchNormalization()(_g, training=True)
            # leaky relu activation
            _g = LeakyReLU(alpha=0.2)(_g)
            return _g

        def decoder_block(
                layer_in: 'Layer',
                skip_in: 'Layer',
                n_filters: int,
                dropout: bool = True
        ):
            """
            Define decoder block.

            :param layer_in: Input layer
            :param skip_in: Skip layer
            :param n_filters: Number of filters
            :param dropout: Use dropout
            :return: Layer
            """
            # weight initialization
            _init = RandomNormal(stddev=0.02)
            # add upsampling layer
            _g = Conv2DTranspose(n_filters, (4, 4), strides=(2, 2), padding='same', kernel_initializer=_init)(layer_in)
            # add batch normalization
            _g = BatchNormalization()(_g, training=True)
            # conditionally add dropout
            if dropout:
                _g = Dropout(0.5)(_g, training=True)
            # merge with skip connection
            _g = Concatenate()([_g, skip_in])
            # relu activation
            _g = Activation('relu')(_g)
            return _g

        # Weight initialization
        init = RandomNormal(stddev=0.02)

        # Image input
        in_image = Input(shape=input_shape)

        # Encoder model
        e1 = define_encoder_block(in_image, gf, batchnorm=False)
        e2 = define_encoder_block(e1, 2 * gf)
        e3 = define_encoder_block(e2, 4 * gf)
        e4 = define_encoder_block(e3, 8 * gf)
        e5 = define_encoder_block(e4, 8 * gf)
        e6 = define_encoder_block(e5, 8 * gf)
        e7 = define_encoder_block(e6, 8 * gf)

        # Bottleneck, no batch norm and relu
        b = Conv2D(8 * gf, (4, 4), strides=(2, 2), padding='same', kernel_initializer=init)(e7)
        b = Activation('relu')(b)

        # Decoder model
        d1 = decoder_block(b, e7, 8 * gf)
        d2 = decoder_block(d1, e6, 8 * gf)
        d3 = decoder_block(d2, e5, 512)
        d4 = decoder_block(d3, e4, 8 * gf, dropout=False)
        d5 = decoder_block(d4, e3, 4 * gf, dropout=False)
        d6 = decoder_block(d5, e2, 2 * gf, dropout=False)
        d7 = decoder_block(d6, e1, gf, dropout=False)

        # Output
        g = Conv2DTranspose(output_shape[2], (4, 4), strides=(2, 2), padding='same', kernel_initializer=init)(d7)
        out_image = Activation('tanh', name='out_' + self._output_layers[1])(g)

        # Define model
        model = Model(inputs=in_image, outputs=out_image, name=self._output_layers[1])
        return model

    def generate_true_labels(self, n_samples: int) -> 'np.ndarray':
        """
        Returns true label vectors.

        :param n_samples: Number of samples
        :return: Vector
        """
        assert n_samples > 0
        return np.ones((n_samples, self._patch, self._patch, 1))

    def generate_fake_labels(self, n_samples: int) -> 'np.ndarray':
        """
        Returns fake label vectors.

        :param n_samples: Number of samples
        :return: Vector
        """
        assert n_samples > 0
        return np.zeros((n_samples, self._patch, self._patch, 1))

    def _generate_fake_samples(self, samples: 'np.ndarray') -> Tuple['np.ndarray', 'np.ndarray']:
        """
        Generate fake samples.

        :param samples: Image samples
        :return: Fake samples
        """
        # Generate fake instance
        x = self._g_model.predict(samples)

        # Create 'fake' class labels (0)
        y = self.generate_fake_labels(len(x))
        return x, y

    def _custom_train_function(self, inputs) -> List[float]:
        """
        Custom train function.
        inputs: (ximg + ylabel + yimg + ylabel_weights + yimg_weights + uses_learning_phase flag)

        :param inputs: Train input
        :return: Train metrics
        """
        assert len(inputs) == 6

        ximg_real: 'np.ndarray' = inputs[0]

        ylabel_real: 'np.ndarray' = inputs[1]
        yimg_real: 'np.ndarray' = inputs[2]

        ylabel_weights: 'np.ndarray' = inputs[3]
        yimg_weights: 'np.ndarray' = inputs[4]
        # use_learning_phase: int = inputs[5]

        # Generate a batch of fake samples
        yimg_fake, ylabel_fake = self._generate_fake_samples(yimg_real)

        self._d_model.trainable = True

        # Update discriminator for real samples
        d_real_loss = self._d_model.train_on_batch(
            x=[ximg_real, yimg_real],
            y=ylabel_real,
            sample_weight=ylabel_weights
        )

        # Update discriminator for generated samples
        d_fake_loss = self._d_model.train_on_batch(
            x=[ximg_real, yimg_fake],
            y=ylabel_fake,
            sample_weight=ylabel_weights
        )

        self._d_model.trainable = False

        # Update the generator, this does not train discriminator as weights
        # were defined as not trainable
        # 'loss', 'discriminator_loss', 'generator_loss', 'generator_accuracy'
        g_loss, gd_loss, gg_loss, g_acc = self._model.train_on_batch(
            x=ximg_real,
            y=[ylabel_real, yimg_real],
            sample_weight=[ylabel_weights, yimg_weights]
        )

        del yimg_fake, ylabel_fake
        return [g_loss, gd_loss, gg_loss, g_acc, d_real_loss, d_fake_loss]

    def _custom_val_function(self, inputs) -> List[float]:
        """
        Custom validation function.
        inputs: (ximg + ylabel + yimg + ylabel_weights + yimg_weights + uses_learning_phase flag)

        :param inputs: Train input
        :return: Validation metrics
        """
        assert len(inputs) == 6

        ximg_real: 'np.ndarray' = inputs[0]

        ylabel_real: 'np.ndarray' = inputs[1]
        yimg_real: 'np.ndarray' = inputs[2]

        ylabel_weights: 'np.ndarray' = inputs[3]
        yimg_weights: 'np.ndarray' = inputs[4]
        # use_learning_phase: int = inputs[5]

        # Generate a batch of fake samples
        yimg_fake, ylabel_fake = self._generate_fake_samples(yimg_real)

        # Evaluate discriminator for real samples
        d_real_loss = self._d_model.evaluate(
            x=[ximg_real, yimg_real],
            y=ylabel_real,
            sample_weight=ylabel_weights,
            verbose=False
        )

        # Evaluate discriminator for generated samples
        d_fake_loss = self._d_model.evaluate(
            x=[ximg_real, yimg_fake],
            y=ylabel_fake,
            sample_weight=ylabel_weights,
            verbose=False
        )

        # Evaluate the generator
        # 'loss', 'discriminator_loss', 'generator_loss', 'generator_accuracy'
        g_loss, gd_loss, gg_loss, g_acc = self._model.evaluate(
            x=ximg_real,
            y=[ylabel_real, yimg_real],
            sample_weight=[ylabel_weights, yimg_weights],
            verbose=False
        )

        del yimg_fake, ylabel_fake
        return [g_loss, gd_loss, gg_loss, g_acc, d_real_loss, d_fake_loss]

    def _custom_epoch_finish_function(self, num_epoch: int) -> None:
        """
        Function triggered once each epoch finished.

        :param num_epoch: Number of the epoch
        """
        # Create figure
        _ = plt.figure(dpi=DEFAULT_PLOT_DPI)
        plt.style.use(DEFAULT_PLOT_STYLE)
        sample = self._samples[self._current_train_part]
        n_samples = len(sample['input'])
        plt.title(f'Epoch {num_epoch}')
        sample['predicted'] = self.predict_image(sample['input'])

        # plot real source images
        for i in range(n_samples):
            plt.subplot(3, n_samples, 1 + i)
            plt.axis('off')
            plt.imshow(sample['input'][i] / 255)
        # plot generated target image
        for i in range(n_samples):
            plt.subplot(3, n_samples, 1 + n_samples + i)
            plt.axis('off')
            plt.imshow(sample['predicted'][i] / 255)
        # plot real target image
        for i in range(n_samples):
            plt.subplot(3, n_samples, 1 + n_samples * 2 + i)
            plt.axis('off')
            plt.imshow(sample['real'][i] / 255)

        fig_file: str = '{6}{0}{1}{2}_{3}_part_{4}_epoch{5}.png'.format(
            _PATH_LOGS, os.path.sep, self.get_name(True), self._current_train_date,
            self._current_train_part, num_epoch, self._path)
        plt.savefig(fig_file)
        plt.close()

    def reset_train(self) -> None:
        """
        Reset train.
        """
        super().reset_train()
        self._samples.clear()

    def train(
            self,
            epochs: int,
            batch_size: int,
            val_split: float,
            shuffle: bool = True,
            **kwargs
    ) -> None:
        """
        See upper doc.

        Optional parameters:
            - init_part     Initial parts
            - num_samples   Number of samples
            - n_parts       Number of parts to be processed, if -1 there will be no limits
        """
        # Get initial parts
        init_part = kwargs.get('init_part', 1)
        assert isinstance(init_part, int)

        # The idea is to train using each part of the data, metrics will not be evaluated
        total_parts: int = self._data.get_total_parts()
        assert 1 <= init_part <= total_parts, \
            f'Initial part <{init_part}> exceeds total parts <{total_parts}>'

        if self._is_trained:
            print(f'Resuming train, last processed part: {max(list(self._samples.keys()))}')

        # Get number of samples
        n_samples = kwargs.get('num_samples', 3)
        assert isinstance(n_samples, int)
        assert n_samples >= 0
        if n_samples > 0:
            print(f'Evaluation samples: {n_samples}')
        _free()

        # Get total parts to be processed
        n_parts: int = kwargs.get('n_parts', -1)
        assert isinstance(n_parts, int)
        assert total_parts - init_part >= n_parts >= 1 or n_parts == -1  # -1: no limits
        if n_parts != -1:
            print(f'Number of parts to be processed: {n_parts}')

        _crop_len = 500
        if _crop_len != 0:
            print(f'Cropping: {_crop_len} elements')

        _scale_to_1 = True
        if not _scale_to_1:
            print('Scale to (-1,1) is disabled')

        npt = 0  # Number of processed parts
        for i in range(total_parts):
            part = i + 1
            if part < init_part:
                continue

            print(f'Loading data part {part}/{total_parts}', end='')
            part_data = self._data.load_part(part=part, xy=self._xy, remove_null=True, shuffle=False)
            xtrain_img_u: 'np.ndarray' = part_data[self._xy + '_rect'].copy()  # Unscaled, from range (0,255)
            ytrain_img_u: 'np.ndarray' = part_data[self._xy + '_fphoto'].copy()  # Unscaled, from range (0, 255)
            del part_data

            # Crop data
            if _crop_len != 0:
                _cr = min(_crop_len, len(xtrain_img_u))
                xtrain_img_u, ytrain_img_u = xtrain_img_u[0:_cr], ytrain_img_u[0:_cr]

            ytrain_label = self.generate_true_labels(len(ytrain_img_u))
            _free()

            # Make sample inputs
            sample_id = np.random.randint(0, len(xtrain_img_u), n_samples)
            sample_input = xtrain_img_u[sample_id]
            sample_real = ytrain_img_u[sample_id]

            # Convert images to range (-1, 1)
            if _scale_to_1:
                print(', scaling x', end='')
                xtrain_img = scale_array_to_range(xtrain_img_u, (-1, 1), 'int8')  # Rect images to range (-1, 1)
                del xtrain_img_u
                _free()
            else:
                xtrain_img = xtrain_img_u

            if _scale_to_1:
                print(', scaling y', end='')
                ytrain_img = scale_array_to_range(ytrain_img_u, (-1, 1), 'float32')  # Floor photo to range (-1, 1)
                del ytrain_img_u
                _free()
            else:
                ytrain_img = ytrain_img_u
            print(': OK')

            self._samples[part] = {
                'input': sample_input,
                'real': sample_real,
            }
            self._current_train_part = part
            self._current_train_date = datetime.datetime.today().strftime('%Y-%m-%d_%H-%M-%S')

            super()._train(
                xtrain=xtrain_img,
                ytrain=(ytrain_label, ytrain_img),
                xtest=None,
                ytest=None,
                epochs=epochs,
                batch_size=batch_size,
                val_split=val_split,
                shuffle=shuffle,
                use_custom_fit=True,
                continue_train=self._is_trained,
                compute_metrics=False
            )

            del xtrain_img, ytrain_img, ytrain_label
            _free()
            if not self._is_trained:
                print('Train failed, stopping')
                return

            # Predict samples
            sample_predicted = self.predict_image(sample_input)

            # Save samples
            self._samples[part] = {
                'input': sample_input,
                'real': sample_real,
                'predicted': sample_predicted
            }
            self._model.reset_states()

            npt += 1
            if npt == n_parts:
                print(f'Reached number of parts to be processed ({n_parts}), train has finished')
                break

    def predict_image(self, img: 'np.ndarray') -> 'np.ndarray':
        """
        Predict image from common input.

        :param img: Image
        :return: Image
        """
        if len(img.shape) == 3:
            img = img.reshape((-1, img.shape[0], img.shape[1], img.shape[2]))
        # pred_img = self._g_model.predict(scale_array_to_range(img, (-1, 1), 'int8'))
        pred_img = self._model.predict(scale_array_to_range(img, (-1, 1), 'int8'))[1]
        # print(np.min(pred_img), np.max(pred_img))
        # print(pred_img)
        # return pred_img
        return scale_array_to_range(pred_img, (0, 255), 'float32')

    def predict(self, x: 'np.ndarray') -> List[Union['np.ndarray', 'np.ndarray']]:  # Label, Image
        """
        See upper doc.
        """
        return self._model_predict(x=self._format_tuple(x, 'np', 'x'))

    def evaluate(self, x: 'np.ndarray', y: Tuple['np.ndarray', 'np.ndarray']) -> List[float]:
        """
        See upper doc.
        """
        return self._model_evaluate(
            x=self._format_tuple(x, 'np', 'x'),
            y=self._format_tuple(y, ('np', 'np'), 'y')
        )

    def get_xy(self, xy: str) -> Any:
        """
        See upper doc.
        """
        raise RuntimeError('Function invalid in this Model')

    def _custom_save_session(self, filename: str, data: dict) -> None:
        """
        See upper doc.
        """
        # Save samples dict
        if len(self._samples.keys()) > 0:
            if self._get_session_data('train_samples') is None:
                self._register_session_data('train_samples', _PATH_SESSION +
                                            os.path.sep + f'samples_{random.getrandbits(64)}.npz')
            samples_f = self._get_session_data('train_samples')
            np.savez_compressed(samples_f, data=self._samples)

    def _custom_load_session(
            self,
            filename: str,
            asserts: bool,
            data: Dict[str, Any],
            check_hash: bool
    ) -> None:
        """
        See upper doc.
        """
        samples_f: str = self._get_session_data('train_samples')  # Samples File
        if samples_f is not None:
            self._samples = np.load(samples_f, allow_pickle=True)['data'].item()