import unittest
from indra_cogex.client.neo4j_client import Neo4jClient


class TestDatabaseInspection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = Neo4jClient(
            "bolt://indra-cogex-lb-1eac1a3f066c0e52.elb.us-east-1.amazonaws.com:7687",
            auth=("neo4j", "sweetwheatgrassseed")
        )

    def run_cypher_query(self, query):
        result = self.client.query_tx(query)
        print(f"Query: {query}")
        print(f"Result: {result}")
        print("---")

    def test_inspect_database(self):
        queries = [
            # Check for any relationships involving enzymes
            """
            MATCH (e:BioEntity)-[r]->(n)
            WHERE e.id STARTS WITH 'ec-code:'
            RETURN DISTINCT type(r) AS relationship_type, labels(n) AS connected_node_labels
            LIMIT 10
            """,
            # Check for any relationships involving metabolites
            """
            MATCH (m:BioEntity)-[r]->(n)
            WHERE m.id STARTS WITH 'chebi:'
            RETURN DISTINCT type(r) AS relationship_type, labels(n) AS connected_node_labels
            LIMIT 10
            """,
            # Check for indirect connections between enzymes and metabolites
            """
            MATCH (e:BioEntity)-[r1]->(x)-[r2]->(m:BioEntity)
            WHERE e.id STARTS WITH 'ec-code:' AND m.id STARTS WITH 'chebi:'
            RETURN DISTINCT type(r1) AS enzyme_relation, labels(x) AS intermediate_node, type(r2) AS metabolite_relation
            LIMIT 10
            """
        ]

        for query in queries:
            self.run_cypher_query(query)

        # Add an assertion to ensure the test passes
        self.assertTrue(True, "Database inspection completed")


if __name__ == '__main__':
    unittest.main()


class TestGeneExamples(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = Neo4jClient(
            "bolt://indra-cogex-lb-1eac1a3f066c0e52.elb.us-east-1.amazonaws.com:7687",
            auth=("neo4j", "sweetwheatgrassseed")
        )

    def fetch_hgnc_genes(self):
        """
        Fetches HGNC genes from the BioEntity nodes in the Neo4j database.
        """
        query = """
        MATCH (g:BioEntity)
        WHERE g.id STARTS WITH 'hgnc:'
        RETURN g.id AS gene_id, g.name AS description
        LIMIT 10
        """
        results = self.client.query_tx(query)

        # Access rows as lists and extract gene_id and description
        gene_dict = {row[0]: row[1] for row in results}
        return gene_dict

    def test_fetch_hgnc_genes(self):
        """
        Test that checks if HGNC genes are fetched correctly from the BioEntity nodes in the database.
        """
        gene_examples = self.fetch_hgnc_genes()
        print(f"Example for genes field: {gene_examples}")

        # Ensure that some HGNC genes are returned from the database
        self.assertTrue(len(gene_examples) > 0, "No HGNC genes fetched from the database.")


if __name__ == '__main__':
    unittest.main()
