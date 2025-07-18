# DWD Precipitation

This custom component for Home Assistant provides detailed radar precipitation forecasts and historical precipitation values for your location within Germany.

The data is derived from the radar based *Radvor* and *Radolan* products provided by the DWD (Deutscher Wetterdienst) allowing you to track rain events at your precise location. This is ideal for automations and warnings of severe precipitation events.

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


## Data source

The data ist derived from the DWD (Deutscher Wetterdienst).

RADVOR (Radar Real-Time Forecasting): The radar precipitation forecast system (RADVOR) provides real-time quantitative precipitation analyses and forecasts for lead times up to two hours for Germany in high temporal and spatial resolution.
See: https://www.dwd.de/EN/ourservices/radvor/radvor.html;jsessionid=8CA76D75D79EBFAA7B647D6D0643A174.live11052

RADOLAN (Radar online aneichung):

![DWD](https://www.dwd.de/EN/service/legal_notice/dwd-logo-png.png?__blob=publicationFile&v=2)
