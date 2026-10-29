// @ts-check
// Sidebar of the user docs (website/docs/), served at the site root.

/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  docs: [
    'intro',
    {
      type: 'category',
      label: 'Getting started',
      collapsed: false,
      items: ['getting-started/installation', 'getting-started/configuration'],
    },
    {
      type: 'category',
      label: 'Entities',
      collapsed: false,
      link: {type: 'doc', id: 'entities/overview'},
      items: [
        'entities/radvor-rs',
        'entities/radvor-rv',
        'entities/hymecng',
        'entities/radolan',
        'entities/totals',
        'entities/dry-streak',
        'entities/rain-events',
        'entities/rain-warnings',
        'entities/attributes',
      ],
    },
    {
      type: 'category',
      label: 'How it works',
      items: [
        'how-it-works/dwd-products',
        'how-it-works/release-timing',
        'how-it-works/grid-lookup',
        'how-it-works/availability',
      ],
    },
    {
      type: 'category',
      label: 'Help',
      items: ['help/troubleshooting', 'help/faq', 'help/upgrading'],
    },
  ],
};

export default sidebars;
