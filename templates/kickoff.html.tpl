<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'">
  <title>{{title}}</title>
  <style>{{style}}</style>
</head>
<body>
  <a class="skip" href="#main">Skip to project plan</a>
  <header class="topbar">
    <div><p class="eyebrow">PROJECTFORGE KICKOFF</p><h1>{{title}}</h1><p>{{summary}}</p></div>
    <span class="status status-{{status_slug}}">{{status}}</span>
  </header>
  <div class="layout">
    <nav aria-label="Project sections"><h2>On this page</h2>{{navigation}}</nav>
    <main id="main">{{content}}</main>
  </div>
  <footer>Generated from manifest version {{version}}. Keep the manifest as the source of truth.</footer>
  <script>{{script}}</script>
</body>
</html>
