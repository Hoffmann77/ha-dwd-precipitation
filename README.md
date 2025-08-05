# DWD Precipitation

This custom Home Assistant component provides real-time (now) and historical precipitation data (last hour, last 24 hours), as well as short-term forecasts (up to two hours ahead) for Germany. 
The data is based on high-resolution radar and station-based measurements, derived from the DWD’s (Deutscher Wetterdienst) Radolan and Radvor products. 

It offers precise, quantitative analyses and predictions with high temporal and spatial resolution, enabling accurate tracking of rain events at your exact location. 
Ideal for automations and early warnings of severe precipitation.


## Entities

Entitiy | Description | Data source |
| ---- | ---- | ---- |
| `Precipitation +2 hours`| Calibrated precipitation forecast [mm/h] for the timespan from +60 minutes to +120 minutes | Radvor RQ |
| `Precipitation +1 hours`| Calibrated precipitation forecast [mm/h] for the next 60 minutes | Radvor RQ |
| `Precipitation now`| Calibrated precipitation analysis [mm/h] | Radvor RQ |
| `Precipitation last hour`| Adjusted quantitative radar precipitation estimate [mm/h] for the last hour | Radolan RW |
| `Precipitation last 24 hours`| Adjusted quantitative radar precipitation estimate [mm/h] for the last 24 hour | Radolan SF |
| `Precipitation today`| Adjusted quantitative radar precipitation estimate [mm/h] for today | Radolan SF |
| `Precipitation yesterday`| Adjusted quantitative radar precipitation estimate [mm/h] for yesterday | Radolan SF |

## Installation
### Install using HACS (recommended)
If you do not have HACS installed yet visit https://hacs.xyz for installation instructions.

To add the this repository to HACS in your Home Assistant instance, use this Button:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Hoffmann77&repository=ha-dwd-precipitation&category=Integration)

After installation, please restart Home Assistant. To add Power Insight to your Home Assistant instance, use this Button:

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=dwd_precipitation)

<details>
<summary>Manual configuration steps</summary>

### Semi-Manual Installation with HACS
1. Go HACS integrations section.
2. Click on the 3 dots in the top right corner.
3. Select "Custom repositories"
4. Add the URL (https://github.com/hoffmann77/ha-dwd-precipitation) to the repository.
5. Select the integration category.
6. Click the "ADD" button.
7. Now you are able to download the integration

## Manual Installation
1. Access the GitHub repository for this integration.
2. Download the ZIP file of the repository and extract its contents.
3. Copy the "dwd_precipitation" folder into the custom_components directory located typically at /config/custom_components/ in your Home Assistant directory.

## Restart Home Assistant
1. Restart your Home Assistant.

## Add Integration
1. Navigate to Settings > Devices & Services.
2. Click Add Integration and search for "DWD Precipitation".
3. Select the DWD Precipitation integration to initiate setup.

</details>

## Data source

All data is derived from the **DWD (Deutscher Wetterdienst)**.

**[RADVOR](https://www.dwd.de/EN/ourservices/radvor/radvor.html;jsessionid=8CA76D75D79EBFAA7B647D6D0643A174.live11052) (Radar Real-Time Forecasting):**
- Real-time quantitative precipitation analyses and forecasts for lead times up to two hours for Germany in high temporal and spatial resolution.

**[RADOLAN](https://www.dwd.de/DE/leistungen/radolan/radolan.html) (Radar online aneichung):**
- Real-time analysis of precipitation levels based on radar and station-based measurements.

## License

This integration is only possible thanks to the great work done by the contributors of the **[wradlib](https://github.com/wradlib/wradlib)** package.

All contents of the `radar` folder are thereby **licensed** under the [Wradlib license](https://github.com/wradlib/wradlib/blob/main/LICENSE.txt).

A copy of the license can be found under `radar/LICENSE.txt`.

