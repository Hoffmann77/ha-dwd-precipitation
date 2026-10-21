---
title: Installation
description: Install DWD Precipitation with HACS or by hand, then add it to Home Assistant.
---

## Requirements

- Home Assistant 2025.4 or newer, which can reach `opendata.dwd.de` over
  HTTPS.
- A location in Germany, or close to its border. See
  [Grid cell lookup](../how-it-works/grid-lookup.md) for what is covered.

No account or API key is needed.

## Install with HACS (recommended)

If you do not have [HACS](https://hacs.xyz) yet, install it first.

1. Add this repository to HACS with this button:

   [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Hoffmann77&repository=ha-dwd-precipitation&category=Integration)

2. Select **Download** in HACS.
3. [Restart Home Assistant](#restart-home-assistant).
4. [Add the integration](#add-the-integration).

HACS shows a notification when a new version is out; update from there and
restart Home Assistant again.

### Adding the repository by hand

If the button does not work for you, add the repository to HACS yourself:

1. Open HACS.
2. Select the three dots in the top right corner, then **Custom repositories**.
3. Enter `https://github.com/Hoffmann77/ha-dwd-precipitation` as the
   repository and select **Integration** as the type.
4. Select **Add**. DWD Precipitation now appears in HACS and can be
   downloaded.

## Manual installation

1. Download the latest release from
   [GitHub Releases](https://github.com/Hoffmann77/ha-dwd-precipitation/releases/latest)
   and extract it.
2. Copy the `custom_components/dwd_precipitation` folder into the
   `custom_components` folder of your Home Assistant configuration directory,
   so that you end up with `/config/custom_components/dwd_precipitation/`.

To update, replace that folder with the one from the new release. A manual
installation is not updated automatically.

## Restart Home Assistant

Home Assistant only loads a new or updated custom integration on start, so
restart it after installing or updating (**Settings > System > Restart**).

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
2. To remove the code as well, remove it in HACS (or delete the
   `custom_components/dwd_precipitation` folder) and restart Home Assistant.
