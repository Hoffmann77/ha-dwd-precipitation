// @ts-check
// Documentation site of the DWD Precipitation integration.
//
// Three docs instances, each with its own sidebar:
//   docs/          user docs, served at the site root (docs-only mode)
//   development/   contributor docs, at /development
//   ../docs/adr/   the architecture decision records, at /development/adr,
//                  read in place so CLAUDE.md and the repo links keep working
// German translations of all three live under i18n/de/.

import {themes as prismThemes} from 'prism-react-renderer';

const REPO = 'https://github.com/Hoffmann77/ha-dwd-precipitation';

// Set by Docusaurus for each locale it builds; links that differ by language
// (labels are translated in i18n/, URLs are not) are picked here.
const LOCALE = process.env.DOCUSAURUS_CURRENT_LOCALE ?? 'en';

// The terms of use DWD Open Data names in https://opendata.dwd.de/README.txt.
const DWD_TERMS =
  LOCALE === 'de'
    ? 'https://www.dwd.de/DE/service/rechtliche_hinweise/rechtliche_hinweise_node.html'
    : 'https://www.dwd.de/EN/service/legal_notice/legal_notice_node.html';

/**
 * Edit link of a page: the English source, or the German translation on /de.
 * @param {string} pluginId the docs instance (its i18n folder name)
 * @param {string} sourceDir the English sources, relative to the repo root
 * @returns {import('@docusaurus/plugin-content-docs').EditUrlFunction}
 */
function editUrl(pluginId, sourceDir) {
  const i18nDir =
    pluginId === 'default'
      ? 'docusaurus-plugin-content-docs'
      : `docusaurus-plugin-content-docs-${pluginId}`;
  return ({locale, docPath}) =>
    locale === 'de'
      ? `${REPO}/edit/main/website/i18n/de/${i18nDir}/current/${docPath}`
      : `${REPO}/edit/main/${sourceDir}/${docPath}`;
}

/** @type {import('@docusaurus/types').Config} */
const config = {
  title: 'DWD Precipitation',
  tagline:
    'Precipitation nowcasts and analyses from the German Weather Service (DWD) for Home Assistant',

  url: 'https://hoffmann77.github.io',
  baseUrl: '/ha-dwd-precipitation/',
  organizationName: 'Hoffmann77',
  projectName: 'ha-dwd-precipitation',
  trailingSlash: false,

  onBrokenLinks: 'throw',
  onBrokenAnchors: 'throw',
  onDuplicateRoutes: 'throw',

  markdown: {
    // .md is CommonMark, .mdx is MDX: the ADRs are plain Markdown.
    format: 'detect',
    hooks: {
      onBrokenMarkdownLinks: 'throw',
    },
  },

  i18n: {
    defaultLocale: 'en',
    locales: ['en', 'de'],
    localeConfigs: {
      en: {label: 'English', htmlLang: 'en'},
      de: {label: 'Deutsch', htmlLang: 'de'},
    },
  },

  presets: [
    [
      'classic',
      /** @type {import('@docusaurus/preset-classic').Options} */
      ({
        docs: {
          routeBasePath: '/',
          sidebarPath: './sidebars.js',
          editUrl: editUrl('default', 'website/docs'),
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      }),
    ],
  ],

  plugins: [
    [
      '@docusaurus/plugin-content-docs',
      /** @type {import('@docusaurus/plugin-content-docs').Options} */
      ({
        id: 'development',
        path: 'development',
        routeBasePath: 'development',
        sidebarPath: './sidebarsDevelopment.js',
        editUrl: editUrl('development', 'website/development'),
      }),
    ],
    [
      '@docusaurus/plugin-content-docs',
      /** @type {import('@docusaurus/plugin-content-docs').Options} */
      ({
        id: 'adr',
        path: '../docs/adr',
        routeBasePath: 'development/adr',
        sidebarPath: './sidebarsAdr.js',
        editUrl: editUrl('adr', 'docs/adr'),
        // Keep the record number in the URL (/development/adr/0007-...).
        numberPrefixParser: false,
        // The index (README.md) is placed by hand at the top of the sidebar;
        // every numbered record is picked up on its own.
        async sidebarItemsGenerator({defaultSidebarItemsGenerator, ...args}) {
          const items = await defaultSidebarItemsGenerator(args);
          return items.filter((item) => !(item.type === 'doc' && item.id === 'README'));
        },
      }),
    ],
  ],

  themes: [
    [
      '@easyops-cn/docusaurus-search-local',
      /** @type {import('@easyops-cn/docusaurus-search-local').PluginOptions} */
      ({
        hashed: true,
        language: ['en', 'de'],
        indexBlog: false,
        docsPluginIdForPreferredVersion: 'default',
        docsRouteBasePath: ['/', 'development', 'development/adr'],
        docsDir: ['docs', 'development', '../docs/adr'],
        highlightSearchTermsOnTargetPage: true,
      }),
    ],
  ],

  themeConfig:
    /** @type {import('@docusaurus/preset-classic').ThemeConfig} */
    ({
      colorMode: {
        respectPrefersColorScheme: true,
      },
      navbar: {
        title: 'DWD Precipitation',
        items: [
          {
            type: 'docSidebar',
            sidebarId: 'docs',
            position: 'left',
            label: 'Docs',
          },
          {
            type: 'docSidebar',
            sidebarId: 'development',
            docsPluginId: 'development',
            position: 'left',
            label: 'Development',
          },
          {
            href: `${REPO}/releases`,
            position: 'left',
            label: 'Changelog',
          },
          {
            type: 'localeDropdown',
            position: 'right',
          },
          {
            href: REPO,
            position: 'right',
            label: 'GitHub',
          },
        ],
      },
      footer: {
        style: 'dark',
        links: [
          {
            title: 'Docs',
            items: [
              {label: 'Installation', to: '/getting-started/installation'},
              {label: 'Entities', to: '/entities/overview'},
              {label: 'Troubleshooting', to: '/help/troubleshooting'},
            ],
          },
          {
            title: 'Project',
            items: [
              {label: 'GitHub', href: REPO},
              {label: 'Issues', href: `${REPO}/issues`},
              {label: 'Releases', href: `${REPO}/releases`},
            ],
          },
          {
            title: 'Data',
            items: [
              {label: 'DWD Open Data', href: 'https://opendata.dwd.de/'},
              {label: 'DWD terms of use', href: DWD_TERMS},
            ],
          },
        ],
        copyright:
          'Radar data: Deutscher Wetterdienst (DWD). This is a community project, not affiliated with or endorsed by the DWD.',
      },
      prism: {
        theme: prismThemes.github,
        darkTheme: prismThemes.dracula,
        // django brings jinja2 (HA templates); yaml is in the default bundle.
        additionalLanguages: ['django'],
      },
    }),
};

export default config;
