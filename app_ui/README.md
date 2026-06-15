# App UI Module

## Purpose

`app_ui` is the React/Vite single-page workbench for extraction, rewrite, voice synthesis, video rendering, uploads, and task history.

## Entry Points

- `src/main.jsx`: React application and API calls.
- `src/app.css`: active UI layout and component styling.
- `dist/`: built static assets served by `api_server.py`.

## Internal Structure

- Keep application behavior in `src/main.jsx`.
- Keep visual system and responsive layout in `src/app.css`.
- `src/styles.css` is legacy and should not be imported by new code unless it is intentionally revived.

## Dependencies

- React
- Vite
- Lucide React icons

## Validation

```sh
npm run build
```
