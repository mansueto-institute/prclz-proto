# pylint: disable=relative-beyond-top-level

import logging
from typing import Callable, Mapping, Type, Union

import networkx
import osmnx as ox
from shapely.geometry import (LineString, MultiLineString, MultiPolygon,
                              Polygon, mapping)
from shapely.ops import polygonize, unary_union

from .methods import DEFAULT_EXTRACTION_METHOD, BlockExtractionMethod


def edge_to_geometry(nodes: Mapping, edge: Mapping) -> LineString:
    if "geometry" in edge.keys():
        return edge["geometry"]
    src = nodes[edge["source"]]
    tgt = nodes[edge["target"]]
    return LineString([(src["x"], src["y"]), (tgt["x"], tgt["y"])])


def linestrings_from_network(graph: networkx.Graph) -> MultiLineString:
    json_graph = networkx.readwrite.json_graph.node_link_data(graph)
    nodes = {node["id"]: node for node in json_graph["nodes"]}
    edges = json_graph["links"]
    return MultiLineString([edge_to_geometry(nodes, edge) for edge in edges])


def extract_blocks(
    area: Union[Polygon, MultiPolygon],
    buffer_radius: float = 0.001,
    extraction_method: Type[BlockExtractionMethod] = DEFAULT_EXTRACTION_METHOD, 
    clean_periphery: bool = True, 
    simplify: bool = True
) -> MultiPolygon:
    
    logging.info("Unioning input polygons and buffering with radius: %s", buffer_radius)
    multipolygon = unary_union(area)
    buffered_multipolygon = multipolygon.buffer(buffer_radius)
    
    logging.info("Downloading road network from OSM")
    road_network = ox.graph_from_polygon(
        buffered_multipolygon, 
        network_type="all_private", 
        retain_all=True, 
        clean_periphery=clean_periphery, 
        simplify=simplify)

    logging.info("Parsing graph")
    linestrings = linestrings_from_network(road_network)

    extractor = extraction_method()
    logging.info("Extracting blocks using %s", extractor)
    blocks = extractor.extract(area, linestrings)

    logging.info("Filtering extracted blocks")
    mp_border = buffered_multipolygon.boundary
    filtered_blocks = [block for block in blocks if not mp_border.intersects(block)]

    return filtered_blocks
