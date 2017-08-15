#!/usr/bin/env python
##############################################################################
#
# xpdan            by Billinge Group
#                   Simon J. L. Billinge sb2896@columbia.edu
#                   (c) 2016 trustees of Columbia University in the City of
#                        New York.
#                   All rights reserved
#
# File coded by:    Timothy Liu, Christopher J. Wright
#
# See AUTHORS.txt for a list of people who contributed.
# See LICENSE.txt for license information.
#
##############################################################################
import os
from itertools import islice, tee, chain

import numpy as np
import tifffile as tif
import yaml
from pyFAI.azimuthalIntegrator import AzimuthalIntegrator

from .tools import mask_img, decompress_mask
from xpdan.dev_utils import _clean_info, _timestampstr
from xpdan.io import read_fit2d_msk


def _mask_logic(header, mask_setting, ai=None, mask_dict=None, root_dir=None,
                f_name=None, img=None):
    mask = None
    # If we are handed a mask array use it
    if (isinstance(
            mask_setting, np.ndarray) and
            mask_setting.dtype == np.bool):
        mask = mask_setting

    # if we are handed a filename/path load it
    elif isinstance(mask_setting, str) and os.path.exists(
            mask_setting):
        if os.path.splitext(mask_setting)[-1] == '.msk':
            mask = read_fit2d_msk(mask_setting)
        else:
            mask = np.load(mask_setting)

    # default to the mask in the header
    elif mask_setting == 'default':
        mask_md = header['start'].get('mask', None)
        if mask_md is None:
            print(
                "INFO: no mask associated or mask information was"
                " not set up correctly, no mask will be applied")
            mask = None
        else:
            # unpack here
            data, ind, indptr = mask_md
            print(
                "INFO: pull off mask "
                "associate with your image: {}".format(f_name))
            mask = decompress_mask(data, ind, indptr, img.shape)
    # if auto build a mask
    elif mask_setting == 'auto':
        mask = mask_img(img, ai, **mask_dict)
    # if string None, do nothing
    elif mask_setting == 'None':
        mask = None

    mask_fn = os.path.splitext(f_name)[0]  # remove ext
    if mask_setting is not None:
        print("INFO: mask file '{}' is saved at {}"
              .format(mask_fn, root_dir))
        np.save(os.path.join(root_dir, mask_fn),
                mask_setting)  # default is .npy from np.save
    return mask


# top definition for minimal impacts on the code
def _feature_gen(event, labels=None, fields=None, data_fields=None):
    """ generate a human readable file name.

    file name is generated by metadata information in event
    run_start
    """
    if data_fields is None:
        data_fields = ['temperature']
    if fields is None:
        fields = ['sample_name', 'sp_type', 'sp_requested_exposure']
    if labels is None:
        labels = ['dark_frame']
    feature_list = []
    run_start = db[event['descriptor']['run_start']
    uid = run_start['uid'][:6]
    # get special label
    for el in labels:
        label = run_start.get(el, None)
        if label is not None:
            feature_list.append(str(label))
        else:
            pass
    # get fields
    for key in fields:
        el = str(run_start.get(key, None))
        if el is not None:
            # truncate string length
            if len(el) > 12:
                value = el[:12]
            # clear space
            feature = _clean_info(el)
            feature_list.append(feature)
        else:
            pass
    # get data fields
    for key in data_fields:
        val = event['data'].get(key, None)
        if val is not None:
            feature = "{}".format(val)
            feature_list.append(feature)
        else:
            pass
    # get uid
    feature_list.append(uid)
    return "_".join(feature_list)


def _file_name(event, event_timestamp, ind):
    """ priviate method operates on event level """
    f_name = _feature_gen(event)
    f_name = '_'.join([_timestampstr(event_timestamp),
                       f_name])
    f_name = '{}_{:04d}.tif'.format(f_name, ind)
    return f_name


""" analysis function operates at header level """


def _prepare_header_list(headers):
    if not isinstance(headers, list):
        # still do it in two steps, easier to read
        header_list = list()
        header_list.append(headers)
    else:
        header_list = headers
    return header_list


def _load_config(header, config_base='', calib_config_name=''):
    try:
        with open(os.path.join(config_base, calib_config_name)) as f:
            config_dict = yaml.load(f)
    except FileNotFoundError:
        config_dict = header['start'].get('calibration_md', None)
        if config_dict is None:
            # back support
            config_dict = header['start'].get('sc_calibration_md', None)

    return config_dict


def _npt_cal(config_dict, total_shape=(2048, 2048)):
    """ config_dict should be a PyFAI calibration dict """
    x_0, y_0 = (config_dict['centerX'], config_dict['centerY'])
    center_len = np.hypot(x_0, y_0)
    # FIXME : use hardwired shape now, use direct info later
    x_total, y_total = total_shape
    total_len = np.hypot(x_total, y_total)
    # FIXME : use the longest diagonal distance. Optimal value might have
    # to do with grid of Fourier transform. Need to revisit it later
    dist = max(total_len, total_len - center_len)
    return dist


def integrate_and_save(headers, *, db, save_dir,
                       path_append_keys='sample_name',
                       dark_sub_bool=True,
                       polarization_factor=0.99,
                       mask_setting='default',
                       mask_dict=None,
                       save_image=True,
                       config_dict=None,
                       image_data_key='pe1_image',
                       config_base='',
                       calib_config_name='',
                       **kwargs):
    """ integrate and save dark subtracted images for given list of headers

    Parameters
    ----------
    headers : list
        a list of databroker.header objects
    db: databroker.broker.Broker instance
        The databroker holding the data, this must be specified as a `db=` in
        the function call (keyword only argument)
    save_dir: str
        The folder in which to save the data, this must be specified as a
        `save_dir=` in the function call (keyword only argument)
    path_append_keys: str or list of str, optional
        The keys of data to be appended to the path, defaults to 'sample_name'
    dark_sub_bool : bool, optional
        option to turn on/off dark subtraction functionality
    polarization_factor : float, optional
        polarization correction factor, ranged from -1(vertical) to +1
        (horizontal). default is 0.99. set to None for no
        correction.
    mask_setting : {str, ndarray} optional
        string for mask option. Valid options are 'default', 'auto' and
        'None'. If 'default', mask included in metadata will be
        used. If 'auto', a new mask would be generated from current
        image. If 'None', no mask would be applied. If a ndarray of bools
        use as mask. If a path/filename to a valid fit2d or numpy mask file
        (with extensions of `.msk` or `.npy`) load the file and use that.
        Predefined option is 'default'.
    mask_dict : dict, optional
        dictionary stores options for automasking functionality.
        default is defined by an_glbl.auto_mask_dict.
        Please refer to documentation for more details
    save_image : bool, optional
        option to save dark subtracted images. images will be
        saved to the same directory of chi files. default is True.
    config_dict : dict, optional
        dictionary stores integration parameters of pyFAI azimuthal
        integrator. default is the most recent parameters saved in
        xpdUser/conifg_base
    image_data_key: str, optional
        The key for the image data, defaults to `pe1_image`
    calib_config_name: str, optional
        The filename for the calibration file
    config_base: str, optional
        The folder holding the calibration file
    kwargs :
        addtional keywords to overwrite integration behavior. Please
        refer to pyFAI.azimuthalIntegrator.AzimuthalIntegrator for
        more information

    Note
    ----
    complete docstring of masking functionality could be find in
    ``mask_img``

    customized mask can be assign to by kwargs (It must be a ndarray)
    >>> integrate_and_save(mask_setting=my_mask)

    See also
    --------
    xpdan.tools.mask_img
    pyFAI.azimuthalIntegrator.AzimuthalIntegrator
    """
    if mask_dict is None:
        mask_dict = {}
    header_list = _prepare_header_list(headers)
    ai = AzimuthalIntegrator()

    total_rv_list_Q = []
    total_rv_list_2theta = []

    if not isinstance(path_append_keys, (list, tuple)):
        path_append_keys = [path_append_keys]

    save_dir = os.path.expanduser(save_dir)
    for header in header_list:
        header_rv_list_Q, header_rv_list_2theta = [], []
        start = False
        event = False
        stop = False
        for name, doc in db.restream(header, fill=True):
            if name == 'start':
                start = True
                # config_dict
                if config_dict is None:
                    config_dict = _load_config(
                        header, config_base=config_base,
                        calib_config_name=calib_config_name)
                    if config_dict is None:  # still None
                        raise RuntimeError(
                            "Can't find calibration parameter under "
                            "xpdUser/config_base/ or header metadata\n"
                            "data reduction can not be perfomed."
                            "This is likely because a run_calibration() "
                            "was not carried out before the data "
                            "were collected during data acquisition.\n"
                            "If you have a calibration file, please rerun "
                            "integrate_and_save() giving it a path to the "
                            "calib file, e.g., integrate_and_save(header, "
                            "config_base='', calib_config_name=''). "
                            "If you have many files that take the same "
                            "calibration file, define config_base and "
                            "calib_config_name in your config file.")

                if not path_append_keys:
                    path = save_dir
                for s in path_append_keys:
                    path = os.path.join(save_dir, doc[s])
                if not os.path.isdir(path):
                    os.mkdir(path)

                if dark_sub_bool:
                    dark_uid = doc['sc_dk_field_uid']
                    dark_hdr = db[dark_uid]
                    dark_img = next(db.get_events(
                        dark_hdr, fill=True))['data'][image_data_key]

                # setting up geometry
                ai.setPyFAI(**config_dict)
                npt = _npt_cal(config_dict)
            elif name == 'descriptor':
                pass
            elif name == 'event':
                if not start:
                    raise RuntimeError('Event before Start')
                f_name = _feature_gen(doc)
                img = doc['data'][image_data_key]
                if dark_sub_bool:
                    img -= dark_img
                    f_name = 'sub_' + f_name

                mask = _mask_logic(header, mask_setting, ai, mask_dict,
                                   path, f_name, img)

                # integration logic
                stem, ext = os.path.splitext(f_name)
                chi_name_Q = 'Q_' + stem + '.chi'  # q_nm^-1
                chi_name_2th = '2th_' + stem + '.chi'  # deg^-1
                print("INFO: integrating image: {}".format(f_name))
                # Q-integration
                chi_fn_Q = os.path.join(path, chi_name_Q)
                chi_fn_2th = os.path.join(path, chi_name_2th)
                for unit, fn, l in zip(["q_nm^-1", "2th_deg"],
                                       [chi_fn_Q, chi_fn_2th],
                                       [header_rv_list_Q,
                                        header_rv_list_2theta]):
                    print("INFO: save chi file: {}".format(fn))
                    if mask is not None:
                        # make a copy, don't overwrite it
                        _mask = ~mask
                    else:
                        _mask = None

                    rv = ai.integrate1d(
                        img, npt,
                        filename=fn, mask=_mask,
                        polarization_factor=polarization_factor,
                        unit=unit, **kwargs)
                    l.append(rv)

                # save image logic
                tiff_fn = f_name
                w_name = os.path.join(path, tiff_fn)
                if save_image:
                    tif.imsave(w_name+'.tiff', img)
                    if os.path.isfile(w_name+'.tiff'):
                        print('image "%s" has been saved at "%s"' %
                              (tiff_fn, path))
                    else:
                        raise FileNotFoundError('Sorry, something went '
                                                'wrong with your tif saving')

                # save run_start
                stem, ext = os.path.splitext(f_name)
                config_name = f_name.replace(ext, '.yml')
                with open(config_name, 'w') as f:
                    yaml.dump(header['start'], f)  # save all md in start

        # each header generate  a list of rv
        total_rv_list_Q.append(header_rv_list_Q)
        total_rv_list_2theta.append(header_rv_list_2theta)

        print("INFO: chi/image files are saved at {}".format(path))
    return total_rv_list_Q, total_rv_list_2theta


def integrate_and_save_last(**kwargs):
    """ integrate and save dark subtracted images for the latest header

    Parameters
    ----------
    db: databroker.broker.Broker instance
        The databroker holding the data, this must be specified as a `db=` in
        the function call (keyword only argument)
    save_dir: str
        The folder in which to save the data, this must be specified as a
        `save_dir=` in the function call (keyword only argument)
    path_append_keys: str or list of str, optional
        The keys of data to be appended to the path, defaults to 'sample_name'
    dark_sub_bool : bool, optional
        option to turn on/off dark subtraction functionality
    polarization_factor : float, optional
        polarization correction factor, ranged from -1(vertical) to +1
        (horizontal). default is 0.99. set to None for no
        correction.
    mask_setting : str, ndarray optional
        string for mask option. Valid options are 'default', 'auto' and
        'None'. If 'default', mask included in metadata will be
        used. If 'auto', a new mask would be generated from current
        image. If 'None', no mask would be applied. If a ndarray of bools
        use as mask. If a path/filename to a valid fit2d or numpy mask file
        (with extensions of `.msk` or `.npy`) load the file and use that.
        Predefined option is 'default'.
    mask_dict : dict, optional
        dictionary stores options for automasking functionality.
        default is defined by an_glbl.auto_mask_dict.
        Please refer to documentation for more details
    save_image : bool, optional
        option to save dark subtracted images. images will be
        saved to the same directory of chi files. default is True.
    root_dir : str, optional
        path of chi files that are going to be saved. default is
        the same as your image file
    config_dict : dict, optional
        dictionary stores integration parameters of pyFAI azimuthal
        integrator. default is the most recent parameters saved in
        xpdUser/conifg_base
    image_data_key: str, optional
        The key for the image data, defaults to `pe1_image`
    calib_config_name: str, optional
        The filename for the calibration file
    config_base: str, optional
        The folder holding the calibration file
    kwargs :
        addtional keywords to overwrite integration behavior. Please
        refer to pyFAI.azimuthalIntegrator.AzimuthalIntegrator for
        more information

    Note
    ----
    complete docstring of masking functionality could be find in
    ``mask_img``

    customized mask can be assign to by kwargs (It must be a ndarray)
    >>> integrate_and_save(mask_setting=my_mask)

    See also
    --------
    xpdan.tools.mask_img
    pyFAI.azimuthalIntegrator.AzimuthalIntegrator
    """
    integrate_and_save(kwargs['db'][-1], **kwargs)


def save_tiff(headers, *, db, save_dir,
              path_append_keys='sample_name',
              dark_sub_bool=True, dryrun=False,
              image_data_key='pe1_image'
              ):
    """Save images obtained from dataBroker as tiff format files.

    Parameters
    ----------
    headers : list
        a list of header objects obtained from a query to dataBroker.
    db: databroker.broker.Broker instance
        The databroker holding the data, this must be specified as a `db=` in
        the function call (keyword only argument)
    save_dir: str
        The folder in which to save the data, this must be specified as a
        `save_dir=` in the function call (keyword only argument)
    path_append_keys: str or list of str, optional
        The keys of data to be appended to the path, defaults to 'sample_name'
    dark_sub_bool : bool, optional
        Default is True, which allows dark/background subtraction to
        be done before saving each image. If header doesn't contain
        necessary information to perform dark subtraction, uncorrected
        image will be saved.
    dryrun : bool, optional
        if set to True, file won't be saved. default is False
    image_data_key: str
        The key for event['data'] which gives back the image
    """
    # normalize list
    header_list = _prepare_header_list(headers)
    if not isinstance(path_append_keys, (list, tuple)):
        path_append_keys = [path_append_keys]

    save_dir = os.path.expanduser(save_dir)
    for header in header_list:
        for name, doc in db.restream(header, fill=True):
            if name == 'start':
                for s in path_append_keys:
                    path = os.path.join(save_dir, doc[s])
                if dark_sub_bool:
                    dark_uid = doc['sc_dk_field_uid']  # Or something
                    dark_hdr = db[dark_uid]
                    dark_img = next(db.get_events(
                        dark_hdr, fill=True))['data'][image_data_key]
            elif name == 'descriptor':
                pass
            elif name == 'event':
                f_name = _feature_gen(doc)
                img = doc['data'][image_data_key]
                if dark_sub_bool:
                    img -= dark_img
                path = os.path.join(save_dir, f_name)
                if not dryrun:
                    tif.imsave(path+'.tiff', img)
                    if os.path.isfile(path+'.tiff'):
                        print('image "%s" has been saved at "%s"' %
                              (f_name, path))
                    else:
                        print(
                            'Sorry, something went wrong with your tif saving')
                        return
                else:
                    print('dryrun: image "%s" has been saved at "%s"' %
                          (f_name, path))
            elif name == 'stop':
                # save run_start
                stem, ext = os.path.splitext(path)
                config_name = stem + '.yml'
                if not dryrun:
                    with open(config_name, 'w') as f:
                        yaml.dump(header['start'], f)  # save all md in start
                else:
                    print('dryrun: config "%s" has been saved at "%s"' %
                          (stem, path))

    print(" *** {} *** ".format('Saving process finished'))


def save_last_tiff(**kwargs):
    """Save images from latest data set as tiff format files.

    Parameters
    ----------
    db: databroker.broker.Broker instance
        The databroker holding the data, this must be specified as a `db=` in
        the function call (keyword only argument)
    save_dir: str
        The folder in which to save the data, this must be specified as a
        `save_dir=` in the function call (keyword only argument)
    dark_sub_bool : bool, optional
        Default is True, which allows dark/background subtraction to
        be done before saving each image. If header doesn't contain
        necessary information to perform dark subtraction, uncorrected
        image will be saved.
    dryrun : bool, optional
        if set to True, file won't be saved. default is False
    image_data_key: str
        The key for event['data'] which gives back the image
    """

    save_tiff(kwargs['db'][-1], **kwargs)


def sum_images(event_stream, idxs_list=None):
    """Sum images in a header

    Sum the images in a header according to the idxs_list

    Parameters
    ----------
    event_stream: generator
        The event stream to be summed. The image must be first, with the
        event itself last
    idxs_list: list of lists and tuple or list or 'all', optional
        The list of lists and tuples which specify the images to be summed.
        If 'all', sum all the images in the run. If None, do nothing.
        Defaults to None.
    Yields
    -------
    event_stream:
        The event stream, with the images (in the first position) summed

    Examples
    ---------
    Returns one image which is the sum of all the images in hdr

    >>> from databroker import db
    >>> hdr = db[-1]
    >>> total_imgs = sum_images(hdr)

    Returns one image that is the sum of the images in image-events
    (an event that contains an image) 1, 2 and 3 in hdr

    >>> total_imgs = sum_images(hdr, [1, 2, 3])

    Returns two images, the first is the sum of the images in image-events
    1, 2 and 3, the second is the sum of the images in all the image-events
    from 5 to 10.

    >>> total_imgs = sum_images(hdr, [[1, 2, 3], (5,10)])
    """
    if idxs_list is None:
        yield from event_stream
    if idxs_list is 'all':
        total_img = None
        for img, *rest, event in event_stream:
            if total_img is None:
                total_img = img
            else:
                total_img += img
        yield chain([total_img], rest, ['all', event])
    elif idxs_list:
        # If we only have one list make it into a list of lists
        if not all(isinstance(e1, list) or isinstance(e1, tuple) for e1 in
                   idxs_list):
            idxs_list = [idxs_list]
        # Each idx list gets its own copy of the event stream
        # This is to prevent one idx list from eating the generator
        event_stream_copies = tee(event_stream, len(idxs_list))
        for idxs, sub_event_stream in zip(idxs_list, event_stream_copies):
            total_img = None
            if isinstance(idxs, tuple):
                for idx in range(idxs[0], idxs[1]):
                    img, *rest, event = next(islice(sub_event_stream, idx))
                    if total_img is None:
                        total_img = img
                    else:
                        total_img += img
                yield chain([total_img], rest,
                            ['({}-{})'.format(*idxs), event])
            else:
                total_img = None
                for idx in idxs:
                    img, *rest, event = next(islice(sub_event_stream, idx))
                    if total_img is None:
                        total_img = img
                    else:
                        total_img += img
                yield chain([total_img], rest, ['[{}]'.format(
                    ','.join(map(str, idxs))), event])
