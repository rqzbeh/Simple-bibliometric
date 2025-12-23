from bibliometrics import compute_author_metrics, build_coauthorship_graph

pubs = [
    {"title": "Paper A", "authors": [{"name": "Alice"}, {"name": "Bob"}], "citations": 5},
    {"title": "Paper B", "authors": [{"name": "Alice"}], "citations": 2},
]

authors = compute_author_metrics(pubs)
print('authors_len', len(authors))
for a in authors:
    print(getattr(a, 'name', None), getattr(a, 'n_publications', None), getattr(a, 'total_citations', None), getattr(a, 'h_index', None))

G = build_coauthorship_graph(pubs)
print('graph_nodes', G.number_of_nodes(), 'graph_edges', G.number_of_edges())
