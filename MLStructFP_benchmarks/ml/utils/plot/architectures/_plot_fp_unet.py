"""
MLSTRUCT-FP BENCHMARKS - ML - MODEL - UTILS - PLOT - ARCHITECTURES - UNET MODEL

Model plot.
"""

__all__ = ['UNETFloorPhotoModelPlot']

from MLStructFP_benchmarks.ml.utils import iou_metric
from MLStructFP_benchmarks.ml.utils.plot._plot_model import GenericModelPlot
from MLStructFP.utils import save_figure, DEFAULT_PLOT_STYLE, DEFAULT_PLOT_DPI, configure_figure

from typing import TYPE_CHECKING, Dict
import matplotlib.pyplot as plt
import numpy as np

if TYPE_CHECKING:
    from MLStructFP_benchmarks.ml.model.architectures import UNETFloorPhotoModel


class UNETFloorPhotoModelPlot(GenericModelPlot):
    """
    PIX2PIX Model plot.
    """
    _model: 'UNETFloorPhotoModel'

    def __init__(self, model: 'UNETFloorPhotoModel') -> None:
        """
        Constructor.

        :param model: Model object
        """
        super().__init__(model)

    def plot_predict(
            self,
            im: 'np.ndarray',
            real: 'np.ndarray',
            save: str = '',
            inverse: bool = False,
            threshold: bool = True,
            title: bool = True,
            **kwargs
    ) -> None:
        """
        Predict and plot image.

        :param im: Image to predict
        :param real: Real image
        :param save: Save figure to file
        :param inverse: If true, plot inversed colors (white as background)
        :param threshold: Use threshold
        :param title: Show title
        :param kwargs: Optional keyword arguments
        """
        im_pred = self._model.predict_image(im, threshold=threshold)

        if inverse:
            im = 1 - im
            im_pred = 1 - im_pred
            real = 1 - real

        kwargs['cfg_grid'] = False
        fig = plt.figure(dpi=DEFAULT_PLOT_DPI, figsize=(9, 3))
        plt.style.use(DEFAULT_PLOT_STYLE)
        # fig.subplots_adjust(hspace=0.5)
        plt.axis('off')
        configure_figure(**kwargs)

        ax1: 'plt.Axes' = fig.add_subplot(131)
        if title:
            ax1.title.set_text('Input')
        ax1.imshow(im, cmap='gray')
        plt.xlabel('x $(px)$')
        plt.ylabel('y $(px)$')
        plt.axis('off')
        configure_figure(**kwargs)

        ax2 = fig.add_subplot(132)
        if title:
            ax2.title.set_text('Output')
        ax2.imshow(im_pred, cmap='gray')
        plt.axis('off')

        ax2 = fig.add_subplot(133)
        if title:
            ax2.title.set_text('Ground Thruth')
        ax2.imshow(real, cmap='gray')
        plt.axis('off')

        configure_figure(**kwargs)
        save_figure(save, **kwargs)
        plt.show()

    def summarize_performance(self, part: int, save: str = '', **kwargs) -> None:
        """
        Plot examples from part to see model generation performance.

        :param part: Part number
        :param save: Save figure to file
        :param kwargs: Optional keyword arguments
        """
        # noinspection PyProtectedMember
        samples = self._model._samples
        assert part in list(samples.keys()), f'Part <{part}> does not exists on samples'

        sample = samples[part]
        n_samples = len(sample['input'])
        if n_samples == 0:
            raise ValueError(f'Part <{part}> does not have any samples to show')

        # Create figure
        plt.figure(dpi=DEFAULT_PLOT_DPI)
        plt.style.use(DEFAULT_PLOT_STYLE)

        # plot real source images
        for i in range(n_samples):
            plt.subplot(3, n_samples, 1 + i)
            plt.axis('off')
            plt.imshow(sample['input'][i])
        # plot generated target image
        for i in range(n_samples):
            plt.subplot(3, n_samples, 1 + n_samples + i)
            plt.axis('off')
            plt.imshow(sample['predicted'][i])
        # plot real target image
        for i in range(n_samples):
            plt.subplot(3, n_samples, 1 + n_samples * 2 + i)
            plt.axis('off')
            plt.imshow(sample['real'][i])

        save_figure(save, **kwargs)
        plt.show()

    def test(self, data: Dict[str, 'np.ndarray'], idx: int) -> None:
        """
        Plot test data.

        :param data: Data
        :param idx: Index to plot
        """
        img_in = data['photo'][idx]
        img_pred = self._model.predict_image(img_in)
        img_true = data['binary'][idx]
        print(f'IoU: {iou_metric(img_true, img_pred)}')
        self.plot_predict(img_in, img_true)
