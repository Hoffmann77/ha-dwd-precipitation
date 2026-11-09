"""The interpolation evaluation service (docs/interpolation-evaluation.md).

Logs RV nowcast windows around DWD rain gauges, so that sub-cell methods can
later be scored against what the gauges measured. Runs as one long-lived
process in a container (deploy/precip-eval); nothing here ships with the
integration, which it only imports from (``radar.odim``, ``radar.urls``).

"""
