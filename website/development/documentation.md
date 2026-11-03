---
title: Working on these docs
description: How to run, write and translate the DWD Precipitation documentation site.
---

This site is built with [Docusaurus](https://docusaurus.io/) from the
`website/` folder of the repository, and published to GitHub Pages when a
release is published.

## Running it locally

You need Node.js (the version in `website/.nvmrc`) and npm.

```sh
cd website
npm ci
npm start              # English, reloads on every change
npm run start:de       # German
```

Search only works in a production build:

```sh
npm run build          # both languages; fails on broken links
npm run serve
```

## Where the pages live

The site has three parts, each with its own folder and sidebar:

| Part | English sources | Sidebar | URL |
|------|-----------------|---------|-----|
| User docs | `website/docs/` | `website/sidebars.js` | `/` |
| Development | `website/development/` | `website/sidebarsDevelopment.js` | `/development` |
| Architecture decisions | `docs/adr/` | `website/sidebarsAdr.js` | `/development/adr` |

The ADRs are read from `docs/adr/` in place, so they stay next to the code.
A new ADR joins the sidebar by its file name; no sidebar change is needed.

`.md` files are CommonMark, `.mdx` files MDX. Use `.md` unless a page needs
React components. Admonitions (`:::note`, `:::warning`) work in both.

### Links

- Within one part, link to the file: `[Configuration](../getting-started/configuration.md)`.
  The build checks these.
- Across parts, link to the URL path: `[ADR 0007](/development/adr/0007-staleness-deadline-on-the-overdue-release)`.
  It resolves to the same language the reader is in.
- Images from `docs/assets/` are served at the site root:
  `![Setup dialog](/screenshot_config_flow.png)`.

## English and German

Every page exists in English and German. The German pages mirror the English
folders file for file:

| English | German |
|---------|--------|
| `website/docs/` | `website/i18n/de/docusaurus-plugin-content-docs/current/` |
| `website/development/` | `website/i18n/de/docusaurus-plugin-content-docs-development/current/` |
| `docs/adr/` | `website/i18n/de/docusaurus-plugin-content-docs-adr/current/` |

So a change to a page, or a new ADR, comes with its German counterpart.
`tests/parser/test_website.py` fails when a page is missing on either side.

Labels outside the pages (navbar, footer, sidebar categories) are translated
in the JSON files under `website/i18n/de/`. After adding a sidebar category
or navbar item, run `npm run write-translations` to add its key, then
translate it. `code.json` holds only the theme strings Docusaurus does not
already translate.

The German pages use the German entity names from
`custom_components/dwd_precipitation/translations/de.json`, since that is what
Home Assistant shows in German. Entity ids are the same in both languages:
Home Assistant builds them from the English name. They address the reader
with "du", as Home Assistant's German UI does.

German headings carry the id of the English heading they translate, so that
links to an anchor work in both languages:

```md
## Quelle des Trockenzählers {#dry-streak-source}
```

The id is the slug Docusaurus generates from the English heading. A missing
or wrong id fails the build as soon as a link points to the heading, and
`tests/parser/test_website.py` checks every heading.

## Publishing

`docs-deploy.yml` builds and publishes the site when a release is published,
so the docs describe the latest release. To publish a docs-only fix in
between, run the workflow by hand from the Actions tab. `docs-build.yml`
builds every pull request that touches the docs, so a broken link shows up
before it is merged.
