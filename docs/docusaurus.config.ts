import {themes as prismThemes} from 'prism-react-renderer';
import type {Config} from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'AlphaCore',
  tagline: 'Sub-10ns order matching for Indian equity markets',
  favicon: 'img/favicon.ico',
  future: {
    v4: true,
  },
  url: 'https://alphacore.example.com',
  baseUrl: '/',
  organizationName: 'alphacore',
  projectName: 'alphacore',
  onBrokenLinks: 'throw',
  i18n: {
    defaultLocale: 'en',
    locales: ['en'],
  },
  presets: [
    [
      'classic',
      {
        docs: {
          sidebarPath: './sidebars.ts',
        },
        blog: false,
        theme: {
          customCss: './src/css/custom.css',
        },
      } satisfies Preset.Options,
    ],
  ],
  themeConfig: {
    image: 'img/docusaurus-social-card.jpg',
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: 'AlphaCore',
      logo: {
        alt: 'AlphaCore Logo',
        src: 'img/logo.svg',
      },
      items: [
        {to: '/docs/architecture', label: 'Architecture', position: 'left'},
        {to: '/docs/api-reference', label: 'API Reference', position: 'left'},
        {to: '/docs/strategy-guide', label: 'Strategy Guide', position: 'left'},
        {to: '/docs/performance-whitepaper', label: 'Performance Whitepaper', position: 'left'},
        {to: '/docs/runbook', label: 'Runbook', position: 'left'},
      ],
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Docs',
          items: [
            {label: 'Architecture', to: '/docs/architecture'},
            {label: 'API Reference', to: '/docs/api-reference'},
            {label: 'Strategy Guide', to: '/docs/strategy-guide'},
            {label: 'Performance Whitepaper', to: '/docs/performance-whitepaper'},
            {label: 'Runbook', to: '/docs/runbook'},
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} AlphaCore. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
