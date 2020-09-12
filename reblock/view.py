import typing 

import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon, MultiLineString, Point, LineString
from shapely.ops import cascaded_union
from shapely.wkt import loads
import pandas as pd
import geopandas as gpd 
import numpy as np 
import time 

import os 
import matplotlib.pyplot as plt 
import sys 

import argparse
import igraph

import i_topology_utils
from i_topology import *
import time 

from pathlib import Path  
from shapely.wkt import loads 
import ast 

DATA = Path("../data")
REBLOCK = DATA / "reblock"
REBLOCK_VIEWIING = DATA / 'reblock_viewing'
sys.path.insert(0, "../")
from data_processing import process_worldpop
sys.path.insert(0, "../analysis")
import aoi_analysis

# region = "Africa"
# gadm_code = "SLE"
# gadm = "SLE.4.2.1_1"
# example_block = "SLE.4.2.1_1_1241"

# REBLOCK = "../data/reblock/Africa/LBR"

# # (1) Just load our data for one GADM
# print("Begin loading of data")
# blocks = i_topology_utils.csv_to_geo(os.path.join("../data", "blocks", region, gadm_code, "blocks_"+gadm+".csv"))

# # # (2) Now build the parcel graph and prep the buildings
# # # restrict to some example blocks within the GADM
# block = blocks[blocks['block_id']==example_block]

# steiner = gpd.read_file("test_SLE_igraph/steiner_lines.geojson")
# terminal = gpd.read_file("test_SLE_igraph/terminal_points.geojson")

# Bokeh import 
from bokeh.plotting import figure, save
from bokeh.models import GeoJSONDataSource, ColumnDataSource, HoverTool, LinearColorMapper
from bokeh.palettes import RdYlBu11, RdYlGn11, Viridis11
from bokeh.io import output_notebook, output_file, show 

MNP = ["#0571b0", "#f7f7f7", "#f4a582", "#cc0022"]
#MNP = ["#cc0022", "#f4a582", "#f7f7f7", "#0571b0"]
PALETTE = MNP
#RANGE = [(0,1), (2,3), (4,7), (8, np.inf)]
RANGE = [1, 3, 7, np.inf]
RANGE_LABEL = ['high', 'medium', 'low', 'very low']
MATCHED = ['high (<=1)', 'medium (<=3)', 'low (<=7)', 'very low (<=inf)']
for upper, label in zip(RANGE, RANGE_LABEL):
    stub = " (<={})".format(upper)
    MATCHED += (label + stub)

def get_range(complexity):
    for upper, label in zip(RANGE, RANGE_LABEL):
        if complexity <= upper:
            stub = " (<={})".format(upper)
            return label + stub 

def get_point_coords(point, coord_type):
    """Calculates coordinates ('x' or 'y') of a Point geometry"""
    if coord_type == 'x':
        return point.x
    elif coord_type == 'y':
        return point.y

def get_line_coords(line, coord_type):
    """Calculates coordinates ('x' or 'y') of a Point geometry"""
    if coord_type == 'x':
        return list(line.coords.xy[0])
    elif coord_type == 'y':
        return list(line.coords.xy[1])

def get_polygon_coords(polygon, coord_type):
    """Calculates coordinates ('x' or 'y') of a Point geometry"""
    if coord_type == 'x':
        return list(polygon.exterior.coords.xy[0])
    elif coord_type == 'y':
        return list(polygon.exterior.coords.xy[1])

def get_multipolygon_coords(multipolygon, coord_type):
    rv = []
    if multipolygon is None:
        return None 
    for poly in multipolygon:
        if coord_type == 'x':
            rv += get_polygon_coords(poly, 'x')
        else:
            rv += get_polygon_coords(poly, 'y')
    return rv 
  
def make_bokeh(complexity_df, output_filename=None, plot_height=800, plot_width=1600, bldg_alpha=0.3,
               add_reblock=False, region=None, add_avg_building_size=False):
    # c is a complexity geodataframe
    # (1) Process the data sources

    if output_filename is not None:
        output_file(output_filename.split(".")[0])
    cols = ['block_id', 'bldg_count', 'block_area_km2', 'complexity', 'bldg_density', 'total_bldg_area_sq_km']

    # 1.a -- define blocks
    df_blocks = complexity_df[cols].copy()
    #print("df blocks CRS = {}".format(df_blocks.crs))
    g = complexity_df['geometry'].to_crs({'init': 'epsg:3395'})
    df_blocks['x'] = g.apply(lambda p: get_polygon_coords(p, 'x'))
    df_blocks['y'] = g.apply(lambda p: get_polygon_coords(p, 'y'))

    # Added 
    df_blocks['avg_bldg_area_m2'] = 1e6 * df_blocks['total_bldg_area_sq_km'] / df_blocks['bldg_count']

    # 1.b -- define hover tool
    my_hover = HoverTool()
    cols_in_hover = ['block_id', 'complexity', 'bldg_count', 'block_area_km2', 'bldg_density']
    cols_label =    ['Block ID', 'Complexity', 'Building count', 'Block area (km2)', 'Density']

    if add_avg_building_size:
        cols_in_hover.extend(['bldg_area_m2', 'avg_bldg_area_m2'])
        cols_label.extend(['Building area (m2)', 'Avg building area (m2)'])
    my_hover.tooltips = [(l, "@"+c) for l,c in zip(cols_label, cols_in_hover)]

    # 1.c -- define buildings
    df_buildings = ComplexityViewer.make_building_geom(complexity_df)
    missing = df_buildings['geometry'].isna()
    df_buildings = df_buildings.loc[~missing]
    df_buildings = df_buildings.explode()
    df_buildings['geometry'].crs = {'init': 'epsg:4326'}
    df_buildings.crs = {'init': 'epsg:4326'}
    df_buildings['geometry'] = df_buildings['geometry'].to_crs({'init': 'epsg:3395'})
    df_buildings['x'] = df_buildings['geometry'].apply(lambda p: get_polygon_coords(p, 'x'))
    df_buildings['y'] = df_buildings['geometry'].apply(lambda p: get_polygon_coords(p, 'y'))

    # Added
    df_buildings['bldg_area_m2'] = df_buildings['geometry'].area 
    df_buildings_no_geom = df_buildings.drop(columns=['geometry'])

    
    df_blocks['compl_label'] = df_blocks['complexity'].apply(get_range)
    
    # (2) Make the fig
    fig = figure(border_fill_color='blue', border_fill_alpha=0.25, match_aspect=True, aspect_scale=1.0,
                 plot_height=plot_height, plot_width=plot_width, x_axis_type="mercator", y_axis_type="mercator")

    # 2.a -- add the tools
    fig.add_tools(my_hover)

    # (3) Assemble the plot
    #color_mapper = LinearColorMapper(palette=PALETTE)
    #source_df_blocks = ColumnDataSource(df_blocks)
    #fig.patches('x', 'y', fill_color={'field': 'complexity', 'transform':color_mapper}, source=source_df_blocks)

    # Legend plot of blocks
    labels = MATCHED
    for label, color in zip(labels, MNP):
        cur_df = df_blocks.loc[df_blocks['compl_label']==label]
        cur_source = ColumnDataSource(cur_df)

        fig.patches('x', 'y', fill_color=color, source=cur_source, legend=label)
        #fig.patches('x', 'y', fill_color=color, source=cur_source)

    # Legend plot of buildings
    #source_df_buildings = ColumnDataSource(df_buildings_no_geom)
    df_buildings_no_geom['compl_label'] = df_buildings_no_geom['complexity'].apply(get_range)
    for label, color in zip(labels, MNP):
        cur_df = df_buildings_no_geom.loc[df_buildings_no_geom['compl_label']==label]
        cur_source = ColumnDataSource(cur_df)
        fig.patches('x', 'y', line_alpha=0, fill_color='black', fill_alpha=bldg_alpha, source=cur_source, legend=label)

    # Add reblocking. NOTE, only works for a single block currently
    if add_reblock:
        assert region is not None, "If adding reblock need to include region ex. 'Africa'"
        cur_block = df_blocks['block_id'].iloc[0]
        cur_gadm = cur_block[0:cur_block.rfind("_")]
        country_code = cur_block[0:3]

        reblock_path = REBLOCK / region / country_code / "steiner_lines_{}.csv".format(cur_gadm)
        reblock = read_steiner(reblock_path)
        is_block = reblock['block']==cur_block
        if is_block.sum() == 0:
            print("Block {} does not have reblocking yet".format(cur_block))
            new_road_length = None 
             
        else:
            cur_complexity = df_blocks[df_blocks['block_id']==cur_block].iloc[0]['complexity']
            new_road_length = 0
            if cur_complexity > 2:           
                cur_reblock = reblock.loc[is_block]
                cur_reblock = cur_reblock.explode()
                #cur_reblock['geometry'].crs =  {'init': 'epsg:4326'}
                is_new = cur_reblock['line_type']=='new_steiner'
                cur_reblock = cur_reblock.loc[is_new]
                #cur_reblock.crs =  {'init': 'epsg:4326'}
                cur_reblock['geometry'] = cur_reblock['geometry'].to_crs({'init': 'epsg:3395'})
                #print("crs = {}".format(cur_reblock.crs))
                cur_reblock['x'] = cur_reblock['geometry'].apply(lambda geom: get_line_coords(geom, 'x'))
                cur_reblock['y'] = cur_reblock['geometry'].apply(lambda geom: get_line_coords(geom, 'y'))
                # print("type x = {}".format(cur_reblock['x'].iloc[0]))
                # print("type y = {}".format(cur_reblock['y'].iloc[0]))

                temp_df = cur_reblock.drop(columns=['geometry', 'block', 'block_w_type'])
                cur_reblock_source = ColumnDataSource(temp_df)
                line_width = 2
                fig.multi_line('x', 'y', line_color='green', line_width=line_width, source=cur_reblock_source)
                new_road_length = int(np.round(cur_reblock['geometry'].length.sum()))
            else:
                new_road_length = 0
    else:
        new_road_length = None 

    if output_filename is None:
        fig.legend.visible = False 
        print("New road length = {}".format(new_road_length))
        return [fig, new_road_length] 
    else:
        fig.legend.location = "top_left"
        fig.legend.click_policy="hide"
        save(fig, output_filename)
    #show(fig)

# MNP = ["#0571b0", "#f7f7f7", "#f4a582", "#cc0022"]
# PALETTE = MNP
# #RANGE = [(0,1), (2,3), (4,7), (8, np.inf)]
# RANGE = [1, 3, 7, np.inf]
# RANGE_LABEL = ['high', 'medium', 'low', 'very low']

def convert_buildings_OLD(bldg_obs):
    '''
    Converts the literal string repr list of wkt format
    to multipolygons
    '''

    try:
        bldg_list = ast.literal_eval(bldg_obs)
        bldgs = [loads(x) for x in bldg_list]
        return MultiPolygon(bldgs)
    except:
        return None 

def convert_buildings(bldg_obs):
    '''
    Converts the literal string repr list of wkt format
    to multipolygons
    '''
    try:
        bldg_list = ast.literal_eval(bldg_obs)
        bldgs = []
        for b in bldg_list:
            b_shape = loads(b)
            if isinstance(b_shape, Polygon):
                bldgs.append(b_shape)
            elif isinstance(b_shape, MultiPolygon):
                for subpoly in b_shape:
                    bldgs.append(subpoly)
            else:
                print("In converting buildings encontered type of {}".format(type(b_shape)))

        return MultiPolygon(bldgs)
    except:
        return None 
    

def make_scatter_plot(df_path, count_var='bldg_count'):
    df = pd.read_csv(df_path)
    s_time_mins = df['steiner_time'].values / 60
    #count = df['bldg_count'].values
    #count = df['edge_count_post'].values
    df['bldg_count'] = df[count_var]
    count = df[count_var].values

    plt.scatter(count, s_time_mins, color='red', alpha=0.3)
    plt.title("Steiner optimal path time per block (mins)")
    plt.xlabel("Buildings in block")
    plt.ylabel("Compute time (mins)")

    return df 

def line_graph_xy(df_path, count_var='bldg_count'):
    df = pd.read_csv(df_path)
    df['bldg_count'] = df[count_var]
    #count = df['bldg_count'].values
    #count = df['edge_count_post'].values
    g_df = df[['steiner_time', 'bldg_count']].groupby('bldg_count').mean()
    g_df.sort_index(inplace=True)
    g_df['steiner_time'] = g_df['steiner_time'] / 60
    x = g_df.index.values
    y = g_df['steiner_time'].values
    return g_df, x, y 

gadm_list = ['KEN.30.10.1_1', 'KEN.30.10.2_1', 'KEN.30.10.3_1', 'KEN.30.10.4_1',
             'KEN.30.10.5_1', 'KEN.30.11.2_1']


def read_steiner(path, add_len=False):
    wkt_to_geom = lambda x: loads(x) if isinstance(x, str) else None 
    print("Loading reblock at: {}".format(str(path)))
    d = pd.read_csv(str(path))
    d.drop(columns=['Unnamed: 0'], inplace=True)
    d['geometry'] = d['geometry'].apply(wkt_to_geom)

    geo_d = gpd.GeoDataFrame(d)
    geo_d['geometry'].crs =  {'init': 'epsg:4326'}
    geo_d.crs =  {'init': 'epsg:4326'}

    if add_len:
        has_geom = geo_d['geometry'].notna()
        geo_d = geo_d.loc[has_geom]
        geo_d['road_len_m'] = geo_d['geometry'].to_crs({'init': 'epsg:3395'}).length

    return geo_d 

def process_complexity_pop(df):
    gdf = gpd.GeoDataFrame(df)
    gdf['geometry'] = gdf['geometry'].apply(loads)
    gdf.geometry.crs = {'init': 'epsg:4326'}  
    gdf.crs = {'init': 'epsg:4326'}
    gdf['is_neg_pop'] = gdf['pop_est'] < 0
    gdf['bldg_density'] = gdf['total_bldg_area_sq_km'] / gdf['block_area_km2']
    gdf['gt1'] = gdf['bldg_density'] > 1
    return gdf 

def load_complexity_pop(region, country_code, gadm):
    landscan_path = DATA / 'LandScan_Global_2018' / region / country_code
    complexity_pop_path = landscan_path / "complexity_pop_{}.csv".format(gadm) 
    df = pd.read_csv(complexity_pop_path)
    #print("There are {} gt 1".format(gt1.sum()))    #gdf.drop(columns=['Unnamed: 0'], inplace=True)
    return process_complexity_pop(df)  

def load_aoi(aoi_path):
    df = pd.read_csv(aoi_path)
    return process_complexity_pop(df)  

def get_most_dense_within_complexity_level(df, complexity, count):

    comp_bool = df['complexity'] == complexity
    sub_df = df.loc[comp_bool]
    rv = sub_df.sort_values('bldg_density', inplace=False, ascending=False)
    return rv.iloc[0:count]['block_id'].values

def get_blocks_with(df, complexity=None, density_range=[0, 1]):

    c_bool = df['complexity'] == complexity
    b = c_bool & (df['bldg_density'] <= density_range[1]) & (df['bldg_density'] >= density_range[0])
    return sub_df['block_id'][b].values

class ComplexityViewer:

    def __init__(self, gadm_list=None, aoi_path=None, region=None, block_list=None):

        self.gadm_code = gadm_list[0][0:3] if gadm_list is not None else None
        self.region = region 
        self.gadm_list = gadm_list
        self.block_list = block_list
        self.gadm_count = len(gadm_list) if gadm_list is not None else None 
        self.complexity = ComplexityViewer.load_complexity(region, self.gadm_code, aoi_path)
        #self.complexity = pd.concat([load_complexity_pop(region, self.gadm_code, gadm) for gadm in gadm_list])        
        self.buildings = ComplexityViewer.make_building_geom(self.complexity)
        self.block_ids = self.complexity['block_id']

    @staticmethod
    def load_complexity(region, gadm_code, aoi_path):

        if aoi_path is not None:
            rv = load_aoi(aoi_path)
        else:
            rv = pd.concat([load_complexity_pop(region, self.gadm_code, gadm) for gadm in gadm_list])

        rv['gadm'] = rv['block_id'].apply(lambda s: s[0:s.rfind("_")])
        return rv 

    @staticmethod
    def make_building_geom(gdf):
        buildings = gdf['geometry_bldgs'].apply(convert_buildings)
        comp = gdf['complexity'].values 
        #buildings['complexity'] = comp
        buildings_gdf = gpd.GeoDataFrame({"geometry":buildings, "block_id":gdf['block_id']})
        buildings_gdf['gadm'] = buildings_gdf['block_id'].apply(lambda s: s[0:s.rfind("_")])
        buildings_gdf['complexity'] = comp
        return buildings_gdf

    @staticmethod
    def from_block_list(block_list, region):
        '''
        Allows for construction via a list of blocks rather than gadms
        '''
        gadm_list = {s[0:s.rfind("_")] for s in block_list}
        gadm_list = list(gadm_list)

        return ComplexityViewer(gadm_list=gadm_list, region=region, block_list=block_list)

    def restrict(self, gadm_aois=None, block_aois=None):
        def restrict_to_aois(df):
            if block_aois is None and gadm_aois is None:
                return df 
            else:
                aoi_type = 'block_id' if block_aois is not None else 'gadm'
                aois = block_aois if aoi_type == "block_id" else gadm_aois

                aoi_df = pd.DataFrame({aoi_type: aois})
                print(aoi_df.columns)
                df_sub = df.merge(aoi_df, how='left', on=aoi_type, indicator='in_aoi')
                in_aoi_bool = df_sub['in_aoi'] == 'both'
                print("overlap")
                print(in_aoi_bool.sum())
                return df_sub.loc[in_aoi_bool]

        cur_complexity = restrict_to_aois(self.complexity)
        return cur_complexity


    def view(self, gadm_aois=None, block_aois=None, add_buildings=True, annotate_density=False,
                   annotate_block_id=False, save_to=None):
        
        def restrict_to_aois(df):
            if block_aois is None and gadm_aois is None:
                return df 
            else:
                aoi_type = 'block_id' if block_aois is not None else 'gadm'
                aois = block_aois if aoi_type == "block_id" else gadm_aois

                aoi_df = pd.DataFrame({aoi_type: aois})
                print(aoi_df.columns)
                df_sub = df.merge(aoi_df, how='left', on=aoi_type, indicator='in_aoi')
                in_aoi_bool = df_sub['in_aoi'] == 'both'
                print("overlap")
                print(in_aoi_bool.sum())
                return df_sub.loc[in_aoi_bool]
        
        cur_complexity = restrict_to_aois(self.complexity)
        missing_complexity = cur_complexity['complexity'].isna()
        ax = cur_complexity.loc[~missing_complexity].plot(column='complexity', legend=True, figsize=(15,15))
        cur_complexity.loc[missing_complexity].plot(color='black', alpha=0.1, ax=ax)
        #ax = cur_complexity.plot( legend=True, figsize=(15,15))

        if add_buildings:
            restrict_to_aois(self.buildings).plot(color='black', alpha=0.4, ax=ax)

        # add labels
        if annotate_density or annotate_block_id:
            centroids = cur_complexity.centroid
            zipped = zip(cur_complexity.block_id, cur_complexity.bldg_density, centroids.x, centroids.y)
            for block, density, x, y in zipped:
                if annotate_density and annotate_block_id:
                    text = "{}\n{}".format(block, np.round(density, 4))
                else:
                    text = str(block) if annotate_block_id else str(np.round(density, 4))
                ax.annotate(text, (x,y))

        if save_to:
            #fig = plt.gcf()
            #fig.set_size_inches
            plt.savefig(str(save_to))

    
class ReblockPlotter:

    def __init__(self, gadm_list, region, block_list=None, add_complexity=False, add_reblock=False, 
                 add_buildings=False, add_parcels=False, building_type='OSM'):

        if not isinstance(gadm_list, list):
            gadm_list = [gadm_list]
        assert building_type in {'OSM', 'DG'}, "building_type must be 'OSM' or 'DG'"
        bldg_sub_dir = 'buildings' if building_type == 'OSM' else "dg_buildings"
        parcel_sub_dir = 'parcels' if building_type == 'OSM' else "dg_parcels"
        reblock_sub_dir = "reblock" if building_type == 'OSM' else "dg_reblock"

        self.gadm_code = gadm_list[0][0:3]
        self.region = region 
        self.gadm_list = gadm_list
        self.block_list = block_list
        self.gadm_count = len(gadm_list)
        self.add_buildings = add_buildings
        self.add_parcels = add_parcels
        self.add_reblock = add_reblock
        self.add_complexity = add_complexity

        reblock_path = REBLOCK / self.region
        
        for j, gadm in enumerate(self.gadm_list):

            blocks_path = DATA / "blocks" / region / self.gadm_code / "blocks_{}.csv".format(gadm)
            buildings_path = DATA / bldg_sub_dir / region / self.gadm_code / "buildings_{}.geojson".format(gadm)
            parcels_path = DATA / parcel_sub_dir / region / self.gadm_code / "parcels_{}.geojson".format(gadm)
            steiner_path = DATA / reblock_sub_dir / region / self.gadm_code / "steiner_lines_{}.csv".format(gadm)
            terminal_path = DATA / "reblock" / region / self.gadm_code / "terminal_points_{}.csv".format(gadm)
            complexity_path = DATA / "complexity" / region / self.gadm_code / "complexity_{}.csv".format(gadm)

            if j == 0:
                self.blocks = i_topology_utils.csv_to_geo(blocks_path)
                self.complexity = process_worldpop.load_complexity(self.region, self.gadm_code, complexity_path.name) if add_complexity else None 
                self.buildings = gpd.read_file(buildings_path) if self.add_buildings else None 
                self.parcels = gpd.read_file(parcels_path) if self.add_parcels else None 
                self.steiner = read_steiner(steiner_path) if self.add_reblock else None 
            else:
                self.blocks = pd.concat([i_topology_utils.csv_to_geo(blocks_path), self.blocks], axis=0)
                self.complexity = pd.concat([process_worldpop.load_complexity(self.region, self.gadm_code, complexity_path.name), self.complexity], axis=0) if add_complexity else None 
                self.buildings = pd.concat([gpd.read_file(buildings_path), self.buildings], axis=0) if self.add_buildings else None 
                self.parcels = pd.concat([gpd.read_file(parcels_path), self.parcels], axis=0) if self.add_parcels else None 
                self.steiner = pd.concat([read_steiner(steiner_path), self.steiner], axis=0) if self.add_reblock else None 

        self.graph_dict = {}

        self.block_ids = self.blocks['block_id']

    @staticmethod
    def from_block_list(block_list, region, add_complexity=False, add_reblock=False, add_buildings=False, add_parcels=False):
        '''
        Allows for construction via a list of blocks rather than gadms
        '''
        gadm_list = {s[0:s.rfind("_")] for s in block_list}
        gadm_list = list(gadm_list)

        return ReblockPlotter(gadm_list=gadm_list, region=region, block_list=block_list, add_complexity=add_complexity, 
            add_reblock=add_reblock, add_buildings=add_buildings, add_parcels=add_parcels)

    def view(self, ax=None, block_aois=None, add_buildings=None, add_complexity=None, add_parcels=None, save_to=None):
        
        def restrict_to_block_aois(df):
            if block_aois is None:
                return df 
            else:
                block_aoi_df = pd.DataFrame({'block_id': block_aois})
                df_sub = df.merge(block_aoi_df, how='left', on='block_id', indicator='in_aoi')
                in_aoi_bool = df_sub['in_aoi'] == 'both'
                print("overlap")
                print(in_aoi_bool.sum())
                return df_sub.loc[in_aoi_bool]


        # Allow user to override and just view without buildings
        add_buildings = self.add_buildings if add_buildings is None else add_buildings
        add_complexity = self.add_complexity if add_complexity is None else add_complexity
        add_parcels = self.add_parcels if add_parcels is None else add_parcels

        # ax = self.blocks[self.blocks['block_id']==block_id].plot(color='black', alpha=0.2)
        if add_complexity:
            temp = restrict_to_block_aois(self.complexity)
            print(temp.shape)
            ax = temp.plot(column='complexity', legend=True, figsize=(15,15), ax=ax)
        else:
            temp = restrict_to_block_aois(self.blocks)
            ax = temp.plot(figsize=(15,15), alpha=0.3, edgecolor='black', ax=ax)

        if add_buildings:
            self.buildings.plot(color='black', alpha=0.85, ax=ax)
        if add_parcels:
            self.parcels.plot(color='blue', alpha=.6, ax=ax)
            temp.plot(figsize=(15,15), alpha=0, edgecolor='black', ax=ax)

        if save_to:
            #fig = plt.gcf()
            #fig.set_size_inches
            plt.savefig(str(save_to))


    def load_block_graph(self, block_id):
        if isinstance(block_id, int):
            block_id = "{}_{}".format(self.gadm, int)

        graph_path = os.path.join(DATA, "graphs", self.region, self.gadm_code, "{}.igraph".format(block_id))
        return PlanarGraph.load_planar(graph_path)  


    def view_blocks_reblock(self, block_id, add_buildings=None, add_parcels=None, line_types='steiner'):
        '''
        Allows user to visualize reblocking for a single specified block, as determined by the block_id
        Note, if you've imported building and parcels when constructing the viewer, you can choose
        to include/not include them when viewing
        '''
        
        if isinstance(block_id, int):
            block_id = "{}_{}".format(self.gadm, int)

        # Allow user to override and just view without buildings
        add_buildings = self.add_buildings if add_buildings is None else add_buildings
        add_parcels = self.add_parcels if add_parcels is None else add_parcels

        ax = self.blocks[self.blocks['block_id']==block_id].plot(color='black', alpha=0.2)
        self.terminal[self.terminal['block_id']==block_id].plot(color='red', ax=ax)

        if line_types == 'steiner':
            self.steiner[self.steiner['block_id']==block_id].plot(color='red', ax=ax)
        elif line_types == 'all':
            self.graph_dict['block_id'] = self.load_block_graph(block_id)
            lines = convert_to_lines(self.graph_dict['block_id'])
            lines_geo = gpd.GeoSeries(lines)
            lines_geo.plot(color='red', ax=ax)

        if add_buildings:
            self.buildings.plot(color='blue', alpha=0.4, ax=ax)
        if add_parcels:
            self.parcels[self.parcels['block_id']==block_id].plot(color='blue', alpha=0.4, ax=ax)


    def view_all_reblock(self, add_buildings=None, add_parcels=None):
        '''
        Calling this will visualize the reblocking for the entire area you've specified in your constructor
        '''

        # Allow user to override and just view without buildings
        add_buildings = self.add_buildings if add_buildings is None else add_buildings
        add_parcels = self.add_parcels if add_parcels is None else add_parcels

        ax = self.blocks.plot(color='black', alpha=0.2)
        self.steiner.plot(color='red', ax=ax)
        #self.terminal.plot(color='red', ax=ax)
        if add_buildings:
            self.buildings.plot(color='blue', alpha=0.4, ax=ax)

        if add_parcels:
            self.parcels.plot(color='blue', alpha=0.4, ax=ax)

    def export_parcels(self, output_filename):
        self.parcels.to_file(output_filename, driver='GeoJSON')

    def export_steiner(self, output_filename):

        fail_bool = self.steiner['geometry'].isna()
        steiner_fails = self.steiner[fail_bool]
        steiner_success = self.steiner[~fail_bool]
        self.steiner_success.to_file(output_filename, driver='GeoJSON')

# Load all our AoI gadms
l = [
{ "type": "Feature", "properties": { "aoi_names": "Helao Nifidi", "gadms": [ "NAM.7.3_1", "NAM.7.11_1" ] }, "geometry": { "type": "Polygon", "coordinates": [ [ [ 15.879181841881556, -17.390947570393816 ], [ 15.906439658072946, -17.390885784647043 ], [ 15.906504403479577, -17.41664863024576 ], [ 15.879052351068296, -17.41658685318577 ], [ 15.879181841881556, -17.390947570393816 ] ] ] } },
{ "type": "Feature", "properties": { "aoi_names": "Gobabis", "gadms": [ "NAM.8.3_1", "NAM.8.4_1" ] }, "geometry": { "type": "Polygon", "coordinates": [ [ [ 18.942989557687913, -22.417719167201899 ], [ 19.017593848238359, -22.417719167201899 ], [ 19.017725657938978, -22.467302686905978 ], [ 18.943253177089154, -22.467302686905978 ], [ 18.942989557687913, -22.417719167201899 ] ] ] } },
{ "type": "Feature", "properties": { "aoi_names": "Windhoek", "gadms": [ "NAM.5.1_1", "NAM.5.2_1", "NAM.5.3_1", "NAM.5.4_1", "NAM.5.5_1", "NAM.5.6_1", "NAM.5.7_1", "NAM.5.8_1", "NAM.5.9_1", "NAM.5.10_1" ] }, "geometry": { "type": "Polygon", "coordinates": [ [ [ 16.985495388056194, -22.493915958341489 ], [ 17.041770896654064, -22.468626911468171 ], [ 17.099276471013635, -22.487665163089861 ], [ 17.095278757288103, -22.517211888836112 ], [ 17.13033563149661, -22.563224013383397 ], [ 17.147556552160438, -22.594458066529015 ], [ 17.115267325915759, -22.598432801638598 ], [ 17.122647720485972, -22.626252733079948 ], [ 17.066064695447679, -22.643282566379881 ], [ 17.019322196503001, -22.576286387819987 ], [ 16.979960092128536, -22.558964275874036 ], [ 16.985495388056194, -22.493915958341489 ] ] ] } },
{ "type": "Feature", "properties": { "aoi_names": "Tsumeb", "gadms": [ "NAM.11.2_1", "NAM.11.10_1" ] }, "geometry": { "type": "Polygon", "coordinates": [ [ [ 17.683542277466763, -19.242412021806228 ], [ 17.700053359871344, -19.220826315163645 ], [ 17.719231617125896, -19.211471628172966 ], [ 17.739044916011387, -19.221905667864387 ], [ 17.746411398930356, -19.259318842989551 ], [ 17.742474140818494, -19.276943247606027 ], [ 17.706657792833173, -19.275984145101969 ], [ 17.677572886135874, -19.254043142549968 ], [ 17.683542277466763, -19.242412021806228 ] ] ] } }
]

# aoi_gadms = {x['properties']['aoi_names']: x['properties']['gadms'] for x in l}
# #aoi_gadms.pop('Helao Nifidi')
# from pathlib import Path 
# out_dir = Path("workshop")

# for aoi, aoi_gadms in aoi_gadms.items():
#     print("Loading {}".format(aoi))
#     gadm_list = [a for a in aoi_gadms if 'NAM.5.9_1' not in a]
#     #gadm_list = gadm_list[0:1]
#     viewer = ReblockPlotter(gadm_list, region='Africa', add_reblock=True, add_buildings=True, building_type='DG')

#     #viewer.view_all_reblock()
#     #plt.show()

#     buildings_gdf = viewer.buildings
#     blocks_gdf = viewer.blocks
#     reblock_gdf = viewer.steiner

#     bldg_path = out_dir / aoi / "{}_buildings.geojson".format(aoi)
#     blocks_path = out_dir / aoi / "{}_existing_blocks.geojson".format(aoi)
#     reblock_path = out_dir / aoi / "{}_proposed_reblock.geojson".format(aoi)

#     # Drop bad geoms
#     reblock_gdf = reblock_gdf[reblock_gdf.geom_type=='MultiLineString']

#     (out_dir / aoi).mkdir(parents=True, exist_ok=True)

#     buildings_gdf.to_file(str(bldg_path), driver='GeoJSON')
#     blocks_gdf.to_file(str(blocks_path), driver='GeoJSON')
#     reblock_gdf.to_file(str(reblock_path), driver='GeoJSON')
#     print("....saving complete!\n")

#from bokeh_view import *
# aoi_paths = DATA /"LandScan_Global_2018" / "aoi_datasets"

# known_slum_df = pd.read_csv("../Monrovia_Freetown_Kibera.csv")

# # # (1) Kibera
# nairobi_path = [p for p in aoi_paths.iterdir() if "nair" in str(p)][0] 
# nairobi = ComplexityViewer(region='Africa', aoi_path=nairobi_path) 
# kibera_df = nairobi.restrict(gadm_aois=gadm_list)
# #aoi_analysis.make_box_plot_summary(kibera_df, "Kibera, Nairobi", outpath="./bokeh/kibera_plot.png")
# make_bokeh(kibera_df, "./bokeh/kibera_bokeh_test.html", add_avg_building_size=True)

# # (2) Monrovia -- LBR
# known_monrovia = list(known_slum_df[known_slum_df['country_code']=='LBR']['block_id'])
# monrovia_path = [p for p in aoi_paths.iterdir() if "monrovia" in str(p)][0] 
# monrovia = ComplexityViewer(region='Africa', aoi_path=monrovia_path) 
# monrovia_slum_df = monrovia.restrict(block_aois=known_monrovia)
# #aoi_analysis.make_box_plot_summary(monrovia_slum_df, "Monrovia slums", outpath="./bokeh/monrovia_slum_plot.png")
# make_bokeh(monrovia_slum_df, "./bokeh/monrovia_slum_bokeh.html")

# # (3) Port au prince -- HTI
# known_portauprince = list(known_slum_df[known_slum_df['country_code']=='HTI']['block_id'])
# portauprince_path = [p for p in aoi_paths.iterdir() if "prince" in str(p)][0] 
# portauprince = ComplexityViewer(region='Africa', aoi_path=portauprince_path) 
# portauprince_slum_df = portauprince.restrict(block_aois=known_portauprince)
# #aoi_analysis.make_box_plot_summary(portauprince_slum_df, "Port au Prince", outpath="./bokeh/port_au_prince_slum_plot.png")
# make_bokeh(portauprince_slum_df, "./bokeh/port_au_prince_slum_bokeh.html")

# # (4) Freetown -- SLE
# freetown_path = [p for p in aoi_paths.iterdir() if "free" in str(p)][0] 
# freetown = ComplexityViewer(region='Africa', aoi_path=freetown_path) 
# freetown_df = freetown.restrict(gadm_aois=['SLE.4.2.1_1'])
# #aoi_analysis.make_box_plot_summary(freetown_df, "Freetown, SL", outpath="./bokeh/freetown_slum_plot.png")
# make_bokeh(freetown_df, "./bokeh/freetown_bokeh.html")

# import statsmodels.api as sm 
# from mpl_toolkits import mplot3d
# from statsmodels.nonparametric.kde import kernel_switch
# cols = ['complexity', 'bldg_density']
# data = nairobi.complexity[cols]
# missing_compl = data['complexity'].isna()
# data = data.loc[~missing_compl]

# x = data['complexity'].values
# y = data['bldg_density'].values 
# #y = np.log(y)
# bandwidth = 0.1
# dens_fn = sm.nonparametric.KDEMultivariate(data=[x, y], var_type='oc', bw=[bandwidth, bandwidth])

# x_min = 5
# x_max = x.max()
# y_min = 0.0
# y_max = 1.0

# x_plot_point_count = 20 
# y_plot_point_count = 40
# x_plot_vals = np.linspace(x_min, x_max, x_plot_point_count) 
# y_plot_vals = np.linspace(y_min, y_max, y_plot_point_count) 
# X_plot, Y_plot = np.meshgrid(x_plot_vals, y_plot_vals)
# eval_data = [X_plot.ravel(), Y_plot.ravel()]
# z = dens_fn.pdf(eval_data)
# Z_plot = z.reshape(X_plot.shape)

# ax = plt.axes(projection='3d')  
# ax.plot_surface(X_plot, Y_plot, Z_plot, cmap='viridis') 

# if __name__ == "__main__":
#     # gadm_list = ['KEN.30.10.1_1',
#     #  'KEN.30.10.2_1',
#     #  'KEN.30.10.3_1',
#     #  'KEN.30.10.4_1',
#     #  'KEN.30.10.5_1',
#     #  'KEN.30.11.2_1']
#     # gadm_list = ['LBR.11.2.1_1']
#     # #gadm_list = ['DJI.2.1_1']
#     # region = 'Africa'
#     # #viewer = ReblockPlotter(gadm_list, region, add_parcels=False, add_buildings=True)

#     # viewer = ReblockPlotter(gadm_list, region, add_parcels=False, add_buildings=False)
#     # viewer.export_steiner(REBLOCK_VIEWIING / "{}_parcels.geojson".format(gadm_list[0]))

#     gadm_list = ['SLE.4.2.1_1']
#     region = 'Africa'
#     viewer = ReblockPlotter(gadm_list, region, add_parcels=False, add_buildings=False)
#     viewer.export_steiner(REBLOCK_VIEWIING / "{}_opt_path.geojson".format(gadm_list[0]))

    # # This will allow you to view the optimal paths
    # # viewer.view_all()
    # # plt.show()

    # # Now we export to files, assuming we've sanity checked the output and it looks good
    # viewer.export_parcels(os.path.join(DATA, 'KEN_parcels.geojson'))
    # viewer.export_steiner(os.path.join(DATA, 'KEN_opt_path.geojson'))


