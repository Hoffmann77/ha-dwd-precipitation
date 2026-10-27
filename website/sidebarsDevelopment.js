// @ts-check
// Sidebar of the contributor docs (website/development/), at /development.

/** @type {import('@docusaurus/plugin-content-docs').SidebarsConfig} */
const sidebars = {
  development: [
    'index',
    'architecture',
    'adding-a-product',
    'tests-and-checks',
    'documentation',
    {
      type: 'link',
      label: 'Architecture decisions',
      href: '/development/adr',
    },
  ],
};

export default sidebars;
