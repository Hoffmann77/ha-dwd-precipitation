# DWD Precipitation

This custom component for Home Assistant provides detailed radar precipitation forecasts and historical precipitation values from the past for Germany.

Radar based quantitative precipitation estimation products

The data is derived from the radar based *Radvor* and *Radolan* products provided by the DWD (Deutscher Wetterdienst) allowing you to track rain events at your precise location. 

Ideal for automations and warnings of severe precipitation events.

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

## Data sources

RADVOR (Radar Real-Time Forecasting): The radar precipitation forecast system (RADVOR) provides real-time quantitative precipitation analyses and forecasts for lead times up to two hours for Germany in high temporal and spatial resolution.
See: https://www.dwd.de/EN/ourservices/radvor/radvor.html;jsessionid=8CA76D75D79EBFAA7B647D6D0643A174.live11052