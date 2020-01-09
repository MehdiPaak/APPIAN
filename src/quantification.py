from nipype.interfaces.utility import Function
from nipype.interfaces.base import TraitedSpec, File, traits, InputMultiPath, BaseInterface, OutputMultiPath, BaseInterfaceInputSpec, isdefined
from nipype.utils.filemanip import load_json, save_json, split_filename, fname_presuffix, copyfile
from scipy.interpolate import interp1d
from scipy.integrate import simps
from src.utils import splitext
import nipype.pipeline.engine as pe
import nipype.interfaces.io as nio
import nipype.interfaces.utility as niu
import nipype.algorithms.misc as misc
import nibabel as nib
import pandas as pd
import ntpath
import numpy as np
import os
import re
import importlib
import sys
import json

"""
.. module:: quant
    :platform: Unix
    :synopsis: Module to perform for PET quantification 
    
"""
### Quantification models 


def patlak_plot(vol,  int_vol, ref, int_ref, time_frames, opts={}):
    n_frames = len(time_frames)
    start_time = opts["quant_start_time"]
    dim = list(vol.shape)
    
    x = int_vol * (1./ vol)  
    x[np.isnan(x) | np.isinf(x) ] = 0.
    del int_ref

    y = ref * (1./ vol)
    y[np.isnan(y) | np.isinf(y) ] = 0.

    regr_start = np.sum(start_time > np.array(time_frames)) 
    x = x[:, regr_start:n_frames]
    y = y[:, regr_start:n_frames]
    del vol     
    del int_vol
    n_frames -= regr_start

    ki = np.array(map(slope,x,y)) 

    return ki


def logan_plot(vol,  int_vol, ref, int_ref, time_frames, opts={}, roi_based=False ):
    n_frames = len(time_frames)
    start_time = opts["quant_start_time"]
    dim = list(vol.shape)

    x = int_ref * 1.0/vol #[brain_mask]    
    x[np.isnan(x) | np.isinf(x) ] = 0.
    if not roi_based:
        del int_ref

    y = int_vol * 1.0/ vol # [brain_mask]
    y[np.isnan(y) | np.isinf(y) ] = 0.

    '''
    df = None
    if roi_based == True:
        pet_vol_list = [{'roi-'+str(i):vol[i]} for i in  range(vol.shape[0])  ]
        int_vol_list = [{'int-roi-'+str(i):int_vol[i]} for i in range(int_vol.shape[0])  ]
        ref_tac_list = [{'ref-'+str(i):ref[i]} for i in range(ref.shape[0])  ]
        int_ref_list = [{'int-ref-'+str(i):int_ref[i]} for i in range(int_ref.shape[0])  ]
        x_list = [{'x-'+str(i):x[i]} for i in range(x.shape[0]) ]
        y_list = [{'y-'+str(i):y[i]} for i in range(y.shape[0]) ]

        df_dict = {'frames':time_frames}
        for item in pet_vol_list + int_vol_list + ref_tac_list + int_ref_list +x_list +y_list:
            df_dict.update(item)
            df = pd.DataFrame( df_dict )
        print(df)
    '''

    regr_start = np.sum(start_time >= np.array(time_frames)) 
    print("Start frame (counting from 0):", regr_start)
    x = x[:, regr_start:]
    y = y[:, regr_start:]
    del vol     
    del int_vol
    n_frames -= regr_start

    dvr = np.array(list(map(slope,x,y))) 
        
    if opts["quant_DVR"] :
        out = dvr
    else :
        out = dvr - 1 #BPnd
    print(out)
    return out

def suv(vol, brain_mask, int_vol, int_ref, time_frames, opts):
    pass

def suvr(vol, brain_mask, int_vol, int_ref, time_frames, opts):
    pass

from scipy.stats import linregress
global model_dict
model_dict={'pp':patlak_plot, 'lp':logan_plot,  'suv':suv, 'suvr':suvr}


def slope(x,y):
    return linregress(x,y)[0]
### Helper functions 

def regr(x,y,tac_len, n_frames):
    #x_mean = np.mean( x, axis=1)
    #y_mean = np.mean( y, axis=1)
    #x_mean = np.repeat(x_mean, n_frames).reshape( [tac_len]+[-1] )
    #y_mean = np.repeat(y_mean, n_frames).reshape( [tac_len]+[-1] )
    print(list(map(slope, x, y)))
    return (n_frames * np.sum(x*y,axis=1) - np.sum(x,axis=1)*np.sum(y,axis=1)) /  (n_frames * np.sum(x**2,axis=1) - np.sum(x,axis=1)**2)

    xx = x - x_mean 
    print(xx)
    del x
    del x_mean
    yy = y - y_mean
    print(yy)
    del y_mean
    del y

    return np.sum(xx*yy, axis=1) / np.sum( xx**2, axis=1 )

def integrate_tac(vol, time_frames):
    int_vol = np.zeros(vol.shape).astype('f4')
    for t in range(1,len(time_frames)) :
        integrated = simps( vol[:,0:t], time_frames[0:t], axis=1)
        int_vol[:,t] = integrated

    return int_vol

def read_arterial_file(arterial_file) :
    ref_times = []
    ref_tac = []
    with open(arterial_file, 'r') as f:
        for i, l in enumerate(f.readlines()) :
            if i >= 4 :
                lsplit = l.split(' ')
                stime = float(lsplit[0])
                etime = float(lsplit[1])
                
                activity = float(lsplit[2])
                ref_times += [ (stime + etime) / 2. ]
                ref_tac += [ activity ]
                
    return ref_times, ref_tac
    
def get_reference(pet_vol, brain_mask_vol, ref_file, time_frames, arterial_file=None):
    ref_tac = np.zeros([1,len(time_frames)])
    ref_times = np.zeros(len(time_frames))
    
    if isdefined(arterial_file) and arterial_file != None : 
        '''read arterial input file'''
        art_times, art_tac = read_arterial_file(arterial_file)
        vol_times = np.array([ (t[0]+t[1]) / 2.0 for f in time_frames ])
        f = interp1d(art_times, art_tac, kind='cubic')
        ref_tac = f(vol_times)

    elif isdefined(ref_file) and  ref_file != None :
        ref_img = nib.load(ref_file)
        ref_vol = ref_img.get_data()
        ref_vol = ref_vol.reshape(np.product(ref_vol.shape), -1) 
        ref_vol = ref_vol[brain_mask_vol]
        for t in range(len(time_frames)) :
            frame = pet_vol[:,t]
            frame = frame.reshape( list(frame.shape)+[1] )
            ref_tac[0,t] = np.mean(frame[ ref_vol != 0 ])
    else :
        print('Error: no arterial file or reference volume file')
        exit(1)
    
    return  ref_tac

def get_roi_tac(roi_file,pet_vol,brain_mask_vol, time_frames ):
    roi_img = nib.load(roi_file)
    roi_vol = roi_img.get_data()
    roi_vol = roi_vol.reshape(roi_vol.shape[0:3])
    roi_vol = roi_vol.reshape(-1,)
    roi_vol = roi_vol[brain_mask_vol]

    unique_roi = np.unique(roi_vol)[1:]
    roi_tac = np.zeros( (len(unique_roi), len(time_frames)) )
    for t in range(len(time_frames)) :
        for i, roi in enumerate(unique_roi):
            frame = pet_vol[:,t]
            roi_tac[i][t] = np.mean(frame[roi_vol == roi])
    del pet_vol
    return roi_tac


def create_output_array(dims,  roi_based, quant_vol, roi_file, brain_mask_vol ):
    roi_img = nib.load(roi_file)
    roi_vol = roi_img.get_data().reshape(-1,)
    n3d=np.product(dims[0:3]) 
    n_frames=dims[3]
    unique_roi=np.unique(roi_vol)[1:]
    
    ar = np.zeros([n3d] )
    
    if  roi_based == True :
        for t in range(n_frames) :
            for label, value in enumerate(unique_roi) : 
                ar[ roi_vol == value ] = quant_vol[label]
        
    else : 
        ar[ brain_mask_vol ] = quant_vol
    ar = ar.reshape(dims[0:3])
    return ar

### Class Node for doing quantification

class ApplyModelOutput(TraitedSpec):  
    out_file = File(desc="Reconstruced 3D image based on .dft ROI values")
    out_df = File(desc="Reconstruced 3D image based on .dft ROI values")

class ApplyModelInput(TraitedSpec):
    out_file = File(desc="Reconstruced 3D image based on .dft ROI values")
    out_df = File(desc="Reconstruced 3D image based on .dft ROI values")
    pet_file = File(exists=True, mandatory=True, desc=" .dft ROI values")
    header_file = File(exists=True, mandatory=True, desc=" .dft ROI values")
    brain_mask_file = File( desc=" .dft ROI values") #,default_value=None, usedefault=True)
    reference_file = File(mandatory=True, desc=" .dft ROI values") #, usedefault=True, default_value=None)
    roi_file = File( desc=" .dft ROI values") #, usedefault=True, default_value=None)
    arterial_file = File( desc=" .dft ROI values")
    quant_method = traits.Str(mandatory=True)
    roi_based = traits.Bool(mandatory=False)
    opts = traits.Dict(mandatory=True)


class ApplyModel(BaseInterface) :
    input_spec = ApplyModelInput
    output_spec = ApplyModelOutput

    def _run_interface(self, runtime) :
        pet_file = self.inputs.pet_file
        ref_file = self.inputs.reference_file
        header_file = self.inputs.header_file
        arterial_file = self.inputs.arterial_file
        brain_mask_file = self.inputs.brain_mask_file
        roi_file = self.inputs.roi_file
        opts = self.inputs.opts
        if not isdefined(self.inputs.out_file) :
            self.inputs.out_file = self._gen_output()
        
        if not isdefined(self.inputs.out_df) and self.inputs.roi_based == True:
            self.inputs.out_df = os.getcwd() + os.sep + self.inputs.quant_method+".csv" 

        pet_img = nib.load(pet_file)
        pet_vol = pet_img.get_data().astype('f4')
        print(pet_vol.shape)
        dims = pet_vol.shape
        n3d=np.product(pet_vol.shape[0:3])
        pet_vol = pet_vol.reshape([n3d]+[pet_vol.shape[3]])
       
        brain_mask_img = nib.load(brain_mask_file)
        brain_mask_vol = brain_mask_img.get_data().astype(bool)
        print(brain_mask_vol.shape)
        brain_mask_vol = brain_mask_vol.reshape(-1,)
        pet_vol = pet_vol[ brain_mask_vol, :  ]
        
        model = model_dict[self.inputs.quant_method]
        header = json.load(open(header_file, "r") )
        time_frames = [ (float(s) + float(e)) / 3. for s,e in  header['Time']["FrameTimes"]["Values"] ]
        n_frames=len(time_frames)
        
        ref_tac = get_reference(pet_vol, brain_mask_vol, ref_file, time_frames, arterial_file)

        if  self.inputs.roi_based == True :
            pet_vol = get_roi_tac(roi_file, pet_vol, brain_mask_vol, time_frames )
        
        int_vol = integrate_tac(pet_vol, time_frames)
        int_ref = integrate_tac(ref_tac, time_frames)

        quant_vol = model(pet_vol, int_vol, ref_tac, int_ref, time_frames, opts=opts, roi_based=self.inputs.roi_based)
        
        out_ar = create_output_array(dims, self.inputs.roi_based, quant_vol, roi_file, brain_mask_vol )

        print(self.inputs.out_file)
        nib.Nifti1Image(out_ar, pet_img.affine).to_filename(self.inputs.out_file)
        
        return runtime

    def _list_outputs(self):
        outputs = self.output_spec().get()
        if not isdefined(self.inputs.out_file) :
            self.inputs.out_file = self._gen_output()
        if not isdefined(self.inputs.out_df) and self.inputs.roi_based :
            self.inputs.out_df = os.getcwd() + os.sep + self.inputs.quant_method+".csv" 

        outputs["out_file"] = self.inputs.out_file
        outputs["out_df"] = self.inputs.out_df
        return outputs

    def _gen_output(self):
        fname = ntpath.basename(self.inputs.pet_file)
        fname_list = splitext(fname) # [0]= base filename; [1] =extension
        dname = os.getcwd() 
        kind='vxl'
        if self.inputs.roi_based == True :
            kind = 'roi'
        return dname+ os.sep+fname_list[0] +'_quant-'+kind+'-'+ self.inputs.quant_method +'.nii.gz'


