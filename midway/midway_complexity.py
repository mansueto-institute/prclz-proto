import argparse
import json
import logging
from logging import info
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd
import shapely.wkt
from joblib import Parallel, delayed
from networkx.readwrite import json_graph
from shapely.geometry import MultiPoint

from prclz.complexity import get_complexity, get_weak_dual_sequence


def weak_dual_sequence_to_json_string(weak_duals):
    return json.dumps(list(map(json_graph.node_link_data, weak_duals)), default=lambda _:_.__dict__)


def read_file(path, **kwargs):
    """ ensures geometry set correctly when reading from csv
    otherwise, pd.BlockManager malformed when using gpd.read_file(*) """
    if not path.endswith(".csv"):
        return gpd.read_file(path)
    raw = pd.read_csv(path, **kwargs)
    raw["geometry"] = raw["geometry"].apply(shapely.wkt.loads)
    return gpd.GeoDataFrame(raw, geometry="geometry")


def calculate_complexity(index, block, centroids):
    sequence = get_weak_dual_sequence(block, centroids)
    complexity = get_complexity(sequence)
    centroids_multipoint = MultiPoint(centroids)

    return (index, complexity, centroids_multipoint)

def main(blocks_path: Path, buildings_path: Path, complexity_output: Path, graph_output: Optional[Path], parallelism: int, overwrite: bool):
    if (not complexity_output.exists()) or (complexity_output.exists() and overwrite):
        info("Reading geospatial data from files.")
        blocks    = read_file(str(blocks_path), index_col="block_id", usecols=["block_id", "geometry"], low_memory=False)
        buildings = read_file(str(buildings_path), low_memory=False)
        buildings["geometry"] = buildings.centroid

        info("Aggregating buildings by street block.")
        block_aggregation = gpd.sjoin(blocks, buildings, how="right", op="intersects")
        block_aggregation = block_aggregation[pd.notnull(block_aggregation["index_left"])].groupby("index_left")["geometry"].agg(list)
        block_aggregation.name = "centroids"
        block_buildings = blocks.join(block_aggregation)
        block_buildings = block_buildings[pd.notnull(block_buildings["centroids"])]

        info("Calculating block complexity.")
        complexity = Parallel(n_jobs=parallelism, verbose=100)(delayed(calculate_complexity)(idx, block, centroids) for (idx, block, centroids) in block_buildings[["geometry", "centroids"]].itertuples())
        
        info("Restructuring complexity calculations by block_id index.")
        block_buildings = block_buildings.join(pd.DataFrame(complexity, columns=["block_id", "complexity", "centroids_multipoint"]).set_index("block_id"))

        info("Serializing complexity calculations to %s.", complexity_output)
        block_buildings[['geometry', 'complexity', 'centroids_multipoint']].to_csv(complexity_output)
        # if graph_output:
        #     info("Serializing graph sequences to %s", graph_output)
        #     block_buildings[['weak_duals']].to_csv(complexity_output)
    else: 
        info("Skipping processing %s (output exists and overwrite flag not given)", complexity_output)


def setup(args=None):
    # logging
    logging.basicConfig(format="%(asctime)s/%(filename)s/%(funcName)s | %(levelname)s - %(message)s", datefmt='%Y-%m-%d %H:%M:%S')
    logging.getLogger().setLevel("INFO")

    # read arguments
    parser = argparse.ArgumentParser(description='Run complexity workflow on midway2.')
    parser.add_argument('--blocks',      required=True,  type=Path, help='path to blocks',      dest="blocks_path")
    parser.add_argument('--buildings',   required=True,  type=Path, help='path to buildings',   dest="buildings_path")
    parser.add_argument('--output',      required=True,  type=Path, help='path to output',      dest="complexity_output")
    parser.add_argument('--graphs',      required=False, type=Path, help='path to save graphs', dest="graph_output")
    parser.add_argument('--parallelism', default=4,      type=int,  help='number of cores to use')
    parser.add_argument('--overwrite',   default=False,  type=bool, help='whether to overwrite existing block files')

    return parser.parse_args(args)


if __name__ == "__main__":
    main(**vars(setup()))
