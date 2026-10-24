---
title: Installation
description: Install DWD Precipitation from the Marketplace, with HACS or by hand, then add it to Home Assistant.
---

## Requirements

- Home Assistant 2025.4 or newer, which can reach `opendata.dwd.de` over
  HTTPS.
- A location in Germany, or close to its border. See
  [Grid cell lookup](../how-it-works/grid-lookup.md) for what is covered.

No account or API key is needed.

How you install depends on your Home Assistant version: from Home Assistant
2026.11 on, community integrations come from the **Marketplace**, which is
built in. Before that, they came from [HACS](https://hacs.xyz), which you
installed yourself.

## Install from the Marketplace (Home Assistant 2026.11 and newer) {#install-from-the-marketplace}

1. Open DWD Precipitation in the Marketplace with this button:

   [![Open your Home Assistant instance and open a repository in the Marketplace.](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=Hoffmann77&repository=ha-dwd-precipitation&category=integration)

   Or go to **Settings > Marketplace** and search for **DWD Precipitation**.
   The first time you open the Marketplace, it asks you to accept a warning
   that community content is not checked by the Home Assistant project.
2. Select **Install**, check the version, and select **Install** again.
3. The setup opens by itself when the installation is done. No restart is
   needed. If you closed it, [add the integration](#add-the-integration)
   yourself.

**Updates** appear under **Settings > Updates**, next to the updates of Home
Assistant itself, with the release notes. After you install one, restart
Home Assistant; a repair under **Settings > System > Repairs** reminds you
and can restart it for you. A new release can take a few hours to show up
there, because the Marketplace only checks the catalog for new versions
every few hours.

### Coming from HACS

If you installed DWD Precipitation with HACS, there is nothing to do: when
Home Assistant 2026.11 starts for the first time, the Marketplace takes over
everything HACS installed. DWD Precipitation stays installed, keeps its
settings and entities, and keeps getting updates.

## Install with HACS (Home Assistant 2026.10 and older) {#install-with-hacs-recommended}

If you do not have [HACS](https://hacs.xyz) yet, install it first.

1. Open DWD Precipitation in HACS with this button:

   [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Hoffmann77&repository=ha-dwd-precipitation&category=integration)

   Or open HACS and search for **DWD Precipitation**.
2. Select **Download**.
3. [Restart Home Assistant](#restart-home-assistant).
4. [Add the integration](#add-the-integration).

HACS shows a notification when a new version is out; update from there and
restart Home Assistant again.

## Manual installation

1. Download the latest release from
   [GitHub Releases](https://github.com/Hoffmann77/ha-dwd-precipitation/releases/latest)
   and extract it.
2. Copy the `custom_components/dwd_precipitation` folder into the
   `custom_components` folder of your Home Assistant configuration directory,
   so that you end up with `/config/custom_components/dwd_precipitation/`.
3. [Restart Home Assistant](#restart-home-assistant).
4. [Add the integration](#add-the-integration).

To update, replace that folder with the one from the new release. A manual
installation is not updated automatically.

## Restart Home Assistant

After installing with HACS or by hand, and after every update, Home Assistant
needs a restart to load the new code (**Settings > System > Restart**). Only
a first installation from the Marketplace works without one.

## Add the integration

Use this button:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=dwd_precipitation)

Or add it yourself:

1. Go to **Settings > Devices & services**.
2. Select **Add integration** and search for **DWD Precipitation**.
3. Enter a name and pick the location. See [Configuration](configuration.md)
   for both.

The sensors fill in within a few minutes: each DWD product is fetched once at
startup and then whenever DWD publishes a new file.

## Removing the integration

1. Go to **Settings > Devices & services > DWD Precipitation**, open the
   entry's menu and select **Delete**. This also deletes the integration's
   stored data, such as the rain events record.
2. Remove the code as well:
   - **Marketplace:** when you delete the last entry, Home Assistant asks
     whether to uninstall DWD Precipitation too. You can also uninstall it
     later from its page in the Marketplace (three dots menu, then
     **Uninstall**). The Marketplace does not uninstall it while an entry
     still exists, and offers **Delete and uninstall** instead. If Home
     Assistant still has it loaded, a repair asks you to restart.
   - **HACS:** remove it in HACS, then restart Home Assistant.
   - **Manual installation:** delete the `custom_components/dwd_precipitation`
     folder, then restart Home Assistant.
