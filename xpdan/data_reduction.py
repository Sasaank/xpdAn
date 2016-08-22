#!/usr/bin/env python
##############################################################################
#
# xpdacq            by Billinge Group
#                   Simon J. L. Billinge sb2896@columbia.edu
#                   (c) 2016 trustees of Columbia University in the City of
#                        New York.
#                   All rights reserved
#
# File coded by:    Timothy Liu
#
# See AUTHORS.txt for a list of people who contributed.
# See LICENSE.txt for license information.
#
##############################################################################
#from dataportal import DataBroker as db
#from dataportal import get_events, get_table, get_images
#from metadatastore.commands import find_run_starts

import os
import warnings
import datetime
import yaml
import numpy as np
import tifffile as tif
import matplotlib as plt
from time import strftime
from unittest.mock import MagicMock

from .glbl import an_glbl
from .utils import _clean_info, _timestampstr

from pyFAI.azimuthalIntegrator import AzimuthalIntegrator

# top definition for minimal impacts on the code 
if an_glbl._is_simulation:
    db = MagicMock()
    get_events = MagicMock()
    get_images = MagicMock()
else:
    from databroker.databroker import get_table
    from databroker.databroker import DataBroker as db
    from databroker import get_images
    from databroker import get_events

w_dir = os.path.join(an_glbl.home, 'tiff_base')
W_DIR = w_dir # in case of crashes in old codes



class DataReduction:
    """ class that handle operations on images from databroker header

        Note: not a callback
    """
    def __init__(self, image_field=None):
        # for file name 
        self.fields = ['sample_name','sp_type', 'sp_requested_exposure']
        self.labels = ['dark_frame']
        self.data_fields = ['temperature']
        self.root_dir_name = 'sample_name'
        if image_field is None:
            self.image_field = an_glbl.det_image_field

    def _feature_gen(self, event):
        ''' generate a human readable file name.

        file name is generated by metadata information in event
        run_start
        '''
        feature_list = []
        run_start = event.descriptor['run_start']
        uid = run_start['uid'][:6]
        # get special label
        for el in self.labels:
                label = run_start.get(el, None)
                if label is not None:
                    feature_list.append(str(label))
                else:
                    pass
        # get fields
        for key in self.fields:
            el = str(run_start.get(key, None))
            if el is not None:
                # truncate string length
                if len(el) >12:
                    value = el[:12]
                # clear space
                feature = _clean_info(el)
                feature_list.append(feature)
            else:
                pass
        # get data fields
        for key in self.data_fields:
            val = event['data'].get(key, None)
            if el is not None:
                feature = "{}={}".format(key, val)
                feature_list.append(feature)
            else:
                pass
        # get uid
        feature_list.append(uid)
        return "_".join(feature_list)

    def pull_dark(self, header):
        dark_uid = header.start.get(an_glbl.dark_field_key, None)
        if dark_uid is None:
            print("INFO: no dark frame is associated in this header, "
                  "subrraction will not be processed")
            return None
        else:
            dark_search = {'group': 'XPD', 'uid': dark_uid}
            dark_header = db(**dark_search)
            dark_img = np.asarray(get_images(dark_header,
                                             self.image_field)).squeeze()
        return dark_img, dark_header[0].start.time

    def _dark_sub(self, event, dark_img):
        """ priviate method operates on event level """
        dark_sub = False
        img = event['data'][self.image_field]
        if dark_img is not None and isinstance(dark_img, np.ndarray):
            dark_sub = True
            img -= dark_img
        ind = event['seq_num']
        event_timestamp = event['timestamps'][self.image_field]
        return img, event_timestamp, ind, dark_sub

    def dark_sub(self, header):
        """ public method operates on header level """
        img_list = []
        timestamp_list = []
        dark_img, dark_time_stamp = self.pull_dark(header)
        for ev in get_events(header, fill=True):
            sub_img, timestamp, ind, dark_sub = self._dark_sub(ev, dark_img)
            img_list.append(sub_img)
            timestamp_list.append(timestamp)
        return img_list, timestamp_list, dark_img, header.start

    def _file_name(self, event, event_timestamp, ind):
        """ priviate method operates on event level """
        f_name = self._feature_gen(event)
        f_name = '_'.join([f_name,
                           _timestampstr(event_timestamp)])
        f_name = '{}_{:04d}.tif'.format(f_name, ind)
        return f_name


# init
xpd_data_proc = DataReduction()
ai = AzimuthalIntegrator()


### analysis function operates at header level ###
def _prepare_header_list(headers):
    if type(list(headers)[1]) == str:
        header_list = list()
        header_list.append(headers)
    else:
        header_list = headers
    return header_list

def _load_config():
    with open(os.path.join(an_glbl.config_base, an_glbl.calib_config_name)) as f:
        config_dict = yaml.load(f)
    return config_dict

def _npt_cal(config_dict):
    """ config_dict should be a PyFAI calibration dict """
    x_0, y_0 = (config_dict['centerX'], config_dict['centerY'])
    dist = np.sqrt((2048-x_0)**2 + (2048-y_0)**2)
    return dist

def pyFAI_integrate(headers, root_dir=None, config_dict=None,
                    handler=xpd_data_proc):
    """ integrate dark subtracted image for given list of headers

        Parameters
        ----------
        headers : list
            a list of header objects obtained from a query to dataBroker

        root_dir : str, optional
            path of chi files that are going to be saved. default is
            xpdUser/userAnalysis/

        config_dict : dict, optional
            dictionary stores integration parameters of pyFAI azimuthal
            integrator. default is the most recent parameters saved in
            xpdUser/conifg_base

        handler : instance of class, optional
            instance of class that handles data process, don't change it
            unless needed.
    """
    # normalize list
    header_list = _prepare_header_list(headers)

    # config_dict
    if config_dict is None:
        config_dict = _load_config() # default one
    ai.setPyFAI(**config_dict)
    npt = _npt_cal(config_dict)

    # iterate over header
    total_rv_list = []
    root_dir = an_glbl.usrAnalysis_dir
    for header in header_list:
        header_rv_list = []
        # dark logic
        dark_img = handler.pull_dark(header)
        #if not dark_sub:
        #    dark_img = None
        # event
        for event in get_events(header, fill=True):
            img, event_timestamp, ind, dark_sub = handler._dark_sub(event,
                                                                    dark_img)
            f_name = handler._file_name(event, event_timestamp, ind)
            if dark_sub:
                f_name = 'sub_' + f_name
            w_name = os.path.join(root_dir, f_name)
            integration_dict = {'filename':w_name,
                                'polarization_factor': 0.99}
            print("INFO: integrating image: {}".format(f_name))
            rv = ai.integrate1d(img, npt, **integration_dict)
            header_rv_list.append(rv)
            stem, ext = os.path.splitext(f_name)
            chi_name = stem + '.chi'
            print("INFO: save chi file: {}".format(chi_name))
            np.savetxt(w_name.replace('.tif', '.chi'), np.asarray(rv).T)
        total_rv_list.append(header_rv_list)
        # each header generate  a list of rv

    print(" *** {} *** ".format('Integration process finished'))

    print("INFO: chi files are saved at {}".format(root_dir))
    return total_rv_list


def pyFAI_integrate_last(root_dir=None, config_dict=None,
                               handler=xpd_data_proc):
    """ integrate dark subtracted image for given list of headers

        Parameters
        ----------
        root_dir : str, optional
            path of chi files that are going to be saved. default is
            xpdUser/userAnalysis/

        config_dict : dict, optional
            dictionary stores integration parameters of pyFAI azimuthal
            integrator. default is the most recent parameters saved in
            xpdUser/conifg_base

        handler : instance of class, optional
            instance of class that handles data process, don't change it
            unless needed.
    """
    pyFAI_integrate(db[-1], root_dir=root_dir,
                    config_dict=config_dict,
                    handler=handler)


def save_tiff(headers, dark_sub=True, max_count=None, dryrun=False,
              handler=xpd_data_proc):
    """ save images obtained from dataBroker as tiff format files.

    Parameters
    ----------
    headers : list
        a list of header objects obtained from a query to dataBroker

    dark_subtraction : bool, optional
        Default is True, which allows dark/background subtraction to 
        be done before saving each image. If header doesn't contain
        necessary information to perform dark subtraction, uncorrected
        image will be saved.

    max_count : int, optional
        The maximum number of events to process per-run.  This can be
        useful to 'preview' an export or if there are corrupted files
        in the data stream (ex from the IOC crashing during data
        acquisition).

    dryrun : bool, optional
        if set to True, file won't be saved. default is False

    handler : instance of class
        instance of class that handles data process, don't change it
        unless needed.
    """
    # normalize list
    header_list = _prepare_header_list(headers)

    for header in header_list:
        # create root_dir
        root = header.start.get(handler.root_dir_name, None)
        if root is not None:
            root_dir = os.path.join(W_DIR, root)
            os.makedirs(root_dir, exist_ok=True)
        else:
            root_dir = W_DIR
        # dark logic
        dark_img, dark_time = handler.pull_dark(header)
        if not dark_sub:
            dark_img = None # no sub
        # event
        for event in get_events(header, fill=True):
            img, event_timestamp, ind, dark_sub = handler._dark_sub(event,
                                                                    dark_img)
            f_name = handler._file_name(event, event_timestamp, ind)
            if dark_sub:
                f_name = 'sub_' + f_name
            # save tif
            w_name = os.path.join(root_dir, f_name)
            if not dryrun:
                tif.imsave(w_name, img)
                if os.path.isfile(w_name):
                    print('image "%s" has been saved at "%s"' %
                        (f_name, root_dir))
                else:
                    print('Sorry, something went wrong with your tif saving')
                    return
            # dryrun : print
            else:
                print("dryrun: image {} has been saved at {}"
                      .format(f_name, root_dir))
            if max_count is not None and ind >= max_count:
                # break the loop if max_count reached, move to next header
                break

        # save run_start
        stem, ext = os.path.splitext(w_name)
        config_name = w_name.replace(ext, '.yaml')
        with open(config_name, 'w') as f:
            #yaml.dump(header.start['sc_calibration_md'], f)
            yaml.dump(header.start, f) # save all md in start

    print(" *** {} *** ".format('Saving process finished'))

def save_last_tiff(dark_sub=True, max_count=None, dryrun=False):
    """ save images from the most recent scan as tiff format files.

    Parameters
    ----------
    dark_subtraction : bool, optional
        Default is True, which allows dark/background subtraction to 
        be done before saving each image. If header doesn't contain
        necessary information to perform dark subtraction, uncorrected
        image will be saved.

    max_count : int, optional
        The maximum number of events to process per-run.  This can be
        useful to 'preview' an export or if ithere are corrupted files
        in the data stream (ex from the IOC crashing during data acquisition).

    dryrun : bool, optional
        if set to True, file won't be saved. default is False
    """

    save_tiff(db[-1], dark_sub, max_count, dryrun)

