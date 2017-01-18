"""
<b>Crop</b> crops or masks an image.
<hr>
This module crops images into a rectangle, ellipse, an arbitrary shape provided by you, the shape of object(s)
identified by an <b>Identify</b> module, or a shape created using a previous <b>Crop</b> module in the pipeline.
<p>Keep in mind that cropping changes the size of your images, which may have unexpected consequences. For example,
identifying objects in a cropped image and then trying to measure their intensity in the <i>original</i> image will not
work because the two images are not the same size.</p>
<h4>Available measurements</h4>
<ul>
    <li><i>AreaRetainedAfterCropping:</i> The area of the image left after cropping.</li>
    <li><i>OriginalImageArea:</i> The area of the original input image.</li>
</ul><i>Special note on saving images:</i> You can save the cropping shape that you have defined in this module (e.g.,
an ellipse you drew) so that you can use the <i>Image</i> option in future analyses. To do this, save either the mask
or cropping in <b>SaveImages</b>. See the <b>SaveImages</b> module help for more information on saving cropping shapes.
"""

import logging
import math
import sys

import numpy
import centrosome.filter

import cellprofiler.image
import cellprofiler.module
import cellprofiler.measurement
import cellprofiler.preferences
import cellprofiler.setting

logger = logging.getLogger(__name__)

SH_RECTANGLE = "Rectangle"
SH_ELLIPSE = "Ellipse"
SH_IMAGE = "Image"
SH_OBJECTS = "Objects"
SH_CROPPING = "Previous cropping"
CM_COORDINATES = "Coordinates"
CM_MOUSE = "Mouse"
IO_INDIVIDUALLY = "Every"
IO_FIRST = "First"
RM_NO = "No"
RM_EDGES = "Edges"
RM_ALL = "All"

# Doens't seem to like importing defs from cellprofiler.gui.moduleview so define here
ABSOLUTE = "Absolute"
FROM_EDGE = "From edge"

EL_XCENTER = "xcenter"
EL_YCENTER = "ycenter"
EL_XRADIUS = "xradius"
EL_YRADIUS = "yradius"

RE_LEFT = "left"
RE_TOP = "top"
RE_RIGHT = "right"
RE_BOTTOM = "bottom"

FF_AREA_RETAINED = 'Crop_AreaRetainedAfterCropping_%s'
FF_ORIGINAL_AREA = 'Crop_OriginalImageArea_%s'

OFF_IMAGE_NAME = 0
OFF_CROPPED_IMAGE_NAME = 1
OFF_SHAPE = 2
OFF_CROP_METHOD = 3
OFF_INDIVIDUAL_OR_ONCE = 4
OFF_HORIZONTAL_LIMITS = 5
OFF_VERTICAL_LIMITS = 6
OFF_CENTER = 7
OFF_X_RADIUS = 8
OFF_Y_RADIUS = 9
OFF_PLATE_FIX = 10
OFF_REMOVE_ROWS_AND_COLUMNS = 11
OFF_IMAGE_MASK_SOURCE = 12
OFF_CROPPING_MASK_SOURCE = 13

D_FIRST_IMAGE_SET = "FirstImageSet"
D_FIRST_CROPPING = "FirstCropping"
D_FIRST_CROPPING_MASK = "FirstCroppingMask"


class Crop(cellprofiler.module.Module):
    module_name = "Crop"
    variable_revision_number = 2
    category = "Image Processing"

    def create_settings(self):
        self.image_name = cellprofiler.setting.ImageNameSubscriber(
            "Select the input image",
            cellprofiler.setting.NONE,
            doc="Choose the image to be cropped."
        )

        self.cropped_image_name = cellprofiler.setting.CroppingNameProvider(
            "Name the output image",
            "CropBlue",
            doc="Enter the name to be given to cropped image."
        )

        self.shape = cellprofiler.setting.Choice(
            "Select the cropping shape",
            [
                SH_RECTANGLE,
                SH_ELLIPSE,
                SH_IMAGE,
                SH_OBJECTS,
                SH_CROPPING
            ],
            SH_RECTANGLE,
            doc="""
            Choose the shape into which you would like to crop:
            <ul>
                <li><i>{SH_RECTANGLE}:</i> Self-explanatory.</li>
                <li><i>{SH_ELLIPSE}:</i> Self-explanatory.</li>
                <li>
                    <i>{SH_IMAGE}:</i> Cropping will occur based on a binary image you specify. A choice box
                    with available images will appear from which you can select an image. To crop into an arbitrary
                    shape that you define, choose <i>{SH_IMAGE}</i> and use the <b>LoadSingleImage</b> module to
                    load a black and white image that you have already prepared from a file. If you have created
                    this image in a program such as Photoshop, this binary image should contain only the values 0
                    and 255, with zeros (black) for the parts you want to remove and 255 (white) for the parts you
                    want to retain. Alternately, you may have previously generated a binary image using this module
                    (e.g., using the <i>{SH_ELLIPSE}</i> option) and saved it using the <b>SaveImages</b>
                    module.<br>
                    In any case, the image must be exactly the same starting size as your image and should contain
                    a contiguous block of white pixels, because the cropping module may remove rows and columns
                    that are completely blank.
                </li>
                <li>
                    <i>{SH_OBJECTS}:</i> Crop based on labeled objects identified by a previous <b>Identify</b>
                    module.
                </li>
                <li>
                    <i>{SH_CROPPING}:</i> The cropping generated by a previous cropping module. You will be
                    able to select images that were generated by previous <b>Crop</b> modules. This <b>Crop</b>
                    module will use the same cropping that was used to generate whichever image you choose.
                </li>
            </ul>
            """.format(**{
                "SH_RECTANGLE": SH_RECTANGLE,
                "SH_ELLIPSE": SH_ELLIPSE,
                "SH_IMAGE": SH_IMAGE,
                "SH_OBJECTS": SH_OBJECTS,
                "SH_CROPPING": SH_CROPPING
            })
        )

        self.crop_method = cellprofiler.setting.Choice(
            "Select the cropping method",
            [CM_COORDINATES, CM_MOUSE],
            CM_COORDINATES,
            doc="""
            Choose whether you would like to crop by typing in pixel coordinates or clicking with the mouse.
            <ul>
                <li><i>{CM_COORDINATES}:</i> For <i>{SH_ELLIPSE}</i>, you will be asked to enter the geometric
                parameters of the ellipse. For <i>{SH_RECTANGLE}</i>, you will be asked to specify the
                coordinates of the corners.</li>
                <li><i>{CM_MOUSE}:</i> For <i>{SH_ELLIPSE}</i>, you will be asked to click five or more points
                to define an ellipse around the part of the image you want to analyze. Keep in mind that the
                more points you click, the longer it will take to calculate the ellipse shape. For
                <i>{SH_RECTANGLE}</i>, you can click as many points as you like that are in the interior of the
                region you wish to retain.</li>
            </ul>
            """.format(**{
                "CM_COORDINATES": CM_COORDINATES,
                "SH_ELLIPSE": SH_ELLIPSE,
                "SH_RECTANGLE": SH_RECTANGLE,
                "CM_MOUSE": CM_MOUSE
            })
        )

        self.individual_or_once = cellprofiler.setting.Choice(
            "Apply which cycle's cropping pattern?",
            [IO_INDIVIDUALLY, IO_FIRST],
            IO_INDIVIDUALLY,
            doc="""
            Specify how a given cropping pattern should be applied to other image cycles:
            <ul>
                <li><i>{IO_FIRST}:</i> The cropping pattern from the first image cycle is applied to all
                subsequent cyles. This is useful if the first image is intended to function as a template in
                some fashion.</li>
                <li><i>{IO_INDIVIDUALLY}:</i> Every image cycle is cropped individually.</li>
            </ul>
            """.format(**{
                "IO_FIRST": IO_FIRST,
                "IO_INDIVIDUALLY": IO_INDIVIDUALLY
            })
        )

        self.horizontal_limits = cellprofiler.setting.IntegerOrUnboundedRange(
            "Left and right rectangle positions",
            minval=0,
            doc="""
            <i>(Used only if {SH_RECTANGLE} selected as cropping shape, or if using Plate Fix)</i><br>
            Specify the left and right positions for the bounding rectangle by selecting one of the
            following:<br>
            <ul>
                <li><i>{ABSOLUTE}:</i> Specify these values as absolute pixel coordinates in the original
                image. For instance, you might enter "25", "225", and "Absolute" to create a 200&times;200
                pixel image that is 25 pixels from the top-left corner.</li>
                <li><i>{FROM_EDGE}:</i> Specify the position relative to the image edge. For instance, you
                might enter "25", "25", and "Edge" to crop 25 pixels from both the left and right edges of the
                image, irrespective of the image's original size.</li>
            </ul>
            """.format(**{
                "SH_RECTANGLE": SH_RECTANGLE,
                "ABSOLUTE": ABSOLUTE,
                "FROM_EDGE": FROM_EDGE
            })
        )

        self.vertical_limits = cellprofiler.setting.IntegerOrUnboundedRange(
            "Top and bottom rectangle positions",
            minval=0,
            doc="""
            <i>(Used only if {SH_RECTANGLE} selected as cropping shape, or if using Plate Fix)</i><br>
            Specify the top and bottom positions for the bounding rectangle by selecting one of the
            following:<br>
            <ul>
                <li><i>{ABSOLUTE}:</i> Specify these values as absolute pixel coordinates. For instance, you
                might enter "25", "225", and "Absolute" to create a 200&times;200 pixel image that's 25 pixels
                from the top-left corner.</li>
                <li><i>{FROM_EDGE}:</i> Specify position relative to the image edge. For instance, you might
                enter "25", "25", and "Edge" to crop 25 pixels from the edges of your images irrespective of
                their size.</li>
            </ul>
            """.format(**{
                "SH_RECTANGLE": SH_RECTANGLE,
                "ABSOLUTE": ABSOLUTE,
                "FROM_EDGE": FROM_EDGE
            })
        )

        self.ellipse_center = cellprofiler.setting.Coordinates(
            "Coordinates of ellipse center",
            (500, 500),
            doc="""
            <i>(Used only if {SH_ELLIPSE} selected as cropping shape)</i><br>
            Specify the center pixel position of the ellipse.
            """.format(**{
                "SH_ELLIPSE": SH_ELLIPSE
            })
        )

        self.ellipse_x_radius = cellprofiler.setting.Integer(
            "Ellipse radius, X direction",
            400,
            doc="""
            <i>(Used only if {SH_ELLIPSE} selected as cropping shape)</i><br>
            Specify the radius of the ellipse in the X direction.
            """.format(**{
                "SH_ELLIPSE": SH_ELLIPSE
            })
        )

        self.ellipse_y_radius = cellprofiler.setting.Integer(
            "Ellipse radius, Y direction",
            200,
            doc="""
            <i>(Used only if {SH_ELLIPSE} selected as cropping shape)</i><br>
            Specify the radius of the ellipse in the Y direction.
            """.format(**{
                "SH_ELLIPSE": SH_ELLIPSE
            })
        )

        self.image_mask_source = cellprofiler.setting.ImageNameSubscriber(
            "Select the masking image",
            cellprofiler.setting.NONE,
            doc="""
            <i>(Used only if {SH_IMAGE} selected as cropping shape)</i><br>
            Select the image to be use as a cropping mask.
            """.format(**{
                "SH_IMAGE": SH_IMAGE
            })
        )

        self.cropping_mask_source = cellprofiler.setting.CroppingNameSubscriber(
            "Select the image with a cropping mask",
            cellprofiler.setting.NONE,
            doc="""
            <i>(Used only if {SH_CROPPING} selected as cropping shape)</i><br>
            Select the image associated with the cropping mask that you want to use.
            """.format(**{
                "SH_CROPPING": SH_CROPPING
            })
        )

        self.objects_source = cellprofiler.setting.ObjectNameSubscriber(
            "Select the objects",
            cellprofiler.setting.NONE,
            doc="""
            <i>(Used only if {SH_OBJECTS} selected as cropping shape)</i><br>
            Select the objects that are to be used as a cropping mask.
            """.format(**{
                "SH_OBJECTS": SH_OBJECTS
            })
        )

        self.use_plate_fix = cellprofiler.setting.Binary(
            "Use Plate Fix?",
            False,
            doc="""
            <i>(Used only if {SH_IMAGE} selected as cropping shape)</i><br>
            Select <i>{YES}</i> to attempt to regularize the edges around a previously-identified plate object.
            <p>When attempting to crop based on a previously identified object such as a rectangular plate, the
            plate may not have precisely straight edges: there might be a tiny, almost unnoticeable "appendage"
            sticking out. Without Plate Fix, the <b>Crop</b> module would not crop the image tightly enough: it
            would retain the tiny appendage, leaving a lot of blank space around the plate and potentially
            causing problems with later modules (especially ones involving illumination correction).</p>
            <p>Plate Fix takes the identified object and crops to exclude any minor appendages (technically,
            any horizontal or vertical line where the object covers less than 50% of the image). It also sets
            pixels around the edge of the object (for regions greater than 50% but less than 100%) that
            otherwise would be 0 to the background pixel value of your image, thus avoiding problems with other
            modules.</p>
            <p><i>Important note:</i> Plate Fix uses the coordinates entered in the boxes normally used for
            rectangle cropping (Top, Left and Bottom, Right) to tighten the edges around your identified plate.
            This is done because in the majority of plate identifications you do not want to include the sides
            of the plate. If you would like the entire plate to be shown, you should enter "1:end" for both
            coordinates. If, for example, you would like to crop 80 pixels from each edge of the plate, you
            could enter Top, Left and Bottom, Right values of 80 and select <i>{FROM_EDGE}</i>.</p>
            """.format(**{
                "SH_IMAGE": SH_IMAGE,
                "YES": cellprofiler.setting.YES,
                "FROM_EDGE": FROM_EDGE
            })
        )

        self.remove_rows_and_columns = cellprofiler.setting.Choice(
            "Remove empty rows and columns?",
            [RM_NO, RM_EDGES, RM_ALL],
            RM_ALL,
            doc="""
            Use this option to choose whether to remove rows and columns that lack objects:
            <ul>
                <li>
                    <i>{RM_NO}:</i> Leave the image the same size. The cropped areas will be set to zeroes, and
                will appear as black.</li>
                <li>
                    <i>{RM_EDGES}:</i> Crop the image so that its top, bottom, left and right are at the first
                    non-blank pixel for that edge.
                </li>
                <li>
                    <i>{RM_ALL}:</i> Remove any row or column of all-blank pixels, even from the internal
                    portion of the image.
                </li>
            </ul>
            """.format(**{
                "RM_NO": RM_NO,
                "RM_EDGES": RM_EDGES,
                "RM_ALL": RM_ALL
            })
        )

    def settings(self):
        return [self.image_name, self.cropped_image_name, self.shape,
                self.crop_method, self.individual_or_once,
                self.horizontal_limits, self.vertical_limits,
                self.ellipse_center, self.ellipse_x_radius,
                self.ellipse_y_radius, self.use_plate_fix,
                self.remove_rows_and_columns, self.image_mask_source,
                self.cropping_mask_source, self.objects_source]

    def visible_settings(self):
        result = [self.image_name, self.cropped_image_name, self.shape]
        if self.shape.value in (SH_RECTANGLE, SH_ELLIPSE):
            result += [self.crop_method, self.individual_or_once]
            if self.crop_method == CM_COORDINATES:
                if self.shape == SH_RECTANGLE:
                    result += [self.horizontal_limits, self.vertical_limits]
                elif self.shape == SH_ELLIPSE:
                    result += [self.ellipse_center, self.ellipse_x_radius,
                               self.ellipse_y_radius]
        elif self.shape == SH_IMAGE:
            result += [self.image_mask_source, self.use_plate_fix]
            if self.use_plate_fix.value:
                result += [self.horizontal_limits, self.vertical_limits]
        elif self.shape == SH_CROPPING:
            result.append(self.cropping_mask_source)
        elif self.shape == SH_OBJECTS:
            result.append(self.objects_source)
        else:
            raise NotImplementedError("Unimplemented shape type: %s" % self.shape.value)
        result += [self.remove_rows_and_columns]
        return result

    def run(self, workspace):
        first_image_set = workspace.measurements.get_current_image_measurement(
                cellprofiler.measurement.GROUP_INDEX) == 1
        image_set_list = workspace.image_set_list
        d = self.get_dictionary(image_set_list)
        orig_image = workspace.image_set.get_image(self.image_name.value)
        recalculate_flag = (self.shape not in (SH_ELLIPSE, SH_RECTANGLE) or
                            self.individual_or_once == IO_INDIVIDUALLY or
                            first_image_set or
                            workspace.pipeline.test_mode)
        save_flag = (self.individual_or_once == IO_FIRST and first_image_set)
        if not recalculate_flag:
            if d[D_FIRST_CROPPING].shape != orig_image.pixel_data.shape[:2]:
                recalculate_flag = True
                logger.warning("""Image, "%s", size changed from %s to %s during cycle %d, recalculating""",
                               self.image_name.value,
                               str(d[D_FIRST_CROPPING].shape),
                               str(orig_image.pixel_data.shape[:2]),
                               workspace.image_set.image_number)
        mask = None  # calculate the mask after cropping unless set below
        cropping = None
        masking_objects = None
        if not recalculate_flag:
            cropping = d[D_FIRST_CROPPING]
            mask = d[D_FIRST_CROPPING_MASK]
        elif self.shape == SH_CROPPING:
            cropping_image = workspace.image_set.get_image(self.cropping_mask_source.value)
            cropping = cropping_image.crop_mask
        elif self.shape == SH_IMAGE:
            source_image = workspace.image_set.get_image \
                (self.image_mask_source.value).pixel_data
            if self.use_plate_fix.value:
                source_image = self.plate_fixup(source_image)
            cropping = source_image > 0
        elif self.shape == SH_OBJECTS:
            masking_objects = workspace.get_objects(self.objects_source.value)
            cropping = masking_objects.segmented > 0
        elif self.crop_method == CM_MOUSE:
            cropping = self.ui_crop(workspace, orig_image)
        elif self.shape == SH_ELLIPSE:
            cropping = self.get_ellipse_cropping(workspace, orig_image)
        elif self.shape == SH_RECTANGLE:
            cropping = self.get_rectangle_cropping(workspace, orig_image)
        if self.remove_rows_and_columns == RM_NO:
            cropped_pixel_data = orig_image.pixel_data.copy()
            if cropped_pixel_data.ndim == 3:
                cropped_pixel_data[~cropping, :] = 0
            else:
                cropped_pixel_data[numpy.logical_not(cropping)] = 0
            if mask is None:
                mask = cropping
            if orig_image.has_mask:
                image_mask = mask & orig_image.mask
            else:
                image_mask = mask
        else:
            internal_cropping = self.remove_rows_and_columns == RM_ALL
            cropped_pixel_data = cellprofiler.image.crop_image(orig_image.pixel_data,
                                                               cropping,
                                                               internal_cropping)
            if mask is None:
                mask = cellprofiler.image.crop_image(cropping, cropping, internal_cropping)
            if orig_image.has_mask:
                image_mask = cellprofiler.image.crop_image(
                        orig_image.mask, cropping, internal_cropping) & mask
            else:
                image_mask = mask

            if cropped_pixel_data.ndim == 3:
                cropped_pixel_data[~mask, :] = 0
            else:
                cropped_pixel_data[~mask] = 0
        if self.shape == SH_OBJECTS:
            # Special handling for objects - masked objects instead of
            # mask and crop mask
            output_image = cellprofiler.image.Image(image=cropped_pixel_data,
                                                    masking_objects=masking_objects,
                                                    parent_image=orig_image)
        else:
            output_image = cellprofiler.image.Image(image=cropped_pixel_data,
                                                    mask=image_mask,
                                                    parent_image=orig_image,
                                                    crop_mask=cropping)
        #
        # Display the image
        #
        if self.show_window:
            workspace.display_data.orig_image_pixel_data = orig_image.pixel_data
            workspace.display_data.cropped_pixel_data = cropped_pixel_data
            workspace.display_data.image_set_number = workspace.measurements.image_set_number

        if save_flag:
            d[D_FIRST_CROPPING_MASK] = mask
            d[D_FIRST_CROPPING] = cropping
        #
        # Save the image / cropping / mask
        #
        workspace.image_set.add(self.cropped_image_name.value, output_image)
        #
        # Save the old and new image sizes
        #
        original_image_area = numpy.product(orig_image.pixel_data.shape[:2])
        area_retained_after_cropping = numpy.sum(cropping)
        feature = FF_AREA_RETAINED % self.cropped_image_name.value
        m = workspace.measurements
        m.add_measurement('Image', feature,
                          numpy.array([area_retained_after_cropping]))
        feature = FF_ORIGINAL_AREA % self.cropped_image_name.value
        m.add_measurement('Image', feature,
                          numpy.array([original_image_area]))

    def display(self, workspace, figure):
        orig_image_pixel_data = workspace.display_data.orig_image_pixel_data
        cropped_pixel_data = workspace.display_data.cropped_pixel_data
        figure.set_subplots((2, 1))

        title = "Original: %s, cycle # %d" % (self.image_name.value,
                                              workspace.display_data.image_set_number)
        figure.subplot_imshow_grayscale(0, 0, orig_image_pixel_data, title)
        figure.subplot_imshow_bw(1, 0, cropped_pixel_data,
                                 self.cropped_image_name.value)

    def get_measurement_columns(self, pipeline):
        '''Return information on the measurements made during cropping'''
        return [(cellprofiler.measurement.IMAGE,
                 x % self.cropped_image_name.value,
                 cellprofiler.measurement.COLTYPE_INTEGER)
                for x in (FF_AREA_RETAINED, FF_ORIGINAL_AREA)]

    def ui_crop(self, workspace, orig_image):
        """Crop into a rectangle or ellipse, guided by UI"""
        d = self.get_dictionary(workspace.image_set_list)
        if ((not d.has_key(self.shape.value)) or
                    self.individual_or_once == IO_INDIVIDUALLY):
            d[self.shape.value] = \
                workspace.interaction_request(self, d.get(self.shape.value, None), orig_image.pixel_data)
        if self.shape == SH_ELLIPSE:
            return self.apply_ellipse_cropping(workspace, orig_image)
        else:
            return self.apply_rectangle_cropping(workspace, orig_image)

    def handle_interaction(self, current_shape, orig_image):
        '''Show the cropping user interface'''
        import matplotlib as M
        import matplotlib.cm
        import wx
        from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg
        pixel_data = centrosome.filter.stretch(orig_image)
        #
        # Create the UI - a dialog with a figure inside
        #
        style = wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER
        dialog_box = wx.Dialog(wx.GetApp().TopWindow, -1,
                               "Select the cropping region",
                               size=(640, 480),
                               style=style)
        sizer = wx.BoxSizer(wx.VERTICAL)
        figure = matplotlib.figure.Figure()
        panel = FigureCanvasWxAgg(dialog_box, -1, figure)
        sizer.Add(panel, 1, wx.EXPAND)
        btn_sizer = wx.StdDialogButtonSizer()
        btn_sizer.AddButton(wx.Button(dialog_box, wx.ID_OK))
        btn_sizer.AddButton(wx.Button(dialog_box, wx.ID_CANCEL))
        btn_sizer.Realize()
        sizer.Add(btn_sizer, 0, wx.ALIGN_CENTER_HORIZONTAL | wx.ALL, 5)
        dialog_box.SetSizer(sizer)
        dialog_box.Size = dialog_box.BestSize
        dialog_box.Layout()

        axes = figure.add_subplot(1, 1, 1)
        assert isinstance(axes, matplotlib.axes.Axes)
        if pixel_data.ndim == 2:
            axes.imshow(pixel_data, matplotlib.cm.Greys_r, origin="upper")
        else:
            axes.imshow(pixel_data, origin="upper")
        # t = axes.transData.inverted()
        current_handle = [None]

        def data_xy(mouse_event):
            '''Return the mouse event's x & y converted into data-relative coords'''
            x = mouse_event.xdata
            y = mouse_event.ydata
            return x, y

        class handle(M.patches.Rectangle):
            dm = max((10, min(pixel_data.shape) / 50))
            height, width = (dm, dm)

            def __init__(self, x, y, on_move):
                x = max(0, min(x, pixel_data.shape[1]))
                y = max(0, min(y, pixel_data.shape[0]))
                self.__selected = False
                self.__color = cellprofiler.preferences.get_primary_outline_color()
                self.__color = numpy.hstack((self.__color, [255])).astype(float) / 255.0
                self.__on_move = on_move
                super(handle, self).__init__((x - self.width / 2, y - self.height / 2),
                                             self.width, self.height,
                                             edgecolor=self.__color,
                                             facecolor="none")
                self.set_picker(True)

            def move(self, x, y):
                self.set_xy((x - self.width / 2, y - self.height / 2))
                self.__on_move(x, y)

            def select(self, on):
                self.__selected = on
                if on:
                    current_handle[0] = self
                    self.set_facecolor(self.__color)

                else:
                    self.set_facecolor("none")
                    if current_handle[0] == self:
                        current_handle[0] = None
                figure.canvas.draw()
                dialog_box.Update()

            @property
            def is_selected(self):
                return self.__selected

            @property
            def center_x(self):
                '''The handle's notion of its x coordinate'''
                return self.get_x() + self.get_width() / 2

            @property
            def center_y(self):
                '''The handle's notion of its y coordinate'''
                return self.get_y() + self.get_height() / 2

            def handle_pick(self, event):
                mouse_event = event.mouseevent
                x, y = data_xy(mouse_event)
                if mouse_event.button == 1:
                    self.select(True)
                    self.orig_x = self.center_x
                    self.orig_y = self.center_y
                    self.first_x = x
                    self.first_y = y

            def handle_mouse_move_event(self, event):
                x, y = data_xy(event)
                if x is None or y is None:
                    return
                x = x - self.first_x + self.orig_x
                y = y - self.first_y + self.orig_y
                if x < 0:
                    x = 0
                if x >= pixel_data.shape[1]:
                    x = pixel_data.shape[1] - 1
                if y < 0:
                    y = 0
                if y >= pixel_data.shape[0]:
                    y = pixel_data.shape[0] - 1
                self.move(x, y)

        class crop_rectangle(object):
            def __init__(self, top_left, bottom_right):
                self.__left, self.__top = top_left
                self.__right, self.__bottom = bottom_right
                color = cellprofiler.preferences.get_primary_outline_color()
                color = numpy.hstack((color, [255])).astype(float) / 255.0
                self.rectangle = M.patches.Rectangle(
                        (min(self.__left, self.__right),
                         min(self.__bottom, self.__top)),
                        abs(self.__right - self.__left),
                        abs(self.__top - self.__bottom),
                        edgecolor=color,
                        facecolor="none"
                )
                self.top_left_handle = handle(top_left[0], top_left[1],
                                              self.handle_top_left)
                self.bottom_right_handle = handle(bottom_right[0],
                                                  bottom_right[1],
                                                  self.handle_bottom_right)

            def handle_top_left(self, x, y):
                self.__left = x
                self.__top = y
                self.__reshape()

            def handle_bottom_right(self, x, y):
                self.__right = x
                self.__bottom = y
                self.__reshape()

            def __reshape(self):
                self.rectangle.set_xy((min(self.__left, self.__right),
                                       min(self.__bottom, self.__top)))
                self.rectangle.set_width(abs(self.__right - self.__left))
                self.rectangle.set_height(abs(self.__bottom - self.__top))
                self.rectangle.figure.canvas.draw()
                dialog_box.Update()

            @property
            def patches(self):
                return [self.rectangle, self.top_left_handle,
                        self.bottom_right_handle]

            @property
            def handles(self):
                return [self.top_left_handle, self.bottom_right_handle]

            @property
            def left(self):
                return min(self.__left, self.__right)

            @property
            def right(self):
                return max(self.__left, self.__right)

            @property
            def top(self):
                return min(self.__top, self.__bottom)

            @property
            def bottom(self):
                return max(self.__top, self.__bottom)

        class crop_ellipse(object):
            def __init__(self, center, radius):
                '''Draw an ellipse with control points at the ellipse center and
                a given x and y radius'''
                self.center_x, self.center_y = center
                self.radius_x = self.center_x + radius[0] / 2
                self.radius_y = self.center_y + radius[1] / 2
                color = cellprofiler.preferences.get_primary_outline_color()
                color = numpy.hstack((color, [255])).astype(float) / 255.0
                self.ellipse = M.patches.Ellipse(center, self.width, self.height,
                                                 edgecolor=color,
                                                 facecolor="none")
                self.center_handle = handle(self.center_x, self.center_y,
                                            self.move_center)
                self.radius_handle = handle(self.radius_x, self.radius_y,
                                            self.move_radius)

            def move_center(self, x, y):
                self.center_x = x
                self.center_y = y
                self.redraw()

            def move_radius(self, x, y):
                self.radius_x = x
                self.radius_y = y
                self.redraw()

            @property
            def width(self):
                return abs(self.center_x - self.radius_x) * 4

            @property
            def height(self):
                return abs(self.center_y - self.radius_y) * 4

            def redraw(self):
                self.ellipse.center = (self.center_x, self.center_y)
                self.ellipse.width = self.width
                self.ellipse.height = self.height
                self.ellipse.figure.canvas.draw()
                dialog_box.Update()

            @property
            def patches(self):
                return [self.ellipse, self.center_handle, self.radius_handle]

            @property
            def handles(self):
                return [self.center_handle, self.radius_handle]

        if self.shape == SH_ELLIPSE:
            if current_shape is None:
                current_shape = {
                    EL_XCENTER: pixel_data.shape[1] / 2,
                    EL_YCENTER: pixel_data.shape[0] / 2,
                    EL_XRADIUS: pixel_data.shape[1] / 2,
                    EL_YRADIUS: pixel_data.shape[0] / 2
                }
            ellipse = current_shape
            shape = crop_ellipse((ellipse[EL_XCENTER], ellipse[EL_YCENTER]),
                                 (ellipse[EL_XRADIUS], ellipse[EL_YRADIUS]))
        else:
            if current_shape is None:
                current_shape = {
                    RE_LEFT: pixel_data.shape[1] / 4,
                    RE_TOP: pixel_data.shape[0] / 4,
                    RE_RIGHT: pixel_data.shape[1] * 3 / 4,
                    RE_BOTTOM: pixel_data.shape[0] * 3 / 4
                }
            rectangle = current_shape
            shape = crop_rectangle((rectangle[RE_LEFT], rectangle[RE_TOP]),
                                   (rectangle[RE_RIGHT], rectangle[RE_BOTTOM]))
        for patch in shape.patches:
            axes.add_artist(patch)

        def on_mouse_down_event(event):
            axes.pick(event)

        def on_mouse_move_event(event):
            if current_handle[0] is not None:
                current_handle[0].handle_mouse_move_event(event)

        def on_mouse_up_event(event):
            if current_handle[0] is not None:
                current_handle[0].select(False)

        def on_pick_event(event):
            for h in shape.handles:
                if id(h) == id(event.artist):
                    h.handle_pick(event)

        figure.canvas.mpl_connect('button_press_event', on_mouse_down_event)
        figure.canvas.mpl_connect('button_release_event', on_mouse_up_event)
        figure.canvas.mpl_connect('motion_notify_event', on_mouse_move_event)
        figure.canvas.mpl_connect('pick_event', on_pick_event)

        try:
            if dialog_box.ShowModal() != wx.ID_OK:
                raise ValueError("Cancelled by user")
        finally:
            dialog_box.Destroy()
        if self.shape == SH_RECTANGLE:
            return {
                RE_LEFT: shape.left,
                RE_TOP: shape.top,
                RE_RIGHT: shape.right,
                RE_BOTTOM: shape.bottom
            }
        else:
            return {
                EL_XCENTER: shape.center_x,
                EL_YCENTER: shape.center_y,
                EL_XRADIUS: shape.width / 2,
                EL_YRADIUS: shape.height / 2
            }

    def get_ellipse_cropping(self, workspace, orig_image):
        """Crop into an ellipse using user-specified coordinates"""
        x_center = self.ellipse_center.x
        y_center = self.ellipse_center.y
        x_radius = self.ellipse_x_radius.value
        y_radius = self.ellipse_y_radius.value
        d = self.get_dictionary(workspace.image_set_list)
        d[SH_ELLIPSE] = {
            EL_XCENTER: x_center,
            EL_YCENTER: y_center,
            EL_XRADIUS: x_radius,
            EL_YRADIUS: y_radius
        }
        return self.apply_ellipse_cropping(workspace, orig_image)

    def apply_ellipse_cropping(self, workspace, orig_image):
        d = self.get_dictionary(workspace.image_set_list)
        ellipse = d[SH_ELLIPSE]
        x_center, y_center, x_radius, y_radius = [
            ellipse[x] for x in (EL_XCENTER, EL_YCENTER, EL_XRADIUS, EL_YRADIUS)]
        pixel_data = orig_image.pixel_data
        x_max = pixel_data.shape[1]
        y_max = pixel_data.shape[0]
        if x_radius > y_radius:
            dist_x = math.sqrt(x_radius ** 2 - y_radius ** 2)
            dist_y = 0
            major_radius = x_radius
        else:
            dist_x = 0
            dist_y = math.sqrt(y_radius ** 2 - x_radius ** 2)
            major_radius = y_radius

        focus_1_x, focus_1_y = (x_center - dist_x, y_center - dist_y)
        focus_2_x, focus_2_y = (x_center + dist_x, y_center + dist_y)
        y, x = numpy.mgrid[0:y_max, 0:x_max]
        d1 = numpy.sqrt((x - focus_1_x) ** 2 + (y - focus_1_y) ** 2)
        d2 = numpy.sqrt((x - focus_2_x) ** 2 + (y - focus_2_y) ** 2)
        cropping = d1 + d2 <= major_radius * 2
        return cropping

    def get_rectangle_cropping(self, workspace, orig_image):
        """Crop into a rectangle using user-specified coordinates"""
        cropping = numpy.ones(orig_image.pixel_data.shape[:2], bool)
        if not self.horizontal_limits.unbounded_min:
            cropping[:, :self.horizontal_limits.min] = False
        if not self.horizontal_limits.unbounded_max:
            cropping[:, self.horizontal_limits.max:] = False
        if not self.vertical_limits.unbounded_min:
            cropping[:self.vertical_limits.min, :] = False
        if not self.vertical_limits.unbounded_max:
            cropping[self.vertical_limits.max:, :] = False
        return cropping

    def apply_rectangle_cropping(self, workspace, orig_image):
        cropping = numpy.ones(orig_image.pixel_data.shape[:2], bool)
        d = self.get_dictionary(workspace.image_set_list)
        r = d[SH_RECTANGLE]
        left, top, right, bottom = [
            r[x] for x in (RE_LEFT, RE_TOP, RE_RIGHT, RE_BOTTOM)]
        if left > 0:
            cropping[:, :left] = False
        if right < cropping.shape[1]:
            cropping[:, right:] = False
        if top > 0:
            cropping[:top, :] = False
        if bottom < cropping.shape[0]:
            cropping[bottom:, :] = False
        return cropping

    def plate_fixup(self, pixel_data):
        """Fix up the cropping image based on the plate fixup rules

        The rules:
        * Trim rows and columns off of the edges if less than 50%
        * Use the horizontal and vertical trim to trim the image further
        """
        pixel_data = pixel_data.copy()
        i_histogram = pixel_data.sum(axis=1)
        i_cumsum = numpy.cumsum(i_histogram > pixel_data.shape[0] / 2)
        j_histogram = pixel_data.sum(axis=0)
        j_cumsum = numpy.cumsum(j_histogram > pixel_data.shape[1] / 2)
        i_first = numpy.argwhere(i_cumsum == 1)[0]
        i_last = numpy.argwhere(i_cumsum == i_cumsum.max())[0]
        i_end = i_last + 1
        j_first = numpy.argwhere(j_cumsum == 1)[0]
        j_last = numpy.argwhere(j_cumsum == j_cumsum.max())[0]
        j_end = j_last + 1
        if not self.horizontal_limits.unbounded_min:
            j_first = max(j_first, self.horizontal_limits.min)
        if not self.horizontal_limits.unbounded_max:
            j_end = min(j_end, self.horizontal_limits.max)
        if not self.vertical_limits.unbounded_min:
            i_first = max(i_first, self.vertical_limits.min)
        if not self.vertical_limits.unbounded_max:
            i_end = min(i_end, self.vertical_limits.max)
        if i_first > 0:
            if pixel_data.ndim == 3:
                pixel_data[:i_first, :, :] = 0
            else:
                pixel_data[:i_first, :] = 0
        if i_end < pixel_data.shape[0]:
            if pixel_data.ndim == 3:
                pixel_data[i_end:, :, :] = 0
            else:
                pixel_data[i_end:, :] = 0
        if j_first > 0:
            if pixel_data.ndim == 3:
                pixel_data[:, :j_first, :] = 0
            else:
                pixel_data[:, :j_first] = 0
        if j_end < pixel_data.shape[1]:
            if pixel_data.ndim == 3:
                pixel_data[:, j_end:, :] = 0
            else:
                pixel_data[:, j_end:] = 0
        return pixel_data

    def upgrade_settings(self, setting_values, variable_revision_number,
                         module_name, from_matlab):
        if from_matlab and variable_revision_number == 4:
            # Added OFF_REMOVE_ROWS_AND_COLUMNS
            new_setting_values = list(setting_values)
            new_setting_values.append(cellprofiler.setting.NO)
            variable_revision_number = 5
        if from_matlab and variable_revision_number == 5:
            # added image mask source, cropping mask source and reworked
            # the shape to add SH_IMAGE and SH_CROPPING
            new_setting_values = list(setting_values)
            new_setting_values.extend([cellprofiler.setting.NONE, cellprofiler.setting.NONE, cellprofiler.setting.NONE])
            shape = setting_values[OFF_SHAPE]
            if shape not in (SH_ELLIPSE, SH_RECTANGLE):
                # the "shape" is the name of some image file. If it
                # starts with Cropping, then it's the crop mask of
                # some other image
                if shape.startswith('Cropping'):
                    new_setting_values[OFF_CROPPING_MASK_SOURCE] = \
                        shape[len('Cropping'):]
                    new_setting_values[OFF_SHAPE] = SH_CROPPING
                else:
                    new_setting_values[OFF_IMAGE_MASK_SOURCE] = shape
                    new_setting_values[OFF_SHAPE] = SH_IMAGE
            if new_setting_values[OFF_REMOVE_ROWS_AND_COLUMNS] == cellprofiler.setting.YES:
                new_setting_values[OFF_REMOVE_ROWS_AND_COLUMNS] = RM_EDGES
            setting_values = new_setting_values
            variable_revision_number = 2
            from_matlab = False

        if (not from_matlab) and variable_revision_number == 1:
            # Added ability to crop objects
            new_setting_values = list(setting_values)
            new_setting_values.append(cellprofiler.setting.NONE)
            variable_revision_number = 2

        if variable_revision_number == 2 and not from_matlab:
            # minor - "Cropping" changed to "Previous cropping"
            setting_values = list(setting_values)
            if setting_values[OFF_SHAPE] == "Cropping":
                setting_values[OFF_SHAPE] = SH_CROPPING
            #
            # Individually changed to "every"
            #
            if setting_values[OFF_INDIVIDUAL_OR_ONCE] == "Individually":
                setting_values[OFF_INDIVIDUAL_OR_ONCE] = IO_INDIVIDUALLY
        return setting_values, variable_revision_number, from_matlab
