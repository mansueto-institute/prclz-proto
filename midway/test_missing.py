import argparse
import logging
from logging import info, warning
from pathlib import Path
from typing import List, Union

import geopandas as gpd
from joblib import Parallel, delayed
from shapely.geometry import MultiPolygon, Polygon

from prclz.blocks.methods import BufferedLineDifference
import os 
import pandas as pd  

from midway_blocks import extract 

def get_gadm_level_column(gadm: gpd.GeoDataFrame, level: int) -> str:
    gadm_level_column = "GID_{}".format(level)
    while gadm_level_column not in gadm.columns and level > 0:
        warning("GID column for GADM level %s not found, trying with level %s", level, level-1)
        level -= 1
        gadm_level_column = "GID_{}".format(level)
    info("Using GID column for GADM level %s", level)
    return gadm_level_column, level

# def extract(linestrings: gpd.GeoDataFrame, index: str, geometry: Union[Polygon, MultiPolygon], ls_idx: List[int], output_dir: Path) -> None:
#     # minimize synchronization barrier by constructing a new extractor
#     block_polygons = BufferedLineDifference().extract(geometry, linestrings.iloc[ls_idx].unary_union)
    
#     print("Type is : ", type(block_polygons))

#     blocks = gpd.GeoDataFrame(
#         [(index + "_" + str(i), polygon) for (i, polygon) in enumerate(block_polygons)], 
#         columns=["block_id", "geometry"])
#     blocks.set_index("block_id")
#     filename = output_dir+("blocks_{}.csv".format(index))
#     blocks.to_csv(filename)
#     info("Serialized blocks from %s to %s", index, filename)


# DATA PATHS
level = 3
gadm_path = "../data/GADM/MWI/gadm36_MWI_3.shp"
linestrings_path = "../data/geojson/Africa/malawi_lines.geojson"
blocks_path = "../data/blocks/Africa/MWI"

# All blocks files currently output for Malawi
all_blocks_files = [x.replace("blocks_", "").replace(".csv", "") for x in os.listdir(blocks_path)]
all_blocks_files = pd.DataFrame({'out_files':all_blocks_files})
all_blocks_files['block_file_index'] = range(all_blocks_files.shape[0])
all_blocks_files.set_index('out_files', inplace=True)

# Now do the actual block-ing for Malawi
gadm = gpd.read_file(gadm_path)
linestrings = gpd.read_file(linestrings_path)

gamd_column, level = get_gadm_level_column(gadm, level)
gadm               = gadm.set_index(gamd_column, level)

info("Overlaying GADM boundaries on linestrings.")
overlay = gpd.sjoin(gadm, linestrings, how="left", op="intersects")\
             .groupby(lambda idx: idx)["index_right"]\
             .agg(list)

info("Aggregating linestrings by GADM-%s delineation.", level)
gadm_aggregation = gadm.join(overlay)[["geometry", "index_right"]]\
                       .rename({"index_right": "linestring_index"}, axis=1)

gadm_aggregation = gadm_aggregation.join(all_blocks_files, how='left')
gadm_aggregation['success'] = gadm_aggregation['block_file_index'].notnull()

# Make a smaller dataset of both failures and successes
cols = ['geometry', 'linestring_index']
test_fail = gadm_aggregation[ ~gadm_aggregation['success'] ][cols]
test_success = gadm_aggregation[ gadm_aggregation['success'] ][cols].iloc[0:10]

# Run through the successes, for reference
# for index, geometry, ls_idx in test_success.itertuples():
#     extract(linestrings, index, geometry, ls_idx, "small_test")

# Run through the failures, for reference
for index, geometry, ls_idx in test_fail.itertuples():
    print("Index is", index)
    print("ls_idx is", ls_idx)
    extract(linestrings, index, geometry, ls_idx, "small_test")

# Flag for each of the failures what return type the BufferedLineDifference yields
rv = {}
for index, geometry, ls_idx in test_fail.itertuples():
    try:
        block_polygons = BufferedLineDifference().extract(geometry, linestrings.iloc[ls_idx].unary_union)
        print("Pass :", index)
    except:
        print("Fail :", index)

# def main(gadm_path, linestrings_path, output_dir, level, parallelism):
#     info("Reading geospatial data from files.")
#     gadm              = gpd.read_file(str(gadm_path))
#     linestrings       = gpd.read_file(str(linestrings_path))

#     info("Setting up indices.")
#     gamd_column, level = get_gadm_level_column(gadm, level)
#     gadm               = gadm.set_index(gamd_column, level)

#     info("Overlaying GADM boundaries on linestrings.")
#     overlay = gpd.sjoin(gadm, linestrings, how="left", op="intersects")\
#                  .groupby(lambda idx: idx)["index_right"]\
#                  .agg(list)

#     info("Aggregating linestrings by GADM-%s delineation.", level)
#     gadm_aggregation = gadm.join(overlay)[["geometry", "index_right"]]\
#                            .rename({"index_right": "linestring_index"}, axis=1)

#     extractor = BufferedLineDifference()
#     info("Extracting blocks for each delineation using method: %s.", extractor)
#     Parallel(n_jobs=parallelism, verbose=50)(delayed(extract)(linestrings, index, geometry, ls_idx, output_dir) for (index, geometry, ls_idx) in gadm_aggregation.itertuples())

#     info("Done.")


# def setup(args=None):
#     # logging
#     logging.basicConfig(format="%(asctime)s/%(filename)s/%(funcName)s | %(levelname)s - %(message)s", datefmt='%Y-%m-%d %H:%M:%S')
#     logging.getLogger().setLevel("INFO")

#     # read arguments
#     parser = argparse.ArgumentParser(description='Run parcelization workflow on midway2.')
#     parser.add_argument('--gadm',        required=True, type=Path, help='path to GADM file',   dest="gadm_path")
#     parser.add_argument('--linestrings', required=True, type=Path, help='path to linestrings', dest="linestrings_path")
#     parser.add_argument('--output',      required=True, type=Path, help='path to  output',     dest="output_dir")
#     parser.add_argument('--level',       default=3,     type=int,  help='GADM level to use')
#     parser.add_argument('--parallelism', default=4,     type=int,  help='number of cores to use')

#     return parser.parse_args(args)


# if __name__ == "__main__":
#     main(**vars(setup()))
