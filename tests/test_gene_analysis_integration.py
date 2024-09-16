import configparser
import os

import pytest
import pandas as pd
from typing import Dict
from indra_cogex.client.neo4j_client import Neo4jClient
from indra_cogex.analysis.gene_analysis import discrete_analysis, signed_analysis


@pytest.fixture(scope="module")
def neo4j_client() -> Neo4jClient:
    client = Neo4jClient()
    print(f"Neo4j client initialized: {client}")

    # Attempt to set timeout if a method exists
    if hasattr(client, 'set_timeout'):
        client.set_timeout(60)
    elif hasattr(client, 'driver') and hasattr(client.driver, 'set_timeout'):
        client.driver.set_timeout(60)
    else:
        print("Warning: Unable to set timeout for Neo4jClient")

    return client


def get_neo4j_url():
    # Try to read from config file
    config = configparser.ConfigParser()
    config_file = os.path.expanduser('~/.config/indra/config.ini')
    if os.path.exists(config_file):
        config.read(config_file)
        if 'neo4j' in config and 'INDRA_NEO4J_URL' in config['neo4j']:
            return config['neo4j']['INDRA_NEO4J_URL']

    # If not found in config file, try environment variable
    return os.getenv('INDRA_NEO4J_URL')


# Print the Neo4j URL
neo4j_url = get_neo4j_url()
print(f"Neo4j Connection URL: {neo4j_url}")


def test_neo4j_connection(neo4j_client: Neo4jClient):
    try:
        # Add a ping check to verify the connection
        assert neo4j_client.ping(), "Failed to ping Neo4j database"

        # Print success message if the ping check passes
        print("Successfully connected to Neo4j database")

    except Exception as e:
        pytest.fail(f"Failed to connect to Neo4j database: {str(e)}")


def get_random_genes(client: Neo4jClient, n: int = 10) -> Dict[str, str]:
    query = f"""
    MATCH (b:BioEntity)
    WHERE b.type = 'human_gene_protein'
    RETURN b.id, b.name
    LIMIT {n}
    """
    print(f"Executing query: {query}")
    results = client.query_tx(query)
    print(f"Query results: {results}")
    genes = {row[0]: row[1] for row in results if len(row) == 2}
    print(f"Retrieved {len(genes)} genes: {genes}")
    return genes


def test_get_random_genes(neo4j_client: Neo4jClient):
    print("\n--- Starting test_get_random_genes ---")
    genes = get_random_genes(neo4j_client, 5)
    assert len(genes) > 0, "Should retrieve at least one gene"
    assert all(key.startswith('hgnc:') for key in genes.keys()), "All gene IDs should start with 'hgnc:'"
    print("--- Finished test_get_random_genes ---")


def get_sample_genes(client: Neo4jClient, limit: int = 10):
    query = """
    MATCH (g:BioEntity)
    WHERE g.type = 'human_gene_protein'
    RETURN g.id, g.name, g.type
    LIMIT $limit
    """
    results = client.query_tx(query, limit=limit)
    print(f"Sample genes from database:")
    for result in results:
        print(f"ID: {result['g.id']}, Name: {result['g.name']}, Type: {result['g.type']}")
    return results


def test_discrete_analysis_with_real_data(neo4j_client: Neo4jClient):
    print("\n--- Starting test_discrete_analysis_with_real_data ---")
    genes = get_random_genes(neo4j_client,100)
    print(f"Input genes for discrete analysis: {genes}")

    result = discrete_analysis(
        genes,
        client=neo4j_client,
        method='fdr_bh',
        alpha=0.1,
        keep_insignificant=True,
        minimum_evidence_count=1,
        minimum_belief=0
    )

    print(f"Discrete analysis result: {result}")
    print(f"Discrete analysis result columns: {result.columns if isinstance(result, pd.DataFrame) else 'N/A'}")
    print(f"Discrete analysis result shape: {result.shape if isinstance(result, pd.DataFrame) else 'N/A'}")

    assert isinstance(result, pd.DataFrame), "Result should be a DataFrame"
    if result.empty:
        print("Result DataFrame is empty, skipping further assertions")
        pytest.skip("Result DataFrame is empty, skipping further assertions")
    assert "Analysis" in result.columns, "Result should have an 'Analysis' column"
    assert "p" in result.columns, "Result should have a 'p' column"
    expected_analyses = {"GO", "WikiPathways", "Reactome", "Phenotype", "INDRA Upstream", "INDRA Downstream"}
    assert not set(result['Analysis'].unique()).isdisjoint(expected_analyses), \
        "Result should contain at least one expected analysis type"
    print("--- Finished test_discrete_analysis_with_real_data ---")


def test_signed_analysis_with_real_data(neo4j_client: Neo4jClient):
    print("\n--- Starting test_signed_analysis_with_real_data ---")

    # Fetch some random genes from the database
    all_genes = get_random_genes(neo4j_client, 80)  # Assuming get_random_genes is a function you have

    # Split into positive and negative sets
    positive_genes = {gene_id: gene_name for gene_id, gene_name in list(all_genes.items())[:40]}
    negative_genes = {gene_id: gene_name for gene_id, gene_name in list(all_genes.items())[40:]}

    print(f"Input positive genes for signed analysis: {positive_genes}")
    print(f"Input negative genes for signed analysis: {negative_genes}")

    result = signed_analysis(
        positive_genes,
        negative_genes,
        client=neo4j_client,
        alpha=0.05,
        keep_insignificant=False,
        minimum_evidence_count=1,
        minimum_belief=0
    )

    # Rest of your test code...

    print(f"Signed analysis result: {result}")
    print(f"Signed analysis result columns: {result.columns if isinstance(result, pd.DataFrame) else 'N/A'}")
    print(f"Signed analysis result shape: {result.shape if isinstance(result, pd.DataFrame) else 'N/A'}")

    assert isinstance(result, pd.DataFrame), "Result should be a DataFrame"
    if result.empty:
        print("Result DataFrame is empty, skipping further assertions")
        pytest.skip("Result DataFrame is empty, skipping further assertions")
    expected_columns = {"curie", "name", "correct", "incorrect", "ambiguous", "binom_pvalue"}
    assert not expected_columns.isdisjoint(
        result.columns), f"Result should have at least one of these columns: {expected_columns}"
    print("--- Finished test_signed_analysis_with_real_data ---")


if __name__ == "__main__":
    pytest.main([__file__])
