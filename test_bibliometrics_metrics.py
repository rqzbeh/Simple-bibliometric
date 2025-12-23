
from bibliometrics import compute_author_metrics, build_coauthorship_graph


def make_pub(title, authors, citations=0, doi=None, year=2020):
    return {
        "title": title,
        "title_norm": title.lower(),
        "authors": authors,
        "citations": citations,
        "doi": doi or "",
        "year": year,
    }


def test_h_index_and_citation_aggregation():
    # Two authors with multiple coauthored and solo papers
    pubs = []
    # Alice solo papers
    pubs.append(make_pub("A1", [{"name": "Alice"}], citations=10))
    pubs.append(make_pub("A2", [{"name": "Alice"}], citations=5))
    # Bob solo
    pubs.append(make_pub("B1", [{"name": "Bob"}], citations=3))
    # Coauthored A&B
    pubs.append(make_pub("AB1", [{"name": "Alice"}, {"name": "Bob"}], citations=8))
    pubs.append(make_pub("AB2", [{"name": "Alice"}, {"name": "Bob"}], citations=2))

    metrics = compute_author_metrics(pubs)
    # Find authors
    m = {x.name: x for x in metrics}
    assert "Alice" in m and "Bob" in m
    # Alice: citations = 10+5+8+2 =25, n_pubs=4, h-index should be 4? citations sorted [10,8,5,2] -> h=4? 2>=4 false, but 4th (2) <4 so h=3? Let's assert exact
    alice = m["Alice"]
    assert alice.total_citations == 25
    assert alice.n_publications == 4
    assert alice.h_index == 3

    bob = m["Bob"]
    assert bob.total_citations == 13
    assert bob.n_publications == 3
    assert bob.h_index == 2


def test_coauthorship_graph_basic():
    pubs = []
    pubs.append(make_pub("P1", [{"name": "Alice"}, {"name": "Bob"}], citations=5))
    pubs.append(make_pub("P2", [{"name": "Alice"}, {"name": "Carol"}], citations=2))
    pubs.append(make_pub("P3", [{"name": "Bob"}, {"name": "Carol"}], citations=1))

    G = build_coauthorship_graph(pubs)
    # Check nodes
    assert any("alice" in n.lower() or n == "alice" for n in G.nodes())
    # Edge weights: Alice-Bob should be 1
    # Get node ids for names
    alice_id = next(n for n, d in G.nodes(data=True) if d.get("display_name") == "Alice")
    bob_id = next(n for n, d in G.nodes(data=True) if d.get("display_name") == "Bob")
    assert G.has_edge(alice_id, bob_id)
    assert G[alice_id][bob_id]["weight"] == 1

    # Node attributes present
    assert G.nodes[alice_id].get("n_pubs", 0) >= 1
    assert G.nodes[alice_id].get("total_citations", 0) >= 0
