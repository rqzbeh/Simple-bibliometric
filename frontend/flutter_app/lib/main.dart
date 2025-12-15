import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:url_launcher/url_launcher.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';

void main() async {
  // Load .env if it exists, but don't fail if it doesn't
  try {
    await dotenv.load(fileName: ".env");
  } catch (_) {
    // .env file is optional
  }
  runApp(const MyApp());
}

class MyApp extends StatelessWidget {
  const MyApp({Key? key}) : super(key: key);

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Simple Bibliometric Explorer',
      theme: ThemeData(
        primarySwatch: Colors.blue,
        visualDensity: VisualDensity.adaptivePlatformDensity,
      ),
      home: const AnalyzePage(),
    );
  }
}

class AnalyzePage extends StatefulWidget {
  const AnalyzePage({Key? key}) : super(key: key);

  @override
  State<AnalyzePage> createState() => _AnalyzePageState();
}

class _AnalyzePageState extends State<AnalyzePage> {
  final TextEditingController _queryController = TextEditingController(text: 'machine learning in healthcare');
  bool _useCache = true;
  int _maxResults = 200;
  String _jobId = '';
  String _status = '';
  Map<String, dynamic>? _result;
  bool _loading = false;
  Timer? _pollTimer;

  String get _apiBaseUrl {
    // Try to get from .env, fallback to default
    try {
      return dotenv.env['API_BASE_URL'] ?? 'http://localhost:8000';
    } catch (_) {
      return 'http://localhost:8000';
    }
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    _queryController.dispose();
    super.dispose();
  }

  Future<void> _runAnalysis() async {
    setState(() {
      _loading = true;
      _status = 'Submitting analysis request...';
      _result = null;
      _jobId = '';
    });

    try {
      // Step 1: Enqueue the analysis
      final url = Uri.parse('$_apiBaseUrl/analyze_async');
      final resp = await http.post(
        url,
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode({
          'query': _queryController.text,
          'max_results': _maxResults,
          'use_cache': _useCache,
          'sources': ['pubmed', 'sage', 'crossref'],
        }),
      );

      if (resp.statusCode == 200 || resp.statusCode == 201) {
        final data = jsonDecode(resp.body);
        _jobId = data['job_id'];
        setState(() {
          _status = 'Job submitted: $_jobId. Polling for results...';
        });
        _startPolling();
      } else {
        _showError('Failed to submit job: ${resp.statusCode} - ${resp.body}');
      }
    } catch (e) {
      _showError('Request failed: $e');
    }
  }

  void _startPolling() {
    _pollTimer?.cancel();
    _pollTimer = Timer.periodic(const Duration(seconds: 2), (_) async {
      await _checkJobStatus();
    });
  }

  Future<void> _checkJobStatus() async {
    if (_jobId.isEmpty) return;

    try {
      final url = Uri.parse('$_apiBaseUrl/jobs/$_jobId');
      final resp = await http.get(url);

      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        final status = data['status'];
        
        setState(() {
          _status = 'Job status: $status';
        });

        if (status == 'completed') {
          _pollTimer?.cancel();
          await _fetchResult();
        } else if (status == 'failed') {
          _pollTimer?.cancel();
          _showError('Job failed: ${data['error'] ?? 'Unknown error'}');
        }
      } else {
        _showError('Failed to check status: ${resp.statusCode}');
      }
    } catch (e) {
      _showError('Polling failed: $e');
    }
  }

  Future<void> _fetchResult() async {
    try {
      final url = Uri.parse('$_apiBaseUrl/jobs/$_jobId/result');
      final resp = await http.get(url);

      if (resp.statusCode == 200) {
        final data = jsonDecode(resp.body);
        setState(() {
          _result = data;
          _status = 'Analysis complete!';
          _loading = false;
        });
      } else {
        _showError('Failed to fetch result: ${resp.statusCode}');
      }
    } catch (e) {
      _showError('Failed to fetch result: $e');
    }
  }

  void _showError(String message) {
    setState(() {
      _status = 'Error: $message';
      _loading = false;
    });
    _pollTimer?.cancel();
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(message), backgroundColor: Colors.red),
    );
  }

  Future<void> _launchUrl(String url) async {
    final uri = Uri.parse(url);
    if (await canLaunchUrl(uri)) {
      await launchUrl(uri);
    } else {
      _showError('Could not launch $url');
    }
  }

  Widget _buildResultsView() {
    if (_result == null) return const SizedBox.shrink();

    final nPubs = _result!['n_publications'] ?? 0;
    final topAuthors = _result!['top_authors'] as List<dynamic>? ?? [];
    final artifactInfo = _result!['artifact_info'] as Map<String, dynamic>?;
    final downloadUrls = artifactInfo?['download_urls'] as Map<String, dynamic>? ?? {};
    final sourceErrors = _result!['source_errors'] as Map<String, dynamic>? ?? {};

    return SingleChildScrollView(
      child: Padding(
        padding: const EdgeInsets.all(16.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16.0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Summary',
                      style: Theme.of(context).textTheme.headlineSmall,
                    ),
                    const SizedBox(height: 8),
                    Text('Publications found: $nPubs'),
                    if (sourceErrors.isNotEmpty) ...[
                      const SizedBox(height: 8),
                      Text(
                        'Source errors: ${sourceErrors.length}',
                        style: const TextStyle(color: Colors.orange),
                      ),
                    ],
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),
            if (topAuthors.isNotEmpty) ...[
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Top Authors',
                        style: Theme.of(context).textTheme.headlineSmall,
                      ),
                      const SizedBox(height: 8),
                      ...topAuthors.take(10).map((author) {
                        return ListTile(
                          dense: true,
                          title: Text(author['name'] ?? 'Unknown'),
                          subtitle: Text(
                            'Pubs: ${author['publications'] ?? 0}, Citations: ${author['citations'] ?? 0}, h-index: ${author['h_index'] ?? 0}',
                          ),
                        );
                      }).toList(),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),
            ],
            if (downloadUrls.isNotEmpty) ...[
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16.0),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Downloads',
                        style: Theme.of(context).textTheme.headlineSmall,
                      ),
                      const SizedBox(height: 8),
                      ...downloadUrls.entries.map((entry) {
                        final fullUrl = entry.value.toString().startsWith('http')
                            ? entry.value.toString()
                            : '$_apiBaseUrl${entry.value}';
                        return ListTile(
                          dense: true,
                          leading: const Icon(Icons.download),
                          title: Text(entry.key),
                          onTap: () => _launchUrl(fullUrl),
                        );
                      }).toList(),
                    ],
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Simple Bibliometric Explorer'),
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                TextField(
                  controller: _queryController,
                  decoration: const InputDecoration(
                    labelText: 'Query',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    const Text('Max results:'),
                    Expanded(
                      child: Slider(
                        value: _maxResults.toDouble(),
                        min: 10,
                        max: 500,
                        divisions: 49,
                        label: '$_maxResults',
                        onChanged: (v) {
                          setState(() => _maxResults = v.round());
                        },
                      ),
                    ),
                    Text('$_maxResults'),
                  ],
                ),
                CheckboxListTile(
                  title: const Text('Use cache'),
                  value: _useCache,
                  onChanged: (v) => setState(() => _useCache = v ?? true),
                ),
                ElevatedButton.icon(
                  onPressed: _loading ? null : _runAnalysis,
                  icon: const Icon(Icons.search),
                  label: const Text('Run Analysis'),
                ),
                if (_status.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Card(
                    color: _status.contains('Error') ? Colors.red[100] : Colors.blue[50],
                    child: Padding(
                      padding: const EdgeInsets.all(8.0),
                      child: Row(
                        children: [
                          if (_loading) ...[
                            const SizedBox(
                              width: 16,
                              height: 16,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            ),
                            const SizedBox(width: 8),
                          ],
                          Expanded(child: Text(_status)),
                        ],
                      ),
                    ),
                  ),
                ],
              ],
            ),
          ),
          Expanded(child: _buildResultsView()),
        ],
      ),
    );
  }
}
