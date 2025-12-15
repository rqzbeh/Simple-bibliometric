# Icons Directory

This directory should contain the following icon files for the Flutter web application:

- `Icon-192.png` - 192x192 pixel icon
- `Icon-512.png` - 512x512 pixel icon
- `Icon-maskable-192.png` - 192x192 pixel maskable icon
- `Icon-maskable-512.png` - 512x512 pixel maskable icon

These icons are referenced in `web/manifest.json` and are used for Progressive Web App (PWA) functionality.

**Note:** The Flutter build will succeed without these files, but you may see warnings about missing icons. To add proper icons:

1. Create icon files with the sizes mentioned above
2. Place them in this directory
3. Commit and push the changes

You can use tools like:
- [Icon Generator](https://www.favicon-generator.org/)
- [PWA Asset Generator](https://github.com/onderceylan/pwa-asset-generator)
- Or create them manually using image editing software

For a quick placeholder, you can also let Flutter generate default icons by running:
```bash
cd frontend/flutter_app
flutter pub run flutter_launcher_icons:main
```
