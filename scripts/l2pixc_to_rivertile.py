#!/usr/bin/env python
'''
This file is part of the SWOT Hydrology Toolbox
 Copyright (C) 2018 Centre National d’Etudes Spatiales
 This software is released under open source license LGPL v.3 and is distributed WITHOUT ANY WARRANTY, read LICENSE.txt for further details.


Government sponsorship acknowledged.
All rights reserved.

Author (s): Brent Williams

Modified version of processRiverVectors.py written originally by Alex Fore.
'''
import argparse
import glob
import netCDF4 as nc
import numpy as np
import os
import subprocess
import sys

import my_rdf
import cnes.modules.geoloc.lib.pixc_to_shp

from cnes.sas.lib import base_classes


def write_annotation_file(ann_file, 
                          pixc_file,
                          gdem_pixc,
                          pixcvec_file,
                          pixcvec_file_gdem = None):
    """
    write the river-annotation.rdf file so that lake processor can run
    """
    f = open(ann_file,'w')
    f.write("pixc file = %s\n"%pixc_file)
    f.write("gdem pixc file = %s\n"%gdem_pixc)
    f.write("pixcvec file = %s\n"%pixcvec_file)
    if pixcvec_file_gdem is not None:
        f.write("pixcvec file from gdem = %s\n"%pixcvec_file_gdem)
    f.close()


def make_pixc_from_gdem(gdem_file, pixc_file, out_file, subsample_factor=2):
    """
    create a pixel cloud file from a dem file, copying the 
    corresponding pixc attributes.  subsample_factor downsamples 
    in azimuth to make it smaller.
    gdem_file = input gdem
    pixc_file = corresponding pixc file to copy the attributed from
    out_file = output pixc file representing the gdem water-only pixels
    """

    # read in the gdem file
    print ('\n### making a pixc file from gdem ##\n')
    print ('reading gdem',gdem_file)
    with nc.Dataset(gdem_file, 'r') as ifp:
        # faster to read contiguous data then slice
        landtype = ifp.variables['landtype'][:]
        landtype = landtype[::subsample_factor,:]
        elevation = ifp.variables['elevation'][:]
        elevation = elevation[::subsample_factor,:]
        lat = ifp.variables['latitude'][:]
        lat = lat[::subsample_factor,:]
        lon = ifp.variables['longitude'][:]
        lon = lon[::subsample_factor,:]
        cross_track = ifp.variables['cross_track'][:]
        r_spacing = ifp.ground_spacing
        a_spacing = ifp.azimuth_spacing
        cycle_num = ifp.cycle_number
        pass_num = ifp.pass_number

    # create fake range and azimuth indices and dims
    A,R = np.shape(landtype)
    range_index, azimuth_index = np.meshgrid(np.arange(R), np.arange(A))
    cross_track, azimuth_index = np.meshgrid(cross_track, np.arange(A))
    # get only water pixels (assumes that water is value 1 in gdem)
    classif = landtype[landtype==1] # map to interior water class
    elevation = elevation[landtype==1]
    lat = lat[landtype==1]
    lon = lon[landtype==1]
    cross_track = cross_track[landtype==1]
    range_index = range_index[landtype==1]
    azimuth_index = azimuth_index[landtype==1]
    # make the pixel cloud object and assign desired data fields
    pixc = base_classes.PixelCloud()
    pixc_in = base_classes.PixelCloud()
    print ("loading pixc attributes",pixc_file)
    pixc_in = base_classes.PixelCloud.from_ncfile(pixc_file,force=True) #variables=[])
    print ("pixc_in.tile_ref",pixc_in.tile_ref)
    pixc.copy_attributes(pixc_in)
    # replace global attributes
    pixc.description = 'gdem water pixels repacked as a pixel cloud'
    pixc.nr_pixels = R
    pixc.nr_lines = A
    # replace this incase we want to acess it later
    pixc.num_rare_looks = subsample_factor
    # set variables
    pixc.classification = classif*0 + 4 # remap all to interior water
    pixc.continuous_classification = classif*0+1.0 #remap to 1
    pixc.height = elevation
    pixc.latitude = lat
    pixc.longitude = lon
    pixc.pixel_area = np.zeros(np.shape(lat)) + r_spacing * a_spacing * subsample_factor
    pixc.cross_track = cross_track
    pixc.range_index = range_index
    pixc.azimuth_index = azimuth_index
    pixc.illumination_time = azimuth_index
    pixc.num_rare_looks = np.zeros(np.shape(azimuth_index))+subsample_factor
    # split filename from dir path
    pth, out_name = os.path.split(out_file)
    out_path = os.path.abspath(pth)
    print ("writting output gdem pixc file:",out_name)
    print ("to path:",out_path)
    pixc.to_ncfile(out_name,out_path)


#######################################
    

def execute(cmd):
    with subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, bufsize=1, universal_newlines=True) as p:
        for line in p.stdout:
            print(line, end='') # process line here

    if p.returncode != 0:
        raise subprocess.CalledProcessError(p.returncode, p.args)


def main():
    """When run as a script"""
    parser = argparse.ArgumentParser()
    parser.add_argument('l2pixc_annotation_file', help="PixC annotation file", type=str)
    parser.add_argument('output_dir', help="output directory", type=str)
    parser.add_argument('parameter_riverobs', help="param file for RiverObs", type=str)
    parser.add_argument('--riverobs_path', help="full path to RiverObs software (if not in os.environ)", type=str)
    parser.add_argument("--nogdem", 
        help="if true, don't call riverobs with gdem", 
        nargs='?', type=bool, default=False, const=True)
    parser.add_argument("--noshp", 
        help="if true, don't produce shapefiles", 
        nargs='?', type=bool, default=False, const=True)
    parser.add_argument(
        '-f', '--force', action='store_true', dest='force', default=False,
        help='force overwrite existing outputs; default is to quit')
    args = vars(parser.parse_args())

    print("===== l2pixc_to_rivertile = BEGIN =====")
    print("")

    # Load rdf files
    if os.path.isfile(args['l2pixc_annotation_file']):
        # Unite file case
        rdf_files = glob.glob(args['l2pixc_annotation_file'])
    else:
        # multi files case
        rdf_files = glob.glob(os.path.join(args['l2pixc_annotation_file'],"*.rdf"))
    if len(rdf_files) == 0:
        print("> NO PixC annotation file to deal with")
    else:
        print("> %d PixC annotation file(s) to deal with" % len(rdf_files))
    print()
   
    for pixc_ann_file in rdf_files:
        
        print("> Dealing with PixC annotation file %s" % pixc_ann_file)
        
        # Open and read RDF file
        rdf = my_rdf.myRdfReader(os.path.abspath(pixc_ann_file))
        ann_cfg = rdf.parameters
        
        # Get value of orbit cycle, orbit number and latitude tile coordinates
        pixc_ann_split = os.path.basename(pixc_ann_file).split(".")[0].split("_")
        num_cycle = pixc_ann_split[2]
        num_orbit = pixc_ann_split[3]
        lat_tile = pixc_ann_split[4]
        print("Cycle number = %s - Orbit number = %s - Tile ref = %s" % (num_cycle, num_orbit, lat_tile))
        print()
        
        #~ ann_cfg = rdf.parse(
            #~ os.path.abspath(args['l2pixc_annotation_file']), comment='!')
    
        # Clone the tail of proc directory structure
        river_dir = os.path.abspath(os.path.join(args['output_dir'], 'pixc'))
        if not os.path.isdir(river_dir):
            os.makedirs(river_dir)
        if not args['nogdem']:
            river_dir_gdem = os.path.join(args['output_dir'], 'gdem')
            if not os.path.isdir(river_dir_gdem):
                os.makedirs(river_dir_gdem)
    
        # Prepare args for l2pixc_to_rivertile.py
        # File path
        pixc_file = os.path.abspath(ann_cfg['l2pixc file'])
        output_riverobs = os.path.join(river_dir, "rivertile_" + num_cycle + "_" + num_orbit + "_" + lat_tile + ".nc")
        output_pixcvec = os.path.join(river_dir, "pixcvec_" + num_cycle + "_" + num_orbit + "_" + lat_tile + ".nc")
        river_ann_file = os.path.join(args['output_dir'],'river-annotation_' + num_cycle + '_' + num_orbit + '_' + lat_tile + '.rdf')
        # Specific cases
        output_riverobs_gdem = None
        output_pixcvec_gdem = None
        gdem_pixc = None
        if args['nogdem']:  # No GDEM option set
            if (not args['force'] and
                os.path.isfile(output_riverobs) and
                os.path.isfile(output_pixcvec)):  # No force option set and output files already exist
                    print("--> Output files already exist; EXIT")
                    return
        else:
            
            # Output files
            output_riverobs_gdem = os.path.join(river_dir_gdem, "rivertile_" + num_cycle + "_" + num_orbit + "_" + lat_tile + ".nc")
            output_pixcvec_gdem = os.path.join(river_dir_gdem, "pixcvec_" + num_cycle + "_" + num_orbit + "_" + lat_tile + ".nc")
            if (not args['force'] and
                os.path.isfile(output_riverobs) and
                os.path.isfile(output_pixcvec)):
                    print("--> Output files already exist; EXIT")
                    return
    
            # PixC GDEM output file
            gdem_pixc = os.path.join(river_dir_gdem,'pixel_cloud_gdem' + num_cycle + '-' + num_orbit + '_' + lat_tile + '.nc')
            print(ann_cfg['true GDEM file'])
            make_pixc_from_gdem(
                ann_cfg['true GDEM file'],
                pixc_file,
                gdem_pixc,
                subsample_factor=2)
    
        # check to see if need a different prior river database file 
        # (NA,EU only handled) 
        
        #~ if float(param_rdf.getValue('lonmin')) > 0:
            #~ print ('assuming european river databse')
            #~ riv_db_name = cfg['shape_file_root']
            #~ riv_db_name = riv_db_name.replace('NA_reaches','EU_reaches')
            #~ riv_db_name = riv_db_name.replace(
                #~ 'grdc_revised','grdc_below60N_revised')
            #~ cfg['shape_file_root'] = riv_db_name
            #~ estimate_swot_river_gdem_cfg['shape_file_root'] = riv_db_name
    
    
        # this is for if we want to run estimate_swot_river.py on the 2D gdem (not the pixel cloud gdem)
        #~ if not args["nogdem"]:
            #~ estimate_swot_river_gdem_cfg.tofile(os.path.join(river_dir_gdem, "estimate_swot_river.rdf"))
    
        # setup to process with the sas
        # write out the config
        #~ cfg_file = os.path.join(river_dir, "rivertile.rdf")
        #~ # replace filenames with the ones that they will be replaced by in the sas
        #~ cfg['l2_file'] = pixc_file
        #~ cfg['fout_reach'] = output_riverobs
        #~ cfg['fout_node'] = output_riverobs
        #~ cfg['fout_index'] = output_pixcvec
        #~ cfg.tofile(cfg_file)
    
        # Make rivertile sas with pixelcloud
        # Path to RiverObs
        if args['riverobs_path'] is not None:
            path_to_riverobs = args['riverobs_path']
        else:
            path_to_riverobs = os.environ['RIVEROBS']
        # Build RiverObs main lib
        prog_name = os.path.join(
            path_to_riverobs,
            'src','bin','swot_pixc2rivertile.py')
        # Build command
        cmd = "{} {} {} {} {}".format(prog_name,
                                         pixc_file,
                                         output_riverobs,
                                         output_pixcvec,
                                         os.path.abspath(args['parameter_riverobs']))
        # Excute command
        print ("> executing:", cmd) 
        #subprocess.check_call(cmd, shell=True)
        execute(cmd)
        print("== Execution OK")
        print()
    
        # run processing for pixel-cloud-ised gdem
        #~ if not args["nogdem"]:
            #~ # first read in the pixc rdf and use it as the gdem one
            #~ gdem_cfg = rdf.parse(cfg_file, comment='!')
            #~ gdem_cfg['do_improved_geolocation'] = False
            #~ # write out the config
            #~ cfg_gdem_file = os.path.join(river_dir_gdem, "rivertile.rdf")
            #~ # replace filenames with the ones that they will be replaced by in the sas
            #~ gdem_cfg['l2_file'] = gdem_pixc
            #~ gdem_cfg['fout_reach'] = output_riverobs_gdem
            #~ gdem_cfg['fout_node'] = output_riverobs_gdem
            #~ gdem_cfg['fout_index'] = output_pixcvec_gdem
            #~ gdem_cfg.tofile(cfg_file)
            #~ gdem_cfg.tofile(cfg_gdem_file)
            #~ # Make river tile with gdem-pixel cloud
            #~ cmd = "{} {} {} {} {} {}".format(prog_name,
                                             #~ gdem_pixc,
                                             #~ output_riverobs_gdem,
                                             #~ output_pixcvec_gdem,
                                             #~ cfg_gdem_file)
            #~ print ("executing:",cmd)
            #~ subprocess.check_call(cmd, shell=True)
    
    
        # Make the desired shape files
        if not args["noshp"]:
            print("> Converting .nc files to shapefiles...")
            pixcvec_vars = ["height_vectorproc", 
                           "node_index", 
                           "reach_index", 
                           "azimuth_index", 
                           "range_index"]
            node_vars = ["time", 
                         "height",
                         "width", 
                         "area_total",    
                         "node_id", 
                         "reach_id"]
            reach_vars = ["reach_id","width","height","slope","area_total"]
            
            # write node shape file
            print(". Node shapefile")
            cnes.modules.geoloc.lib.pixc_to_shp.pixc_to_shp(
                output_riverobs, 
                output_riverobs.replace(".nc","_node.shp"), 
                "latitude", "longitude", node_vars, group_name="nodes")
            
            # write reach shape file
            print(". Reach shapefile")
            cnes.modules.geoloc.lib.pixc_to_shp.pixc_to_shp(
                output_riverobs, 
                output_riverobs.replace(".nc","_reach.shp"), 
                "p_latitud", "p_longitud", reach_vars, group_name="reaches")
            
            # write pixcvec shape file
            print(". PIXCVec shapefile")
            cnes.modules.geoloc.lib.pixc_to_shp.pixc_to_shp(
                output_pixcvec, 
                output_pixcvec.replace(".nc",".shp"), 
                "latitude_vectorproc", "longitude_vectorproc", 
                pixcvec_vars, group_name=None)
    
            #~ if not args['nogdem']:
                #~ # write gdem node shape file
                #~ cnes.modules.geoloc.lib.pixc_to_shp.pixc_to_shp(
                    #~ output_riverobs_gdem, 
                    #~ output_riverobs_gdem.replace(".nc","_node.shp"), 
                    #~ "lat", "lon", node_vars, group_name="nodes")
                #~ # write gdem reach shape file
                #~ cnes.modules.geoloc.lib.pixc_to_shp.pixc_to_shp(
                    #~ output_riverobs_gdem, 
                    #~ output_riverobs_gdem.replace(".nc","_reach.shp"), 
                    #~ "lat_min", "lon_min", reach_vars, group_name="reaches")
                #~ # write gdem pixcvec shape file
                #~ cnes.modules.geoloc.lib.pixc_to_shp.pixc_to_shp(
                    #~ output_pixcvec_gdem, 
                    #~ output_pixcvec_gdem.replace(".nc",".shp"), 
                    #~ "latitude_vectorproc", "longitude_vectorproc", 
                    #~ pixcvec_vars, group_name=None)
    
        # write annotation file(s)
        
        
        write_annotation_file(
            river_ann_file, 
            pixc_file,
            gdem_pixc,
            output_pixcvec,  
            output_pixcvec_gdem)

    print("")
    print("===== l2pixc_to_rivertile = END =====")


#######################################


if __name__ == "__main__":
    main()
