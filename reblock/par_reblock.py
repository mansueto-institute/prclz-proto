import typing
from typing import List, Tuple  
import multiprocessing 

import geopandas as gpd
from shapely.geometry import MultiPolygon, Polygon, MultiLineString, Point, LineString
from shapely.ops import cascaded_union
from shapely.wkt import loads, dumps
import pandas as pd
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
import tqdm 

ROOT = "../"
DATA = os.path.join(ROOT, "data")
TRANS_TABLE = pd.read_csv(os.path.join(ROOT, "data_processing", 'country_codes.csv'))


def add_buildings(graph: PlanarGraph, buildings: List[Tuple]):

    total_blgds = len(buildings)
    #print("\t\tbuildings....")
    for i, bldg_node in enumerate(buildings):
        graph.add_node_to_closest_edge(bldg_node, terminal=True)

    if total_blgds > 0:
        graph.cleanup_linestring_attr()
    return graph 

def clean_graph(graph):
    is_conn = graph.is_connected()
    if is_conn:
        #print("Graph is connected")
        return graph, 1
    else:
        components = graph.components(mode=igraph.WEAK)
        num_components = len(components)
        #print("--DISCONNECTED: has {} components".format(num_components))
        comp_sizes = [len(idxs) for idxs in components]
        arg_max = np.argmax(comp_sizes)
        comp_indices = components[arg_max]

        return graph.subgraph(comp_indices), num_components

def get_optimal_path(graph: PlanarGraph, buildings: List[Tuple], verbose: bool=False):
    '''
    Given a graph of the Parcel and the corresponding list of buildings (expressed as a list of tuple pairs),
    does the reblocking
    '''

    # Step 1: add the buildings to the PlanarGraph
    start = time.time()
    graph = add_buildings(graph, buildings)
    bldg_time = time.time() - start

    # Step 2: clean the graph if it's disconnected
    graph, num_components = clean_graph(graph)

    # Step 3: do the Steiner Tree approx
    start = time.time()
    graph.steiner_tree_approx()
    stiener_time = time.time() - start 

    # Step 4: convert the stiener edges and terminal nodes to linestrings and points, respecitvely
    #steiner_lines = graph.get_steiner_linestrings()
    new_steiner, existing_steiner = graph.get_steiner_linestrings()
    terminal_points = graph.get_terminal_points()

    if verbose:
        return new_steiner, existing_steiner, terminal_points, [bldg_time, stiener_time, num_components]
    else:
        return new_steiner, existing_steiner, terminal_points

class CheckPointer:
    '''
    Small container class which handles saving of work, checking if
    prior work exists, etc
    '''

    def __init__(self, region: str, gadm: str, gadm_code: str, drop_already_completed: bool, checkpoint_every=1):

        self.reblock_path = os.path.join(DATA, "reblock", region, gadm_code)
        if not os.path.exists(self.reblock_path):
            os.makedirs(self.reblock_path)
        self.summary_path = os.path.join(self.reblock_path, "reblock_summary_{}.csv".format(gadm))
        self.steiner_path = os.path.join(self.reblock_path, "steiner_lines_{}.csv".format(gadm))
        self.terminal_path = os.path.join(self.reblock_path, "terminal_points_{}.csv".format(gadm))

        self.prior_work_exists = (os.path.exists(self.summary_path)) and drop_already_completed

        self.summary_dict, self.steiner_lines_dict, self.terminal_points_dict = self.load_dicts()
        self.completed = set(self.summary_dict.keys())
        self.iter = 0
        self.checkpoint_every = checkpoint_every
        self.process_queues = []
        self.process_status = []
        if self.prior_work_exists:
            print("--Loading {} previously computed results".format(len(self.completed)))

    def update(self, block_id, new_steiner, existing_steiner, terminal_points, summary):
        new_steiner = new_steiner if new_steiner is None else dumps(new_steiner)
        existing_steiner = existing_steiner if existing_steiner is None else dumps(existing_steiner)
        terminal_points = terminal_points if terminal_points is None else dumps(terminal_points)    
        
        self.summary_dict[block_id] = summary 
        self.terminal_points_dict[block_id] = [terminal_points, block_id]
        self.steiner_lines_dict[block_id+'new_steiner'] = [new_steiner, block_id, 'new_steiner', block_id+'new_steiner'] 
        self.steiner_lines_dict[block_id+'existing_steiner'] = [existing_steiner, block_id, 'existing_steiner', block_id+'existing_steiner'] 

        # Save out on first iteration and on checkpoint iterations
        if (self.iter == 0) or (self.iter % self.checkpoint_every == 0):
            self.save() 
        self.iter += 1

    def _get_active_process_count(self):
        i = 0
        for num in self.process_status:
            i += num.value 
        return i 

    def process_par(self):
        active = self._get_active_process_count()
        while active:
            for i, q in enumerate(self.process_queues):
                if not q.empty():
                    output = q.get()                    
                    #print("Getting output from process {}:\n{}".format(i, output))
                    self.update(*output)
            active = self._get_active_process_count()


    def load_dicts(self):
        if self.prior_work_exists:
            summary_records = pd.read_csv(self.summary_path).drop(['Unnamed: 0'], axis=1).to_dict('records')
            summary_dict = {d['block']:list(d.values()) for d in summary_records}

            steiner_records = pd.read_csv(self.steiner_path).drop(['Unnamed: 0'], axis=1).to_dict('records')
            steiner_dict = {d['block_w_type']:list(d.values()) for d in steiner_records}

            terminal_points_records = pd.read_csv(self.terminal_path).drop(['Unnamed: 0'], axis=1).to_dict('records')
            terminal_points_dict = {d['block']:list(d.values()) for d in terminal_points_records}
            return summary_dict, steiner_dict, terminal_points_dict
        else:
            return {}, {}, {}

    def save(self):
        summary_columns = ['bldg_time', 'steiner_time', 'num_graph_comps', 'bldg_count', 'num_block_coords', 'num_block_coords_unmatched', 'block']
        steiner_columns = ['geometry', 'block', 'line_type', 'block_w_type']
        terminal_columns = ['geometry', 'block']

        summary_df = pd.DataFrame.from_dict(self.summary_dict, orient='index', columns=summary_columns)
        steiner_df = pd.DataFrame.from_dict(self.steiner_lines_dict, orient='index', columns=steiner_columns)
        terminal_df = pd.DataFrame.from_dict(self.terminal_points_dict, orient='index', columns=terminal_columns)

        summary_df.to_csv(self.summary_path)
        steiner_df.to_csv(self.steiner_path)
        terminal_df.to_csv(self.terminal_path)


def do_reblock(input_stream, checkpointer=None, shared_status=None):
    '''
    Each item within input_list is of structure (block_id, parcel_geom, building_list, block_geom)
    
    input_stream = List[tuple0, tuple1, ... ]

    '''
    t = 'nonpar'
    for (block_id, parcel_geom, building_list, block_geom) in input_stream:
        if len(building_list) <= 1:
            continue 

        # (1) Convert parcel geometry to planar graph
        planar_graph = PlanarGraph.multilinestring_to_planar_graph(parcel_geom)

        # (2) Update the edge types based on the block graph
        missing, total_block_coords = i_topology_utils.update_edge_types(planar_graph, block_geom, check=True)

        # (3) Do reblocking 
        try:
            new_steiner, existing_steiner, terminal_points, summary = get_optimal_path(planar_graph, building_list, verbose=True)
        except:
            new_steiner = None 
            existing_steiner = None 
            terminal_points = None 
            summary = [None, None, None]

        # Collect and store the summary info from reblocking
        summary = summary + [len(building_list), total_block_coords, missing, block_id]

        if isinstance(checkpointer, CheckPointer):
            # If we are saving data to just a CheckPointer class instance, i.e. no parallelisim
            t = 'nonpar'
            checkpointer.update(block_id, new_steiner, existing_steiner, terminal_points, summary)
        else:
            # assert that checkpointer is instead an input side of a multiprocessing pipe
            t = 'par'
            checkpointer.put([block_id, new_steiner, existing_steiner, terminal_points, summary], block=False) 
    if t == 'par':
        with shared_status.get_lock():
            print("Changing status....")
            shared_status.value = 0


def prepare_inputs(parcels_df, buildings_df, blocks_df, all_blocks, num_processes=1):
    '''
    Restructure our inputs to better accomodate mulitprocessing
    '''
    inputs = [ [] ]*num_processes
    for i, block_id in enumerate(all_blocks):
        parcel_geom = parcels_df[parcels_df['block_id']==block_id]['geometry'].iloc[0]
        building_list = buildings_df[buildings_df['block_id']==block_id]['buildings'].iloc[0]
        block_geom = blocks_df[blocks_df['block_id']==block_id]['geometry'].iloc[0]

        input_idx = i%num_processes
        inputs[input_idx].append((block_id, parcel_geom, building_list, block_geom))
    return inputs 

def reblock_gadm(region, gadm_code, gadm, drop_already_completed=True, num_processes=1):
    '''
    Does reblocking for an entire GADM boundary
    '''

    # (1) Just load our data for one GADM
    print("Begin loading of data--{}-{}".format(region, gadm))
    parcels, buildings, blocks = i_topology_utils.load_reblock_inputs(region, gadm_code, gadm) 

    buildings.sort_values(by=['building_count'], inplace=True)

    # (2) Create a checkpointer which will handle saving and restoring of past work
    checkpointer = CheckPointer(region, gadm, gadm_code, drop_already_completed, checkpoint_every = 1)
    all_blocks = [b for b in buildings['block_id'] if b not in checkpointer.completed]

    print("\nBegin looping")

    input_streams = prepare_inputs(parcels, buildings, blocks, all_blocks, num_processes)

    # (4) Loop and process one block at-a-time
    if num_processes == 1:  # No multiprocessing
        stream = input_streams[0]
        do_reblock(stream, checkpointer)
    else:
        # Make a list of processes
        # Each process gets an input stream and a pipe to the checkpointer
        processes = []
        for stream in input_streams:
            q = multiprocessing.Queue()
            status = multiprocessing.Value('d', 1)
            p = multiprocessing.Process(target=do_reblock, args=(stream, q, status))
            processes.append(p)
            checkpointer.process_queues.append(q)
            checkpointer.process_status.append(status)
            p.start()
        checkpointer.process_par()
        for p in processes:
            p.join()



if __name__ == "__main__":

    parser = argparse.ArgumentParser(description='Do reblocking on a GADM')
    parser.add_argument('--region', type=str, required=True, help="region to process")
    parser.add_argument('--gadm_code', type=str, required=True, help="3-digit country gadm code to process")
    parser.add_argument('--gadm', help='process this gadm')
    parser.add_argument('--pcount', dest='num_processes', type=int, help='number of parallelisim', default=1)

    args = parser.parse_args()
   
    start = time.time()
    reblock_gadm(**vars(args))
    print("Takes {} seconds".format(time.time()-start))

