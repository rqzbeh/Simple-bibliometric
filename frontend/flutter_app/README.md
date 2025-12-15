# Flutter frontend scaffold for Simple-bibliometric

This directory contains guidance and a minimal scaffold plan for building a Flutter front-end that interacts with the Simple-bibliometric backend (FastAPI). The goal is to provide a modern, responsive UI (web & mobile) that lets users run bibliometric queries, inspect results, visualize author networks and download exports.

> Note: This directory includes a minimal, runnable Flutter web prototype at `lib/main.dart`. The prototype demonstrates an asynchronous job flow: it enqueues an analysis via `POST /analyze_async`, polls `/jobs/{job_id}`, and displays results (including export download links served from the backend). It's intended for local development and demonstration—ensure the backend API is running and CORS permits requests from the frontend origin. See "Running the included prototype (web)" below for quick start instructions.

---

## Overview

A minimal workflow for the Flutter app:

1. User enters a query and selects options (sources, max results, cache).
2. Flutter app sends a POST `/analyze` request to the backend.
3. Backend runs the analysis pipeline and returns a JSON summary with:
   - `n_publications`, `top_authors`, `time_series`, `forecast`
   - `graph_summary` (counts, sample degrees)
   - `exports` (paths to generated files; consider adding a secure file-serving endpoint)
   - `source_errors` (any crawl failures)
4. Flutter presents the results with lists, charts and an interactive network viewer (embedding viz or providing links to HTML files) and allows file downloads.

---

## Prerequisites

- Flutter SDK installed (https://flutter.dev/docs/get-started/install)
- For local testing, the backend API should be running:
  ```bash
  cd Simple-bibliometric
  pip install -r requirements.txt
  uvicorn api:app --reload --port 8000
  ```
- The backend `api` exposes a `POST /analyze` endpoint (see below).

Running the included prototype (web)
-----------------------------------
1. Ensure the backend is running and CORS permits your frontend origin (the API is permissive by default during development).
2. Start the Flutter prototype:
   ```bash
   cd frontend/flutter_app
   # Optionally create a `.env` file to override the API base URL, e.g.:
   # API_BASE_URL=http://localhost:8000
   flutter pub get
   flutter run -d chrome
   ```
3. The prototype demonstrates the async flow:
   - Enqueue an analysis via `POST /analyze_async`
   - Poll status with `GET /jobs/{job_id}`
   - When finished, fetch results with `GET /jobs/{job_id}/result`. The response includes `artifact_info` with `download_urls` (mapped to `/artifacts/{artifact_id}/download/{filename}`) and a `download_token` when applicable.

Alternative: Build and serve static web artifacts
```bash
cd frontend/flutter_app
flutter build web
# Serve the files under build/web/ with your preferred static server
```

If you need the frontend to talk to a backend running on a different host/port, set `API_BASE_URL` in the `.env` file inside `frontend/flutter_app` (for example `API_BASE_URL=http://localhost:8000`) before running the app.

---

## Backend API (quick reference)

- `POST /analyze` — request JSON:
  ```json
  {
    "query": "machine learning in healthcare",
    "max_results": 200,
    "sources": ["pubmed", "sage"],
    "use_cache": true,
    "cache_ttl_hours": 24
  }
  ```
- Response: JSON with keys like `n_publications`, `top_authors`, `time_series`, `forecast`, `graph_summary`, `exports`, `source_errors`.

- Example `curl`:
  ```bash
  curl -s -X POST "http://localhost:8000/analyze" \
    -H "Content-Type: application/json" \
    -d '{"query":"machine learning in healthcare","max_results":100}'
  ```

> Note: For production, consider adding authentication & secure file serving instead of exposing raw filesystem paths in `exports`.

---

## Flutter app: Getting started (skeleton)

1. Create a new Flutter app (web/mobile):
   ```bash
   flutter create flutter_app
   cd flutter_app
   ```

2. Add dependencies in `pubspec.yaml`:
   ```yaml
   dependencies:
     flutter:
       sdk: flutter
     http: ^0.14.0
     # Optional for charts:
     charts_flutter: ^0.12.0
     # or use charting packages you prefer (syncfusion, fl_chart, etc.)
   ```

3. Minimal `lib/main.dart` concept (very small example)
   ```dart
   import 'dart:convert';
   import 'package:flutter/material.dart';
   import 'package:http/http.dart' as http;

   void main() => runApp(MyApp());

   class MyApp extends StatelessWidget {
     @override
     Widget build(BuildContext context) {
       return MaterialApp(
         title: 'Simple Bibliometric',
         home: AnalyzePage(),
       );
     }
   }

   class AnalyzePage extends StatefulWidget {
     @override
     _AnalyzePageState createState() => _AnalyzePageState();
   }

   class _AnalyzePageState extends State<AnalyzePage> {
     final TextEditingController _queryController = TextEditingController();
     bool _useCache = true;
     int _maxResults = 200;
     Map<String, dynamic>? _result;
     bool _loading = false;

     Future<void> _runAnalysis() async {
       setState(() => _loading = true);
       try {
         final url = Uri.parse('http://localhost:8000/analyze');
         final resp = await http.post(url,
             headers: {'Content-Type': 'application/json'},
             body: jsonEncode({
               'query': _queryController.text,
               'max_results': _maxResults,
               'use_cache': _useCache
             }));
         if (resp.statusCode == 200) {
           setState(() {
             _result = jsonDecode(resp.body);
           });
         } else {
           final err = 'Server error: ${resp.statusCode}';
           ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(err)));
         }
       } catch (e) {
         ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Request failed: $e')));
       } finally {
         setState(() => _loading = false);
       }
     }

     @override
     Widget build(BuildContext context) {
       return Scaffold(
         appBar: AppBar(title: Text('Simple Bibliometric Explorer')),
         body: Padding(
           padding: EdgeInsets.all(16.0),
           child: Column(
             children: [
               TextField(controller: _queryController, decoration: InputDecoration(labelText: 'Query')),
               Row(
                 children: [
                   Text('Max results:'),
                   Expanded(child: Slider(value: _maxResults.toDouble(), min: 10, max: 1000, divisions: 99, label: '$_maxResults', onChanged: (v) { setState(() => _maxResults = v.round()); })),
                 ],
               ),
               CheckboxListTile(title: Text('Use cache'), value: _useCache, onChanged: (v) => setState(() => _useCache = v ?? true)),
               ElevatedButton(onPressed: _loading ? null : _runAnalysis, child: Text('Analyze')),
               if (_loading) CircularProgressIndicator(),
               if (_result != null) Expanded(child: SingleChildScrollView(child: Text(jsonEncode(_result), style: TextStyle(fontFamily: 'monospace')))),
             ],
           ),
         ),
       );
     }
   }
   ```

> This snippet is minimal and intended to illustrate the request/response flow. For production UIs you will implement richer components (data tables, charts and network visualizers).

---

## Suggested UI components & workflow

- **Search form**: `TextField` for query, multi-select for sources, slider / numeric input for max results, a cache toggle, and a Run button.
- **Progress / Status**: show a spinner or progress indicator. For long-running analyses, consider implementing a background job endpoint and poll for updates or use WebSockets.
- **Summary card**: show `n_publications`, quick stats, and `source_errors` (if any).
- **Top authors**: table (name, pubs, citations, h-index) + bar charts (publications / citations).
- **Trend visualization**: chart for publications per year and forecast (historical vs predicted).
- **Network view**:
  - Option A: embed server-generated pyvis HTML (returned in `exports`) into a WebView (web) or open in external browser.
  - Option B: implement a native Flutter graph viewer (e.g., use a canvas-based library or a plugin) to render simple node-edge graphs.
- **Downloads**: buttons to download CSV/JSON/BibTeX exported from server (either direct content or via a secure download endpoint).

---

## File serving & downloads

Currently the backend returns export paths in `exports`. For production-grade UI, consider:
- Exposing secure endpoints like `/download?file=<id>` that validates access and streams the file (FastAPI has `FileResponse`).
- Avoid returning raw absolute file paths to clients.

---

## Security and CORS

- The scaffolded backend described here accepts cross-origin requests for convenience. For deployed systems, ensure you:
  - Restrict CORS to trusted origins
  - Add authentication / API keys
  - Securely serve files (no path traversal)

---

## Next steps / roadmap ideas

- Background processing via a task queue (Celery/RQ) so `/analyze` enqueues a job and returns a job id for polling. Useful for long/heavy analyses.
- WebSocket or SSE endpoints for progress updates.
- Implement secure, authenticated file download endpoints and direct links in the UI.
- Add advanced visual analytics: interactive time-series, author comparison, community detection visual overlays, export to Gephi-ready formats.
- Build complete Flutter UI with modular widgets, state management (Provider / Riverpod / Bloc), and rich charting.

---

## Help & contribution

If you'd like, I can:
- Scaffold a complete Flutter app with core screens (Search / Results / Detail) and a simple charting integration.
- Add secure download endpoints to the backend for easy file-serving.
- Implement background job queue for asynchronous long-running analyses.

Tell me which direction you'd like me to take next and I can prepare a focused PR with the Flutter skeleton or the server-side download endpoints & background job integration.
