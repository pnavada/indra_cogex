# -*- coding: utf-8 -*-

"""Processor for the InterPro database.

.. seealso:: https://ftp.ebi.ac.uk/pub/databases/interpro/current_release/
"""

import gzip
import logging
from collections import defaultdict
from typing import Iterable, List, Mapping, Set, Tuple

import pandas as pd
import pystow
from protmapper import uniprot_client
from tqdm import tqdm

from ..processor import Processor
from ...representation import Node, Relation

logger = logging.getLogger(__name__)

INTERPRO_ENTRIES_URL = (
    "ftp://ftp.ebi.ac.uk/pub/databases/interpro/current_release/entry.list"
)
INTERPRO_SHORT_NAMES_URL = (
    "ftp://ftp.ebi.ac.uk/pub/databases/interpro/current_release/short_names.dat"
)
INTERPRO_TREE_URL = (
    "ftp://ftp.ebi.ac.uk/pub/databases/interpro/current_release/ParentChildTreeFile.txt"
)
INTERPRO_PROTEINS_URL = (
    "ftp://ftp.ebi.ac.uk/pub/databases/interpro/current_release/protein2ipr.dat.gz"
)
INTERPRO_GO_URL = (
    "ftp://ftp.ebi.ac.uk/pub/databases/interpro/current_release/interpro2go"
)


class InterproProcessor(Processor):
    """Processor for Interpro."""

    name = "interpro"
    node_types = ["BioEntity"]

    def __init__(self, force: bool = False):
        """Initialize the InterPro processor."""
        self.entries_df = get_entries_df(module=self.module)
        self.interpro_ids = set(self.entries_df["ENTRY_AC"])
        self.parents = get_parent_to_children(force=force, module=self.module)
        self.interpro_to_goa = get_interpro_to_goa(force=force, module=self.module)

        interpro_to_proteins = get_interpro_to_proteins(
            force=force, interpro_ids=self.interpro_ids, module=self.module
        )
        interpro_to_genes = defaultdict(set)
        for interpro_id, uniprot_ids in interpro_to_proteins.items():
            for uniprot_id in uniprot_ids:
                hgnc_id = uniprot_client.get_hgnc_id(uniprot_id)
                if hgnc_id is not None:
                    # there are a lot of TrEMBL entries, these will return none
                    interpro_to_genes[interpro_id].add(hgnc_id)
        self.interpro_to_genes = dict(interpro_to_genes)

    def get_nodes(self):  # noqa:D102
        unique_go = set()
        unique_hgnc = set()
        for interpro_id, interpro_type, name, short_name in self.entries_df.values:
            yield Node(
                "interpro",
                interpro_id,
                ["BioEntity"],
                dict(name=name, short_name=short_name, type=interpro_type),
            )
            unique_go.update(self.interpro_to_goa.get(interpro_id, set()))
            unique_hgnc.update(self.interpro_to_genes.get(interpro_id, set()))
        for go_id in sorted(unique_go):
            yield Node("GO", go_id, ["BioEntity"])
        for hgnc_id in sorted(unique_hgnc, key=int):
            yield Node("HGNC", hgnc_id, ["BioEntity"])

    def get_relations(self):  # noqa:D102
        for interpro_id in self.interpro_ids:
            for child_interpro_id in self.parents.get(interpro_id, []):
                yield Relation(
                    "interpro", child_interpro_id, "interpro", interpro_id, "isa"
                )

            for go_id in self.interpro_to_goa.get(interpro_id, []):
                yield Relation("interpro", interpro_id, "GO", go_id, "associated_with")

            for hgnc_id in self.interpro_to_genes.get(interpro_id, []):
                yield Relation("interpro", interpro_id, "HGNC", hgnc_id, "has_member")


def get_entries_df(*, force: bool = False, module: pystow.Module) -> pd.DataFrame:
    """Get a dataframe of InterPro entries, filtered to domains."""
    short_names_df = module.ensure_csv(
        url=INTERPRO_SHORT_NAMES_URL,
        read_csv_kwargs=dict(
            header=None,
            names=("ENTRY_AC", "ENTRY_SHORT_NAME"),
        ),
        force=force,
    )

    df = module.ensure_csv(
        url=INTERPRO_ENTRIES_URL,
        read_csv_kwargs=dict(
            skiprows=1,
            names=("ENTRY_AC", "ENTRY_TYPE", "ENTRY_NAME"),
        ),
        force=force,
    )
    # Filter to entry types that represent domains
    df = df[df["ENTRY_TYPE"] == "Domain"]
    df = df.merge(short_names_df, on="ENTRY_AC", how="left")
    return df


def get_parent_to_children(
    *, force: bool = False, module: pystow.Module
) -> Mapping[str, List[str]]:
    """The a mapping from parent InterPro ID to list of children InterPro IDs."""
    path = module.ensure(url=INTERPRO_TREE_URL, force=force)
    with open(path) as file:
        return _parse_tree_helper(file)


def _parse_tree_helper(lines: Iterable[str]) -> Mapping[str, List[str]]:
    child_to_parents = defaultdict(list)
    previous_depth, previous_id = 0, None
    stack = [previous_id]

    for line in tqdm(lines, desc="parsing InterPro tree"):
        depth = _count_leading_dashes(line)
        parent_id, _ = line[depth:].split("::", 1)

        if depth == 0:
            stack.clear()
            stack.append(parent_id)
        else:
            if depth > previous_depth:
                stack.append(previous_id)

            elif depth < previous_depth:
                del stack[-1]

            child_id = stack[-1]
            child_to_parents[child_id].append(parent_id)  # type:ignore

        previous_depth, previous_id = depth, parent_id

    parent_to_children = defaultdict(list)
    for child_id, parent_ids in child_to_parents.items():
        for parent_id in parent_ids:
            parent_to_children[parent_id].append(child_id)
    return dict(parent_to_children)


def _count_leading_dashes(s: str) -> int:
    """Count the number of leading dashes on a string."""
    for position, element in enumerate(s):
        if element != "-":
            return position
    raise ValueError


def get_interpro_to_proteins(
    *, force: bool = False, interpro_ids, module: pystow.Module
) -> Mapping[str, Set[str]]:
    """Get a mapping from InterPro identifiers to a set of UniProt identifiers."""
    cache_path = module.join(name="protein2ipr_human.tsv")

    if cache_path.is_file():
        interpro_to_uniprots = defaultdict(set)
        with cache_path.open() as file:
            for line in file:
                interpro_id, uniprot_id = line.strip().split("\t", 1)
                interpro_to_uniprots[interpro_id].add(uniprot_id)
        return dict(interpro_to_uniprots)

    path = module.ensure(url=INTERPRO_PROTEINS_URL, force=force)
    interpro_to_uniprots = defaultdict(set)
    with gzip.open(path, "rt") as file:
        for line in tqdm(
            file,
            unit_scale=True,
            unit="line",
            desc="Processing ipr2protein",
            total=1_216_508_710,
        ):
            uniprot_id, interpro_id, _ = line.split("\t", 2)
            if interpro_id not in interpro_ids:
                continue
            if uniprot_client.is_human(uniprot_id):
                interpro_to_uniprots[interpro_id].add(uniprot_id)

    interpro_to_uniprots = dict(interpro_to_uniprots)

    with cache_path.open("w") as file:
        for interpro_id, uniprot_ids in tqdm(
            sorted(interpro_to_uniprots.items()),
            unit_scale=True,
            desc="Writing human subset",
        ):
            for uniprot_id in sorted(uniprot_ids):
                print(interpro_id, uniprot_id, sep="\t", file=file)

    return interpro_to_uniprots


def get_interpro_to_goa(
    *, force: bool = False, module: pystow.Module
) -> Mapping[str, Set[str]]:
    """Get a mapping from InterPro identifiers to sets of GO id/name pairs.."""
    path = module.ensure(url=INTERPRO_GO_URL, name="interpro2go.tsv", force=force)
    interpro_to_go_annotations = defaultdict(set)
    with path.open() as file:
        for line in file:
            line = line.strip()
            if line[0] == "!":
                continue
            interpro_id, go_id = process_go_mapping_line(line)
            interpro_to_go_annotations[interpro_id].add(go_id)
    return dict(interpro_to_go_annotations)


def process_go_mapping_line(line: str) -> Tuple[str, str]:
    """Process a GO mapping file line.

    Example lines:

    .. code-block::

        !date: 2022/10/05 11:07:08
        !Mapping of InterPro entries to GO
        !external resource: http://www.ebi.ac.uk/interpro
        !citation: Blum et al. (2021) Nucl. Acids Res. 49:D344â€“D354
        !contact:interhelp@ebi.ac.uk!
        InterPro:IPR000003 Retinoid X receptor/HNF4 > GO:DNA binding ; GO:0003677
        InterPro:IPR000003 Retinoid X receptor/HNF4 > GO:nuclear steroid receptor activity ; GO:0003707
    """
    line = line[len("InterPro:") :]
    line, go_id = (part.strip() for part in line.rsplit(";", 1))
    line, _go_name = (part.strip() for part in line.rsplit(">", 1))
    interpro_id, _interpro_name = (part.strip() for part in line.split(" ", 1))
    return interpro_id, go_id
